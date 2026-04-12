"""Sampling policy tests for current crystal_field feedback."""

from __future__ import annotations

import colorsys
import random
from dataclasses import replace

import pytest

from examples.python.families.crystal_field.catalog import LIGHT_COLORS, _build_catalog_entries
from examples.python.families.crystal_field.materials import build_materials
from examples.python.families.crystal_field.params import (
    WALL_ID,
    AmbientConfig,
    GridConfig,
    LightConfig,
    LightSpectrumConfig,
    MaterialConfig,
    range_spectrum,
)
from examples.python.families.crystal_field.sampling import (
    DEFAULT_SAMPLER_POLICY,
    OUTCOMES,
    SampleOverrides,
    _biased_uniform_low,
    _brushed_metal_material,
    _colored_diffuse_material,
    _gray_diffuse_material,
    _polygon_shape,
    _random_look,
    ambient_for_moving_spectrum,
    sample,
    sample_ambient_for_moving_light,
)
from examples.python.families.crystal_field.scene import rendered_light_intensity


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


def test_active_path_styles_are_channel_and_drift_only():
    assert DEFAULT_SAMPLER_POLICY.light.path_style_weights == (
        ("waypoints", 0.0),
        ("random_walk", 0.0),
        ("vertical_drift", 0.0),
        ("drift", 2.0),
        ("channel", 3.0),
    )

    rng = random.Random(31)
    paths = {sample(rng).light.path_style for _ in range(200)}

    assert paths == {"channel", "drift"}


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


def test_spacing_pack_bias_prefers_lower_spacing_without_changing_range():
    bounds = (0.20, 0.32)
    uniform_rng = random.Random(12)
    packed_rng = random.Random(12)

    uniform = [_biased_uniform_low(uniform_rng, bounds, 1.0) for _ in range(200)]
    packed = [_biased_uniform_low(packed_rng, bounds, 1.4) for _ in range(200)]

    assert all(bounds[0] <= spacing <= bounds[1] for spacing in packed)
    assert all(packed_spacing <= uniform_spacing for packed_spacing, uniform_spacing in zip(packed, uniform, strict=True))
    assert sum(packed) / len(packed) < sum(uniform) / len(uniform)


def test_sparse_polygon_grids_bias_size_factor_upward_without_changing_max():
    policy = replace(
        DEFAULT_SAMPLER_POLICY.shape,
        polygon_size_factor=(0.28, 0.43),
        polygon_sides=((4, 1.0),),
        corner_radius_factor=(0.0, 0.0),
        rotation_probability=0.0,
    )
    sparse_rng = random.Random(12)
    dense_rng = random.Random(12)

    sparse = [
        _polygon_shape(sparse_rng, 1.0, planned_count=12.0, policy=policy).size
        for _ in range(40)
    ]
    dense = [
        _polygon_shape(dense_rng, 1.0, planned_count=36.0, policy=policy).size
        for _ in range(40)
    ]

    assert all(
        sparse_size > dense_size
        for sparse_size, dense_size in zip(sparse, dense, strict=True)
    )
    assert max(sparse) <= policy.polygon_size_factor[1]


def test_triangle_shapes_are_about_fifteen_percent_of_polygons():
    rng = random.Random(17)
    policy = replace(
        DEFAULT_SAMPLER_POLICY.shape,
        corner_radius_factor=(0.0, 0.0),
        rotation_probability=0.0,
    )
    counts = {3: 0, 4: 0, 5: 0, 6: 0}

    for _ in range(2000):
        shape = _polygon_shape(rng, 1.0, planned_count=36.0, policy=policy)
        counts[shape.n_sides] += 1

    triangle_ratio = counts[3] / sum(counts.values())
    assert 0.12 <= triangle_ratio <= 0.18
    assert counts[3] < counts[4]
    assert counts[3] < counts[5]
    assert counts[3] < counts[6]


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
    low, high = DEFAULT_SAMPLER_POLICY.light.ambient.white_mix
    assert low <= ambient.spectrum.white_mix <= high


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


def test_sample_overrides_force_only_catalog_axes():
    grid = GridConfig(rows=5, cols=7, spacing=0.26, offset_rows=True, hole_fraction=0.0)
    spectrum = range_spectrum(550.0, 700.0)

    p = sample(
        random.Random(5),
        overrides=SampleOverrides(
            outcome="colored_diffuse",
            grid=grid,
            n_lights=2,
            path_style="channel",
            n_waypoints=8,
            ambient_style="corners",
            speed=0.12,
            spectrum=spectrum,
        ),
    )

    assert p.material.outcome == "colored_diffuse"
    assert p.grid == grid
    assert p.shape.kind == "polygon"
    assert p.light.n_lights == 2
    assert p.light.path_style == "channel"
    assert p.light.n_waypoints == 8
    assert p.light.ambient.style == "corners"
    assert p.light.speed == pytest.approx(0.12)
    assert p.light.spectrum == spectrum


