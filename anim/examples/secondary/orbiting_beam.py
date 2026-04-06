"""Beam light orbiting three dispersive spheres in a mirror box.

Secondary exploratory example demonstrating the animation API:
- Group-based composition (actors: box, spheres, fill light, beam)
- Track for declarative motion and exposure control
- Camera2D for stable framing
- Frame for per-frame look overrides
- Quality presets for draft/final workflow
"""

import math
import sys

from anim import (
    Camera2D,
    Circle,
    Frame,
    FrameContext,
    Group,
    Key,
    Look,
    ProjectorLight,
    Scene,
    Segment,
    SegmentLight,
    Timeline,
    Track,
    Transform2D,
    Wrap,
    glass,
    mirror,
    render,
    sample_scalar,
    smoothstep,
)

# --- Constants ---

NAME = "orbiting_beam"
DURATION = 12.0
BOX_HALF = 1.2
ORBIT_RADIUS = 1.0

WALL = mirror(0.95)
SPHERE_GLASS = glass(1.5, cauchy_b=20000, absorption=0.5)

CAMERA = Camera2D(bounds=[-BOX_HALF - 0.1, -BOX_HALF - 0.1, BOX_HALF + 0.1, BOX_HALF + 0.1])

# --- Tracks ---

ORBIT_ANGLE = Track(
    [
        Key(0.0, math.pi),
        Key(DURATION, math.pi + math.tau, ease=smoothstep),
    ],
    wrap=Wrap.LOOP,
)
BEAM_WIDTH = Track(
    [
        Key(0.0, 0.06),
        Key(4.0, 0.10, ease="ease_in_out_sine"),
        Key(8.0, 0.06, ease="ease_in_out_sine"),
        Key(DURATION, 0.08, ease="ease_in_out_sine"),
    ],
    wrap=Wrap.PINGPONG,
)
# Exposure tuned for normalize="rays" + reinhardx wp=0.5
EXPOSURE = Track(
    [
        Key(0.0, 3.0),
        Key(3.0, 3.3, ease="ease_in_out_sine"),
        Key(7.0, 3.1, ease="ease_in_out_sine"),
        Key(DURATION, 3.2, ease="ease_in_out_sine"),
    ],
    wrap=Wrap.PINGPONG,
)


# --- Actors ---


def make_box() -> Group:
    h = BOX_HALF
    return Group(
        id="mirror_box",
        shapes=[
            Segment(a=[-h, -h], b=[h, -h], material=WALL),
            Segment(a=[h, h], b=[-h, h], material=WALL),
            Segment(a=[-h, h], b=[-h, -h], material=WALL),
            Segment(a=[h, -h], b=[h, h], material=WALL),
        ],
    )


def make_spheres() -> Group:
    return Group(
        id="glass_spheres",
        shapes=[Circle(center=[x, 0], radius=0.2, material=SPHERE_GLASS) for x in (-0.5, 0.0, 0.5)],
    )


def make_fill_light() -> Group:
    w = BOX_HALF * 0.8
    y = BOX_HALF - 0.24 * (BOX_HALF * 2)
    return Group(
        id="fill_light",
        lights=[SegmentLight(a=[-w, y], b=[w, y], intensity=1.5)],
    )


def make_beam(t: float) -> Group:
    angle = sample_scalar(ORBIT_ANGLE, t)
    return Group(
        id="beam",
        transform=Transform2D(
            translate=[math.cos(angle) * ORBIT_RADIUS, math.sin(angle) * ORBIT_RADIUS],
            rotate=angle + math.pi,
        ),
        lights=[
            ProjectorLight(
                position=[0.0, 0.0],
                direction=[1.0, 0.0],
                source_radius=0.0,
                spread=sample_scalar(BEAM_WIDTH, t),
                intensity=0.8,
            )
        ],
    )


# --- Animation ---


def animate(ctx: FrameContext) -> Frame:
    return Frame(
        scene=Scene(
            groups=[make_box(), make_spheres(), make_fill_light(), make_beam(ctx.time)],
        ),
        look=Look(
            exposure=sample_scalar(EXPOSURE, ctx.time),
            tonemap="reinhardx",
            white_point=0.5,
        ),
    )


if __name__ == "__main__":
    preset = "production" if "--hq" in sys.argv else "draft"
    fps = 60 if "--hq" in sys.argv else 2
    render(
        animate,
        Timeline(DURATION, fps=fps),
        f"{NAME}_{preset}.mp4",
        settings=preset,
        camera=CAMERA,
    )
