"""Simple camera-only zoom animation on the authored three-spheres shot.

The move stays locked to the original camera center:

- 0s -> 5s: zoom in from the authored framing to 800%
- 5s -> 8s: zoom out to 50% of the starting zoom
"""

from __future__ import annotations

import math
from pathlib import Path

from anim import Camera2D, Frame, FrameContext, Shot
from anim.examples_support import run_example

NAME = "three_spheres_center_zoom"
SUMMARY = "Camera-only zoom on the authored three-spheres shot."
WORKFLOW = "camera-only-animation"
DURATION = 8.0
ZOOM_IN_DURATION = 5.0
ZOOM_OUT_DURATION = 3.0

REPO_ROOT = Path(__file__).resolve().parents[2]
BASE_SHOT = Shot.load(REPO_ROOT / "scenes" / "three_spheres.json")

if BASE_SHOT.camera is None or BASE_SHOT.camera.bounds is None:
    raise ValueError("three_spheres_center_zoom requires authored camera bounds")

START_BOUNDS = BASE_SHOT.camera.bounds
CAMERA_CENTER = [
    (START_BOUNDS.min[0] + START_BOUNDS.max[0]) * 0.5,
    (START_BOUNDS.min[1] + START_BOUNDS.max[1]) * 0.5,
]
START_WIDTH = START_BOUNDS.max[0] - START_BOUNDS.min[0]
ZOOMED_IN_WIDTH = START_WIDTH / 8.0
ZOOMED_OUT_WIDTH = START_WIDTH * 2.0


def _ease_in_out_sine(t: float) -> float:
    t = max(0.0, min(1.0, t))
    return 0.5 - 0.5 * math.cos(math.pi * t)


def _lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def make_settings(mode: str = "preview") -> Shot:
    if mode == "hq":
        shot = Shot.preset("production", width=1920, height=1080, rays=500_000, depth=10)
    else:
        shot = Shot.preset("preview", width=960, height=540, rays=350_000, depth=10)
    shot.name = NAME
    shot.scene = BASE_SHOT.scene
    shot.camera = BASE_SHOT.camera
    shot.look = BASE_SHOT.look
    shot.trace.intensity = BASE_SHOT.trace.intensity
    return shot


def frame(ctx: FrameContext) -> Frame:
    if ctx.time <= ZOOM_IN_DURATION:
        width = _lerp(
            START_WIDTH,
            ZOOMED_IN_WIDTH,
            _ease_in_out_sine(ctx.time / ZOOM_IN_DURATION),
        )
    else:
        width = _lerp(
            ZOOMED_IN_WIDTH,
            ZOOMED_OUT_WIDTH,
            _ease_in_out_sine((ctx.time - ZOOM_IN_DURATION) / ZOOM_OUT_DURATION),
        )

    return Frame(
        scene=BASE_SHOT.scene,
        camera=Camera2D(center=CAMERA_CENTER, width=width),
    )


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
