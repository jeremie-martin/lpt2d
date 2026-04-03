"""Group-driven prism flower built around the new animation authoring API."""

import math
import sys

from anim import (
    BeamLight,
    Camera2D,
    Circle,
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
    glass,
    render,
    smoothstep,
)

NAME = "chromatic_kaleidoscope"
DURATION = 10.0
PRISM_COUNT = 4
EMITTER_RADIUS = 1.18

PRISM_MATERIALS = (
    glass(1.46, cauchy_b=14_000, absorption=0.12),
    glass(1.56, cauchy_b=24_000, absorption=0.16),
    glass(1.66, cauchy_b=34_000, absorption=0.2),
)
CORE_MATERIAL = glass(1.72, cauchy_b=28_000, absorption=0.18)
SATELLITE_MATERIAL = glass(1.38, cauchy_b=9_000, absorption=0.06)

CROWN_RADIUS = Track(
    [
        Key(0.0, 0.62),
        Key(3.8, 0.8, ease="ease_in_out_sine"),
        Key(DURATION, 0.68, ease="ease_in_out_sine"),
    ],
    wrap=Wrap.PINGPONG,
)
CAMERA_CENTER = Track(
    [
        Key(0.0, (-0.06, 0.02)),
        Key(3.6, (0.08, -0.04), ease="ease_in_out_sine"),
        Key(7.2, (0.04, 0.08), ease="ease_in_out_sine"),
        Key(DURATION, (-0.04, 0.0), ease="ease_in_out_sine"),
    ],
    wrap=Wrap.PINGPONG,
)
CAMERA_WIDTH = Track(
    [
        Key(0.0, 3.7),
        Key(3.8, 3.05, ease="ease_in_out_cubic"),
        Key(DURATION, 3.45, ease="ease_in_out_sine"),
    ],
    wrap=Wrap.PINGPONG,
)
CORE_SCALE = Track(
    [
        Key(0.0, 0.96),
        Key(2.2, 1.08, ease="ease_in_out_sine"),
        Key(6.0, 1.0, ease="ease_in_out_sine"),
        Key(DURATION, 1.05, ease="ease_in_out_sine"),
    ],
    wrap=Wrap.PINGPONG,
)
PRIMARY_BEAM_ORBIT = Track(
    [
        Key(0.0, 0.88 * math.pi),
        Key(3.3, 1.18 * math.pi, ease="ease_in_out_sine"),
        Key(6.8, 1.72 * math.pi, ease="ease_in_out_sine"),
        Key(DURATION, 2.36 * math.pi, ease="ease_in_out_cubic"),
    ],
    wrap=Wrap.LOOP,
)
ACCENT_BEAM_ORBIT = Track(
    [
        Key(0.0, -0.18 * math.pi),
        Key(3.5, -0.36 * math.pi, ease="ease_in_out_sine"),
        Key(7.0, -0.72 * math.pi, ease="ease_in_out_sine"),
        Key(DURATION, -1.12 * math.pi, ease="ease_in_out_cubic"),
    ],
    wrap=Wrap.LOOP,
)
EXPOSURE = Track(
    [
        Key(0.0, -9.95),
        Key(4.0, -9.35, ease="ease_in_out_sine"),
        Key(DURATION, -9.75, ease="ease_in_out_sine"),
    ],
    wrap=Wrap.PINGPONG,
)


def polar(radius: float, angle: float) -> list[float]:
    return [radius * math.cos(angle), radius * math.sin(angle)]


def reveal(progress: float) -> float:
    fade_in = smoothstep(min(progress / 0.12, 1.0))
    fade_out = smoothstep(min((1.0 - progress) / 0.08, 1.0))
    return fade_in * fade_out


