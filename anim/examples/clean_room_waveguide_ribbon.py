"""Clean bezier ribbon waveguide fed by a narrow beam."""

from __future__ import annotations

import math

from anim import Bezier, Frame, FrameContext, Group, Segment
from anim.examples._clean_room_shared import (
    FACET_MIRROR,
    GLASS_BOLD,
    GLASS_SOFT,
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
    bend = 0.09 * math.sin(phase)
    ribbon = Group(
        name="ribbon",
        shapes=[
            Bezier(
                p0=[-1.02, 0.18 + bend],
                p1=[-0.1, 0.54],
                p2=[1.02, 0.2 - bend],
                material=GLASS_SOFT,
            ),
            Bezier(
                p0=[-1.02, -0.18 - bend],
                p1=[0.1, -0.54],
                p2=[1.02, -0.2 + bend],
                material=GLASS_BOLD,
            ),
            Segment(a=[-1.12, 0.18 + bend], b=[-1.12, -0.18 - bend], material=FACET_MIRROR),
            Segment(a=[1.12, -0.2 + bend], b=[1.12, 0.2 - bend], material=FACET_MIRROR),
        ],
    )
    beam_origin = (-1.55, 0.14 * math.sin(2.0 * phase))
    beam = beam_group(
        "feed_beam",
        beam_origin,
        angle_between(beam_origin, (-0.84, 0.05 * math.sin(phase))),
        intensity=0.78,
        width=0.038,
        wavelength_min=390.0,
        wavelength_max=730.0,
    )
    lower_fill = fill_group("lower_fill", -0.76, intensity=0.04, width=1.1)
    return frame_for([room_group(), ribbon, beam, lower_fill])


SPEC = SceneSpec(
    name="waveguide_ribbon",
    duration=6.0,
    build=build,
    base_exposure=3.20,
    description="A clean bezier ribbon waveguide fed by a narrow beam.",
)


if __name__ == "__main__":
    run_scene_cli(SPEC, __doc__ or SPEC.description)
