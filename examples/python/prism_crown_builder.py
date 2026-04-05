"""Canonical example: builder/composition authoring.

This example shows how the current builder surface, reusable scene motifs, and
group transforms can be composed into a compact optical animation without
falling back to large amounts of one-off geometry math.
"""

from __future__ import annotations

import math

from anim import (
    Camera2D,
    Frame,
    FrameContext,
    Group,
    Key,
    Look,
    Material,
    ParallelBeamLight,
    Scene,
    Shot,
    Track,
    Transform2D,
    Wrap,
    beam_splitter,
    elliptical_lens,
    glass,
    mirror,
    mirror_box,
    prism,
    thick_segment,
)
from anim.examples_support import run_example

NAME = "prism_crown_builder"
SUMMARY = "Builder-driven composition: a rotating prism crown around a shared optical core."
WORKFLOW = "builder-composition"
DURATION = 10.0
PRISM_COUNT = 5

CAMERA = Camera2D(bounds=[-1.5, -0.95, 1.5, 0.95])

WALL = mirror(0.94, roughness=0.02)
GUIDE = beam_splitter(0.36, roughness=0.01)
CORE_GLASS = glass(1.52, cauchy_b=18_000, absorption=0.1)
PRISM_MATERIALS = (
    glass(1.46, cauchy_b=14_000, absorption=0.08),
    glass(1.58, cauchy_b=26_000, absorption=0.14),
    glass(1.68, cauchy_b=34_000, absorption=0.2),
)

CROWN_RADIUS = Track(
    [
        Key(0.0, 0.58),
        Key(4.0, 0.78, ease="ease_in_out_sine"),
        Key(DURATION, 0.64, ease="ease_in_out_sine"),
    ],
    wrap=Wrap.PINGPONG,
)
CROWN_SPIN = Track(
    [
        Key(0.0, 0.2 * math.pi),
        Key(DURATION, 1.6 * math.pi, ease="ease_in_out_cubic"),
    ],
    wrap=Wrap.LOOP,
)
CORE_SCALE = Track(
    [
        Key(0.0, 0.94),
        Key(5.0, 1.06, ease="ease_in_out_sine"),
        Key(DURATION, 0.98, ease="ease_in_out_sine"),
    ],
    wrap=Wrap.PINGPONG,
)
BEAM_SWEEP = Track(
    [
        Key(0.0, -0.12),
        Key(4.5, 0.09, ease="ease_in_out_sine"),
        Key(DURATION, -0.05, ease="ease_in_out_sine"),
    ],
    wrap=Wrap.PINGPONG,
)
EXPOSURE = Track(
    [
        Key(0.0, 2.9),
        Key(4.8, 3.1, ease="ease_in_out_sine"),
        Key(DURATION, 2.95, ease="ease_in_out_sine"),
    ],
    wrap=Wrap.PINGPONG,
)


def _bind_material_id(shape, material_id: str):
    shape.material_id = material_id
    return shape


def _normalize(x: float, y: float) -> list[float]:
    length = math.hypot(x, y)
    if length <= 1e-9:
        return [1.0, 0.0]
    return [x / length, y / length]


def _make_prism_group(index: int, radius: float, spin: float) -> Group:
    angle = spin + index * math.tau / PRISM_COUNT
    scale = 0.94 + 0.08 * math.sin(angle * 1.3)
    material_id = f"prism_glass_{index % len(PRISM_MATERIALS)}"
    return Group(
        id=f"crown_prism_{index}",
        transform=Transform2D.uniform(
            translate=(radius * math.cos(angle), radius * math.sin(angle)),
            rotate=angle + math.pi / 2,
            scale=scale,
        ),
        shapes=[
            _bind_material_id(
                prism(
                    center=(0.0, 0.0),
                    size=0.18,
                    material=PRISM_MATERIALS[index % len(PRISM_MATERIALS)],
                    rotation=math.pi / 2,
                    id_prefix=f"body_{index}",
                ),
                material_id,
            )
        ],
    )


def _make_core_group(scale: float) -> Group:
    return Group(
        id="core",
        transform=Transform2D.uniform(scale=scale),
        shapes=[
            *[
                _bind_material_id(shape, "core_glass")
                for shape in elliptical_lens(
                    center=(0.0, 0.0),
                    semi_a=0.22,
                    semi_b=0.4,
                    material=CORE_GLASS,
                    id_prefix="lens",
                )
            ],
            _bind_material_id(
                thick_segment(
                    (-0.34, 0.0),
                    (0.34, 0.0),
                    0.04,
                    GUIDE,
                    id_prefix="guide",
                ),
                "guide_splitter",
            ),
        ],
    )


def make_settings(mode: str = "preview") -> Shot:
    if mode == "hq":
        shot = Shot.preset("production", width=1920, height=1080, rays=3_200_000, depth=12)
    else:
        shot = Shot.preset("preview", width=960, height=540, rays=1_100_000, depth=10)
    shot.name = NAME
    shot.camera = CAMERA
    shot.look = shot.look.with_overrides(
        exposure=3.0,
        gamma=2.1,
        tonemap="reinhardx",
        white_point=0.55,
        normalize="rays",
    )
    return shot


def frame(ctx: FrameContext) -> Frame:
    radius = CROWN_RADIUS(ctx.time)
    spin = CROWN_SPIN(ctx.time)
    materials: dict[str, Material] = {
        "wall_mirror": WALL,
        "guide_splitter": GUIDE,
        "core_glass": CORE_GLASS,
        "prism_glass_0": PRISM_MATERIALS[0],
        "prism_glass_1": PRISM_MATERIALS[1],
        "prism_glass_2": PRISM_MATERIALS[2],
    }
    scene = Scene(
        materials=materials,
        shapes=[
            *[
                _bind_material_id(shape, "wall_mirror")
                for shape in mirror_box(1.35, 0.82, materials["wall_mirror"], id_prefix="wall")
            ]
        ],
        lights=[
            ParallelBeamLight(
                id="beam_main",
                a=[-0.45, 0.72],
                b=[0.45, 0.72],
                direction=_normalize(BEAM_SWEEP(ctx.time), -1.0),
                angular_width=0.015,
                intensity=1.0,
            )
        ],
        groups=[
            _make_core_group(CORE_SCALE(ctx.time)),
            *[_make_prism_group(index, radius, spin) for index in range(PRISM_COUNT)],
        ],
    )
    return Frame(scene=scene, look=Look(exposure=EXPOSURE(ctx.time)))


def main(argv: list[str] | None = None) -> None:
    run_example(
        name=NAME,
        duration=DURATION,
        make_settings=make_settings,
        animate=frame,
        argv=argv,
        description=__doc__,
    )


if __name__ == "__main__":
    main()
