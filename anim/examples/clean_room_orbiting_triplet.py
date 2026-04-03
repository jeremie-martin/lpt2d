"""Wall-safe orbiting triplet in a mirror room."""

from __future__ import annotations

import math

from anim import Circle, Frame, FrameContext, Group, Transform2D
from anim.examples._clean_room_shared import (
    GLASS_BOLD,
    GLASS_MEDIUM,
    GLASS_SOFT,
    SceneSpec,
    angle_between,
    beam_group,
    frame_for,
    room_group,
    run_scene_cli,
    tau,
)


def build(ctx: FrameContext) -> Frame:
    phase = tau(ctx.progress)
    orbit_angle = phase + 0.62 * math.pi
    beam_origin = (1.36 * math.cos(orbit_angle), 0.74 * math.sin(orbit_angle))

    cluster = Group(
        name="triplet",
        transform=Transform2D.uniform(
            rotate=0.14 * math.sin(phase),
            scale=1.0 + 0.05 * math.sin(2.0 * phase - 0.3),
        ),
        shapes=[
            Circle(center=[-0.54, 0.06], radius=0.18, material=GLASS_SOFT),
            Circle(center=[0.0, -0.02], radius=0.21, material=GLASS_MEDIUM),
            Circle(center=[0.54, 0.06], radius=0.18, material=GLASS_BOLD),
        ],
    )
    beam = beam_group(
        "orbit_beam",
        beam_origin,
        angle_between(beam_origin, (0.0, 0.0)),
        intensity=0.82,
        width=0.05 + 0.012 * (0.5 + 0.5 * math.sin(3.0 * phase)),
        wavelength_min=395.0,
        wavelength_max=720.0,
    )
    return frame_for([room_group(), cluster, beam])


SPEC = SceneSpec(
    name="orbiting_triplet",
    duration=6.0,
    build=build,
    base_exposure=3.05,
    description="Three-lens cluster with a wall-safe orbiting beam.",
)


if __name__ == "__main__":
    run_scene_cli(SPEC, __doc__ or SPEC.description)
