"""Dual-beam resonator with warm and white beams crossing a persistent center gap."""

from __future__ import annotations

import math

from anim import Frame, FrameContext, Group, Transform2D, ball_lens, thick_arc
from anim.examples._clean_room_shared import (
    GLASS_SOFT,
    SOFT_MIRROR,
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
    left_arc = Group(
        name="left_arc",
        transform=Transform2D.uniform(translate=(-0.54, 0.02), rotate=0.08 + 0.09 * math.sin(phase)),
        shapes=thick_arc((0.0, 0.0), 0.48, 0.1, 5.22, 1.88, SOFT_MIRROR),
    )
    right_arc = Group(
        name="right_arc",
        transform=Transform2D.uniform(
            translate=(0.54, -0.02),
            rotate=-0.1 + 0.07 * math.sin(phase * 1.13 + 0.7),
        ),
        shapes=thick_arc((0.0, 0.0), 0.48, 0.1, 2.33, 1.88, SOFT_MIRROR),
    )

    warm_origin = (-1.5, 0.16 * math.sin(phase))
    warm_target = (0.02, 0.08 * math.sin(phase + 0.6))
    white_origin = (1.5, 0.12 * math.sin(phase * 1.19 + 0.9))
    white_target = (-0.02, 0.06 * math.sin(phase * 0.91 + 1.7))

    warm_beam = beam_group(
        "warm_beam",
        warm_origin,
        angle_between(warm_origin, warm_target),
        intensity=0.78,
        width=0.034 + 0.006 * (0.5 + 0.5 * math.sin(2.7 * phase)),
        wavelength_min=550.0,
        wavelength_max=780.0,
    )
    white_beam = beam_group(
        "white_beam",
        white_origin,
        angle_between(white_origin, white_target),
        intensity=0.78,
        width=0.034 + 0.006 * (0.5 + 0.5 * math.sin(3.1 * phase + 0.9)),
        wavelength_min=390.0,
        wavelength_max=780.0,
    )
    focus = Group(name="focus", shapes=ball_lens((0.0, 0.0), 0.07, GLASS_SOFT))
    return frame_for([room_group(), left_arc, right_arc, focus, warm_beam, white_beam])


SPEC = SceneSpec(
    name="arc_resonator_dual_beam",
    duration=6.0,
    build=build,
    base_exposure=2.95,
    description="Warm and white beams crossing a resonator gap with independently animated arcs.",
)


if __name__ == "__main__":
    run_scene_cli(SPEC, __doc__ or SPEC.description)
