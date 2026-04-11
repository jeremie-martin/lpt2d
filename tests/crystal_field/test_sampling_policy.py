"""Sampling policy tests for current crystal_field feedback."""

from __future__ import annotations

import random

import pytest

from examples.python.families.crystal_field.catalog import LIGHT_COLORS, _build_catalog_entries
from examples.python.families.crystal_field.materials import build_materials
from examples.python.families.crystal_field.params import (
    AmbientConfig,
    LightConfig,
    MaterialConfig,
    WALL_ID,
)
from examples.python.families.crystal_field.sampling import (
    _WARM_SPECTRA,
    _brushed_metal_material,
    _random_look,
)


def test_catalog_light_colors_exclude_yellow():
    assert list(LIGHT_COLORS) == ["white", "orange", "deep_orange"]
    entries = _build_catalog_entries()
    assert len(entries) == 90
    assert all(e["light_color"] != "yellow" for e in entries)


def test_general_warm_spectra_exclude_yellow_ranges():
    assert _WARM_SPECTRA == [
        (550.0, 700.0),
        (570.0, 700.0),
    ]


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
