"""Collimated beam reflecting off a concave mirror arc."""

from __future__ import annotations

import math

from anim import (
    Camera2D,
    Frame,
    FrameContext,
    ProjectorLight,
    Scene,
    Shot,
    absorber,
    mirror,
    mirror_box,
    thick_arc,
)
from anim.examples_support import run_example

NAME = "thick_arc_demo"
DURATION = 1.0
CAMERA = Camera2D(bounds=[-1.2, -0.675, 1.2, 0.675])


def make_settings(mode: str = "preview") -> Shot:
    preset = "production" if mode == "hq" else "preview"
    shot = Shot.preset(preset, width=1920 if mode == "hq" else 960,
                       height=1080 if mode == "hq" else 540,
                       rays=3_000_000 if mode == "hq" else 900_000, depth=12)
    shot.name = NAME
    shot.camera = CAMERA
    shot.look = shot.look.with_overrides(
        exposure=-4.5, contrast=1.2, gamma=2.0,
        tonemap="reinhardx", white_point=0.5, normalize="rays", ambient=0.01,
    )
    return shot


def frame(_ctx: FrameContext) -> Frame:
    arc_mat = mirror(1.0)
    wall_mat = absorber()

    arc = thick_arc((0, 0), radius=0.5, thickness=0.15,
                    angle_start=math.pi / 2, sweep=math.pi,
                    material=arc_mat, smooth_angle=1.0,
                    end_cap_radii=(0.075, 0.0), id_prefix="arc")
    arc[0].material_id = "arc"

    walls = mirror_box(1.2, 0.675, wall_mat, id_prefix="wall")
    for w in walls:
        w.material_id = "wall"

    return Frame(scene=Scene(
        materials={"arc": arc_mat, "wall": wall_mat},
        shapes=[*walls, *arc],
        lights=[ProjectorLight(
            id="beam", position=[0.9, 0.0], direction=[-1.0, 0.0],
            source_radius=0.05, spread=0.0, intensity=1.0,
        )],
    ))


def main(argv: list[str] | None = None) -> None:
    run_example(name=NAME, duration=DURATION, make_settings=make_settings,
                animate=frame, argv=argv, description=__doc__)


if __name__ == "__main__":
    main()
