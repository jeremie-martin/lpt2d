"""Canonical example: procedural-from-scratch authoring.

This is the starter example for the current Python animation API. It keeps the
authored camera and base look in ``make_settings()`` and uses ``frame(ctx)``
only for the animated deltas.
"""

from __future__ import annotations

import math

from anim import (
    BeamLight,
    Camera2D,
    Circle,
    Frame,
    FrameContext,
    Key,
    Look,
    Material,
    Scene,
    Shot,
    Track,
    Wrap,
    beam_splitter,
    glass,
    mirror,
    mirror_box,
    thick_segment,
)
from anim.examples_support import run_example

NAME = "beam_chamber_starter"
SUMMARY = "Procedural from scratch: a mirror chamber, glass actors, and one animated beam."
WORKFLOW = "procedural-from-scratch"
DURATION = 12.0

CAMERA = Camera2D(bounds=[-1.35, -0.82, 1.35, 0.82])

WALL = mirror(0.95, roughness=0.02)
PRIMARY_GLASS = glass(1.48, cauchy_b=16_000, absorption=0.08)
SECONDARY_GLASS = glass(1.6, cauchy_b=28_000, absorption=0.15)
SPLITTER = beam_splitter(0.42, roughness=0.01)

BEAM_ANGLE = Track(
    [
        Key(0.0, -0.12 * math.pi),
        Key(4.0, 0.02 * math.pi, ease="ease_in_out_sine"),
        Key(8.0, 0.22 * math.pi, ease="ease_in_out_sine"),
        Key(DURATION, -0.08 * math.pi, ease="ease_in_out_sine"),
    ],
    wrap=Wrap.LOOP,
)
BEAM_HEIGHT = Track(
    [
        Key(0.0, 0.34),
        Key(3.6, 0.08, ease="ease_in_out_sine"),
        Key(7.2, -0.24, ease="ease_in_out_sine"),
        Key(DURATION, 0.28, ease="ease_in_out_sine"),
    ],
    wrap=Wrap.PINGPONG,
)
PANEL_SWAY = Track(
    [
        Key(0.0, -0.05),
        Key(4.5, 0.06, ease="ease_in_out_sine"),
        Key(DURATION, -0.04, ease="ease_in_out_sine"),
    ],
    wrap=Wrap.PINGPONG,
)
EXPOSURE = Track(
    [
        Key(0.0, 2.75),
        Key(5.5, 3.0, ease="ease_in_out_sine"),
        Key(DURATION, 2.82, ease="ease_in_out_sine"),
    ],
    wrap=Wrap.PINGPONG,
)


def _bind_material_id(shape, material_id: str):
    shape.material_id = material_id
    return shape


def _unit(angle: float) -> list[float]:
    return [math.cos(angle), math.sin(angle)]


def make_settings(mode: str = "preview") -> Shot:
    if mode == "hq":
        shot = Shot.preset("production", width=1920, height=1080, rays=3_000_000, depth=12)
    else:
        shot = Shot.preset("preview", width=960, height=540, rays=900_000, depth=10)
    shot.name = NAME
    shot.camera = CAMERA
    shot.look = shot.look.with_overrides(
        exposure=2.85,
        gamma=2.1,
        tonemap="reinhardx",
        white_point=0.55,
        normalize="rays",
    )
    return shot


def frame(ctx: FrameContext) -> Frame:
    phase = math.sin(math.tau * ctx.progress)
    panel_sway = PANEL_SWAY(ctx.time)
    materials: dict[str, Material] = {
        "wall_mirror": WALL,
        "primary_glass": PRIMARY_GLASS,
        "secondary_glass": SECONDARY_GLASS,
        "splitter_panel": SPLITTER,
    }
    chamber = [
        _bind_material_id(shape, "wall_mirror")
        for shape in mirror_box(1.2, 0.7, materials["wall_mirror"], id_prefix="wall")
    ]
    scene = Scene(
        materials=materials,
        shapes=[
            *chamber,
            Circle(
                id="glass_left",
                center=[-0.38, 0.18 + 0.05 * phase],
                radius=0.22,
                material=materials["primary_glass"],
                material_id="primary_glass",
            ),
            Circle(
                id="glass_right",
                center=[0.36, -0.14 - 0.04 * phase],
                radius=0.17,
                material=materials["secondary_glass"],
                material_id="secondary_glass",
            ),
            thick_segment(
                (-0.18, -0.42 + panel_sway),
                (0.24, 0.30 + panel_sway),
                0.05,
                materials["splitter_panel"],
                id_prefix="splitter_panel",
            ),
        ],
        lights=[
            BeamLight(
                id="beam_main",
                origin=[-1.02, BEAM_HEIGHT(ctx.time)],
                direction=_unit(BEAM_ANGLE(ctx.time)),
                angular_width=0.02,
                intensity=1.0,
            )
        ],
    )
    scene.shapes[-1].material_id = "splitter_panel"
    return Frame(scene=scene, look=Look(exposure=EXPOSURE(ctx.time)))


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