def test_sampled_ambient_rendered_intensity_is_capped_by_moving_light():
    rng = random.Random(23)
    moving_spectrum = range_spectrum(550.0, 700.0)
    ambient = sample_ambient_for_moving_light(
        rng,
        style="corners",
        moving_intensity=0.75,
        moving_spectrum=moving_spectrum,
    )

    ambient_rendered = rendered_light_intensity(ambient.intensity, ambient.spectrum)
    moving_rendered = rendered_light_intensity(0.75, moving_spectrum)

    assert ambient_rendered <= moving_rendered + 1e-12


def test_free_sampler_never_makes_rendered_ambient_stronger_than_moving_light():
    rng = random.Random(29)

    for _ in range(300):
        p = sample(rng)
        ambient_rendered = rendered_light_intensity(
            p.light.ambient.intensity,
            p.light.ambient.spectrum,
        )
        moving_rendered = rendered_light_intensity(
            p.light.moving_intensity,
            p.light.spectrum,
        )

        assert ambient_rendered <= moving_rendered + 1e-12


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
    assert all(look.vignette_radius == DEFAULT_SAMPLER_POLICY.look.vignette_radius for look in looks)
    assert all(1.0 <= look.saturation <= 2.2 for look in looks)
    assert all(
        DEFAULT_SAMPLER_POLICY.look.highlights[0]
        <= look.highlights
        <= DEFAULT_SAMPLER_POLICY.look.highlights[1]
        for look in looks
    )
    assert all(
        DEFAULT_SAMPLER_POLICY.look.shadows[0]
        <= look.shadows
        <= DEFAULT_SAMPLER_POLICY.look.shadows[1]
        for look in looks
    )
    assert any(look.saturation > 1.0 for look in looks)
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


def test_random_look_applies_warm_spectrum_exposure_gamma_compensation_with_floor():
    material = MaterialConfig(outcome="gray_diffuse", albedo=0.8, fill=0.16)
    policy = replace(
        DEFAULT_SAMPLER_POLICY.look,
        exposure=(-5.0, -5.0),
        gamma=(0.8, 0.8),
        contrast=(1.0, 1.0),
        white_point=(0.5, 0.5),
        saturation=(1.4, 1.4),
        temperature_enabled_probability=0.0,
        highlights=(0.0, 0.0),
        shadows=(0.0, 0.0),
        chromatic_aberration_enabled_probability=0.0,
    )

    def sampled_look(wavelength_min: float, wavelength_max: float):
        light = LightConfig(
            n_lights=1,
            path_style="channel",
            n_waypoints=8,
            ambient=AmbientConfig(style="corners", intensity=0.3),
            speed=0.12,
            moving_intensity=0.8,
            spectrum=range_spectrum(wavelength_min, wavelength_max),
        )
        return _random_look(random.Random(7), material, light, policy=policy)

    white = sampled_look(380.0, 780.0)
    orange = sampled_look(550.0, 700.0)
    deep_orange = sampled_look(570.0, 700.0)

    assert white.exposure == pytest.approx(-5.0)
    assert white.gamma == pytest.approx(1.0)
    assert white.saturation == pytest.approx(1.4)
    assert orange.exposure == pytest.approx(-4.76)
    assert orange.gamma == pytest.approx(1.0)
    assert deep_orange.exposure == pytest.approx(-4.29)
    assert deep_orange.gamma == pytest.approx(1.0)


def test_brushed_metal_sampler_sets_wall_metallic_and_object_ior_ranges():
    rng = random.Random(11)
    materials = [_brushed_metal_material(rng) for _ in range(100)]

    assert all(0.66 <= m.wall_metallic <= 1.0 for m in materials)
    assert all(1.0 <= m.ior <= 1.4 for m in materials)
    assert any(m.ior == 1.0 for m in materials)
    assert any(m.ior > 1.0 for m in materials)


def test_brushed_metal_colored_objects_use_muted_hsv_saturation():
    rng = random.Random(13)
    colors = [
        color
        for _ in range(200)
        for color in _brushed_metal_material(rng).color_names
        if color is not None
    ]

    assert colors
    for color in colors:
        assert isinstance(color, list)
        _hue, saturation, _value = colorsys.rgb_to_hsv(color[0], color[1], color[2])
        assert 0.1 <= saturation <= 0.4


def test_diffuse_samplers_set_subtle_transmission_and_absorption_ranges():
    rng = random.Random(19)
    gray = [_gray_diffuse_material(rng) for _ in range(100)]
    colored = [_colored_diffuse_material(rng) for _ in range(100)]

    assert all(0.0 <= m.transmission <= 0.05 for m in [*gray, *colored])
    assert all(0.75 <= m.absorption <= 1.25 for m in [*gray, *colored])
    assert any(m.transmission > 0.0 for m in [*gray, *colored])


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
