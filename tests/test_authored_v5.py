from __future__ import annotations

import json

import pytest

from anim import renderer as renderer_mod
from anim.types import BeamLight, Circle, Frame, Group, Material, Scene, Segment, Shot


def _make_bound_scene() -> Scene:
    return Scene(
        materials={"glass": Material(ior=1.5, transmission=1.0)},
        shapes=[
            Circle(id="lens_a", center=[-0.5, 0.0], radius=0.2, material_id="glass"),
            Circle(id="lens_b", center=[0.5, 0.0], radius=0.2, material_id="glass"),
        ],
        lights=[
            BeamLight(
                id="beam_main",
                origin=[-1.0, 0.0],
                direction=[1.0, 0.0],
                angular_width=0.02,
                intensity=1.0,
            )
        ],
        groups=[
            Group(
                id="cluster",
                shapes=[
                    Segment(
                        id="cluster_edge",
                        a=[-0.1, -0.2],
                        b=[0.1, -0.2],
                        material=Material(albedo=0.0),
                    )
                ],
            )
        ],
    ).sync_material_bindings()


def test_v5_round_trip_preserves_ids_and_material_bindings():
    shot = Shot(name="authored_v5", scene=_make_bound_scene())

    loaded = Shot.from_json(shot.to_json())

    assert loaded.scene.require_shape("lens_a").material_id == "glass"
    assert loaded.scene.require_shape("lens_b").material_id == "glass"
    assert loaded.scene.require_light("beam_main").id == "beam_main"
    assert loaded.scene.require_group("cluster").id == "cluster"
    assert loaded.scene.require_shape("cluster_edge").id == "cluster_edge"


def test_v5_rejects_duplicate_entity_ids():
    scene = Scene(
        shapes=[
            Circle(id="dup", radius=0.2),
            Circle(id="dup", center=[1.0, 0.0], radius=0.3),
        ]
    )

    with pytest.raises(ValueError, match="duplicate entity id: dup"):
        scene.validate()


def test_v5_rejects_unknown_material_id():
    scene = Scene(shapes=[Circle(id="lens", radius=0.2, material_id="missing")])

    with pytest.raises(ValueError, match="unknown material_id: missing"):
        scene.validate()


def test_v5_rejects_shape_without_material_payload():
    bad = {
        "version": 5,
        "name": "bad",
        "shapes": [{"id": "lens", "type": "circle", "center": [0.0, 0.0], "radius": 0.2}],
        "lights": [],
        "groups": [],
    }

    with pytest.raises(
        ValueError, match="shape entries must declare exactly one of material and material_id"
    ):
        Shot.from_json(json.dumps(bad))


def test_scene_id_lookup_helpers_cover_shapes_lights_and_groups():
    scene = _make_bound_scene()

    assert scene.find_shape("lens_a") is scene.shapes[0]
    assert scene.find_light("beam_main") is scene.lights[0]
    assert scene.find_group("cluster") is scene.groups[0]
    assert scene.find_shape("missing") is None
    assert scene.find_light("missing") is None
    assert scene.find_group("missing") is None

    with pytest.raises(ValueError, match="unknown shape id: missing"):
        scene.require_shape("missing")
    with pytest.raises(ValueError, match="unknown light id: missing"):
        scene.require_light("missing")
    with pytest.raises(ValueError, match="unknown group id: missing"):
        scene.require_group("missing")


def test_shared_material_edits_propagate_and_detach_to_inline():
    scene = _make_bound_scene()
    lens_a = scene.require_shape("lens_a")
    lens_b = scene.require_shape("lens_b")

    scene.materials["glass"].ior = 1.7
    scene.sync_material_bindings()

    assert lens_a.material.ior == pytest.approx(1.7)
    assert lens_b.material.ior == pytest.approx(1.7)

    scene.detach_material("lens_a")
    scene.materials["glass"].ior = 1.9
    scene.sync_material_bindings()

    assert lens_a.material_id is None
    assert lens_a.material.ior == pytest.approx(1.7)
    assert lens_b.material_id == "glass"
    assert lens_b.material.ior == pytest.approx(1.9)

    scene.bind_material("lens_a", "glass")
    assert lens_a.material_id == "glass"
    assert lens_a.material.ior == pytest.approx(1.9)


def test_shot_to_json_does_not_mutate_shared_scene_ids():
    shot = Shot(scene=Scene(shapes=[Circle(center=[0.0, 0.0], radius=0.2, material=Material())]))
    derived = shot.with_look(exposure=1.0)

    derived.to_json()

    assert shot.scene.shapes[0].id == ""
    assert derived.scene.shapes[0].id == ""


def test_wire_json_does_not_mutate_scene_or_force_material_sync():
    scene = Scene(
        materials={"glass": Material(ior=1.7, transmission=1.0)},
        shapes=[Circle(center=[0.0, 0.0], radius=0.2, material_id="glass")],
    )

    wire = json.loads(
        renderer_mod._build_wire_json(
            Frame(scene=scene),
            camera=None,
            shot_camera=None,
            aspect=16.0 / 9.0,
        )
    )

    assert scene.shapes[0].id == ""
    assert scene.shapes[0].material.ior == pytest.approx(1.0)
    assert wire["shapes"][0]["material_id"] == "glass"
    assert "material" not in wire["shapes"][0]


def test_save_load_modify_by_id_preserves_shared_material_meaning(tmp_path):
    path = tmp_path / "authored_scene.json"
    shot = Shot(name="roundtrip", scene=_make_bound_scene())
    shot.save(path)

    loaded = Shot.load(path)
    beam = loaded.scene.require_light("beam_main")
    assert isinstance(beam, BeamLight)
    beam.origin[1] = 0.15

    lens = loaded.scene.require_shape("lens_a")
    lens.radius = 0.35

    loaded.scene.require_group("cluster").transform.translate = [0.25, -0.1]
    loaded.save(path)

    reloaded = Shot.load(path)
    lens_reloaded = reloaded.scene.require_shape("lens_a")
    beam_reloaded = reloaded.scene.require_light("beam_main")

    assert lens_reloaded.radius == pytest.approx(0.35)
    assert lens_reloaded.material_id == "glass"
    assert isinstance(beam_reloaded, BeamLight)
    assert beam_reloaded.origin == [-1.0, 0.15]

    wire = json.loads(
        renderer_mod._build_wire_json(
            Frame(scene=reloaded.scene),
            camera=None,
            shot_camera=None,
            aspect=16.0 / 9.0,
        )
    )
    assert wire["version"] == 5
    lens_wire = next(shape for shape in wire["shapes"] if shape["id"] == "lens_a")
    assert lens_wire["material_id"] == "glass"
