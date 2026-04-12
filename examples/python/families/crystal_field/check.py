"""Quality check for crystal_field variants.

The rejection policy is intentionally small and explicit: one analyzed
probe frame supplies the moving/ambient light radii plus normalized image
stats, and the thresholds below decide acceptance. The metric keys mirror
the generic C++ image-analysis contract instead of crystal-field-specific
aliases.
"""

from __future__ import annotations

import math
import random
from collections.abc import Iterable, Iterator
from dataclasses import asdict, dataclass

from anim import Camera2D, Shot, Timeline, Verdict, iter_frame_variants, render_frame

from .grid import build_grid, remove_holes
from .params import DURATION, LookConfig, Params

# ---------------------------------------------------------------------------
# Thresholds
# ---------------------------------------------------------------------------

PROBE_W, PROBE_H = 960, 540
PROBE_FPS = 4
PROBE_RAYS = 400_000

MIN_MOVING_RADIUS_RATIO = 0.014
MAX_MOVING_RADIUS_RATIO = 0.046
MIN_AMBIENT_RADIUS_RATIO = 0.008
MAX_AMBIENT_RADIUS_RATIO = 0.042
MIN_RADIUS_RATIO = 1.33
MAX_RADIUS_RATIO = 2.5

MAX_NEAR_BLACK_FRACTION = 0.035
MIN_MEAN_LUMA = 60.0 / 255.0
MAX_MEAN_LUMA = 140.0 / 255.0
GLASS_MAX_MEAN_LUMA = 80.0 / 255.0
MIN_P05_LUMA = 0.06
MAX_P05_LUMA = 80.0 / 255.0
MIN_INTERDECILE_LUMA_RANGE = 50.0 / 255.0
MIN_LOCAL_CONTRAST = 0.015
MAX_BRIGHT_NEUTRAL_FRACTION = 0.40
MAX_MEAN_SATURATION = 0.69

METRIC_KEYS: tuple[str, ...] = (
    "mean_luma",
    "median_luma",
    "p05_luma",
    "p95_luma",
    "p10_luma",
    "p90_luma",
    "near_black_fraction",
    "near_white_fraction",
    "clipped_channel_fraction",
    "rms_contrast",
    "interdecile_luma_range",
    "interdecile_luma_contrast",
    "local_contrast",
    "mean_saturation",
    "p95_saturation",
    "colorfulness",
    "bright_neutral_fraction",
    "luma_entropy_normalized",
    "saturation_coverage",
    "colored_fraction",
    "mean_saturation_colored",
    "moving_radius_min",
    "moving_radius_mean",
    "moving_radius_max",
    "ambient_radius_min",
    "ambient_radius_mean",
    "ambient_radius_max",
    "moving_to_ambient_radius_ratio",
)


@dataclass
class MeasurementResult:
    """Bundled measurement + verdict returned by ``_measure_and_verdict``."""

    metrics: dict[str, float]
    verdict: Verdict
    analysis_frame: int = 0
    analysis_fps: int = PROBE_FPS
    analysis_time: float = 0.0


