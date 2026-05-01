"""Tiny Family example. Try: `python -m examples.python.families.family_starter search -n 1 --preset tiny`."""

from __future__ import annotations

import math
import random
from dataclasses import dataclass

import anim as a
from anim.family import Family, Verdict, probe

CAMERA = a.Camera2D(center=[0, 0], width=3.0)
DURATION = 6.0


@dataclass
class Params:
    beam_y: float
    beam_dx: float
    glass_x: float
    exposure: float


def sample(rng: random.Random) -> Params:
    return Params(rng.uniform(-0.25, 0.25), rng.uniform(-0.18, 0.18), rng.uniform(-0.45, 0.45), rng.uniform(-4.8, -4.2))


def build(p: Params):
    def animate(ctx):
        bob = 0.12 * math.sin(math.tau * ctx.progress)
        return a.Frame(
            scene=a.Scene(
                materials={"wall": a.mirror(0.95, roughness=0.02), "glass": a.glass(1.55, cauchy_b=22_000, fill=0.08)},
                shapes=[*a.mirror_box(1.35, 0.8, "wall"), a.Circle(id="lens", center=[p.glass_x, bob], radius=0.22, material_id="glass")],
                lights=[a.ProjectorLight(id="beam", position=[-1.1, p.beam_y], direction=[1.0, p.beam_dx], spread=0.03, intensity=1.0, spectrum=a.LightSpectrum.range(580, 650))],
            ),
            look={"exposure": p.exposure},
        )
    return animate


def check(animate) -> Verdict:
    best = max(probe(animate, DURATION, fps=3, width=480, height=270, rays=80_000, camera=CAMERA), key=lambda f: f.colorfulness)
    ok = 0.18 <= best.mean_luma <= 0.75 and best.colorfulness >= 0.08
    return Verdict(ok, f"best color={best.colorfulness:.3f} mean={best.mean_luma:.3f}")


def describe(p: Params) -> str:
    return f"glass_x={p.glass_x:+.2f} beam_y={p.beam_y:+.2f} dx={p.beam_dx:+.2f} exp={p.exposure:.2f}"


FAMILY = Family("family_starter", DURATION, Params, sample, build, check=check, describe=describe, camera=CAMERA)


if __name__ == "__main__":
    FAMILY.main()
