"""Catalog retry scoring follows crystal_field's current rejection policy."""

from __future__ import annotations

from examples.python.families.crystal_field.check import (
    METRIC_KEYS,
    MIN_CONTRAST_SPREAD,
    PROBE_FPS,
    measurement_context,
    _measure_and_verdict,
)
from examples.python.families.crystal_field.params import (
    AmbientConfig,
    GridConfig,
    LightConfig,
    LookConfig,
    MaterialConfig,
    Params,
    ShapeConfig,
)


def test_failure_distance_is_zero_for_passing():
    """Baseline: a passing result should have _failure_distance near 0."""
    from anim.family import Verdict
    from examples.python.families.crystal_field.catalog import (
        _failure_distance,
    )
    from examples.python.families.crystal_field.check import MeasurementResult

    # Fabricate a metrics dict that lies safely inside every threshold.
    good_metrics = {
        "mean": 120.0,
        "contrast_spread": 8.0,
        "near_black_fraction": 0.03,
        "moving_radius_min": 0.015,
        "moving_radius_mean": 0.025,
        "moving_radius_max": 0.035,
        "ambient_radius_min": 0.010,
        "ambient_radius_mean": 0.015,
        "ambient_radius_max": 0.025,
        "moving_to_ambient_radius_ratio": 1.67,
    }
    result = MeasurementResult(
        metrics=good_metrics,
        verdict=Verdict(True, "synthetic pass"),
    )
    assert _failure_distance(result) == 0.0


def test_failure_distance_increases_with_washed_out():
    """A metrics dict that fails MIN_CONTRAST_SPREAD should produce a positive score."""
    from anim.family import Verdict
    from examples.python.families.crystal_field.catalog import (
        _failure_distance,
    )
    from examples.python.families.crystal_field.check import MeasurementResult

    washed_metrics = {
        "mean": 120.0,
        "contrast_spread": MIN_CONTRAST_SPREAD / 2,  # half the threshold
        "near_black_fraction": 0.03,
        "moving_radius_min": 0.015,
        "moving_radius_mean": 0.025,
        "moving_radius_max": 0.035,
        "ambient_radius_min": 0.010,
        "ambient_radius_mean": 0.015,
        "ambient_radius_max": 0.025,
        "moving_to_ambient_radius_ratio": 1.67,
    }
    result = MeasurementResult(
        metrics=washed_metrics,
        verdict=Verdict(False, "washed out"),
    )
    # Distance should reflect the spread shortfall.
    assert _failure_distance(result) > 0.0


def test_measure_and_verdict_populates_all_overlay_keys():
    """The metrics dict must contain every key the overlay displays.

    This protects against silent drops in ``measure_all`` — if the overlay
    expects a key and check.py stops producing it, the overlay would show
    a blank line.  Here we use a small synthetic Params to keep the test cheap.
    """
    grid = GridConfig(rows=3, cols=4, spacing=0.30, offset_rows=False, hole_fraction=0.0)
    shape = ShapeConfig(
        kind="circle",
        size=0.06,
        n_sides=0,
        corner_radius=0.0,
        rotation=None,
    )
    material = MaterialConfig(
        outcome="black_diffuse",
        albedo=0.85,  # analysis: never 0.15; high albedo is the rule for diffuse
        fill=0.0,
        color_names=[],
    )
    light = LightConfig(
        n_lights=1,
        path_style="channel",
        n_waypoints=8,
        ambient=AmbientConfig(style="corners", intensity=0.3),
        speed=0.12,
        moving_intensity=0.6,
        wavelength_min=380.0,
        wavelength_max=780.0,
    )
    look = LookConfig(exposure=-4.5)
    p = Params(grid=grid, shape=shape, material=material, light=light, look=look, build_seed=42)

    from examples.python.families.crystal_field.scene import build

    animate = build(p)
    result = _measure_and_verdict(p, animate)
    ctx = measurement_context(p, animate)

    # Every overlay key must be present, regardless of pass/fail.
    required_keys = set(METRIC_KEYS)
    missing = required_keys - set(result.metrics.keys())
    assert not missing, f"measure_all missing keys: {missing}"
    assert result.analysis_fps == PROBE_FPS
    assert result.analysis_frame == ctx.frame
    assert result.analysis_time == ctx.time
    assert result.metrics["analysis_frame"] == float(ctx.frame)
    assert result.metrics["analysis_fps"] == float(ctx.fps)
    assert result.metrics["analysis_time"] == ctx.time
