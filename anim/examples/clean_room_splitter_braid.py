"""Two beams braided through a reflective splitter cross."""

from __future__ import annotations

import math

from anim import Circle, Frame, FrameContext, Group, Segment, Transform2D
from anim.examples._clean_room_shared import (
    GLASS_FOCUS,
    SPLITTER,
    SceneSpec,
    angle_between,
    beam_group,
    fill_group,
    frame_for,
    room_group,
    run_scene_cli,
    tau,
)


def build(ctx: FrameContext) -> Frame:
    phase = tau(ctx.progress)
    left_origin = (-1.55, 0.44 * math.sin(phase))
    right_origin = (1.55, -0.44 * math.sin(phase))
    target_y = 0.16 * math.sin(phase + 0.5)

    splitters = Group(
        name="splitters",
        transform=Transform2D.uniform(rotate=0.18 * math.sin(phase)),
        shapes=[
            Segment(a=[-0.68, -0.26], b=[0.68, 0.26], material=SPLITTER),
            Segment(a=[-0.68, 0.26], b=[0.68, -0.26], material=SPLITTER),
            Circle(center=[0.0, 0.0], radius=0.13, material=GLASS_FOCUS),
        ],
    )
    left_beam = beam_group(
        "left_beam",
        left_origin,
        angle_between(left_origin, (0.08, target_y)),
        intensity=0.64,
        width=0.044,
        wavelength_min=400.0,
        wavelength_max=610.0,
    )
    right_beam = beam_group(
        "right_beam",
        right_origin,
        angle_between(right_origin, (-0.08, -target_y)),
        intensity=0.64,
        width=0.044,
        wavelength_min=500.0,
        wavelength_max=780.0,
    )
    floor_fill = fill_group("floor_fill", -0.8, intensity=0.06, width=1.2)
    return frame_for([room_group(), splitters, left_beam, right_beam, floor_fill])


SPEC = SceneSpec(
    name="splitter_braid",
    duration=6.0,
    build=build,
    base_exposure=3.10,
    description="Two beams braid through a reflective beam-splitter cross.",
)


if __name__ == "__main__":
    run_scene_cli(SPEC, __doc__ or SPEC.description)