LookVariantInput = LookConfig | tuple[str, LookConfig]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_measurement_shot() -> Shot:
    """Low-res authored shot used by the rejection metrics."""
    shot = Shot.preset("draft", width=PROBE_W, height=PROBE_H, rays=PROBE_RAYS, depth=10)
    shot.camera = Camera2D(center=[0, 0], width=3.2)
    shot.look = shot.look.with_overrides(
        gamma=2.0,
        tonemap="reinhardx",
        white_point=0.5,
        normalize="rays",
        temperature=0.1,
    )
    return shot


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
    fps: int = PROBE_FPS,
) -> int:
    """Frame index where moving lights are furthest from objects.

    Calls ``animate()`` without rendering to inspect light positions.
    Returns the single best frame index for light-radius measurement.
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
        clearance = min(_min_object_distance(lp, object_positions) for lp in moving)
        if clearance > best_clearance:
            best_clearance = clearance
            best_idx = fi

    return best_idx


def _mean(values: list[float]) -> float:
    return float(sum(values) / len(values)) if values else 0.0


def _object_positions_for_params(p: Params) -> list[tuple[float, float]]:
    rng = random.Random(p.build_seed)
    positions = build_grid(p.grid)
    if p.grid.hole_fraction > 0:
        positions = remove_holes(positions, p.grid.hole_fraction, rng)
    return positions


def _selected_measurement_frame(p: Params, animate) -> tuple[Timeline, int]:
    """Return the single frame used for crystal_field probe/check analysis."""
    positions = _object_positions_for_params(p)
    timeline = Timeline(DURATION, fps=PROBE_FPS)
    return timeline, _find_clear_frame(animate, DURATION, positions, fps=PROBE_FPS)


def measurement_context(p: Params, animate):
    """Return the FrameContext selected for probe/check/catalog consistency."""
    timeline, frame = _selected_measurement_frame(p, animate)
    return timeline.context_at(frame)


def metrics_from_analysis(analysis) -> dict[str, float]:
    """Build crystal_field metrics from core FrameAnalysis binding data.

    Pixel statistics and per-light circle radii come from the C++ analysis
    object.  Python only groups the already-measured light radii into the
    moving/ambient aggregates used by the family rejection policy.
    """
    lights = list(analysis.lights)
    moving = [c for c in lights if c.id.startswith("light_")]
    ambient = [c for c in lights if c.id.startswith("amb_")]

    moving_radii = [float(c.radius_ratio) for c in moving]
    ambient_radii = [float(c.radius_ratio) for c in ambient]

    moving_radius_mean = _mean(moving_radii)
    moving_radius_min = float(min(moving_radii)) if moving_radii else 0.0
    moving_radius_max = float(max(moving_radii)) if moving_radii else 0.0
    ambient_radius_mean = _mean(ambient_radii)
    ambient_radius_min = float(min(ambient_radii)) if ambient_radii else 0.0
    ambient_radius_max = float(max(ambient_radii)) if ambient_radii else 0.0
    radius_ratio = moving_radius_mean / ambient_radius_mean if ambient_radius_mean > 0 else 0.0

    image = analysis.image
    debug = analysis.debug
    metrics: dict[str, float] = {
        "mean_luma": float(image.mean_luma),
        "median_luma": float(image.median_luma),
        "p05_luma": float(image.p05_luma),
        "p95_luma": float(image.p95_luma),
        "p10_luma": float(debug.p10_luma),
        "p90_luma": float(debug.p90_luma),
        "near_black_fraction": float(image.near_black_fraction),
        "near_white_fraction": float(image.near_white_fraction),
        "clipped_channel_fraction": float(image.clipped_channel_fraction),
        "rms_contrast": float(image.rms_contrast),
        "interdecile_luma_range": float(image.interdecile_luma_range),
        "interdecile_luma_contrast": float(image.interdecile_luma_contrast),
        "local_contrast": float(image.local_contrast),
        "mean_saturation": float(image.mean_saturation),
        "p95_saturation": float(image.p95_saturation),
        "colorfulness": float(image.colorfulness),
        "bright_neutral_fraction": float(image.bright_neutral_fraction),
        "luma_entropy_normalized": float(debug.luma_entropy_normalized),
        "saturation_coverage": float(debug.saturation_coverage),
        "colored_fraction": float(debug.colored_fraction),
        "mean_saturation_colored": float(debug.mean_saturation_colored),
        "moving_radius_min": moving_radius_min,
        "moving_radius_mean": moving_radius_mean,
        "moving_radius_max": moving_radius_max,
        "ambient_radius_min": ambient_radius_min,
        "ambient_radius_mean": ambient_radius_mean,
        "ambient_radius_max": ambient_radius_max,
        "moving_to_ambient_radius_ratio": radius_ratio,
    }

    return metrics


def _measurement_result_from_analysis(
    p: Params,
    analysis,
    timeline: Timeline,
    best_fi: int,
) -> MeasurementResult:
    metrics = metrics_from_analysis(analysis)
    metrics["analysis_frame"] = float(best_fi)
    metrics["analysis_fps"] = float(PROBE_FPS)
    metrics["analysis_time"] = timeline.time_at(best_fi)

    return MeasurementResult(
        metrics=metrics,
        verdict=_verdict_for_metrics(
            metrics,
            moving_count=sum(1 for c in analysis.lights if c.id.startswith("light_")),
            ambient_count=sum(1 for c in analysis.lights if c.id.startswith("amb_")),
            outcome=p.material.outcome,
        ),
        analysis_frame=best_fi,
        analysis_fps=PROBE_FPS,
        analysis_time=timeline.time_at(best_fi),
    )


def _verdict_for_metrics(
    metrics: dict[str, float],
    *,
    moving_count: int,
    ambient_count: int,
    outcome: str | None = None,
) -> Verdict:
    """Apply the rejection thresholds to already-measured metrics."""
    moving_radius_mean = metrics["moving_radius_mean"]
    ambient_radius_mean = metrics["ambient_radius_mean"]
    moving_radius_min = metrics["moving_radius_min"]
    moving_radius_max = metrics["moving_radius_max"]
    ambient_radius_min = metrics["ambient_radius_min"]
    ambient_radius_max = metrics["ambient_radius_max"]
    radius_ratio = metrics["moving_to_ambient_radius_ratio"]
    near_black_fraction = metrics["near_black_fraction"]
    mean_luma = metrics["mean_luma"]
    p05_luma = metrics["p05_luma"]
    interdecile_luma_range = metrics["interdecile_luma_range"]
    local_contrast = metrics["local_contrast"]
    bright_neutral_fraction = metrics["bright_neutral_fraction"]
    mean_saturation = metrics["mean_saturation"]
    max_mean_luminance = GLASS_MAX_MEAN_LUMA if outcome == "glass" else MAX_MEAN_LUMA
    has_p05_luma_constraint = outcome != "black_diffuse"

    prefix = (
        f"moving_mean={moving_radius_mean:.3f} "
        f"ambient_mean={ambient_radius_mean:.3f} "
        f"moving_to_ambient={radius_ratio:.2f}"
    )

    if moving_count <= 0:
        return Verdict(False, "no moving lights")
    if ambient_count <= 0:
        return Verdict(False, f"{prefix} -- no ambient lights")
    if moving_radius_min < MIN_MOVING_RADIUS_RATIO:
        return Verdict(False, f"{prefix} moving_radius_min={moving_radius_min:.3f} (too small)")
    if moving_radius_max > MAX_MOVING_RADIUS_RATIO:
        return Verdict(False, f"{prefix} moving_radius_max={moving_radius_max:.3f} (too large)")
    if ambient_radius_min < MIN_AMBIENT_RADIUS_RATIO:
        return Verdict(False, f"{prefix} ambient_radius_min={ambient_radius_min:.3f} (too small)")
    if ambient_radius_max > MAX_AMBIENT_RADIUS_RATIO:
        return Verdict(False, f"{prefix} ambient_radius_max={ambient_radius_max:.3f} (too large)")
    if radius_ratio < MIN_RADIUS_RATIO:
        return Verdict(
            False,
            f"{prefix} moving_to_ambient_radius_ratio={radius_ratio:.2f} (too small)",
        )
    if radius_ratio > MAX_RADIUS_RATIO:
        return Verdict(
            False,
            f"{prefix} moving_to_ambient_radius_ratio={radius_ratio:.2f} (too large)",
        )
    if near_black_fraction > MAX_NEAR_BLACK_FRACTION:
        return Verdict(False, f"{prefix} near_black={near_black_fraction:.1%} (too dark)")
    if mean_luma < MIN_MEAN_LUMA:
        return Verdict(False, f"{prefix} mean_luma={mean_luma:.3f} (too dark)")
    if mean_luma > max_mean_luminance:
        return Verdict(False, f"{prefix} mean_luma={mean_luma:.3f} (too bright)")
    if has_p05_luma_constraint and p05_luma < MIN_P05_LUMA:
        return Verdict(False, f"{prefix} p05_luma={p05_luma:.3f} (shadows too dark)")
    if has_p05_luma_constraint and p05_luma > MAX_P05_LUMA:
        return Verdict(False, f"{prefix} p05_luma={p05_luma:.3f} (shadows too bright)")
    if interdecile_luma_range < MIN_INTERDECILE_LUMA_RANGE:
        return Verdict(
            False,
            f"{prefix} interdecile_luma_range={interdecile_luma_range:.3f} (too low)",
        )
    if local_contrast < MIN_LOCAL_CONTRAST:
        return Verdict(False, f"{prefix} local_contrast={local_contrast:.3f} (too low)")
    if bright_neutral_fraction > MAX_BRIGHT_NEUTRAL_FRACTION:
        return Verdict(
            False,
            f"{prefix} bright_neutral={bright_neutral_fraction:.1%} (washed out)",
        )
    if mean_saturation >= MAX_MEAN_SATURATION:
        return Verdict(False, f"{prefix} saturation={mean_saturation:.3f} (too high)")

    return Verdict(
        True,
        f"{prefix} near_black={near_black_fraction:.1%} "
        f"mean_luma={mean_luma:.3f} p05_luma={p05_luma:.3f} "
        f"interdecile_luma_range={interdecile_luma_range:.3f}",
    )


# ---------------------------------------------------------------------------
# Core measurement + verdict
# ---------------------------------------------------------------------------


def _measure_and_verdict(p: Params, animate) -> MeasurementResult:
    """Run the rejection measurements and return metrics plus Verdict."""
    timeline, best_fi = _selected_measurement_frame(p, animate)
    rr = render_frame(
        animate,
        timeline,
        frame=best_fi,
        settings=_make_measurement_shot(),
        analyze=True,
    )
    return _measurement_result_from_analysis(p, rr.analysis, timeline, best_fi)


def _named_look_configs(look_variants: Iterable[LookVariantInput]) -> list[tuple[str, LookConfig]]:
    named: list[tuple[str, LookConfig]] = []
    for idx, variant in enumerate(look_variants):
        if isinstance(variant, tuple):
            named.append((variant[0], variant[1]))
        else:
            named.append((f"look_{idx:03d}", variant))
    return named


def _look_overrides(look: LookConfig) -> dict[str, float]:
    return asdict(look)


def measure_look_variants(
    p: Params,
    animate,
    look_variants: Iterable[LookVariantInput],
) -> Iterator[tuple[str, LookConfig, MeasurementResult]]:
    """Measure many post-process looks over one traced crystal-field frame.

    The clear analysis frame is selected once. The first look traces that
    frame; every subsequent look uses Python post-process replay, so catalog
    search can cheaply try many look variants before discarding a scene.
    """
    named_looks = _named_look_configs(look_variants)
    if not named_looks:
        return

    timeline, best_fi = _selected_measurement_frame(p, animate)
    replay_variants = [(name, _look_overrides(look)) for name, look in named_looks]

    for variant, (name, look) in zip(
        iter_frame_variants(
            animate,
            timeline,
            frame=best_fi,
            settings=_make_measurement_shot(),
            variants=replay_variants,
            analyze=True,
        ),
        named_looks,
        strict=True,
    ):
        yield (
            name,
            look,
            _measurement_result_from_analysis(p, variant.result.analysis, timeline, best_fi),
        )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def check(p: Params, animate) -> Verdict:
    """Family.search-compatible acceptance gate."""
    return _measure_and_verdict(p, animate).verdict


def measure_all(p: Params, animate) -> dict[str, float]:
    """Return every numeric metric the filter and catalogue overlay use."""
    return _measure_and_verdict(p, animate).metrics
