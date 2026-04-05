"""Layered orbiting beams around a breathing glass triplet."""

import math
import sys

from anim import (
    Arc,
    BeamLight,
    Camera2D,
    Circle,
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
    glass,
    mirror,
    render,
    sample_scalar,
    sample_vec2,
    smoothstep,
)

NAME = "layered_orbiting_beam"
DURATION = 12.0
BOX_HALF_EXTENT = 1.25

BOX_MATERIAL = mirror(0.96)
ACCENT_MIRROR = mirror(0.9)
GLASS_MATERIALS = (
    glass(1.46, cauchy_b=14_000, absorption=0.16),
    glass(1.58, cauchy_b=24_000, absorption=0.22),
    glass(1.7, cauchy_b=32_000, absorption=0.28),
)

PRIMARY_ORBIT = Track(
    [
        Key(0.0, 0.96 * math.pi),
        Key(2.8, 1.28 * math.pi, ease="ease_in_out_sine"),
        Key(5.4, 1.66 * math.pi, ease="ease_in_out_sine"),
        Key(8.8, 2.12 * math.pi, ease="ease_in_out_sine"),
        Key(DURATION, 2.7 * math.pi, ease="ease_in_out_cubic"),
    ],
    wrap=Wrap.LOOP,
)
ACCENT_ORBIT = Track(
    [
        Key(0.0, 0.18 * math.pi),
        Key(3.1, -0.04 * math.pi, ease="ease_in_out_sine"),
        Key(6.3, -0.36 * math.pi, ease="ease_in_out_sine"),
        Key(9.2, -0.72 * math.pi, ease="ease_in_out_sine"),
        Key(DURATION, -1.04 * math.pi, ease="ease_in_out_cubic"),
    ],
    wrap=Wrap.LOOP,
)
BEAM_RADIUS = Track(
    [
        Key(0.0, 0.96),
        Key(4.0, 1.05, ease="ease_in_out_sine"),
        Key(8.0, 0.99, ease="ease_in_out_sine"),
        Key(DURATION, 1.08, ease="ease_in_out_cubic"),
    ],
    wrap=Wrap.PINGPONG,
)
CLUSTER_ROTATION = Track(
    [
        Key(0.0, -0.18),
        Key(3.4, 0.12, ease="ease_in_out_sine"),
        Key(7.0, -0.08, ease="ease_in_out_sine"),
        Key(DURATION, 0.16, ease="ease_in_out_cubic"),
    ],
    wrap=Wrap.PINGPONG,
)
CLUSTER_SCALE = Track(
    [
        Key(0.0, 0.94),
        Key(3.0, 1.08, ease="ease_in_out_sine"),
        Key(7.4, 0.98, ease="ease_in_out_sine"),
        Key(DURATION, 1.12, ease="ease_in_out_cubic"),
    ],
    wrap=Wrap.PINGPONG,
)
SHUTTER_ROTATION = Track(
    [
        Key(0.0, 0.08 * math.pi),
        Key(4.3, -0.14 * math.pi, ease="ease_in_out_sine"),
        Key(8.5, 0.12 * math.pi, ease="ease_in_out_sine"),
        Key(DURATION, -0.1 * math.pi, ease="ease_in_out_cubic"),
    ],
    wrap=Wrap.PINGPONG,
)
FILL_PROGRESS = Track(
    [
        Key(0.0, 0.86),
        Key(3.0, 0.24, ease="ease_in_out_sine"),
        Key(7.0, 0.68, ease="ease_in_out_sine"),
        Key(DURATION, 0.18, ease="ease_in_out_cubic"),
    ],
    wrap=Wrap.PINGPONG,
)
FILL_WIDTH = Track(
    [
        Key(0.0, 0.9),
        Key(4.0, 1.18, ease="ease_in_out_sine"),
        Key(8.0, 0.96, ease="ease_in_out_sine"),
        Key(DURATION, 1.12, ease="ease_in_out_cubic"),
    ],
    wrap=Wrap.PINGPONG,
)
CAMERA_CENTER = Track(
    [
        Key(0.0, (0.0, -0.02)),
        Key(4.0, (0.08, 0.05), ease="ease_in_out_sine"),
        Key(8.0, (-0.07, 0.04), ease="ease_in_out_sine"),
        Key(DURATION, (0.0, -0.03), ease="ease_in_out_sine"),
    ],
    wrap=Wrap.PINGPONG,
)
CAMERA_WIDTH = Track(
    [
        Key(0.0, 2.86),
        Key(3.6, 2.48, ease="ease_in_out_cubic"),
        Key(8.1, 2.34, ease="ease_in_out_sine"),
        Key(DURATION, 2.74, ease="ease_in_out_cubic"),
    ],
    wrap=Wrap.PINGPONG,
)
# Exposure tuned for normalize="rays" + reinhardx wp=0.5
EXPOSURE = Track(
    [
        Key(0.0, 3.75),
        Key(4.0, 3.96, ease="ease_in_out_sine"),
        Key(8.0, 3.88, ease="ease_in_out_sine"),
        Key(DURATION, 4.02, ease="ease_in_out_cubic"),
    ],
    wrap=Wrap.PINGPONG,
)


