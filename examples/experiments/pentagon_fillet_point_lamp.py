"""Minimal reflection repro: native rounded pentagon mirror in an absorbing box.

The scene is intentionally sparse:

- one point light
- one closed pentagon outline with native `Polygon.corner_radius` bevel fillets
- four perfectly absorbing walls

The goal is to isolate mirror reflection behavior without secondary room
reflections from mirror walls.
"""

from __future__ import annotations

import argparse
import math
from functools import cache
from pathlib import Path

from anim import (
    Camera2D,
    Frame,
    FrameContext,
    PointLight,
    Polygon,
    Scene,
    Segment,
    Shot,
    Timeline,
    absorber,
    auto_look,
    opaque_mirror,
    render,
    render_still,
)
from anim.examples_support import REPO_ROOT

NAME = "pentagon_fillet_point_lamp"
SUMMARY = "Minimal point-light reflection repro with a native rounded pentagon mirror and absorbing walls."
WORKFLOW = "reflection-repro"
DURATION = 1.0

CAMERA = Camera2D(bounds=[-1.08, -0.62, 1.08, 0.62])

ABSORB_ID = "wall_absorber"
MIRROR_ID = "pentagon_mirror"
DEFAULT_CORNER_RADIUS = 0.028
CORNER_RADIUS = DEFAULT_CORNER_RADIUS


def _regular_polygon_vertices(
    center: tuple[float, float],
    radius: float,
    sides: int,
    rotation: float,
) -> list[list[float]]:
    cx, cy = center
    return [
        [
            cx + radius * math.cos(rotation - i * math.tau / sides),
            cy + radius * math.sin(rotation - i * math.tau / sides),
        ]
        for i in range(sides)
    ]


def _pentagon_shape(corner_radius: float) -> Polygon:
    base = _regular_polygon_vertices(
        center=(0.0, 0.0), radius=0.24, sides=5, rotation=0.5 * math.pi
    )
    return Polygon(
        id="pentagon_body",
        vertices=base,
        material_id=MIRROR_ID,
        corner_radius=corner_radius,
    )


def _walls() -> list[Segment]:
    return [
        Segment(id="wall_bottom", a=[-0.98, -0.54], b=[0.98, -0.54], material_id=ABSORB_ID),
        Segment(id="wall_top", a=[0.98, 0.54], b=[-0.98, 0.54], material_id=ABSORB_ID),
        Segment(id="wall_left", a=[-0.98, 0.54], b=[-0.98, -0.54], material_id=ABSORB_ID),
        Segment(id="wall_right", a=[0.98, -0.54], b=[0.98, 0.54], material_id=ABSORB_ID),
    ]


def _base_scene(corner_radius: float) -> Scene:
    return Scene(
        materials={
            ABSORB_ID: absorber(),
            MIRROR_ID: opaque_mirror(1.0, roughness=0.0),
        },
        shapes=[*_walls(), _pentagon_shape(corner_radius)],
        lights=[
            PointLight(
                id="lamp",
                position=[-0.58, 0.28],
                intensity=1.6,
            )
        ],
    )


def _make_base_settings(mode: str) -> Shot:
    if mode == "hq":
        shot = Shot.preset("production", width=1920, height=1080, rays=30_000_000, depth=12)
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


def _authored_shot(mode: str) -> Shot:
    shot = _make_base_settings(mode)
    shot.name = NAME
    shot.scene = _base_scene(CORNER_RADIUS)
    shot.look = _analyzed_look(mode, CORNER_RADIUS).with_overrides()
    return shot


@cache
def _analyzed_look(mode: str, corner_radius: float):
    return auto_look(
        frame,
        Timeline(DURATION),
        settings=_make_base_settings(mode),
        camera=CAMERA,
        frame=0,
        sample_count=1,
        target_mean=0.26,
        max_clipped_channel_fraction=0.01,
    )


def make_settings(mode: str = "preview") -> Shot:
    return _authored_shot(mode)


def frame(_ctx: FrameContext) -> Frame:
    return Frame(scene=_base_scene(CORNER_RADIUS))


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hq", action="store_true", help="render the HQ variant")
    parser.add_argument("--frame", type=int, help="render a still frame instead of a video")
    parser.add_argument("--output", type=Path, help="explicit output path")
    parser.add_argument("--fast", action="store_true", help="pass --fast to the renderer")
    parser.add_argument(
        "--corner-radius",
        type=float,
        default=DEFAULT_CORNER_RADIUS,
        help="native Polygon.corner_radius bevel-fillet radius in scene units",
    )
    parser.add_argument(
        "--save-json",
        type=Path,
        help="optional authored shot export path; defaults to a sibling .json next to the render output",
    )
    return parser.parse_args(argv)


def _json_output_path(args: argparse.Namespace, mode: str, output: Path) -> Path:
    if args.save_json is not None:
        return args.save_json
    return output.with_suffix(".json")


def main(argv: list[str] | None = None) -> None:
    global CORNER_RADIUS

    args = _parse_args(argv)
    CORNER_RADIUS = max(0.0, args.corner_radius)
    mode = "hq" if args.hq else "preview"
    settings = make_settings(mode)
    timeline = Timeline(DURATION, fps=60 if args.hq else 30)

    if args.frame is not None:
        output = args.output or (REPO_ROOT / f"{NAME}_{mode}_{args.frame:04d}.png")
        json_path = _json_output_path(args, mode, output)
        settings.save(json_path)
        print(f"saved {json_path}")
        render_still(
            frame,
            timeline,
            str(output),
            frame=args.frame,
            settings=settings,
            fast=args.fast,
        )
        return

    output = args.output or (REPO_ROOT / f"{NAME}_{mode}.mp4")
    json_path = _json_output_path(args, mode, output)
    settings.save(json_path)
    print(f"saved {json_path}")
    render(
        frame,
        timeline,
        str(output),
        settings=settings,
        fast=args.fast,
        crf=16 if args.hq else 18,
    )


if __name__ == "__main__":
    main()
