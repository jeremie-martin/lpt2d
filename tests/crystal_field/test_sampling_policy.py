"""Sampling policy tests for current crystal_field feedback."""

from __future__ import annotations

import random
from dataclasses import replace

import pytest

from examples.python.families.crystal_field.catalog import LIGHT_COLORS, _build_catalog_entries
from examples.python.families.crystal_field.materials import build_materials
from examples.python.families.crystal_field.params import (
    WALL_ID,
    AmbientConfig,
    LightConfig,
    LightSpectrumConfig,
    MaterialConfig,
    range_spectrum,
)
from examples.python.families.crystal_field.sampling import (
    DEFAULT_SAMPLER_POLICY,
    OUTCOMES,
    _brushed_metal_material,
    _random_look,
    ambient_for_moving_spectrum,
    sample,
)


def test_catalog_light_colors_exclude_yellow():
    assert list(LIGHT_COLORS) == ["white", "orange", "deep_orange"]
    entries = _build_catalog_entries()
    assert len(entries) == 72
    assert all(e["light_color"] != "yellow" for e in entries)
    assert all(e["outcome"] != "glass" for e in entries)


def test_general_warm_spectra_exclude_yellow_ranges():
    assert DEFAULT_SAMPLER_POLICY.light.warm_spectra == (
        (550.0, 700.0),
        (570.0, 700.0),
    )


def test_active_free_sampler_temporarily_excludes_glass():
    assert OUTCOMES == (
        "black_diffuse",
        "gray_diffuse",
        "colored_diffuse",
        "brushed_metal",
    )
    assert OUTCOMES == DEFAULT_SAMPLER_POLICY.active_outcomes

    rng = random.Random(123)
    outcomes = {sample(rng).material.outcome for _ in range(200)}

    assert outcomes == set(OUTCOMES)


def test_sampler_policy_can_force_a_targeted_outcome():
    policy = replace(DEFAULT_SAMPLER_POLICY, outcomes=(("glass", 1.0),))

    p = sample(random.Random(1), policy=policy)

    assert p.material.outcome == "glass"
    assert p.shape.kind == "circle"


def test_complementary_ambient_is_blueish_for_orange_ranges():
    ambient = ambient_for_moving_spectrum(
        random.Random(3),
        style="corners",
        intensity=0.3,
        moving_spectrum=range_spectrum(550.0, 700.0),
    )

    assert ambient.spectrum.type == "color"
    assert ambient.spectrum.linear_rgb[0] == pytest.approx(0.0)
    assert ambient.spectrum.linear_rgb[2] == pytest.approx(1.0)
    assert 0.25 <= ambient.spectrum.white_mix <= 0.75


def test_full_range_light_keeps_white_ambient():
    ambient = ambient_for_moving_spectrum(
        random.Random(3),
        style="corners",
        intensity=0.3,
        moving_spectrum=LightSpectrumConfig(),
    )

    assert ambient.spectrum.type == "range"
    assert ambient.spectrum.wavelength_min == 380.0
    assert ambient.spectrum.wavelength_max == 780.0


def test_random_look_samples_highlights_shadows_and_disables_vignette():
    rng = random.Random(7)
    material = MaterialConfig(outcome="gray_diffuse", albedo=0.8, fill=0.16)
    light = LightConfig(
        n_lights=1,
        path_style="channel",
        n_waypoints=8,
        ambient=AmbientConfig(style="corners", intensity=0.3),
        speed=0.12,
        moving_intensity=0.8,
        wavelength_min=380.0,
        wavelength_max=780.0,
    )

    looks = [_random_look(rng, material, light) for _ in range(100)]

    assert all(look.vignette == 0.0 for look in looks)
    assert all(look.vignette_radius == 0.7 for look in looks)
    assert all(-0.22 <= look.highlights <= 0.22 for look in looks)
    assert all(-0.22 <= look.shadows <= 0.22 for look in looks)
    assert any(abs(look.highlights) > 1e-6 for look in looks)
    assert any(abs(look.shadows) > 1e-6 for look in looks)


def test_random_look_policy_controls_optional_effect_probabilities():
    rng = random.Random(7)
    material = MaterialConfig(outcome="gray_diffuse", albedo=0.8, fill=0.16)
    light = LightConfig(
        n_lights=1,
        path_style="channel",
        n_waypoints=8,
        ambient=AmbientConfig(style="corners", intensity=0.3),
        speed=0.12,
        moving_intensity=0.8,
        wavelength_min=380.0,
        wavelength_max=780.0,
    )
    policy = replace(
        DEFAULT_SAMPLER_POLICY.look,
        temperature_enabled_probability=0.0,
        chromatic_aberration_enabled_probability=0.0,
    )

    looks = [_random_look(rng, material, light, policy=policy) for _ in range(20)]

    assert all(look.temperature == 0.0 for look in looks)
    assert all(look.chromatic_aberration == 0.0 for look in looks)


def test_brushed_metal_sampler_sets_wall_metallic_and_object_ior_ranges():
    rng = random.Random(11)
    materials = [_brushed_metal_material(rng) for _ in range(100)]

    assert all(0.66 <= m.wall_metallic <= 1.0 for m in materials)
    assert all(1.0 <= m.ior <= 1.4 for m in materials)
    assert any(m.ior == 1.0 for m in materials)
    assert any(m.ior > 1.0 for m in materials)


def test_brushed_metal_materials_apply_wall_metallic_and_object_ior():
    cfg = MaterialConfig(
        outcome="brushed_metal",
        albedo=0.82,
        fill=0.10,
        ior=1.27,
        color_names=[],
        wall_metallic=0.73,
    )

    mats = build_materials(cfg)

    assert mats[WALL_ID].metallic == pytest.approx(0.73)
    assert mats["crystal"].ior == pytest.approx(1.27)


def test_non_brushed_materials_keep_default_wall_metallic():
    cfg = MaterialConfig(
        outcome="gray_diffuse",
        albedo=0.82,
        fill=0.16,
        wall_metallic=0.20,
    )

    mats = build_materials(cfg)

    assert mats[WALL_ID].metallic == pytest.approx(1.0)
