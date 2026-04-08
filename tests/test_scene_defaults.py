from __future__ import annotations

import json
from pathlib import Path

SCENE_DIR = Path("scenes")
ROOM_WALL_IDS = ("wall_floor", "wall_ceiling", "wall_left", "wall_right")
EXACT_ROOM_CAMERA_SCENES = {
    "crystal_field.json",
    "diamond.json",
    "double_slit.json",
    "lens.json",
    "mirror_box.json",
    "prism.json",
    "ring.json",
    "three_spheres.json",
    "twin_prisms.json",
}
DEFAULT_LOOK = {
    "exposure": -5.0,
    "contrast": 1.0,
    "gamma": 2.0,
    "tonemap": "reinhardx",
    "white_point": 0.5,
    "normalize": "rays",
    "normalize_ref": 0.0,
    "normalize_pct": 1.0,
    "ambient": 0.0,
    "background": [0.0, 0.0, 0.0],
    "opacity": 1.0,
    "saturation": 1.0,
    "vignette": 0.0,
    "vignette_radius": 0.699999988079071,
    "temperature": 0.0,
    "highlights": 0.0,
    "shadows": 0.0,
    "hue_shift": 0.0,
    "grain": 0.0,
    "grain_seed": 0,
    "chromatic_aberration": 0.0,
}
DEFAULT_TRACE = {
    "rays": 10_000_000,
    "batch": 200_000,
    "depth": 12,
    "intensity": 1.0,
    "seed_mode": "deterministic",
}


def _iter_scene_paths() -> list[Path]:
    return sorted(SCENE_DIR.glob("*.json"))


def _load(path: Path) -> dict:
    return json.loads(path.read_text())


def _assert_authored_shape(
    path: Path,
    shape: dict,
    context: str,
    entity_ids: set[str],
    material_ids: set[str],
) -> None:
    shape_id = shape.get("id")
    assert isinstance(shape_id, str) and shape_id, (
        f"{path} {context} is missing a non-empty shape id"
    )
    assert not shape_id.startswith("root_"), f"{path} still uses legacy shape id {shape_id!r}"
    assert shape_id not in entity_ids, f"{path} has duplicate entity id {shape_id!r}"
    entity_ids.add(shape_id)

    assert "material" not in shape, f"{path} {shape_id!r} still uses inline material payloads"
    assert "material_id" in shape, f"{path} {shape_id!r} is missing material_id"
    assert shape["material_id"] in material_ids, (
        f"{path} {shape_id!r} references unknown material_id {shape['material_id']!r}"
    )


def _assert_authored_light(path: Path, light: dict, context: str, entity_ids: set[str]) -> None:
    light_id = light.get("id")
    assert isinstance(light_id, str) and light_id, (
        f"{path} {context} is missing a non-empty light id"
    )
    assert not light_id.startswith("root_"), f"{path} still uses legacy light id {light_id!r}"
    assert light_id not in entity_ids, f"{path} has duplicate entity id {light_id!r}"
    entity_ids.add(light_id)


def test_authored_json_uses_explicit_look_trace_and_groups():
    for path in _iter_scene_paths():
        data = _load(path)
        assert data.get("look") == DEFAULT_LOOK, (
            f"{path} should store the full canonical look block"
        )
        assert data.get("trace") == DEFAULT_TRACE, (
            f"{path} should store the full canonical trace block"
        )
        assert "groups" in data, f"{path} should include groups explicitly"
        assert isinstance(data["groups"], list), f"{path} groups must be an array"


def test_repo_authored_json_is_strict_and_id_coherent():
    for path in _iter_scene_paths():
        data = _load(path)
        assert data.get("version") == 11, f"{path} must declare version 11"
        assert "camera" in data, f"{path} must include an explicit camera block"
        assert "canvas" in data, f"{path} must include an explicit canvas block"

        material_ids = set(data.get("materials", {}))
        assert material_ids, f"{path} must define a named materials library"
        for material_id, material in data["materials"].items():
            assert "emission" in material, (
                f"{path} material {material_id!r} must store explicit emission"
            )

        entity_ids: set[str] = set()

        for shape in data.get("shapes", []):
            _assert_authored_shape(path, shape, "root shape", entity_ids, material_ids)
        for light in data.get("lights", []):
            _assert_authored_light(path, light, "root light", entity_ids)
        for group in data.get("groups", []):
            group_id = group.get("id")
            assert isinstance(group_id, str) and group_id, (
                f"{path} has a group without a non-empty id"
            )
            assert not group_id.startswith("group_"), (
                f"{path} still uses legacy group id {group_id!r}"
            )
            assert group_id not in entity_ids, f"{path} has duplicate entity id {group_id!r}"
            entity_ids.add(group_id)
            assert set(group) == {"id", "transform", "shapes", "lights"}, (
                f"{path} group {group_id!r} has non-canonical keys"
            )
            for shape in group.get("shapes", []):
                _assert_authored_shape(
                    path, shape, f"group {group_id!r} shape", entity_ids, material_ids
                )
            for light in group.get("lights", []):
                _assert_authored_light(path, light, f"group {group_id!r} light", entity_ids)


def test_room_box_cameras_match_wall_bounds():
    for path in sorted(SCENE_DIR.glob("*.json")):
        if path.name not in EXACT_ROOM_CAMERA_SCENES:
            continue
        data = _load(path)
        room_shapes = {shape["id"]: shape for shape in data["shapes"]}
        room = [room_shapes[wall_id] for wall_id in ROOM_WALL_IDS]
        xs = [p[0] for wall in room for p in (wall["a"], wall["b"])]
        ys = [p[1] for wall in room for p in (wall["a"], wall["b"])]
        bounds = [min(xs), min(ys), max(xs), max(ys)]
        assert data["camera"]["bounds"] == bounds, f"{path} camera does not match room bounds"
