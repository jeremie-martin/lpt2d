"""Clean scanning reflective field.

Inspired by the exported middle_frame draft, but rebuilt to be:
- cleaner
- more aligned
- more legible
- more architectural

Scene language:
- fixed outer frame
- fixed top rail light
- one scanning beam moving left -> right
- structured reflector field below
- tiny camera drift and zoom only
"""

import math
import sys

from anim import (
    BeamLight,
    Camera2D,
    Frame,
    FrameContext,
    Group,
    Key,
    Look,
    Scene,
    Segment,
    SegmentLight,
    Shot,
    Timeline,
    Track,
    Transform2D,
    Wrap,
    mirror,
    render,
)
from anim.types import Material

NAME = "clean_scanning_reflective_field"
DURATION = 12.0

# Materials
FRAME_MATERIAL = mirror(0.95, roughness=0.02)
FIELD_MATERIAL = Material(
    ior=1.45,
    roughness=0.01,
    metallic=0.5,
    transmission=0.2,
    absorption=0.2,
    albedo=0.4,
)

# Beam path: left -> right near the top, gently descending.
BEAM_X = Track(
    [
        Key(0.0, -1.2),
        Key(DURATION, 1.42, ease="linear"),
    ],
    wrap=Wrap.CLAMP,
)
BEAM_Y = Track(
    [
        Key(0.0, 0.93),
        Key(DURATION, 0.85, ease="linear"),
    ],
    wrap=Wrap.CLAMP,
)

# Camera: almost fixed, tiny diagonal drift and tiny zoom-out.
CAMERA_CENTER = Track(
    [
        Key(0.0, (0.00, 0.10)),
        Key(DURATION, (0.00, 0.1), ease="linear"),
    ],
    wrap=Wrap.CLAMP,
)
CAMERA_WIDTH = Track(
    [
        Key(0.0, 3.72),
        Key(DURATION, 3.72, ease="linear"),
    ],
    wrap=Wrap.CLAMP,
)

# Look shaping (tuned for normalize="rays" + reinhardx wp=0.5)
EXPOSURE = Track(
    [
        Key(0.0, 3.80, ease="linear"),
        Key(DURATION, 3.80, ease="linear"),
    ],
    wrap=Wrap.CLAMP,
)


def seg(a, b, material=FIELD_MATERIAL):
    return Segment(a=list(a), b=list(b), material=material)


def make_frame_group() -> Group:
    # Clean, aligned outer box.
    left = -1.72
    right = 1.72
    top = 1.03
    bottom = -0.88

    shapes = [
        seg((left, top), (right, top), FRAME_MATERIAL),
        seg((left, top), (left, bottom), FRAME_MATERIAL),
        seg((left, bottom), (right, bottom), FRAME_MATERIAL),
        seg((right, bottom), (right, top), FRAME_MATERIAL),
    ]
    return Group(id="frame", shapes=shapes)


def make_top_rail_light() -> Group:
    # Very soft structural fill, inspired by the segment light in the draft.
    dx = 0.001
    return Group(
        id="top_rail_light",
        lights=[
            SegmentLight(
                a=[-1.72 + dx, 1.03 - dx],
                b=[1.72 - dx, 1.03 - dx],
                intensity=0.5,
                wavelength_min=430.0,
                wavelength_max=700.0,
            )
        ],
    )