def polar(radius: float, angle: float) -> tuple[float, float]:
    return (radius * math.cos(angle), radius * math.sin(angle))


def vertical_position(progress: float) -> float:
    top = BOX_HALF_EXTENT - 0.16
    bottom = -BOX_HALF_EXTENT + 0.16
    t = max(0.0, min(progress, 1.0))
    return top + (bottom - top) * t


def reveal(progress: float) -> float:
    fade_in = smoothstep(min(progress / 0.12, 1.0))
    fade_out = smoothstep(min((1.0 - progress) / 0.08, 1.0))
    return fade_in * fade_out


def make_box_group() -> Group:
    h = BOX_HALF_EXTENT
    return Group(
        id="mirror_box",
        shapes=[
            Segment(a=[-h, -h], b=[h, -h], material=BOX_MATERIAL),
            Segment(a=[h, h], b=[-h, h], material=BOX_MATERIAL),
            Segment(a=[-h, h], b=[-h, -h], material=BOX_MATERIAL),
            Segment(a=[h, -h], b=[h, h], material=BOX_MATERIAL),
            Segment(a=[-h, 0.52], b=[-0.78, h], material=ACCENT_MIRROR),
            Segment(a=[0.78, h], b=[h, 0.52], material=ACCENT_MIRROR),
            Segment(a=[-0.78, -h], b=[-h, -0.52], material=ACCENT_MIRROR),
            Segment(a=[h, -0.52], b=[0.78, -h], material=ACCENT_MIRROR),
        ],
    )


def make_cluster_group(t: float) -> Group:
    scale = sample_scalar(CLUSTER_SCALE, t)
    return Group(
        id="glass_triplet",
        transform=Transform2D.uniform(rotate=sample_scalar(CLUSTER_ROTATION, t), scale=scale),
        shapes=[
            Circle(center=[-0.46, 0.08], radius=0.18, material=GLASS_MATERIALS[0]),
            Circle(center=[0.0, -0.02], radius=0.2, material=GLASS_MATERIALS[1]),
            Circle(center=[0.46, 0.08], radius=0.18, material=GLASS_MATERIALS[2]),
        ],
    )


def make_shutter_group(t: float) -> Group:
    return Group(
        id="mirror_shutters",
        transform=Transform2D(rotate=sample_scalar(SHUTTER_ROTATION, t)),
        shapes=[
            Arc(
                center=[0.0, 0.0],
                radius=0.62,
                angle_start=0.16 * math.pi,
                sweep=0.68 * math.pi,
                material=ACCENT_MIRROR,
            ),
            Arc(
                center=[0.0, 0.0],
                radius=0.62,
                angle_start=1.16 * math.pi,
                sweep=0.68 * math.pi,
                material=ACCENT_MIRROR,
            ),
        ],
    )


