"""Cool and warm beams crossing through a simple glass doublet."""

from __future__ import annotations

import math

from anim import Circle, Frame, FrameContext, Group
from anim.examples._clean_room_shared import (
    GLASS_BOLD,
    GLASS_FOCUS,
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
    cool_origin = (-1.55, 0.82 - 0.12 * (0.5 + 0.5 * math.sin(phase)))
    warm_origin = (1.55, -0.82 + 0.12 * (0.5 + 0.5 * math.sin(phase)))
    cool_max = 560.0 + 45.0 * (0.5 + 0.5 * math.sin(phase))
    warm_min = 470.0 + 35.0 * (0.5 + 0.5 * math.sin(phase + 1.1))

    doublet = Group(
        name="doublet",
        shapes=[
            Circle(center=[-0.24, -0.12], radius=0.17, material=GLASS_SOFT),
            Circle(center=[0.24, 0.12], radius=0.17, material=GLASS_BOLD),
            Circle(center=[0.0, 0.0], radius=0.08, material=GLASS_FOCUS),
        ],
    )
    cool = beam_group(
        "cool_beam",
        cool_origin,
        angle_between(cool_origin, (-0.12, -0.06)),
        intensity=0.7,
        width=0.044,
        wavelength_min=390.0,
        wavelength_max=cool_max,
    )
    warm = beam_group(
        "warm_beam",
        warm_origin,
        angle_between(warm_origin, (0.12, 0.06)),
        intensity=0.7,
        width=0.044,
        wavelength_min=warm_min,
        wavelength_max=780.0,
    )
    return frame_for([room_group(), doublet, cool, warm])


SPEC = SceneSpec(
    name="corner_crossfire",
    duration=6.0,
    build=build,
    base_exposure=3.00,
    description="Cool and warm corner beams cross through a simple glass doublet.",
)


if __name__ == "__main__":
    run_scene_cli(SPEC, __doc__ or SPEC.description)
