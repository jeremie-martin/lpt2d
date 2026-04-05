"""Canonical example: load, patch, and animate a saved shot.

This example shows the current best available load-modify-animate workflow:
start from a saved JSON shot, patch named groups and a top-level light, then
animate the result frame by frame.
"""

from __future__ import annotations

import math
from functools import cache

from anim import BeamLight, Canvas, Frame, FrameContext, Look, Shot
from anim.examples_support import REPO_ROOT, run_example

NAME = "twin_prisms_scene_patch"
SUMMARY = "Load a saved shot, patch named groups, and animate the result."
WORKFLOW = "load-modify-animate"
DURATION = 10.0

SCENE_PATH = REPO_ROOT / "scenes" / "twin_prisms.json"


@cache
def _base_shot() -> Shot:
    return Shot.load(SCENE_PATH)


def _normalize(x: float, y: float) -> list[float]:
    length = math.hypot(x, y)
    if length <= 1e-9:
        return [1.0, 0.0]
    return [x / length, y / length]

def _require_primary_beam(scene) -> BeamLight:
    light = scene.require_light("root_light_beam_0")
    if not isinstance(light, BeamLight):
        raise ValueError("root_light_beam_0 must be a beam light")
    return light


def make_settings(mode: str = "preview") -> Shot:
    shot = _base_shot().with_look(
        exposure=2.25,
        gamma=2.1,
        tonemap="reinhardx",
        white_point=0.5,
        normalize="rays",
    )
    if mode == "hq":
        shot.canvas = Canvas(1920, 1080)
        shot = shot.with_trace(rays=3_000_000, depth=12)
    else:
        shot.canvas = Canvas(960, 540)
        shot = shot.with_trace(rays=900_000, depth=10)
    shot.name = NAME
    return shot


def frame(ctx: FrameContext) -> Frame:
    swing = math.sin(math.tau * ctx.progress)
    scene = _base_shot().scene.clone()

    left = scene.require_group("prism_left")
    right = scene.require_group("prism_right")

    left.transform.translate[1] += 0.16 * swing
    right.transform.translate[1] -= 0.18 * swing
    left.transform.rotate += 0.16 * swing
    right.transform.rotate += 0.22 * swing
    right.transform.scale = [0.8 + 0.05 * swing, 0.8 + 0.05 * swing]

    beam = _require_primary_beam(scene)
    beam.origin[1] = 0.1 * swing
    beam.direction = _normalize(1.0, 0.12 * math.cos(math.tau * ctx.progress))

    return Frame(scene=scene, look=Look(exposure=2.2 + 0.18 * max(0.0, swing)))


def main(argv: list[str] | None = None) -> None:
    run_example(
        name=NAME,
        duration=DURATION,
        make_settings=make_settings,
        animate=frame,
        argv=argv,
        description=__doc__,
    )


if __name__ == "__main__":
    main()
