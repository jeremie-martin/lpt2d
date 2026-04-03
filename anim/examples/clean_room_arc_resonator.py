"""Warm beam through a wall-safe resonator gap."""

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
        transform=Transform2D.uniform(translate=(-0.52, 0.0), rotate=0.1 * math.sin(phase)),
        shapes=thick_arc((0.0, 0.0), 0.5, 0.1, 5.16, 2.0, SOFT_MIRROR),
    )
    right_arc = Group(
        name="right_arc",
        transform=Transform2D.uniform(translate=(0.52, 0.0), rotate=-0.1 * math.sin(phase)),
        shapes=thick_arc((0.0, 0.0), 0.5, 0.1, 2.26, 2.0, SOFT_MIRROR),
    )
    beam_origin = (-1.5, 0.14 * math.sin(phase))
    beam_target = (0.08, 0.04 * math.sin(phase + 0.7))
    beam = beam_group(
        "resonator_beam",
        beam_origin,
        angle_between(beam_origin, beam_target),
        intensity=0.78,
        width=0.034 + 0.006 * (0.5 + 0.5 * math.sin(3.0 * phase)),
        wavelength_min=540.0,
        wavelength_max=780.0,
    )
    focus = Group(name="focus", shapes=ball_lens((0.0, 0.0), 0.075, GLASS_SOFT))
    return frame_for([room_group(), left_arc, right_arc, focus, beam])


SPEC = SceneSpec(
    name="arc_resonator",
    duration=6.0,
    build=build,
    base_exposure=3.05,
    description="A curved resonator cavity with a wall-safe warm beam through the center gap.",
)


if __name__ == "__main__":
    run_scene_cli(SPEC, __doc__ or SPEC.description)