def make_core_group(t: float) -> Group:
    scale = float(CORE_SCALE(t))
    rotation = 0.22 * math.tau * t / DURATION
    return Group(
        name="core",
        transform=Transform2D(rotate=rotation, scale=[scale, scale]),
        shapes=[
            Circle(center=[0.0, 0.0], radius=0.13, material=CORE_MATERIAL),
            Circle(center=[0.18, 0.0], radius=0.06, material=SATELLITE_MATERIAL),
            Circle(center=[-0.09, 0.155], radius=0.06, material=SATELLITE_MATERIAL),
            Circle(center=[-0.09, -0.155], radius=0.06, material=SATELLITE_MATERIAL),
        ],
    )


def make_prism_group(index: int, t: float, crown_spin: float) -> Group:
    phase = index / PRISM_COUNT
    orbit_angle = crown_spin + phase * math.tau
    radius = float(CROWN_RADIUS(t))
    twist = orbit_angle + math.pi + 0.2 * math.sin(1.45 * t + phase * math.tau)
    scale = 0.96 + 0.08 * math.sin(1.3 * t + phase * math.tau)
    material = PRISM_MATERIALS[index % len(PRISM_MATERIALS)]

    return Group(
        name=f"prism_{index}",
        transform=Transform2D(
            translate=polar(radius, orbit_angle),
            rotate=twist,
            scale=[scale, scale],
        ),
        shapes=[
            Segment(a=[-0.22, -0.12], b=[0.22, -0.12], material=material),
            Segment(a=[0.22, -0.12], b=[0.0, 0.22], material=material),
            Segment(a=[0.0, 0.22], b=[-0.22, -0.12], material=material),
        ],
    )


def make_beam_group(
    name: str,
    angle: float,
    scale: float,
    intensity: float,
    angular_width: float,
    wavelength_min: float,
    wavelength_max: float,
) -> Group:
    return Group(
        name=name,
        transform=Transform2D(
            translate=polar(EMITTER_RADIUS, angle),
            rotate=angle + math.pi,
            scale=[scale, scale],
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
    crown_spin = 0.16 * math.tau * math.sin(ctx.progress * math.pi)

    groups = [make_core_group(ctx.time)]
    groups.extend(make_prism_group(index, ctx.time, crown_spin) for index in range(PRISM_COUNT))

    primary_scale = 0.96 + 0.1 * (0.5 + 0.5 * math.sin(ctx.time * 1.5))
    accent_scale = 0.9 + 0.08 * (0.5 + 0.5 * math.sin(ctx.time * 1.1 + 1.1))

    groups.append(
        make_beam_group(
            name="primary_beam",
            angle=float(PRIMARY_BEAM_ORBIT(ctx.time)),
            scale=primary_scale,
            intensity=0.085 * fade,
            angular_width=0.04,
            wavelength_min=380.0,
            wavelength_max=780.0,
        )
    )
    groups.append(
        make_beam_group(
            name="accent_beam",
            angle=float(ACCENT_BEAM_ORBIT(ctx.time)),
            scale=accent_scale,
            intensity=0.038 * fade,
            angular_width=0.026,
            wavelength_min=420.0,
            wavelength_max=660.0,
        )
    )

    center_x, center_y = CAMERA_CENTER(ctx.time)
    camera = Camera2D(center=[center_x, center_y], width=float(CAMERA_WIDTH(ctx.time)))

    return Frame(
        scene=Scene(name=NAME, groups=groups),
        camera=camera,
        render=RenderOverrides(
            exposure=float(EXPOSURE(ctx.time)),
            contrast=1.02,
            tonemap="aces",
            white_point=1.0,
        ),
    )


if __name__ == "__main__":
    hq = "--hq" in sys.argv
    settings = RenderSettings.preset(
        "production" if hq else "draft",
        width=1600 if hq else 720,
        height=1600 if hq else 720,
        rays=12_000_000 if hq else 700_000,
        batch=300_000 if hq else 100_000,
        depth=14 if hq else 10,
    )
    render(
        animate,
        Timeline(DURATION, fps=60 if hq else 30),
        f"{NAME}_{'hq' if hq else 'preview'}.mp4",
        settings=settings,
    )
