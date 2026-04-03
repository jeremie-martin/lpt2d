"""Five-blade mirror fan catching a beam through a small prism."""

from __future__ import annotations

import math

from anim import Frame, FrameContext, Group, Transform2D, regular_polygon
from anim.examples._clean_room_shared import (
    FACET_MIRROR,
    GLASS_MEDIUM,
    SceneSpec,
    angle_between,
    beam_group,
    blade,
    frame_for,
    room_group,
    run_scene_cli,
    tau,
)


def build(ctx: FrameContext) -> Frame:
    phase = tau(ctx.progress)
    groups = [room_group()]
    pivot = (0.68, 0.0)

    for index, base_angle in enumerate((-0.5, -0.24, 0.02, 0.28, 0.54)):
        groups.append(
            Group(
                name=f"fan_blade_{index}",
                transform=Transform2D.uniform(
                    translate=pivot,
                    rotate=base_angle + 0.16 * math.sin(phase + index * 0.45),
                ),
                shapes=blade(0.78, FACET_MIRROR),
            )
        )

    groups.append(
        Group(
            name="fan_prism",
            transform=Transform2D.uniform(
                translate=(-0.18, 0.0),
                rotate=0.18 * math.sin(phase),
                scale=1.0 + 0.06 * math.sin(2.0 * phase),
            ),
            shapes=regular_polygon(
                center=(0.0, 0.0),
                radius=0.18,
                n=3,
                material=GLASS_MEDIUM,
                rotation=math.pi / 2,
            ),
        )
    )

    beam_origin = (-1.55, -0.2 + 0.16 * math.sin(phase))
    groups.append(
        beam_group(
            "fan_beam",
            beam_origin,
            angle_between(beam_origin, (0.48, 0.06 * math.sin(phase + 0.4))),
            intensity=0.82,
            width=0.042,
            wavelength_min=420.0,
            wavelength_max=730.0,
        )
    )
    return frame_for(groups)


SPEC = SceneSpec(
    name="mirror_fan",
    duration=6.0,
    build=build,
    base_exposure=3.15,
    description="A five-blade mirror fan catches a beam through a small prism.",
)


if __name__ == "__main__":
    run_scene_cli(SPEC, __doc__ or SPEC.description)
