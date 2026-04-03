"""Simplified two-lens scan with restrained breathing motion."""

from __future__ import annotations

import math

from anim import (
    Frame,
    FrameContext,
    Group,
    Transform2D,
    ball_lens,
    biconvex_lens,
    plano_convex_lens,
)
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
    beam_origin = (-1.5, 0.08 * math.sin(phase))
    beam_target = (1.08, 0.05 * math.sin(phase + 0.3))

    left_lens = Group(
        name="left_lens",
        transform=Transform2D.uniform(
            translate=(-0.6, 0.0),
            scale=1.0 + 0.03 * math.sin(phase),
        ),
        shapes=biconvex_lens(
            center=(0.0, 0.0),
            aperture=0.72,
            center_thickness=0.2,
            left_radius=1.18,
            right_radius=1.18,
            material=GLASS_SOFT,
        ),
    )
    right_lens = Group(
        name="right_lens",
        transform=Transform2D.uniform(
            translate=(0.56, 0.0),
            scale=1.0 + 0.03 * math.sin(phase + math.pi),
        ),
        shapes=plano_convex_lens(
            center=(0.0, 0.0),
            aperture=0.72,
            center_thickness=0.2,
            radius=0.92,
            curved_side="left",
            material=GLASS_BOLD,
        ),
    )
    beam = beam_group(
        "scan_beam",
        beam_origin,
        angle_between(beam_origin, beam_target),
        intensity=0.76,
        width=0.04,
        wavelength_min=430.0,
        wavelength_max=780.0,
    )
    focus = Group(name="focus", shapes=ball_lens((0.0, 0.0), 0.1, GLASS_FOCUS))
    return frame_for([room_group(), left_lens, right_lens, focus, beam])


SPEC = SceneSpec(
    name="breathing_lenses",
    duration=6.0,
    build=build,
    base_exposure=3.60,
    description="A simplified two-lens scan with restrained breathing motion.",
)


if __name__ == "__main__":
    run_scene_cli(SPEC, __doc__ or SPEC.description)
