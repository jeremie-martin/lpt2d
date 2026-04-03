"""Static reflective field with a single scanning beam.

Design goals:
- very readable
- no object motion except the beam source
- fixed segment field
- camera almost fixed, with a tiny linear diagonal drift
- many small reflective/transmissive segments
- normalize="max" for stable output
- preview render uses 100K rays
"""

import sys

from anim import (
    BeamLight,
    Camera2D,
    Frame,
    FrameContext,
    Group,
    Key,
    RenderOverrides,
    RenderSettings,
    Scene,
    Segment,
    Timeline,
    Track,
    Transform2D,
    Wrap,
    mirror,
    render,
)

import json
from anim import Frame, FrameContext, Timeline

def export_frame_json(animate, timeline, frame_index: int, path: str):
    if isinstance(timeline, (int, float)):
        timeline = Timeline(duration=float(timeline))

    ctx = FrameContext(
        frame=frame_index,
        time=timeline.time_at(frame_index),
        progress=timeline.progress_at(frame_index),
        fps=timeline.fps,
        dt=timeline.dt,
        total_frames=timeline.total_frames,
        duration=timeline.duration,
    )

    result = animate(ctx)
    frame = result if isinstance(result, Frame) else Frame(scene=result)

    scene_dict = frame.scene.to_dict()

    with open(path, "w") as f:
        json.dump(scene_dict, f, indent=2)

    print(f"Exported frame {frame_index} → {path}")

NAME = "scanning_reflective_field"
DURATION = 10.0

# Semi-reflective / semi-transmissive mirror feel with slight softness.
SEGMENT_MATERIAL = mirror(0.88, roughness=0.04)

# Beam path: left -> right near the top, with a slight downward drift.
BEAM_X = Track(
    [
        Key(0.0, -1.55),
        Key(DURATION, 1.45, ease="linear"),
    ],
    wrap=Wrap.CLAMP,
)
BEAM_Y = Track(
    [
        Key(0.0, 1.10),
        Key(DURATION, 0.98, ease="linear"),
    ],
    wrap=Wrap.CLAMP,
)

# Camera: almost fixed, tiny diagonal drift and tiny zoom-out.
CAMERA_CENTER = Track(
    [
        Key(0.0, (-0.02, 0.18)),
        Key(DURATION, (0.05, 0.14), ease="linear"),
    ],
    wrap=Wrap.CLAMP,
)
CAMERA_WIDTH = Track(
    [
        Key(0.0, 3.55),
        Key(DURATION, 3.70, ease="linear"),
    ],
    wrap=Wrap.CLAMP,
)

# Gentle look shaping only.
EXPOSURE = Track(
    [
        Key(0.0, -1.20, ease="linear"),
        Key(DURATION, -1.05, ease="linear"),
    ],
    wrap=Wrap.CLAMP,
)
WHITE_POINT = Track(
    [
        Key(0.0, 1.14, ease="linear"),
        Key(DURATION, 1.26, ease="linear"),
    ],
    wrap=Wrap.CLAMP,
)


def make_segment(a, b):
    return Segment(a=list(a), b=list(b), material=SEGMENT_MATERIAL)


def make_reflector_field() -> Group:
    shapes = [
        # far left cluster
        make_segment((-1.42, -0.05), (-1.08, -0.22)),
        make_segment((-1.48,  0.10), (-1.22,  0.00)),
        make_segment((-1.30,  0.28), (-1.02,  0.18)),
        make_segment((-1.42, -0.42), (-1.18, -0.62)),

        # left cluster
        make_segment((-0.96, -0.04), (-0.62, -0.10)),
        make_segment((-0.86,  0.02), (-0.48, -0.02)),
        make_segment((-0.82,  0.36), (-0.60,  0.28)),
        make_segment((-0.86, -0.36), (-0.50, -0.40)),
        make_segment((-0.72, -0.66), (-0.38, -0.67)),

        # left-mid
        make_segment((-0.42, -0.22), (-0.18, -0.25)),
        make_segment((-0.24, -0.46), ( 0.06, -0.38)),
        make_segment((-0.22,  0.02), ( 0.04,  0.00)),
        make_segment((-0.28,  0.18), (-0.02,  0.17)),
        make_segment((-0.18, -0.74), ( 0.18, -0.76)),

        # center
        make_segment(( 0.10, -0.16), ( 0.38, -0.22)),
        make_segment(( 0.06, -0.48), ( 0.42, -0.58)),
        make_segment(( 0.10, -0.64), ( 0.48, -0.66)),
        make_segment(( 0.02,  0.06), ( 0.32,  0.05)),
        make_segment(( 0.16, -0.08), ( 0.42, -0.10)),

        # right-mid
        make_segment(( 0.56, -0.44), ( 1.02, -0.43)),
        make_segment(( 0.74, -0.18), ( 1.16, -0.14)),
        make_segment(( 0.72, -0.72), ( 1.08, -0.64)),
        make_segment(( 0.70, -0.34), ( 1.22, -0.30)),
        make_segment(( 0.66,  0.12), ( 1.06,  0.20)),

        # right cluster
        make_segment(( 1.16, -0.28), ( 1.48, -0.18)),
        make_segment(( 1.20, -0.72), ( 1.46, -0.66)),
        make_segment(( 1.26, -0.56), ( 1.48, -0.48)),
        make_segment(( 1.18, -0.02), ( 1.50,  0.02)),
        make_segment(( 1.20,  0.22), ( 1.56,  0.30)),
    ]
    return Group(name="reflector_field", shapes=shapes)


def make_beam(ctx: FrameContext) -> Group:
    return Group(
        name="scanning_beam",
        transform=Transform2D(
            translate=[float(BEAM_X(ctx.time)), float(BEAM_Y(ctx.time))],
            rotate=-0.42,  # downward-right so rays actually hit the field
        ),
        lights=[
            BeamLight(
                origin=[0.0, 0.0],
                direction=[1.0, 0.0],
                angular_width=0.09,
                intensity=1.15,
                wavelength_min=430.0,
                wavelength_max=700.0,
            )
        ],
    )


FIELD_GROUP = make_reflector_field()


def animate(ctx: FrameContext) -> Frame:
    center_x, center_y = CAMERA_CENTER(ctx.time)
    camera = Camera2D(center=[center_x, center_y], width=float(CAMERA_WIDTH(ctx.time)))

    return Frame(
        scene=Scene(
            name=NAME,
            groups=[
                FIELD_GROUP,
                make_beam(ctx),
            ],
        ),
        camera=camera,
        render=RenderOverrides(
            exposure=float(EXPOSURE(ctx.time)),
            contrast=1.0,
            tonemap="reinhardx",
            white_point=float(WHITE_POINT(ctx.time)),
            normalize="max",
        ),
    )


if __name__ == "__main__":
    hq = "--hq" in sys.argv
    settings = RenderSettings.preset(
        "production" if hq else "draft",
        width=1600 if hq else 720,
        height=900 if hq else 404,
        rays=7_000_000 if hq else 100_000,
        batch=300_000 if hq else 100_000,
        depth=14 if hq else 10,
    )
    timeline = Timeline(DURATION, fps=30)

    mid_frame = timeline.total_frames // 2

    export_frame_json(
        animate,
        timeline,
        frame_index=mid_frame,
        path="middle_frame.json",
    )

    exit()

    render(
        animate,
        Timeline(DURATION, fps=60 if hq else 30),
        f"{NAME}_{'hq' if hq else 'preview'}.mp4",
        settings=settings,
    )
