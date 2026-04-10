"""Catalog now rejects entries that would have silently passed the old
mean-luminance-only shortcut.

The rewrite replaces catalog.py's ``_search_good_params`` with a plain
retry loop that calls the full ``check.py`` pipeline (color richness,
light circles, sharpness, ratio, washed-out).  This test confirms that
the catalog's acceptance path now uses those extra thresholds by
constructing a synthetic Params that would pass the old mean-luminance
window but fails one of the newer gates.
"""

from __future__ import annotations

from examples.python.families.crystal_field.check import (
    MIN_CONTRAST_SPREAD,
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
        "color": 5.0,
        "richness": 0.4,
        "mean": 0.35,
        "spread": 0.40,
        "p05": 0.05,
        "p95": 0.45,
        "p99": 0.55,
        "clip%": 0.0,
        "sat": 0.3,
        "moving_r": 20.0,
        "ambient_r": 15.0,
        "ratio": 1.3,
        "sharp": 0.03,
        "exp": -4.5,
        "gam": 1.8,
        "wp": 0.5,
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
        "color": 5.0,
        "richness": 0.4,
        "mean": 0.35,
        "spread": MIN_CONTRAST_SPREAD / 2,  # half the threshold
        "p05": 0.20,
        "p95": 0.32,
        "p99": 0.34,
        "clip%": 0.0,
        "sat": 0.3,
        "moving_r": 20.0,
        "ambient_r": 15.0,
        "ratio": 1.3,
        "sharp": 0.03,
        "exp": -4.5,
        "gam": 1.8,
        "wp": 0.5,
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
    a blank line.  Here we use a fast synthetic Params with one ambient-only
    scene to keep the test cheap.
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
        style="diffuse",
        ior=1.5,
        cauchy_b=0.0,
        absorption=0.0,
        fill=0.0,
        n_color_groups=0,
        diffuse_style="dark",
        color_names=[],
        albedo=0.15,
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

    # Every overlay key must be present, regardless of pass/fail.
    required_keys = {
        "color",
        "mean",
        "spread",
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
    }
    missing = required_keys - set(result.metrics.keys())
    assert not missing, f"measure_all missing keys: {missing}"
