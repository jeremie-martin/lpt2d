"""Material construction tests for crystal_field."""

from __future__ import annotations

from examples.python.families.crystal_field.materials import build_materials
from examples.python.families.crystal_field.params import MaterialConfig


def test_brushed_metal_materials_are_transmissive():
    cfg = MaterialConfig(
        outcome="brushed_metal",
        albedo=0.82,
        fill=0.11,
        color_names=["cyan", None],
    )

    mats = build_materials(cfg)

    brushed = [mat for mat_id, mat in mats.items() if mat_id.startswith("crystal")]
    assert brushed
    for mat in brushed:
        assert abs(mat.transmission - 1.0) < 1e-6
        assert abs(mat.metallic - 1.0) < 1e-6
        assert abs(mat.roughness - 0.6) < 1e-6
        assert abs(mat.albedo - cfg.albedo) < 1e-6
        assert abs(mat.fill - cfg.fill) < 1e-6
