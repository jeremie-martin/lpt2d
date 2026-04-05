"""Symmetric beam-height swap for the root-level twin_prisms scene."""

from __future__ import annotations

import argparse
import math
from dataclasses import dataclass
from functools import cache
from pathlib import Path

from anim import (
    BeamLight,
    Camera2D,
    Canvas,
    Frame,
    FrameContext,
    Look,
    Scene,
    Segment,
    Shot,
    Timeline,
    TraceDefaults,
    render,
)

NAME = "twin_prisms_vertical_swap"
DURATION = 14.0

REPO_ROOT = Path(__file__).resolve().parents[3]
SCENE_PATH = REPO_ROOT / "scenes" / "twin_prisms.json"
BINARY = REPO_ROOT / "build" / "lpt2d-cli"

FRAME_LOOK = Look(
    exposure=2.0,
    gamma=2.1,
    tonemap="reinhardx",
    white_point=0.5,
    normalize="rays",
)


@cache
def _base_shot() -> Shot:
    return Shot.load(SCENE_PATH)


@dataclass(frozen=True)
class Bounds:
    xmin: float
    ymin: float
    xmax: float
    ymax: float

    @property
    def width(self) -> float:
        return self.xmax - self.xmin

    @property
    def height(self) -> float:
        return self.ymax - self.ymin

    @property
    def center(self) -> tuple[float, float]:
        return ((self.xmin + self.xmax) * 0.5, (self.ymin + self.ymax) * 0.5)


@dataclass(frozen=True)
class Layout:
    camera: Camera2D
    left_beam_index: int
    right_beam_index: int
    start_left: tuple[float, float]
    start_right: tuple[float, float]
    end_left: tuple[float, float]
    end_right: tuple[float, float]


def ease_in_out_sine(t: float) -> float:
    return 0.5 * (1.0 - math.cos(math.pi * t))


def lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def infer_room_bounds(scene: Scene) -> Bounds:
    xs: list[float] = []
    ys: list[float] = []
    for shape in scene.shapes:
        if not isinstance(shape, Segment):
            continue
        xs.extend((shape.a[0], shape.b[0]))
        ys.extend((shape.a[1], shape.b[1]))
    if not xs or not ys:
        raise ValueError("expected top-level room segments in twin_prisms scene")
    return Bounds(min(xs), min(ys), max(xs), max(ys))


def infer_beam_indices(scene: Scene) -> tuple[int, int]:
    beam_indices = [i for i, light in enumerate(scene.lights) if isinstance(light, BeamLight)]
    if len(beam_indices) != 2:
        raise ValueError("expected exactly two top-level beam lights")

    left_index = min(beam_indices, key=lambda i: scene.lights[i].origin[0])
    right_index = max(beam_indices, key=lambda i: scene.lights[i].origin[0])
    return left_index, right_index


def infer_corner_inset(scene: Scene, room: Bounds, left_index: int, right_index: int) -> float:
    left_beam = scene.lights[left_index]
    right_beam = scene.lights[right_index]
    return min(
        left_beam.origin[0] - room.xmin,
        room.ymax - left_beam.origin[1],
        room.xmax - right_beam.origin[0],
        right_beam.origin[1] - room.ymin,
    )


def cover_bounds(room: Bounds, aspect: float) -> Bounds:
    room_aspect = room.width / room.height
    cx, cy = room.center
    if aspect >= room_aspect:
        width = room.width
        height = width / aspect
    else:
        height = room.height
        width = height * aspect
    return Bounds(cx - width * 0.5, cy - height * 0.5, cx + width * 0.5, cy + height * 0.5)


def infer_layout(scene: Scene, aspect: float) -> Layout:
    room = infer_room_bounds(scene)
    left_index, right_index = infer_beam_indices(scene)
    inset = infer_corner_inset(scene, room, left_index, right_index)
    visible = cover_bounds(room, aspect)

    camera = Camera2D(center=list(visible.center), width=visible.width)
    start_left = (visible.xmin + inset, visible.ymax - inset)
    start_right = (visible.xmax - inset, visible.ymin + inset)
    end_left = (start_left[0], start_right[1])
    end_right = (start_right[0], start_left[1])
    return Layout(
        camera=camera,
        left_beam_index=left_index,
        right_beam_index=right_index,
        start_left=start_left,
        start_right=start_right,
        end_left=end_left,
        end_right=end_right,
    )


def make_animate(layout: Layout):
    def animate(ctx: FrameContext) -> Frame:
        scene = _base_shot().scene.clone()
        p = ease_in_out_sine(ctx.progress)
        left_x = lerp(layout.start_left[0], layout.end_left[0], p)
        left_y = lerp(layout.start_left[1], layout.end_left[1], p)
        right_x = lerp(layout.start_right[0], layout.end_right[0], p)
        right_y = lerp(layout.start_right[1], layout.end_right[1], p)
        scene.lights[layout.left_beam_index].origin = [left_x, left_y]
        scene.lights[layout.right_beam_index].origin = [right_x, right_y]
        return Frame(scene=scene, look=FRAME_LOOK)

    return animate


def shot_for(mode: str) -> tuple[Shot, int, int]:
    if mode == "hq":
        return (
            Shot(
                canvas=Canvas(1920, 1080),
                trace=TraceDefaults(rays=3_000_000, batch=200_000, depth=12),
            ),
            60,
            16,
        )
    return (
        Shot(
            canvas=Canvas(960, 540),
            trace=TraceDefaults(rays=400_000, batch=100_000, depth=12),
        ),
        30,
        18,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--hq", action="store_true", help="render the HQ version instead of the preview"
    )
    parser.add_argument("--both", action="store_true", help="render preview and HQ back-to-back")
    parser.add_argument("--start", type=float, default=0.0, help="start time in seconds")
    parser.add_argument("--end", type=float, help="end time in seconds")
    parser.add_argument("--stride", type=int, default=1, help="render every Nth frame")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    modes = ("preview", "hq") if args.both else (("hq",) if args.hq else ("preview",))

    for mode in modes:
        shot, fps, crf = shot_for(mode)
        layout = infer_layout(_base_shot().scene, shot.canvas.aspect)
        output = REPO_ROOT / f"{NAME}_{mode}.mp4"
        render(
            make_animate(layout),
            Timeline(DURATION, fps=fps),
            str(output),
            settings=shot,
            camera=layout.camera,
            binary=str(BINARY),
            crf=crf,
            start=args.start,
            end=args.end,
            stride=args.stride,
        )


if __name__ == "__main__":
    main()
