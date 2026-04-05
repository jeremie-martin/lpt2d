from __future__ import annotations

import json
from pathlib import Path

from anim.types import Look


SCENE_DIR = Path("scenes")
BENCH_DIR = Path("bench/scenes")

LOOK_DEFAULTS = {
    "exposure": Look().exposure,
    "gamma": Look().gamma,
    "tonemap": Look().tonemap,
    "white_point": Look().white_point,
    "normalize": Look().normalize,
}

ROOM_BOX_WALL_IDS = {
    "three_spheres.json": [
        "root_shape_segment_3",
        "root_shape_segment_4",
        "root_shape_segment_5",
        "root_shape_segment_6",
    ],
    "twin_prisms.json": [
        "root_shape_segment_0",
        "root_shape_segment_1",
        "root_shape_segment_2",
        "root_shape_segment_3",
    ],
    "diamond.json": [
        "root_shape_segment_1",
        "root_shape_segment_2",
        "root_shape_segment_3",
        "root_shape_segment_4",
    ],
    "crystal_field.json": [
        "root_shape_segment_33",
        "root_shape_segment_34",
        "root_shape_segment_35",
        "root_shape_segment_36",
    ],
    "prism.json": [
        "root_shape_segment_3",
        "root_shape_segment_4",
        "root_shape_segment_5",
        "root_shape_segment_6",
    ],
    "double_slit.json": [
        "root_shape_segment_3",
        "root_shape_segment_4",
        "root_shape_segment_5",
        "root_shape_segment_6",
    ],
    "lens.json": [
        "root_shape_segment_0",
        "root_shape_segment_1",
        "root_shape_segment_2",
        "root_shape_segment_3",
    ],
    "mirror_box.json": [
        "root_shape_segment_0",
        "root_shape_segment_1",
        "root_shape_segment_2",
        "root_shape_segment_3",
    ],
    "ring.json": [
        "root_shape_segment_8",
        "root_shape_segment_9",
        "root_shape_segment_10",
        "root_shape_segment_11",
    ],
}


def _iter_scene_paths() -> list[Path]:
    return sorted(SCENE_DIR.glob("*.json")) + sorted(BENCH_DIR.glob("bench_*.json"))


def _load(path: Path) -> dict:
    return json.loads(path.read_text())


def test_authored_json_omits_trace_batch():
    for path in _iter_scene_paths():
        data = _load(path)
        trace = data.get("trace", {})
        assert "batch" not in trace, f"{path} still serializes trace.batch"


def test_repo_scene_look_blocks_match_defaults():
    for path in sorted(SCENE_DIR.glob("*.json")):
        data = _load(path)
        look = data.get("look", {})
        assert look == LOOK_DEFAULTS, f"{path} has stale look defaults: {look}"


def test_repo_authored_json_is_v5_and_id_coherent():
    for path in _iter_scene_paths():
        data = _load(path)
        assert data.get("version") == 5, f"{path} must declare version 5"

        material_ids = set(data.get("materials", {}))
        entity_ids: set[str] = set()

        def check_shape(shape: dict, context: str) -> None:
            shape_id = shape.get("id")
            assert isinstance(shape_id, str) and shape_id, f"{path} {context} is missing a non-empty shape id"
            assert shape_id not in entity_ids, f"{path} has duplicate entity id {shape_id!r}"
            entity_ids.add(shape_id)

            has_inline = "material" in shape
            has_binding = "material_id" in shape
            assert has_inline != has_binding, f"{path} {shape_id!r} must declare exactly one of material/material_id"
            if has_binding:
                assert shape["material_id"] in material_ids, (
                    f"{path} {shape_id!r} references unknown material_id {shape['material_id']!r}"
                )

        def check_light(light: dict, context: str) -> None:
            light_id = light.get("id")
            assert isinstance(light_id, str) and light_id, f"{path} {context} is missing a non-empty light id"
            assert light_id not in entity_ids, f"{path} has duplicate entity id {light_id!r}"
            entity_ids.add(light_id)

        for shape in data.get("shapes", []):
            check_shape(shape, "root shape")
        for light in data.get("lights", []):
            check_light(light, "root light")
        for group in data.get("groups", []):
            group_id = group.get("id")
            assert isinstance(group_id, str) and group_id, f"{path} has a group without a non-empty id"
            assert group_id not in entity_ids, f"{path} has duplicate entity id {group_id!r}"
            entity_ids.add(group_id)
            for shape in group.get("shapes", []):
                check_shape(shape, f"group {group_id!r} shape")
            for light in group.get("lights", []):
                check_light(light, f"group {group_id!r} light")


def test_room_box_cameras_match_wall_bounds():
    for path in sorted(SCENE_DIR.glob("*.json")):
        wall_ids = ROOM_BOX_WALL_IDS.get(path.name)
        if wall_ids is None:
            continue
        data = _load(path)
        room_shapes = {shape["id"]: shape for shape in data["shapes"]}
        room = [room_shapes[wall_id] for wall_id in wall_ids]
        xs = [p[0] for wall in room for p in (wall["a"], wall["b"])]
        ys = [p[1] for wall in room for p in (wall["a"], wall["b"])]
        bounds = [min(xs), min(ys), max(xs), max(ys)]
        assert data["camera"]["bounds"] == bounds, f"{path} camera does not match room bounds"
