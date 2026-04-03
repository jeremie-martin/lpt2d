"""Mirror slats opening and closing into a rhythmic gated field."""

from __future__ import annotations

import math

from anim import Frame, FrameContext, Group, Transform2D
from anim.examples._clean_room_shared import (
    FACET_MIRROR,
    SceneSpec,
    angle_between,
    beam_group,
    fill_group,
    frame_for,
    room_group,
    run_scene_cli,
    slat,
    tau,
)


def build(ctx: FrameContext) -> Frame:
    phase = tau(ctx.progress)
    groups = [room_group(), fill_group("top_fill", 0.8, intensity=0.11)]

    for index, base_x in enumerate((0.22, 0.54, 0.86)):
        wobble = 0.06 * math.sin(phase + index * 0.8)
        twist = 0.08 * math.sin(2.0 * phase + index)
        for side in (-1.0, 1.0):
            x = side * (base_x + wobble * side)
            groups.append(
                Group(
                    name=f"slat_{index}_{int(side)}",
                    transform=Transform2D.uniform(translate=(x, 0.0), rotate=twist * side),
                    shapes=slat(1.18, FACET_MIRROR),
                )
            )

    beam_origin = (-1.55, 0.18 * math.sin(2.0 * phase))
    groups.append(
        beam_group(
            "aperture_beam",
            beam_origin,
            angle_between(beam_origin, (0.92, -0.06 * math.sin(phase))),
            intensity=0.76,
            width=0.044,
            wavelength_min=390.0,
            wavelength_max=730.0,
        )
    )
    return frame_for(groups)


SPEC = SceneSpec(
    name="aperture_waltz",
    duration=6.0,
    build=build,
    base_exposure=3.15,
    description="Mirror slats open and close into a rhythmic gated field.",
)


if __name__ == "__main__":
    run_scene_cli(SPEC, __doc__ or SPEC.description)
