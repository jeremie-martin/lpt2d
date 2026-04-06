"""Per-frame scene animation for evaluation benchmarks.

Applies gentle oscillating transforms to groups so each frame exercises
a slightly different scene state, defeating GPU caching and giving more
representative timing on variable-clock hardware (laptops).
"""

from __future__ import annotations

import copy
import math


def animate_scene(scene_dict: dict, frame: int, total_frames: int) -> dict:
    """Return a modified copy of *scene_dict* with per-frame group transforms.

    Each group gets a gentle sinusoidal rotation (±3°) and translation
    (±0.015 world units) so the scene changes smoothly across frames without
    dramatically altering the render workload or composition.
    """
    scene = copy.deepcopy(scene_dict)
    if total_frames <= 1:
        return scene

    t = frame / (total_frames - 1)  # 0..1

    for i, group in enumerate(scene.get("groups", [])):
        transform = group.get("transform", {})
        base_rotate = transform.get("rotate", 0.0)
        base_translate = list(transform.get("translate", [0.0, 0.0]))

        # Phase-shift per group so they don't all move in sync
        phase = i * math.tau / max(len(scene.get("groups", [])), 1)

        angle = math.sin(t * math.tau + phase) * math.radians(3)
        dx = math.sin(t * math.tau + phase) * 0.015
        dy = math.cos(t * math.tau + phase) * 0.01

        transform["rotate"] = base_rotate + angle
        transform["translate"] = [base_translate[0] + dx, base_translate[1] + dy]
        group["transform"] = transform

    return scene
