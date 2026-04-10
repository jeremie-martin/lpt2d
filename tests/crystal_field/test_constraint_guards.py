"""Constraint-guard tests for crystal_field check.py.

The sampler already suppresses these combinations, so these guards only
fire for manually-authored or manually-loaded Params.  The tests
construct deliberately-invalid Params and confirm check.py rejects each
with the expected verdict summary — belt-and-suspenders.
"""

from __future__ import annotations

from examples.python.families.crystal_field.check import _check_constraint_guards
from examples.python.families.crystal_field.params import (
    AmbientConfig,
    GridConfig,
    LightConfig,
    LookConfig,
    MaterialConfig,
    Params,
    ShapeConfig,
)


def _base_params(**overrides) -> Params:
    """Build a baseline Params that passes every guard (for mutation)."""
    grid = GridConfig(rows=5, cols=7, spacing=0.26, offset_rows=True, hole_fraction=0.0)
    shape = ShapeConfig(
        kind="circle",
        size=0.08,
        n_sides=0,
        corner_radius=0.0,
        rotation=None,
    )
    material = MaterialConfig(
        style="glass",
        ior=1.5,
        cauchy_b=20_000.0,
        absorption=1.0,
        fill=0.1,
        n_color_groups=0,
        diffuse_style="dark",
        color_names=[],
        albedo=0.8,
    )
    light = LightConfig(
        n_lights=1,
        path_style="channel",
        n_waypoints=8,
        ambient=AmbientConfig(style="corners", intensity=0.25),
        speed=0.12,
        moving_intensity=0.8,
        wavelength_min=380.0,
        wavelength_max=780.0,
    )
    look = LookConfig(exposure=-4.5)
    p = Params(grid=grid, shape=shape, material=material, light=light, look=look, build_seed=42)
    for key, value in overrides.items():
        if "." in key:
            obj_name, field_name = key.split(".", 1)
            sub = getattr(p, obj_name)
            setattr(sub, field_name, value)
        else:
            setattr(p, key, value)
    return p


def test_baseline_passes_guards():
    """The baseline Params (no overrides) must pass all constraint guards."""
    p = _base_params()
    assert _check_constraint_guards(p) is None


def test_glass_cauchy_b_above_cap_rejected():
    p = _base_params()
    p.material.cauchy_b = 35_000.0
    verdict = _check_constraint_guards(p)
    assert verdict is not None
    assert not verdict.ok
    assert "cauchy_b" in verdict.summary


def test_glass_cauchy_b_at_cap_accepted():
    """Exactly 30000 is fine (strict > 30000 triggers rejection)."""
    p = _base_params()
    p.material.cauchy_b = 30_000.0
    assert _check_constraint_guards(p) is None


def test_warm_light_plus_positive_temperature_rejected():
    p = _base_params()
    p.light.wavelength_min = 550.0  # warm (≥ 500)
    p.light.wavelength_max = 700.0
    p.look.temperature = 0.3
    verdict = _check_constraint_guards(p)
    assert verdict is not None
    assert not verdict.ok
    assert "temperature" in verdict.summary


def test_warm_light_with_zero_temperature_accepted():
    p = _base_params()
    p.light.wavelength_min = 550.0
    p.light.wavelength_max = 700.0
    p.look.temperature = 0.0
    assert _check_constraint_guards(p) is None


def test_cold_light_plus_positive_temperature_accepted():
    """Full-spectrum light + positive temperature is fine."""
    p = _base_params()
    # wavelength_min=380 (default) is < 500
    p.look.temperature = 0.3
    assert _check_constraint_guards(p) is None


def test_glass_plus_chromatic_aberration_rejected():
    p = _base_params()
    # p.material.style == 'glass' by default
    p.look.chromatic_aberration = 0.003
    verdict = _check_constraint_guards(p)
    assert verdict is not None
    assert not verdict.ok
    assert "chromatic_aberration" in verdict.summary


def test_diffuse_plus_chromatic_aberration_accepted():
    p = _base_params()
    p.material.style = "diffuse"
    p.look.chromatic_aberration = 0.003
    assert _check_constraint_guards(p) is None


def test_glass_plus_zero_chromatic_aberration_accepted():
    p = _base_params()
    p.look.chromatic_aberration = 0.0
    assert _check_constraint_guards(p) is None
