"""Quality check — colour richness, point-light appearance, and washed-out guards.

The check pipeline has two layers:

1. **Cheap pre-render guards** — reject manually-authored Params that violate
   the sampler's constraints (no positive temperature on warm lights, no
   chromatic aberration on glass, glass dispersion ≤ 30 000).  These only
   fire for manually-loaded/edited Params because the sampler already
   suppresses them — they exist as belt-and-suspenders.

2. **Measurement + thresholds** — render a probe frame, read the C++
   frame analysis (luminance + colour + per-light appearance), and apply
   the numeric thresholds listed below. All pixel math lives in
   ``src/core/image_analysis.cpp``; this module is pure threshold
   policy — no numpy, no pixel access.

Both ``check()`` and ``measure_all()`` funnel through ``_measure_and_verdict``
so they run one probe per call.  Catalogues and the characterize subcommand
use ``measure_all()`` for the metric overlays; ``Family.search`` uses
``check()``.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass

from anim import Timeline
from anim.family import Verdict, probe

from .grid import build_grid, remove_holes
from .params import DURATION, Params

# ---------------------------------------------------------------------------
# Thresholds
# ---------------------------------------------------------------------------

PROBE_W, PROBE_H = 640, 360

RICHNESS_THRESHOLD = 0.15
MIN_COLORFUL_SECONDS = 2.5

# Point-light appearance thresholds (measured on the normalized authored
# camera image at probe resolution 640x360).
MAX_MEAN_LUMINANCE = 0.70  # reject if scene is too bright overall (hard backstop)
MIN_MEAN_LUMINANCE = 0.12  # reject if scene is too dark (objects blocking too much light)
MIN_CONTRAST_SPREAD = 0.25  # reject washed-out scenes: p95_luminance - p05_luminance
MIN_MOVING_RADIUS_RATIO = 3.0 / PROBE_H  # moving light must be a visible blob
MAX_MOVING_RADIUS_RATIO = 80.0 / PROBE_H  # not a featureless wash
MIN_COVERAGE_FRACTION = 20.0 / float(PROBE_W * PROBE_H)
MAX_RADIUS_RATIO = 2.66  # max moving / ambient point-light appearance size ratio
MAX_TRANSITION_WIDTH_RATIO = 12.0 / PROBE_H
MIN_PEAK_CONTRAST = 0.08
MIN_CONFIDENCE = 0.35

# Analysis-driven constraint guards (pre-render).
MAX_GLASS_CAUCHY_B = 30_000.0  # "dispersion should not exceed 30000"
WARM_LIGHT_WL_MIN = 500.0  # wavelength_min at/above which a light is "warm"

METRIC_KEYS: tuple[str, ...] = (
    "colorful_seconds",
    "richness",
    "mean",
    "contrast_spread",
    "shadow_floor",
    "highlight_ceiling",
    "highlight_peak",
    "clipped_channel_fraction",
    "mean_saturation",
    "moving_radius_ratio",
    "ambient_radius_ratio",
    "coverage_fraction",
    "radius_ratio",
    "transition_width_ratio",
    "peak_contrast",
    "confidence",
    "exposure",
    "gamma",
    "white_point",
)


@dataclass
class MeasurementResult:
    """Bundled measurement + verdict returned by ``_measure_and_verdict``.

    ``metrics`` contains every numeric value used by the filters (plus a
    few extras that are displayed on catalogue overlays but not yet
    applied as thresholds). ``verdict`` carries
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
    Returns the single best frame index for point-light appearance measurement.
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
    colorful = sum(1 for f in frames if f.richness > RICHNESS_THRESHOLD)
    colorful_s = colorful / 4  # probe runs at 4 fps
    avg_richness = sum(f.richness for f in frames) / len(frames)
    avg_frame_sat = sum(f.mean_saturation for f in frames) / len(frames) if frames else 0.0

    # Object positions (deterministic from build_seed + grid config).
    rng = random.Random(p.build_seed)
    positions = build_grid(p.grid)
    if p.grid.hole_fraction > 0:
        positions = remove_holes(positions, p.grid.hole_fraction, rng)

    # Pick the clearest frame from the probe result for the point-light
    # appearance measurement — the C++ analyser already measured every PointLight at
    # every probe frame, so we just index into it instead of re-rendering.
    best_fi = _find_clear_frame(animate, DURATION, positions)
    ana = frames[best_fi].analysis

    # Label prefixes distinguish moving ("light_*") from ambient ("amb_*").
    lights = list(ana.lights)
    moving = [c for c in lights if c.id.startswith("light_")]
    ambient = [c for c in lights if c.id.startswith("amb_")]

    mean_brightness = ana.luminance.mean / 255.0
    shadow_floor = ana.luminance.shadow_floor / 255.0
    highlight_ceiling = ana.luminance.highlight_ceiling / 255.0
    highlight_peak = ana.luminance.highlight_peak / 255.0
    contrast_spread = highlight_ceiling - shadow_floor
    clip_frac = ana.luminance.clipped_channel_fraction
    mean_saturation = avg_frame_sat

    # Point-light appearance aggregates.
    med_moving_r = (
        float(sorted(c.radius_ratio for c in moving)[len(moving) // 2])
        if moving
        else 0.0
    )
    med_ambient_r = (
        float(sorted(c.radius_ratio for c in ambient)[len(ambient) // 2])
        if ambient
        else 0.0
    )
    ratio = med_moving_r / med_ambient_r if med_ambient_r > 0 else 0.0
    max_edge = float(max(c.transition_width_ratio for c in moving)) if moving else 0.0
    min_contrast = float(min(c.peak_contrast for c in moving)) if moving else 0.0
    min_confidence = float(min(c.confidence for c in moving)) if moving else 0.0
    min_coverage = float(min(c.coverage_fraction for c in moving)) if moving else 0.0

    metrics: dict[str, float] = {
        "colorful_seconds": colorful_s,
        "richness": avg_richness,
        "mean": mean_brightness,
        "contrast_spread": contrast_spread,
        "shadow_floor": shadow_floor,
        "highlight_ceiling": highlight_ceiling,
        "highlight_peak": highlight_peak,
        "clipped_channel_fraction": clip_frac,
        "mean_saturation": mean_saturation,
        "moving_radius_ratio": med_moving_r,
        "ambient_radius_ratio": med_ambient_r,
        "coverage_fraction": min_coverage,
        "radius_ratio": ratio,
        "transition_width_ratio": max_edge,
        "peak_contrast": min_contrast,
        "confidence": min_confidence,
        "exposure": float(p.look.exposure),
        "gamma": float(p.look.gamma),
        "white_point": float(p.look.white_point),
    }

    def fail(summary: str) -> MeasurementResult:
        return MeasurementResult(metrics=metrics, verdict=Verdict(False, summary))

    prefix = f"color={colorful_s:.1f}s"

    if colorful_s < MIN_COLORFUL_SECONDS:
        return fail(f"{prefix} avg={avg_richness:.3f}")
    if not moving:
        return fail(f"{prefix} -- no moving lights")
    if mean_brightness > MAX_MEAN_LUMINANCE:
        return fail(f"{prefix} mean={mean_brightness:.2f} (too bright)")
    if mean_brightness < MIN_MEAN_LUMINANCE:
        return fail(f"{prefix} mean={mean_brightness:.2f} (too dark)")
    if med_moving_r < MIN_MOVING_RADIUS_RATIO:
        return fail(f"{prefix} moving_radius_ratio={med_moving_r:.3f} (too small)")
    if med_moving_r > MAX_MOVING_RADIUS_RATIO:
        return fail(f"{prefix} moving_radius_ratio={med_moving_r:.3f} (too large)")
    if min_coverage < MIN_COVERAGE_FRACTION:
        return fail(f"{prefix} coverage_fraction={min_coverage:.5f} (too small)")
    if max_edge > MAX_TRANSITION_WIDTH_RATIO:
        return fail(f"{prefix} transition_width_ratio={max_edge:.4f} (too soft)")
    if min_contrast < MIN_PEAK_CONTRAST:
        return fail(f"{prefix} peak_contrast={min_contrast:.3f} (too weak)")
    if min_confidence < MIN_CONFIDENCE:
        return fail(f"{prefix} confidence={min_confidence:.2f} (too uncertain)")
    if ambient and ratio > MAX_RADIUS_RATIO:
        return fail(
            f"{prefix} radius_ratio={ratio:.1f} "
            f"(moving {med_moving_r:.3f} / ambient {med_ambient_r:.3f})"
        )
    # Washed-out guard runs last so trivially-dark scenes get caught by the
    # mean-luminance floor first.
    if contrast_spread < MIN_CONTRAST_SPREAD:
        return fail(f"{prefix} contrast_spread={contrast_spread:.2f} (washed out)")

    ratio_msg = f" radius_ratio={ratio:.1f}" if ambient else ""
    return MeasurementResult(
        metrics=metrics,
        verdict=Verdict(
            True,
            f"{prefix} moving_radius_ratio={med_moving_r:.3f} "
            f"transition_width_ratio={max_edge:.4f} "
            f"peak_contrast={min_contrast:.3f} "
            f"confidence={min_confidence:.2f} "
            f"contrast_spread={contrast_spread:.2f}{ratio_msg}",
        ),
    )


def _empty_metrics(p: Params) -> dict[str, float]:
    """Metric dict populated only with Params-derived fields (no render)."""
    metrics = {k: 0.0 for k in METRIC_KEYS}
    metrics["exposure"] = float(p.look.exposure)
    metrics["gamma"] = float(p.look.gamma)
    metrics["white_point"] = float(p.look.white_point)
    return metrics


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def check(p: Params, animate) -> Verdict:
    """Family.search-compatible acceptance gate."""
    return _measure_and_verdict(p, animate).verdict


def measure_all(p: Params, animate) -> dict[str, float]:
    """Return every numeric metric the filter (and the overlay) uses.

    Runs the full measurement pass — colour richness, point-light appearance,
    luminance stats, saturation, clipping — and returns them as a flat
    dict keyed by short labels suitable for the catalogue overlay.
    """
    return _measure_and_verdict(p, animate).metrics
