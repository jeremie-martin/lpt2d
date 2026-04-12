"""Catalog retry scoring follows crystal_field's current rejection policy."""

from __future__ import annotations

import random
from datetime import datetime

from examples.python.families.crystal_field.check import (
    METRIC_KEYS,
    MIN_INTERDECILE_LUMA_RANGE,
    PROBE_FPS,
    _measure_and_verdict,
    measurement_context,
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


def test_default_catalog_out_uses_timestamp_under_family_render_root():
    from examples.python.families.crystal_field.catalog import _default_catalog_out

    assert _default_catalog_out(datetime(2026, 4, 12, 10, 21, 33)).as_posix() == (
        "renders/families/crystal_field/2026-04-12_10-21-33"
    )


def test_default_catalog_web_out_uses_tmp_and_catalog_name():
    from examples.python.families.crystal_field.catalog import _default_catalog_web_out

    assert _default_catalog_web_out(
        "renders/families/crystal_field/2026-04-12_10-21-33"
    ).as_posix() == "/tmp/crystal_field_2026-04-12_10-21-33_web"


def test_entry_sample_uses_normal_sampler_with_catalog_overrides(monkeypatch):
    from examples.python.families.crystal_field import catalog
    from examples.python.families.crystal_field.sampling import SampleOverrides

    captured: dict[str, SampleOverrides | None] = {}

    def fake_sample(_rng, policy=None, overrides=None):
        assert policy is None
        captured["overrides"] = overrides
        return _synthetic_params()

    monkeypatch.setattr(catalog, "sample", fake_sample)

    entry = {
        "outcome": "colored_diffuse",
        "grid_cfg": GridConfig(rows=5, cols=7, spacing=0.26, offset_rows=True, hole_fraction=0.0),
        "n_lights": 2,
        "wl_min": 550.0,
        "wl_max": 700.0,
    }

    p = catalog._entry_sample(entry, random.Random(0))
    overrides = captured["overrides"]

    assert p == _synthetic_params()
    assert isinstance(overrides, SampleOverrides)
    assert overrides.outcome == "colored_diffuse"
    assert overrides.grid == entry["grid_cfg"]
    assert overrides.n_lights == 2
    assert overrides.path_style == "channel"
    assert overrides.n_waypoints == 8
    assert overrides.ambient_style == "corners"
    assert overrides.speed == 0.12
    assert overrides.spectrum is not None
    assert overrides.spectrum.wavelength_min == 550.0
    assert overrides.spectrum.wavelength_max == 700.0


def test_failure_distance_is_zero_for_passing():
    """Baseline: a passing result should have _failure_distance near 0."""
    from anim.family import Verdict
    from examples.python.families.crystal_field.catalog import (
        _failure_distance,
    )
    from examples.python.families.crystal_field.check import MeasurementResult

    # Fabricate a metrics dict that lies safely inside every threshold.
    good_metrics = {
        "mean_luma": 0.35,
        "p05_luma": 0.10,
        "interdecile_luma_range": 0.40,
        "local_contrast": 0.03,
        "bright_neutral_fraction": 0.10,
        "near_black_fraction": 0.03,
        "mean_saturation": 0.40,
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


def test_failure_distance_increases_with_low_interdecile_range():
    """A metrics dict that fails MIN_INTERDECILE_LUMA_RANGE should produce a positive score."""
    from anim.family import Verdict
    from examples.python.families.crystal_field.catalog import (
        _failure_distance,
    )
    from examples.python.families.crystal_field.check import MeasurementResult

    washed_metrics = {
        "mean_luma": 0.35,
        "p05_luma": 0.10,
        "interdecile_luma_range": MIN_INTERDECILE_LUMA_RANGE / 2,
        "local_contrast": 0.03,
        "bright_neutral_fraction": 0.10,
        "near_black_fraction": 0.03,
        "mean_saturation": 0.40,
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
    # Distance should reflect the robust-range shortfall.
    assert _failure_distance(result) > 0.0


def _synthetic_metrics(**overrides: float) -> dict[str, float]:
    metrics = {
        "mean_luma": 0.35,
        "p05_luma": 0.10,
        "interdecile_luma_range": 0.40,
        "local_contrast": 0.03,
        "bright_neutral_fraction": 0.10,
        "near_black_fraction": 0.03,
        "mean_saturation": 0.40,
        "moving_radius_min": 0.015,
        "moving_radius_mean": 0.024,
        "moving_radius_max": 0.035,
        "ambient_radius_min": 0.010,
        "ambient_radius_mean": 0.014,
        "ambient_radius_max": 0.025,
        "moving_to_ambient_radius_ratio": 1.71,
    }
    metrics.update(overrides)
    return metrics


def _synthetic_params() -> Params:
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
        albedo=0.85,
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
    return Params(
        grid=grid,
        shape=shape,
        material=material,
        light=light,
        look=LookConfig(exposure=-4.5),
        build_seed=42,
    )


def test_find_good_params_replays_look_variants_before_resampling_scene(monkeypatch):
    """One structural candidate should try multiple looks before being discarded."""
    from anim.family import Verdict
    from examples.python.families.crystal_field import catalog
    from examples.python.families.crystal_field.check import MeasurementResult

    p = _synthetic_params()
    entry_calls = 0
    seen_looks: list[LookConfig] = []

    def fake_entry_sample(_entry, _rng):
        nonlocal entry_calls
        entry_calls += 1
        return p

    def fake_build(_params):
        return object()

    def fake_measure_look_variants(_params, _animate, looks):
        materialized = list(looks)
        seen_looks.extend(look for _name, look in materialized)
        assert len(materialized) == 3
        yield (
            materialized[0][0],
            materialized[0][1],
            MeasurementResult(
                metrics=_synthetic_metrics(mean_luma=0.05),
                verdict=Verdict(False, "too dark"),
            ),
        )
        yield (
            materialized[1][0],
            materialized[1][1],
            MeasurementResult(
                metrics=_synthetic_metrics(),
                verdict=Verdict(True, "pass"),
            ),
        )

    monkeypatch.setattr(catalog, "_entry_sample", fake_entry_sample)
    monkeypatch.setattr(catalog, "build", fake_build)
    monkeypatch.setattr(catalog, "measure_look_variants", fake_measure_look_variants)

    found, result = catalog._find_good_params(
        {"outcome": "black_diffuse"},
        random.Random(0),
        max_attempts=5,
        look_attempts=3,
    )

    assert result.verdict.ok
    assert entry_calls == 1
    assert found.look == seen_looks[1]


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
