"""Canonical example: varied solid surfaces under one fixed light.

The scene is meant to answer three practical questions:

- how does one small native bevel radius read across different polygon families?
- how should a compound object like a wheel without its outer rim be authored?
- how expressive can a scene stay when everything shares one material?
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from functools import cache
from typing import Callable

from anim import (
    Camera2D,
    Circle,
    Ellipse,
    Frame,
    FrameContext,
    Group,
    Material,
    Polygon,
    ProjectorLight,
    Scene,
    Shot,
    Timeline,
    Transform2D,
    auto_look,
    mirror_box,
    prism,
    regular_polygon,
    thick_segment,
)
from anim.examples_support import run_example

NAME = "solid_surface_gallery"
SUMMARY = "A fixed-light solid-surface gallery using one transmissive rough-metal material."
WORKFLOW = "solid-surface-gallery"
DURATION = 12.0

ROOM_HALF_W = 1.30
ROOM_HALF_H = 0.78
CAMERA = Camera2D(bounds=[-ROOM_HALF_W, -ROOM_HALF_H, ROOM_HALF_W, ROOM_HALF_H])
BEVEL_RADIUS = 0.01
SURFACE = Material(
    ior=1.0,
    roughness=0.7,
    metallic=0.9,
    transmission=1.0,
    absorption=0.0,
    albedo=1.0,
)

ShapeBuilder = Callable[[str], list]


@dataclass(frozen=True)
class SolidSpec:
    id: str
    center: tuple[float, float]
    builder: ShapeBuilder
    base_rotation: float
    swing: float
    rate: float
    phase: float
    scale: float = 1.0


def _normalize(x: float, y: float) -> list[float]:
    length = math.hypot(x, y)
    if length <= 1e-9:
        return [0.0, -1.0]
    return [x / length, y / length]


def _wobble(spec: SolidSpec, time_s: float) -> float:
    primary = math.sin(spec.rate * time_s + spec.phase)
    secondary = math.sin((0.53 * spec.rate) * time_s - 0.7 * spec.phase)
    return spec.base_rotation + spec.swing * (0.82 * primary + 0.18 * secondary)


def _shape_id(id_prefix: str | None, suffix: str) -> str:
    if id_prefix is None:
        return ""
    return f"{id_prefix}_{suffix}"


def _signed_area2(points: list[list[float]]) -> float:
    area2 = 0.0
    for i, a in enumerate(points):
        b = points[(i + 1) % len(points)]
        area2 += a[0] * b[1] - b[0] * a[1]
    return area2


def _ensure_clockwise(points: list[list[float]]) -> list[list[float]]:
    ordered = [list(p) for p in points]
    if _signed_area2(ordered) > 0.0:
        ordered.reverse()
    return ordered


def _polygon_body(
    points: list[list[float]],
    *,
    id_prefix: str,
    corner_radius: float = BEVEL_RADIUS,
) -> list[Polygon]:
    return [
        Polygon(
            id=_shape_id(id_prefix, "body"),
            vertices=_ensure_clockwise(points),
            material=SURFACE,
            corner_radius=corner_radius,
        )
    ]


def _sample_polar(
    radius_fn: Callable[[float], float],
    samples: int,
    *,
    rotation: float = 0.0,
    scale_x: float = 1.0,
    scale_y: float = 1.0,
) -> list[list[float]]:
    points = [
        [
            scale_x
            * radius_fn(rotation + math.tau * i / samples)
            * math.cos(rotation + math.tau * i / samples),
            scale_y
            * radius_fn(rotation + math.tau * i / samples)
            * math.sin(rotation + math.tau * i / samples),
        ]
        for i in range(samples)
    ]
    return _ensure_clockwise(points)


def _badge_outline() -> list[list[float]]:
    return _ensure_clockwise(
        [
            [-0.16, -0.30],
            [-0.30, -0.16],
            [-0.30, 0.16],
            [-0.16, 0.30],
            [0.16, 0.30],
            [0.30, 0.16],
            [0.30, -0.16],
            [0.16, -0.30],
        ]
    )


def _gem_outline() -> list[list[float]]:
    return _ensure_clockwise(
        [
            [-0.08, -0.30],
            [-0.24, -0.14],
            [-0.28, 0.10],
            [-0.12, 0.30],
            [0.12, 0.30],
            [0.28, 0.10],
            [0.24, -0.14],
            [0.08, -0.30],
        ]
    )


def _kite_outline() -> list[list[float]]:
    return _ensure_clockwise(
        [
            [0.00, -0.32],
            [-0.22, -0.12],
            [-0.18, 0.18],
            [0.00, 0.32],
            [0.22, 0.12],
            [0.26, -0.16],
        ]
    )


def _leaf_outline() -> list[list[float]]:
    return _ensure_clockwise(
        [
            [0.00, -0.32],
            [-0.10, -0.20],
            [-0.18, -0.02],
            [-0.12, 0.20],
            [0.00, 0.32],
            [0.12, 0.20],
            [0.18, -0.02],
            [0.10, -0.20],
        ]
    )


def _build_badge(id_prefix: str) -> list:
    return _polygon_body(_badge_outline(), id_prefix=id_prefix)


def _build_pentagon(id_prefix: str) -> list:
    return [
        regular_polygon(
            (0.0, 0.0),
            0.25,
            5,
            SURFACE,
            rotation=0.5 * math.pi,
            corner_radius=BEVEL_RADIUS,
            id_prefix=id_prefix,
        )
    ]


def _build_prism(id_prefix: str) -> list:
    return [
        prism(
            (0.0, 0.0),
            0.29,
            SURFACE,
            rotation=0.5 * math.pi,
            corner_radius=BEVEL_RADIUS,
            id_prefix=id_prefix,
        )
    ]


def _build_wheel(id_prefix: str) -> list:
    shapes: list = [
        Circle(id=_shape_id(id_prefix, "hub"), center=[0.0, 0.0], radius=0.10, material=SURFACE)
    ]
    start_radius = 0.16
    end_radius = 0.36
    for i in range(5):
        angle = -0.5 * math.pi + i * math.tau / 5
        start = (start_radius * math.cos(angle), start_radius * math.sin(angle))
        end = (end_radius * math.cos(angle), end_radius * math.sin(angle))
        shapes.append(
            thick_segment(
                start,
                end,
                0.07,
                SURFACE,
                corner_radius=BEVEL_RADIUS,
                id_prefix=_shape_id(id_prefix, f"spoke_{i}"),
            )
        )
    return shapes


def _build_leaf(id_prefix: str) -> list:
    return _polygon_body(_leaf_outline(), id_prefix=id_prefix)


def _build_ellipse(id_prefix: str) -> list:
    return [
        Ellipse(
            id=_shape_id(id_prefix, "body"),
            center=[0.0, 0.0],
            semi_a=0.28,
            semi_b=0.15,
            rotation=0.18,
            material=SURFACE,
        )
    ]


def _build_gem(id_prefix: str) -> list:
    return _polygon_body(_gem_outline(), id_prefix=id_prefix)


def _build_teardrop(id_prefix: str) -> list:
    def radius(theta: float) -> float:
        return 0.18 * (1.0 - 0.60 * math.sin(theta))

    points = _sample_polar(radius, 28, rotation=-0.5 * math.pi, scale_x=0.74)
    return _polygon_body(points, id_prefix=id_prefix, corner_radius=0.0)


def _build_kite(id_prefix: str) -> list:
    return _polygon_body(_kite_outline(), id_prefix=id_prefix)


SOLIDS = [
    SolidSpec("badge", (-0.95, 0.46), _build_badge, 0.0, 0.026 * math.pi, 0.54, 0.0),
    SolidSpec("pentagon", (0.0, 0.46), _build_pentagon, 0.0, 0.024 * math.pi, 0.62, 0.6),
    SolidSpec("prism", (0.95, 0.46), _build_prism, 0.0, 0.028 * math.pi, 0.70, 1.0),
    SolidSpec("wheel", (-0.95, 0.00), _build_wheel, 0.0, 0.060 * math.pi, 0.44, 0.2),
    SolidSpec("leaf", (0.0, 0.00), _build_leaf, 0.0, 0.034 * math.pi, 0.56, 1.7),
    SolidSpec("ellipse", (0.95, 0.00), _build_ellipse, 0.18 * math.pi, 0.018 * math.pi, 0.48, 2.1),
    SolidSpec("gem", (-0.95, -0.46), _build_gem, 0.0, 0.030 * math.pi, 0.60, 0.9),
    SolidSpec("teardrop", (0.0, -0.46), _build_teardrop, 0.0, 0.022 * math.pi, 0.52, 1.3),
    SolidSpec("kite", (0.95, -0.46), _build_kite, 0.0, 0.032 * math.pi, 0.66, 2.4),
]


def _make_group(spec: SolidSpec, time_s: float) -> Group:
    return Group(
        id=spec.id,
        transform=Transform2D.uniform(
            translate=spec.center,
            rotate=_wobble(spec, time_s),
            scale=spec.scale,
        ),
        shapes=spec.builder(spec.id),
    )


def _make_base_settings(mode: str) -> Shot:
    if mode == "hq":
        shot = Shot.preset("production", width=1920, height=1080, rays=1_600_000, depth=12)
    else:
        shot = Shot.preset("preview", width=960, height=540, rays=320_000, depth=10)
    shot.camera = CAMERA
    shot.look = shot.look.with_overrides(
        exposure=-5.0,
        gamma=2.1,
        tonemap="reinhardx",
        white_point=0.56,
        normalize="rays",
        ambient=0.0,
        background=[0.0, 0.0, 0.0],
    )
    return shot


@cache
def _analyzed_look(mode: str):
    return auto_look(
        frame,
        Timeline(DURATION),
        settings=_make_base_settings(mode),
        camera=CAMERA,
        sample_count=6,
        target_mean=0.30,
        max_clipping=0.01,
    )


def make_settings(mode: str = "preview") -> Shot:
    shot = _make_base_settings(mode)
    shot.name = NAME
    shot.look = _analyzed_look(mode).with_overrides()
    return shot


def frame(ctx: FrameContext) -> Frame:
    scene = Scene(
        shapes=mirror_box(ROOM_HALF_W, ROOM_HALF_H, SURFACE, id_prefix="room"),
        lights=[
            ProjectorLight(
                id="beam_main",
                position=[0.0, 0.70],
                direction=_normalize(0.12, -1.0),
                source_radius=1.12,
                spread=0.014,
                intensity=1.0,
            )
        ],
        groups=[_make_group(spec, ctx.time) for spec in SOLIDS],
    )
    return Frame(scene=scene)


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
