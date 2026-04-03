"""Slow prism crown with a lead beam and trailing echo."""

from __future__ import annotations

import math

from anim import Frame, FrameContext, Group, Transform2D, ball_lens, regular_polygon
from anim.examples._clean_room_shared import (
    GLASS_BOLD,
    GLASS_FOCUS,
    GLASS_MEDIUM,
    GLASS_SOFT,
    SceneSpec,
    angle_between,
    beam_group,
    frame_for,
    polar,
    room_group,
    run_scene_cli,
    tau,
)


def build(ctx: FrameContext) -> Frame:
    phase = tau(ctx.progress)
    groups = [room_group()]
    ring_spin = 0.3 * phase
    prism_materials = (GLASS_SOFT, GLASS_MEDIUM, GLASS_BOLD, GLASS_MEDIUM)

    for index in range(4):
        orbit = ring_spin + index * math.tau / 4.0
        groups.append(
            Group(
                name=f"prism_{index}",
                transform=Transform2D.uniform(
                    translate=polar(0.56, orbit),
                    rotate=orbit + math.pi / 2 + 0.12 * math.sin(phase + index),
                    scale=0.96 + 0.08 * math.sin(phase + index * 0.7),
                ),
                shapes=regular_polygon(
                    center=(0.0, 0.0),
                    radius=0.23,
                    n=3,
                    material=prism_materials[index],
                    rotation=math.pi / 2,
                ),
            )
        )

    lead_angle = 0.82 * phase + 0.12
    lead_origin = (1.44 * math.cos(lead_angle), 0.74 * math.sin(lead_angle))
    trail_origin = (-lead_origin[0], -lead_origin[1])
    groups.extend(
        [
            Group(name="core", shapes=ball_lens((0.0, 0.0), 0.1, GLASS_FOCUS)),
            beam_group(
                "lead_beam",
                lead_origin,
                angle_between(lead_origin, (0.0, 0.0)),
                intensity=0.66,
                width=0.04,
                wavelength_min=390.0,
                wavelength_max=780.0,
            ),
            beam_group(
                "trail_beam",
                trail_origin,
                angle_between(trail_origin, (0.0, 0.0)),
                intensity=0.34,
                width=0.03,
                wavelength_min=470.0,
                wavelength_max=760.0,
            ),
        ]
    )
    return frame_for(groups)


SPEC = SceneSpec(
    name="prism_crown",
    duration=6.0,
    build=build,
    base_exposure=3.35,
    description="A slow prism crown with a lead beam and a softer trailing echo.",
)


if __name__ == "__main__":
    run_scene_cli(SPEC, __doc__ or SPEC.description)
