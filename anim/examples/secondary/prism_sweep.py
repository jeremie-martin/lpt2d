"""Slow beam sweep across a single prism — spectral dispersion unfolding.

A white projector beam slowly sweeps across an equilateral prism, creating
a continuously evolving rainbow fan.  The animation is meditative: the
physics does the visual work, the motion just reveals new angles.
"""

from __future__ import annotations

import math

from anim import (
    Camera2D,
    Frame,
    FrameContext,
    Key,
    Look,
    Material,
    ProjectorLight,
    Scene,
    Shot,
    Track,
    Wrap,
    glass,
    mirror_box,
    prism,
)
from anim.examples_support import run_example

NAME = "prism_sweep"
SUMMARY = "Minimal optics: one prism, one beam — slow rainbow."
DURATION = 10.0

# --- Scene constants ---

# High Cauchy dispersion for a strong visible rainbow fan.
# Near-white fill (0.968, 0.968, 0.968) at 0.15 makes the prism body visible.
PRISM_GLASS = glass(1.52, cauchy_b=28_000, color=(0.968, 0.968, 0.968), fill=0.15)

# Walls: bright metallic reflector — catches and scatters the dispersed light.
WALL = Material(metallic=1.0, roughness=0.1, transmission=0.0, cauchy_b=0.0, albedo=1.0)

# Camera width auto-derives height from canvas aspect ratio.
CAMERA = Camera2D(center=[0, 0], width=3.2)

# --- Tracks ---

# Beam sweeps well past the prism — overshoots above and below.
BEAM_ANGLE = Track(
    [
        Key(0.0, -0.85),
        Key(5.0, 0.7, ease="ease_in_out_sine"),
        Key(DURATION, -0.85, ease="ease_in_out_sine"),
    ],
    wrap=Wrap.LOOP,
)

# Prism rotation centered on the dispersive zone.
PRISM_ROTATION = Track(
    [
        Key(0.0, math.pi / 2 - 0.55),
        Key(5.0, math.pi / 2 - 0.40, ease="ease_in_out_sine"),
        Key(DURATION, math.pi / 2 - 0.55, ease="ease_in_out_sine"),
    ],
    wrap=Wrap.LOOP,
)

EXPOSURE = Track(
    [
        Key(0.0, -4.5),
        Key(5.0, -5.2, ease="ease_in_out_sine"),
        Key(DURATION, -4.5, ease="ease_in_out_sine"),
    ],
    wrap=Wrap.LOOP,
)


def _unit(angle: float) -> list[float]:
    return [math.cos(angle), math.sin(angle)]


def make_settings(mode: str = "preview") -> Shot:
    if mode == "hq":
        shot = Shot.preset("production", width=1920, height=1080, rays=5_000_000, depth=12)
    else:
        shot = Shot.preset("preview", width=960, height=540, rays=700_000, depth=10)
    shot.name = NAME
    shot.camera = CAMERA
    shot.look = shot.look.with_overrides(
        exposure=-4.5,
        gamma=2.0,
        tonemap="reinhardx",
        white_point=0.5,
        normalize="rays",
        temperature=0.1,
    )
    return shot


def frame(ctx: FrameContext) -> Frame:
    angle = BEAM_ANGLE(ctx.time)
    rot = PRISM_ROTATION(ctx.time)

    scene = Scene(
        shapes=[
            *mirror_box(1.6, 0.9, WALL, id_prefix="wall"),
            prism(
                center=(0.0, 0.0),
                size=0.35,
                material=PRISM_GLASS,
                rotation=rot,
                id_prefix="prism",
            ),
        ],
        lights=[
            ProjectorLight(
                id="beam",
                position=[-1.4, 0.6],
                direction=_unit(angle),
                source_radius=0.01,
                spread=0.041,
                source="ball",
                intensity=1.0,
            ),
        ],
    )
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
