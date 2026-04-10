"""Quality check — colour richness, light circles, washed-out guard, and constraint guards.

The check pipeline has two layers:

1. **Cheap pre-render guards** — reject manually-authored Params that violate
   the sampler's constraints (no positive temperature on warm lights, no
   chromatic aberration on glass, glass dispersion ≤ 30 000).  These only
   fire for manually-loaded/edited Params because the sampler already
   suppresses them — they exist as belt-and-suspenders.

2. **Measurement + thresholds** — render a probe frame, measure light
   circles, extract luminance/colour stats, and apply the numeric
   thresholds listed below.

Both ``check()`` and ``measure_all()`` funnel through ``_measure_and_verdict``
so they run one probe per call.  Catalogues and the characterize subcommand
use ``measure_all()`` for the metric overlays; ``Family.search`` uses
``check()``.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass

import numpy as np

from anim import Camera2D, Shot, Timeline, render_frame
from anim.family import Verdict, probe
from anim.stats import frame_stats

from ..light_circle import LightCircle, _luminance, measure_light_circles
from .grid import build_grid, remove_holes
from .params import DURATION, Params

# ---------------------------------------------------------------------------
# Thresholds
# ---------------------------------------------------------------------------

RICHNESS_THRESHOLD = 0.15
MIN_COLORFUL_SECONDS = 2.5

# Light circle thresholds (at probe resolution 640x360).
# These use the threshold/Voronoi method: radius is the 90th-percentile
# distance of pixels above 0.92 luminance; sharpness is the luminance
# drop per pixel across the edge band.
MAX_MEAN_LUMINANCE = 0.70  # reject if scene is too bright overall (hard backstop)
MIN_MEAN_LUMINANCE = 0.12  # reject if scene is too dark (objects blocking too much light)
MIN_CONTRAST_SPREAD = 0.25  # reject washed-out scenes: p95_luminance - p05_luminance
MIN_MOVING_RADIUS_PX = 3.0  # moving light must be a visible blob
MAX_MOVING_RADIUS_PX = 80.0  # not a featureless wash
MAX_RADIUS_RATIO = 2.66  # max moving / ambient circle size ratio
MIN_SHARPNESS = 0.010  # minimum edge sharpness (lum drop per pixel)

# Analysis-driven constraint guards (pre-render).
MAX_GLASS_CAUCHY_B = 30_000.0  # "dispersion should not exceed 30000"
WARM_LIGHT_WL_MIN = 500.0  # wavelength_min at/above which a light is "warm"

PROBE_W, PROBE_H, PROBE_RAYS = 640, 360, 200_000

METRIC_KEYS: tuple[str, ...] = (
    "color",
    "richness",
    "mean",
    "spread",
    "p05",
    "p95",
    "p99",
    "clip%",
    "sat",
    "moving_r",
    "ambient_r",
    "ratio",
    "sharp",
    "exp",
    "gam",
    "wp",
)


@dataclass
class MeasurementResult:
    """Bundled measurement + verdict returned by ``_measure_and_verdict``.

    ``metrics`` contains every numeric value used by the filters (plus a
    few extras that are displayed on catalogue overlays but not yet
    applied as thresholds — e.g. clip% and p99).  ``verdict`` carries
    the pass/fail decision and a human-readable summary string.
    """

    metrics: dict[str, float]
    verdict: Verdict


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _min_object_distance(
    light_pos: tuple[float, float],
    object_positions: list[tuple[float, float]],
) -> float:
    """Minimum Euclidean distance from a light to any object centre."""
    if not object_positions:
        return float("inf")
    return min(math.hypot(light_pos[0] - ox, light_pos[1] - oy) for ox, oy in object_positions)


def _find_clear_frame(
    animate,
    duration: float,
    object_positions: list[tuple[float, float]],
    fps: int = 4,
) -> int:
    """Frame index where moving lights are furthest from objects.

    Calls ``animate()`` without rendering to inspect light positions.
    Returns the single best frame index for circle measurement.
    """
    timeline = Timeline(duration, fps=fps)
    best_idx = 0
    best_clearance = -1.0

    for fi in range(timeline.total_frames):
        ctx = timeline.context_at(fi)
        frame = animate(ctx)
        moving = [
            (lt.position[0], lt.position[1])
            for lt in frame.scene.lights
            if lt.id.startswith("light_")
        ]
        if not moving:
            continue
        # Worst-case clearance across all moving lights in this frame.
        clearance = min(_min_object_distance(lp, object_positions) for lp in moving)
        if clearance > best_clearance:
            best_clearance = clearance
            best_idx = fi

    return best_idx


_PROBE_CAMERA_CENTER: tuple[float, float] = (0.0, 0.0)
_PROBE_CAMERA_WIDTH: float = 3.2
_PROBE_CAMERA = Camera2D(center=list(_PROBE_CAMERA_CENTER), width=_PROBE_CAMERA_WIDTH)


def _render_probe_frame(
    animate,
    frame_idx: int,
    duration: float,
) -> tuple[list[LightCircle], bytes]:
    """Render one probe-quality frame; return (circles, raw RGB8 bytes)."""
    probe_shot = Shot.preset("draft", width=PROBE_W, height=PROBE_H, rays=PROBE_RAYS, depth=10)
    rr = render_frame(
        animate,
        Timeline(duration, fps=4),
        frame=frame_idx,
        settings=probe_shot,
        camera=_PROBE_CAMERA,
    )

    # Extract light positions from the animate callback's scene.
    ctx = Timeline(duration, fps=4).context_at(frame_idx)
    frame_result = animate(ctx)
    positions = [(lt.position[0], lt.position[1]) for lt in frame_result.scene.lights]
    labels = [lt.id for lt in frame_result.scene.lights]

    circles = measure_light_circles(
        rr.pixels,
        PROBE_W,
        PROBE_H,
        positions,
        camera_center=_PROBE_CAMERA_CENTER,
        camera_width=_PROBE_CAMERA_WIDTH,
        labels=labels,
    )

    return circles, rr.pixels


# ---------------------------------------------------------------------------
# Pre-render constraint guards
# ---------------------------------------------------------------------------


def _check_constraint_guards(p: Params) -> Verdict | None:
    """Return a failing Verdict if the Params violates a hard constraint.

    These are cheap pre-render checks; the sampler already avoids these
    combinations, but ``check.py`` is the authoritative filter for
    manually-loaded / manually-edited Params.
    """
    mat = p.material
    look = p.look
    light = p.light

    if mat.outcome == "glass" and mat.cauchy_b > MAX_GLASS_CAUCHY_B:
        return Verdict(
            False,
            f"glass cauchy_b={mat.cauchy_b:.0f} > {MAX_GLASS_CAUCHY_B:.0f}",
        )

    if look.temperature > 0.0 and light.wavelength_min >= WARM_LIGHT_WL_MIN:
        return Verdict(
            False,
            f"warm light (wl_min={light.wavelength_min:.0f}) + temperature={look.temperature:.2f}",
        )

    if look.chromatic_aberration > 0.0 and mat.outcome == "glass":
        return Verdict(
            False,
            f"glass + chromatic_aberration={look.chromatic_aberration:.4f}",
        )

    return None


# ---------------------------------------------------------------------------
# Core measurement + verdict
# ---------------------------------------------------------------------------


def _measure_and_verdict(p: Params, animate) -> MeasurementResult:
    """Run all measurements, return metrics dict + Verdict in one pass.

    This is the single source of truth — ``check()`` and ``measure_all()``
    both delegate here.  The catalogue loop also imports it directly to
    avoid running the probe twice per entry.
    """
    # Guards first — cheap, no render.
    guard = _check_constraint_guards(p)
    if guard is not None:
        return MeasurementResult(metrics=_empty_metrics(p), verdict=guard)

    # ── Colour richness across the animation (probe at 4 fps) ──
    frames = probe(animate, DURATION)
    colorful = sum(1 for f in frames if f.color_richness > RICHNESS_THRESHOLD)
    colorful_s = colorful / 4  # probe runs at 4 fps
    avg_richness = sum(f.color_richness for f in frames) / len(frames)
    avg_frame_sat = sum(f.mean_saturation for f in frames) / len(frames) if frames else 0.0

    # Object positions (deterministic from build_seed + grid config).
    rng = random.Random(p.build_seed)
    positions = build_grid(p.grid)
    if p.grid.hole_fraction > 0:
        positions = remove_holes(positions, p.grid.hole_fraction, rng)

    # Clearest frame for light-circle measurement.
    best_fi = _find_clear_frame(animate, DURATION, positions)
    circles, pixel_bytes = _render_probe_frame(animate, best_fi, DURATION)

    moving = [c for c in circles if c.label.startswith("light_")]
    ambient = [c for c in circles if c.label.startswith("amb_")]

    fs = frame_stats(pixel_bytes, PROBE_W, PROBE_H)
    mean_lum = fs.mean / 255.0
    p05 = fs.p05 / 255.0
    p95 = fs.p95 / 255.0
    spread = p95 - p05
    clip_frac = fs.pct_clipped

    # p99 isn't in FrameStats — compute on the luminance array directly.
    pixels = np.frombuffer(pixel_bytes, dtype=np.uint8).reshape(PROBE_H, PROBE_W, 3)
    p99 = float(np.percentile(_luminance(pixels), 99.0))

    sat = avg_frame_sat

    # Light circle aggregates.
    med_moving_r = float(sorted(c.radius_px for c in moving)[len(moving) // 2]) if moving else 0.0
    med_ambient_r = (
        float(sorted(c.radius_px for c in ambient)[len(ambient) // 2]) if ambient else 0.0
    )
    ratio = med_moving_r / med_ambient_r if med_ambient_r > 0 else 0.0
    min_sharpness = float(min(c.sharpness for c in moving)) if moving else 0.0

    metrics: dict[str, float] = {
        "color": colorful_s,
        "richness": avg_richness,
        "mean": mean_lum,
        "spread": spread,
        "p05": p05,
        "p95": p95,
        "p99": p99,
        "clip%": clip_frac,
        "sat": sat,
        "moving_r": med_moving_r,
        "ambient_r": med_ambient_r,
        "ratio": ratio,
        "sharp": min_sharpness,
        "exp": float(p.look.exposure),
        "gam": float(p.look.gamma),
        "wp": float(p.look.white_point),
    }

    def fail(summary: str) -> MeasurementResult:
        return MeasurementResult(metrics=metrics, verdict=Verdict(False, summary))

    prefix = f"color={colorful_s:.1f}s"

    if colorful_s < MIN_COLORFUL_SECONDS:
        return fail(f"{prefix} avg={avg_richness:.3f}")
    if not moving:
        return fail(f"{prefix} -- no moving lights")
    if mean_lum > MAX_MEAN_LUMINANCE:
        return fail(f"{prefix} mean={mean_lum:.2f} (too bright)")
    if mean_lum < MIN_MEAN_LUMINANCE:
        return fail(f"{prefix} mean={mean_lum:.2f} (too dark)")
    if med_moving_r < MIN_MOVING_RADIUS_PX:
        return fail(f"{prefix} moving_r={med_moving_r:.1f}px (too small)")
    if med_moving_r > MAX_MOVING_RADIUS_PX:
        return fail(f"{prefix} moving_r={med_moving_r:.1f}px (too large)")
    if min_sharpness < MIN_SHARPNESS:
        return fail(f"{prefix} sharp={min_sharpness:.4f} (too soft)")
    if ambient and ratio > MAX_RADIUS_RATIO:
        return fail(
            f"{prefix} ratio={ratio:.1f} (moving {med_moving_r:.0f}px / amb {med_ambient_r:.0f}px)"
        )
    # Washed-out guard runs last so trivially-dark scenes get caught by the
    # mean-luminance floor first.
    if spread < MIN_CONTRAST_SPREAD:
        return fail(f"{prefix} spread={spread:.2f} (washed out)")

    ratio_msg = f" ratio={ratio:.1f}" if ambient else ""
    return MeasurementResult(
        metrics=metrics,
        verdict=Verdict(
            True,
            f"{prefix} moving_r={med_moving_r:.0f}px "
            f"sharp={min_sharpness:.3f} spread={spread:.2f}{ratio_msg}",
        ),
    )


def _empty_metrics(p: Params) -> dict[str, float]:
    """Metric dict populated only with Params-derived fields (no render)."""
    metrics = {k: 0.0 for k in METRIC_KEYS}
    metrics["exp"] = float(p.look.exposure)
    metrics["gam"] = float(p.look.gamma)
    metrics["wp"] = float(p.look.white_point)
    return metrics


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def check(p: Params, animate) -> Verdict:
    """Family.search-compatible acceptance gate."""
    return _measure_and_verdict(p, animate).verdict


def measure_all(p: Params, animate) -> dict[str, float]:
    """Return every numeric metric the filter (and the overlay) uses.

    Runs the full measurement pass — colour richness, light circles,
    luminance stats, saturation, clipping — and returns them as a flat
    dict keyed by short labels suitable for the catalogue overlay.
    """
    return _measure_and_verdict(p, animate).metrics