def make_fill_group(t: float) -> Group:
    width = sample_scalar(FILL_WIDTH, t)
    intensity = 0.22 + 0.06 * math.sin(1.4 * t + 0.4)
    return Group(
        id="fill_light",
        transform=Transform2D(
            translate=[0.0, vertical_position(sample_scalar(FILL_PROGRESS, t))],
            rotate=0.06 * math.sin(0.8 * t),
            scale=[width, 1.0],
        ),
        lights=[
            SegmentLight(
                a=[-0.42, 0.0],
                b=[0.42, 0.0],
                intensity=intensity,
                wavelength_min=430.0,
                wavelength_max=700.0,
            )
        ],
    )


def make_beam_group(
    name: str,
    angle: float,
    radius: float,
    scale: float,
    intensity: float,
    angular_width: float,
    wavelength_min: float,
    wavelength_max: float,
) -> Group:
    return Group(
        id=name,
        transform=Transform2D.uniform(
            translate=polar(radius, angle),
            rotate=angle + math.pi,
            scale=scale,
        ),
        lights=[
            BeamLight(
                origin=[0.0, 0.0],
                direction=[1.0, 0.0],
                angular_width=angular_width,
                intensity=intensity,
                wavelength_min=wavelength_min,
                wavelength_max=wavelength_max,
            )
        ],
    )


def animate(ctx: FrameContext) -> Frame:
    fade = reveal(ctx.progress)
    radius = sample_scalar(BEAM_RADIUS, ctx.time)
    exposure = 1.0 + (sample_scalar(EXPOSURE, ctx.time) - 1.0) * fade
    groups = [
        make_box_group(),
        make_cluster_group(ctx.time),
        make_shutter_group(ctx.time),
        make_fill_group(ctx.time),
    ]

    groups.append(
        make_beam_group(
            name="primary_beam",
            angle=sample_scalar(PRIMARY_ORBIT, ctx.time),
            radius=radius,
            scale=0.9 + 0.18 * (0.5 + 0.5 * math.sin(1.5 * ctx.time)),
            intensity=1.05 + 0.12 * math.sin(1.2 * ctx.time),
            angular_width=0.052,
            wavelength_min=380.0,
            wavelength_max=780.0,
        )
    )
    groups.append(
        make_beam_group(
            name="accent_beam",
            angle=sample_scalar(ACCENT_ORBIT, ctx.time),
            radius=radius * 0.92,
            scale=0.74 + 0.12 * (0.5 + 0.5 * math.sin(1.1 * ctx.time + 0.8)),
            intensity=0.62 + 0.08 * math.sin(1.7 * ctx.time + 1.1),
            angular_width=0.034,
            wavelength_min=420.0,
            wavelength_max=660.0,
        )
    )

    center_x, center_y = sample_vec2(CAMERA_CENTER, ctx.time)
    camera = Camera2D(center=[center_x, center_y], width=sample_scalar(CAMERA_WIDTH, ctx.time))

    return Frame(
        scene=Scene(groups=groups),
        camera=camera,
        look=Look(
            exposure=exposure,
            contrast=1.0,
            tonemap="reinhardx",
            white_point=0.5,
        ),
    )


if __name__ == "__main__":
    hq = "--hq" in sys.argv
    shot = Shot.preset(
        "production" if hq else "draft",
        width=1440 if hq else 720,
        height=1440 if hq else 720,
        rays=7_000_000 if hq else 350_000,
        batch=300_000 if hq else 100_000,
        depth=14 if hq else 10,
    )
    render(
        animate,
        Timeline(DURATION, fps=60 if hq else 24),
        f"{NAME}_{'hq' if hq else 'preview'}.mp4",
        settings=shot,
    )
