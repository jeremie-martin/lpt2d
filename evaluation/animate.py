"""Per-frame scene animation for evaluation benchmarks.

Applies gentle deterministic motion so each frame exercises a slightly
different scene state without materially changing the overall workload.
"""

from __future__ import annotations

import copy
import math


def _phase(index: int, total: int) -> float:
    return index * math.tau / max(total, 1)


def _offset(t: float, phase: float, dx: float = 0.015, dy: float = 0.01) -> tuple[float, float]:
    return (
        math.sin(t * math.tau + phase) * dx,
        math.cos(t * math.tau + phase) * dy,
    )


def _rotate_vec(x: float, y: float, angle: float) -> list[float]:
    c = math.cos(angle)
    s = math.sin(angle)
    return [x * c - y * s, x * s + y * c]


def _translate_point(point: list[float], dx: float, dy: float) -> list[float]:
    if len(point) < 2:
        return point
    return [point[0] + dx, point[1] + dy]


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


def _animate_light(light: dict, t: float, phase: float) -> None:
    dx, dy = _offset(t, phase, dx=0.02, dy=0.014)
    angle = math.sin(t * math.tau + phase) * math.radians(3.0)

    if "pos" in light:
        light["pos"] = _translate_point(list(light["pos"]), dx, dy)
    if "position" in light:
        light["position"] = _translate_point(list(light["position"]), dx, dy)
    if "direction" in light:
        direction = list(light["direction"])
        if len(direction) >= 2:
            light["direction"] = _rotate_vec(direction[0], direction[1], angle)


def animate_scene(scene_dict: dict, frame: int, total_frames: int) -> dict:
    """Return a modified copy of *scene_dict* with per-frame group transforms.

    Each group gets a gentle sinusoidal rotation (±3°) and translation
    (±0.015 world units). Top-level shapes and lights also get tiny nudges so
    scenes without authored groups still exercise multiple deterministic states.
    """
    scene = copy.deepcopy(scene_dict)
    if total_frames <= 1:
        return scene

    t = frame / (total_frames - 1)  # 0..1

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
        _animate_shape(shape, t, _phase(i, len(shapes)))

    lights = scene.get("lights", [])
    for i, light in enumerate(lights):
        _animate_light(light, t, _phase(i, len(lights)))

    return scene
