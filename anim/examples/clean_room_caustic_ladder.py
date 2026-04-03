"""Scanning beam across a vertical ladder of compact lenses."""

from __future__ import annotations

import math

from anim import Circle, Frame, FrameContext, Group
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
    y_positions = (-0.68, -0.34, 0.0, 0.34, 0.68)
    ladder_materials = (GLASS_SOFT, GLASS_MEDIUM, GLASS_BOLD, GLASS_MEDIUM, GLASS_SOFT)
    ladder_shapes: list[Circle] = []

    for index, base_y in enumerate(y_positions):
        x = 0.24 + 0.09 * math.sin(phase + index * 0.75)
        radius = 0.1 + 0.02 * math.sin(2.0 * phase + index * 0.55)
        ladder_shapes.append(Circle(center=[x, base_y], radius=radius, material=ladder_materials[index]))

    beam_origin = (-1.55, 0.7 * math.sin(phase))
    beam_target = (0.18, 0.24 * math.sin(phase + 0.5))
    beam = beam_group(
        "ladder_beam",
        beam_origin,
        angle_between(beam_origin, beam_target),
        intensity=0.8,
        width=0.042,
        wavelength_min=395.0,
        wavelength_max=780.0,
    )
    ladder = Group(name="ladder", shapes=ladder_shapes)
    return frame_for([room_group(), ladder, beam])


SPEC = SceneSpec(
    name="caustic_ladder",
    duration=6.0,
    build=build,
    base_exposure=3.10,
    description="A scanning beam walks across a vertical ladder of lenses.",
)


if __name__ == "__main__":
    run_scene_cli(SPEC, __doc__ or SPEC.description)
