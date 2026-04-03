"""Opposed mirror shutters opening around a vertical beam."""

from __future__ import annotations

import math

from anim import Frame, FrameContext, Group, Transform2D, ball_lens, thick_arc
from anim.examples._clean_room_shared import (
    FACET_MIRROR,
    GLASS_MEDIUM,
    SceneSpec,
    beam_group,
    fill_group,
    frame_for,
    room_group,
    run_scene_cli,
    tau,
)


def build(ctx: FrameContext) -> Frame:
    phase = tau(ctx.progress)
    top_shutter = Group(
        name="top_shutter",
        transform=Transform2D.uniform(rotate=0.26 * math.sin(phase)),
        shapes=thick_arc((0.0, 0.0), 0.72, 0.12, 0.62 * math.pi, 0.76 * math.pi, FACET_MIRROR),
    )
    bottom_shutter = Group(
        name="bottom_shutter",
        transform=Transform2D.uniform(rotate=-0.26 * math.sin(phase)),
        shapes=thick_arc((0.0, 0.0), 0.72, 0.12, 1.62 * math.pi, 0.76 * math.pi, FACET_MIRROR),
    )
    beam_origin = (0.08 * math.sin(phase), 0.84)
    beam = beam_group(
        "drop_beam",
        beam_origin,
        -0.5 * math.pi + 0.12 * math.sin(2.0 * phase),
        intensity=0.88,
        width=0.05,
        wavelength_min=390.0,
        wavelength_max=700.0,
    )
    focus = Group(name="focus", shapes=ball_lens((0.0, 0.0), 0.15, GLASS_MEDIUM))
    base_fill = fill_group("base_fill", -0.76, intensity=0.05, width=1.0)
    return frame_for([room_group(), top_shutter, bottom_shutter, focus, beam, base_fill])


SPEC = SceneSpec(
    name="mirror_shutters",
    duration=6.0,
    build=build,
    base_exposure=3.15,
    description="Opposed mirror shutters open and close around a downward beam.",
    hq_duration=8.0,
    hq_rays=2_000_000,
)


if __name__ == "__main__":
    run_scene_cli(SPEC, __doc__ or SPEC.description)
