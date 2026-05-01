"""Canonical example: clean iris-style prism ring."""

from __future__ import annotations

import math

import anim as a
from anim.examples_support import run_example

NAME = "iris_ring_starter"
SUMMARY = "Small iris-style prism ring using tracks, groups, builders, and a spectral projector."
WORKFLOW = "compact-iris-starter"
DURATION = 8.0
CAMERA = a.Camera2D(center=[0, 0], width=1.8)
WARM = a.LightSpectrum.range(580, 650)
COUNT = 8
SPIN = a.Track([a.Key(0.0, 0.0), a.Key(DURATION, math.tau, ease="ease_in_out_sine")], wrap=a.Wrap.LOOP)
RADIUS = a.Track([a.Key(0.0, 0.42), a.Key(4.0, 0.56, ease="ease_in_out_sine"), a.Key(DURATION, 0.46)], wrap=a.Wrap.PINGPONG)
SWEEP = a.Track([a.Key(0.0, -0.22), a.Key(4.0, 0.18, ease="ease_in_out_sine"), a.Key(DURATION, -0.12)], wrap=a.Wrap.PINGPONG)


def _unit(x: float, y: float) -> list[float]:
    d = math.hypot(x, y) or 1.0
    return [x / d, y / d]


def _wedge(i: int, radius: float, spin: float) -> a.Group:
    angle = spin + i * math.tau / COUNT
    return a.Group(
        id=f"wedge_{i}",
        transform=a.Transform2D.uniform(translate=(radius * math.cos(angle), radius * math.sin(angle)), rotate=angle + math.pi / 2, scale=0.92 + 0.12 * math.sin(angle * 2.0)),
        shapes=[a.prism((0.0, 0.0), 0.16, "glass", id_prefix=f"wedge_{i}")],
    )


def make_settings(mode: str = "preview") -> a.Shot:
    shot = a.Shot.preset("production", width=1080, height=1920, rays=2_400_000, depth=12) if mode == "hq" else a.Shot.preset("preview", width=540, height=960, rays=750_000, depth=10)
    shot.name, shot.camera = NAME, CAMERA
    shot.look = shot.look.with_overrides(exposure=-3.1, gamma=1.8, contrast=1.05, tonemap="reinhardx", white_point=0.5, normalize="rays")
    return shot


def frame(ctx: a.FrameContext) -> a.Frame:
    radius, spin = RADIUS(ctx.time), SPIN(ctx.time)
    scene = a.Scene(
        materials={"wall": a.mirror(0.96, roughness=0.015), "glass": a.glass(1.56, cauchy_b=26_000, roughness=0.01, fill=0.1, color=(0.97, 0.98, 1.0))},
        shapes=[*a.mirror_box(0.9, 1.6, "wall", id_prefix="wall")],
        groups=[_wedge(i, radius, spin) for i in range(COUNT)],
        lights=[a.ProjectorLight(id="warm", position=[0.0, 1.28], direction=_unit(SWEEP(ctx.time), -1.0), source_radius=0.18, spread=0.03, intensity=a.intensity_for_spectrum(0.65, WARM), spectrum=WARM)],
    )
    return a.Frame(scene=scene, look={"exposure": -3.1 + 0.15 * math.sin(math.tau * ctx.progress)})


def main(argv: list[str] | None = None) -> None:
    run_example(name=NAME, duration=DURATION, make_settings=make_settings, animate=frame, argv=argv, description=__doc__)


if __name__ == "__main__":
    main()
