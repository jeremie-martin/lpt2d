"""Per-frame scene animation for evaluation benchmarks.

Applies gentle deterministic motion so each frame exercises a slightly
different scene state without materially changing the overall workload.
"""

from __future__ import annotations

import copy
import math

_STATIC_BOUNDARY_ID_PREFIXES = ("wall_", "room_")


def _phase(index: int, total: int) -> float:
    return index * math.tau / max(total, 1)


def _offset(t: float, phase: float, dx: float = 0.015, dy: float = 0.01) -> tuple[float, float]:
    return (
        math.sin(t * math.tau + phase) * dx,
        math.cos(t * math.tau + phase) * dy,
    )


def _translate_point(point: list[float], dx: float, dy: float) -> list[float]:
    if len(point) < 2:
        return point
    return [point[0] + dx, point[1] + dy]


def _is_close(a: float, b: float, *, tol: float = 1e-6) -> bool:
    return abs(a - b) <= tol


def _is_static_boundary_shape(shape: dict, camera_bounds: list[float] | None) -> bool:
    shape_id = str(shape.get("id", ""))
    if shape_id.startswith(_STATIC_BOUNDARY_ID_PREFIXES):
        return True

    if shape.get("type") != "segment" or camera_bounds is None or len(camera_bounds) != 4:
        return False

    a = shape.get("a")
    b = shape.get("b")
    if not isinstance(a, list) or not isinstance(b, list) or len(a) < 2 or len(b) < 2:
        return False

    left, bottom, right, top = camera_bounds
    x0, y0 = a[0], a[1]
    x1, y1 = b[0], b[1]

    horizontal = (
        _is_close(y0, y1) and _is_close(min(x0, x1), left) and _is_close(max(x0, x1), right)
    )
    vertical = _is_close(x0, x1) and _is_close(min(y0, y1), bottom) and _is_close(max(y0, y1), top)
    return horizontal or vertical


def _animate_shape(shape: dict, t: float, phase: float) -> None:
    dx, dy = _offset(t, phase, dx=0.012, dy=0.008)
    angle = math.sin(t * math.tau + phase) * math.radians(2.0)

    if "center" in shape:
        shape["center"] = _translate_point(list(shape["center"]), dx, dy)

    if "a" in shape:
        shape["a"] = _translate_point(list(shape["a"]), dx, dy)
    if "b" in shape:
        shape["b"] = _translate_point(list(shape["b"]), dx, dy)

    for key in ("p0", "p1", "p2", "p3"):
        if key in shape:
            shape[key] = _translate_point(list(shape[key]), dx, dy)

    if "vertices" in shape:
        shape["vertices"] = [_translate_point(list(vertex), dx, dy) for vertex in shape["vertices"]]

    if "rotation" in shape:
        shape["rotation"] = shape.get("rotation", 0.0) + angle
    if "angle_start" in shape:
        shape["angle_start"] = shape.get("angle_start", 0.0) + angle


def animate_scene(scene_dict: dict, frame: int, total_frames: int) -> dict:
    """Return a modified copy of *scene_dict* with per-frame group transforms.

    The camera, enclosure walls, and top-level lights stay fixed. Only interior
    objects get gentle deterministic motion so the benchmark remains
    representative of frame-to-frame scene updates without exposing the
    background outside the room bounds.
    """
    scene = copy.deepcopy(scene_dict)
    if total_frames <= 1:
        return scene

    t = frame / (total_frames - 1)  # 0..1
    camera_bounds = scene.get("camera", {}).get("bounds")

    groups = scene.get("groups", [])
    for i, group in enumerate(groups):
        transform = group.get("transform", {})
        base_rotate = transform.get("rotate", 0.0)
        base_translate = list(transform.get("translate", [0.0, 0.0]))

        phase = _phase(i, len(groups))
        angle = math.sin(t * math.tau + phase) * math.radians(3)
        dx, dy = _offset(t, phase)

        transform["rotate"] = base_rotate + angle
        transform["translate"] = [base_translate[0] + dx, base_translate[1] + dy]
        group["transform"] = transform

    shapes = scene.get("shapes", [])
    for i, shape in enumerate(shapes):
        if _is_static_boundary_shape(shape, camera_bounds):
            continue
        _animate_shape(shape, t, _phase(i, len(shapes)))

    return scene