def make_reflector_field() -> Group:
    # Rebuilt as ordered loose columns: cleaner spacing, stronger rhythm.
    shapes = [
        # Column 1
        seg((-1.46, 0.18), (-1.20, 0.08)),
        seg((-1.42, -0.02), (-1.10, -0.14)),
        seg((-1.36, -0.28), (-1.12, -0.42)),
        seg((-1.32, -0.56), (-1.10, -0.68)),
        # Column 2
        seg((-0.98, 0.26), (-0.74, 0.18)),
        seg((-1.00, 0.02), (-0.62, -0.02)),
        seg((-0.94, -0.26), (-0.58, -0.30)),
        seg((-0.88, -0.56), (-0.54, -0.57)),
        # Column 3
        seg((-0.52, 0.20), (-0.24, 0.18)),
        seg((-0.44, -0.02), (-0.14, -0.04)),
        seg((-0.42, -0.26), (-0.18, -0.30)),
        seg((-0.34, -0.60), (-0.02, -0.62)),
        # Column 4
        seg((0.02, 0.14), (0.30, 0.12)),
        seg((0.08, -0.06), (0.38, -0.10)),
        seg((0.10, -0.34), (0.42, -0.42)),
        seg((0.12, -0.62), (0.48, -0.64)),
        # Column 5
        seg((0.56, 0.10), (0.92, 0.18)),
        seg((0.66, -0.10), (1.02, -0.06)),
        seg((0.68, -0.34), (1.14, -0.30)),
        seg((0.72, -0.62), (1.08, -0.54)),
        # Column 6
        seg((1.14, 0.18), (1.48, 0.28)),
        seg((1.18, -0.02), (1.50, 0.02)),
        seg((1.22, -0.28), (1.50, -0.20)),
        seg((1.24, -0.54), (1.50, -0.46)),
        # Smaller linking accents for density and rhythm
        seg((-1.18, 0.42), (-0.96, 0.34)),
        seg((-0.72, 0.40), (-0.50, 0.34)),
        seg((-0.20, 0.34), (0.04, 0.32)),
        seg((0.36, 0.28), (0.62, 0.28)),
        seg((0.94, 0.34), (1.22, 0.40)),
        seg((-1.06, -0.74), (-0.78, -0.76)),
        seg((-0.52, -0.74), (-0.22, -0.76)),
        seg((0.10, -0.76), (0.42, -0.78)),
        seg((0.78, -0.74), (1.06, -0.70)),
    ]
    return Group(id="reflector_field", shapes=shapes)


def make_scanning_beam(ctx: FrameContext) -> Group:
    dx = 1.42 - (-1.45)
    dy = 0.85 - 0.93
    angle_of_path = math.atan2(dy, dx)
    beam_angle = angle_of_path - math.pi / 2  # perpendicular, downward side

    return Group(
        id="scanning_beam",
        transform=Transform2D(
            translate=[float(BEAM_X(ctx.time)), float(BEAM_Y(ctx.time))],
            rotate=beam_angle,
        ),
        lights=[
            BeamLight(
                origin=[0.0, 0.0],
                direction=[1.0, 0.0],
                angular_width=0.070,
                intensity=0.5,
                wavelength_min=430.0,
                wavelength_max=700.0,
            )
        ],
    )


FRAME_GROUP = make_frame_group()
RAIL_LIGHT_GROUP = make_top_rail_light()
FIELD_GROUP = make_reflector_field()


def animate(ctx: FrameContext) -> Frame:
    cx, cy = CAMERA_CENTER(ctx.time)
    camera = Camera2D(center=[cx, cy], width=float(CAMERA_WIDTH(ctx.time)))

    return Frame(
        scene=Scene(
            groups=[
                FRAME_GROUP,
                FIELD_GROUP,
                RAIL_LIGHT_GROUP,
                make_scanning_beam(ctx),
            ],
        ),
        camera=camera,
        look=Look(
            exposure=float(EXPOSURE(ctx.time)),
            contrast=1.0,
            tonemap="reinhardx",
            white_point=0.5,
        ),
    )


if __name__ == "__main__":
    hq = "--hq" in sys.argv
    shot = Shot.preset(
        "production" if hq else "draft",
        width=1920 if hq else 720,
        height=1080 if hq else 404,
        rays=7_000_000 if hq else 100_000,
        batch=300_000 if hq else 100_000,
        depth=14 if hq else 10,
    )
    render(
        animate,
        Timeline(DURATION, fps=60 if hq else 30),
        f"{NAME}_{'hq' if hq else 'preview'}.mp4",
        settings=shot,
    )
