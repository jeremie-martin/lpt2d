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

ROOM_BOX_WALL_INDICES = {
    "three_spheres.json": [3, 4, 5, 6],
    "twin_prisms.json": [0, 1, 2, 3],
    "diamond.json": [1, 2, 3, 4],
    "crystal_field.json": [33, 34, 35, 36],
    "prism.json": [3, 4, 5, 6],
    "double_slit.json": [3, 4, 5, 6],
    "lens.json": [0, 1, 2, 3],
    "mirror_box.json": [0, 1, 2, 3],
    "ring.json": [8, 9, 10, 11],
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


def test_room_box_cameras_match_wall_bounds():
    for path in sorted(SCENE_DIR.glob("*.json")):
        wall_indices = ROOM_BOX_WALL_INDICES.get(path.name)
        if wall_indices is None:
            continue
        data = _load(path)
        room = [data["shapes"][index] for index in wall_indices]
        xs = [p[0] for wall in room for p in (wall["a"], wall["b"])]
        ys = [p[1] for wall in room for p in (wall["a"], wall["b"])]
        bounds = [min(xs), min(ys), max(xs), max(ys)]
        assert data["camera"]["bounds"] == bounds, f"{path} camera does not match room bounds"
