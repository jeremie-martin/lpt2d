"""Iris — a rotating ring of prism wedges forming an aperture.

A projector shines through a ring of glass wedges. Rays passing near the
centre escape unrefracted; rays grazing the ring hit wedges and fan out
into spectrum. As the ring rotates, the chamber continually shifts colour.

Branches:
- solo_white      : one full-spectrum projector
- solo_warm       : one orange projector
- duet_contrast   : warm + white from opposite sides

Iris compositions:
- iris_horizontal : projector on a side wall, ring spins in front of it
- iris_vertical   : medieval inversion — projector on top/bottom

Wired onto :class:`anim.family.Family` so the search loop, CLI, render
shot, and frame.shot.json export are shared with every other family.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field

from anim import (
    Camera2D,
    Frame,
    LightSpectrum,
    Material,
    ProjectorLight,
    Scene,
    Verdict,
    glass,
    intensity_for_spectrum,
    mirror_box,
    probe,
    prism,
)
from anim.family import Family

# ── Constants ─────────────────────────────────────────────────────────

CAMERA = Camera2D(center=[0, 0], width=3.2)
DURATION = 6.0
CHAMBER_HW, CHAMBER_HH = 1.6, 0.9

WALL_ID = "wall"
WEDGE_ID = "iris_glass"

# Aesthetic ranges (per the wall-albedo + light-intensity feedback band).
WALL_ALBEDO_RANGE = (0.9, 1.0)
GLASS_FILL_RANGE = (0.075, 0.15)
INTENSITY_RANGE = (0.8, 1.2)

IRIS_LAYOUTS = ("iris_horizontal", "iris_vertical")


# ── Params ────────────────────────────────────────────────────────────


@dataclass
class LightDef:
    side: str
    offset_tangent: float
    spread: float
    source: str
    source_radius: float
    intensity: float
    color: str  # "warm" | "white"


@dataclass
class Params:
    iris_composition: str
    ring_radius: float
    n_wedges: int
    wedge_size: float
    ring_rotation_rate_rad_per_sec: float
    wedge_ior: float
    wedge_cauchy_b: float
    wedge_fill: float
    wedge_roughness: float
    wall_albedo: float
    lights: list[LightDef] = field(default_factory=list)
    branch: str = "solo_white"
    look_exposure: float = -3.6
    look_gamma: float = 1.7
    look_contrast: float = 1.05
    look_shadows: float = 0.0
    look_vignette: float = 0.3
    look_vignette_radius: float = 1.65


# ── Sampling ──────────────────────────────────────────────────────────


def _wall_material(albedo: float) -> Material:
    roughness = max(0.10, 0.43 - 0.33 * albedo)
    return Material(
        metallic=1.0, roughness=roughness, transmission=0.0, cauchy_b=0.0, albedo=albedo
    )


def _exposure_for(albedo: float, n_lights: int) -> float:
    base = -1.10 * albedo - 2.55
    return base + (0.0 if n_lights == 1 else -0.45)


def _sides_for(layout: str) -> tuple[str, str]:
    return ("left", "right") if layout == "iris_horizontal" else ("top", "bottom")


def _tangent_range(layout: str) -> tuple[float, float]:
    return (-0.25, 0.25) if layout == "iris_horizontal" else (-0.45, 0.45)


def _sample_light(rng: random.Random, *, side: str, color: str, layout: str) -> LightDef:
    return LightDef(
        side=side,
        offset_tangent=rng.uniform(*_tangent_range(layout)),
        spread=rng.uniform(0.05, 0.10),
        source=rng.choice(["ball", "line"]),
        source_radius=rng.uniform(0.008, 0.020),
        intensity=rng.uniform(*INTENSITY_RANGE),
        color=color,
    )


# Each branch defines its own inline sampling — no hoisted shared constants.
def _branch_solo_white(rng: random.Random, layout: str) -> list[LightDef]:
    return [_sample_light(rng, side=rng.choice(_sides_for(layout)), color="white", layout=layout)]


def _branch_solo_warm(rng: random.Random, layout: str) -> list[LightDef]:
    return [_sample_light(rng, side=rng.choice(_sides_for(layout)), color="warm", layout=layout)]


def _branch_duet_contrast(rng: random.Random, layout: str) -> list[LightDef]:
    a, b = _sides_for(layout)
    return [
        _sample_light(rng, side=a, color="warm", layout=layout),
        _sample_light(rng, side=b, color="white", layout=layout),
    ]


_BRANCHES = {
    "solo_white": (_branch_solo_white, 1.2),
    "solo_warm": (_branch_solo_warm, 1.0),
    "duet_contrast": (_branch_duet_contrast, 1.4),
}


def sample(rng: random.Random) -> Params:
    names = list(_BRANCHES)
    branch = rng.choices(names, weights=[_BRANCHES[n][1] for n in names], k=1)[0]
    layout = rng.choice(IRIS_LAYOUTS)
    lights = _BRANCHES[branch][0](rng, layout)
    wall_albedo = rng.uniform(*WALL_ALBEDO_RANGE)
    return Params(
        iris_composition=layout,
        ring_radius=rng.uniform(0.35, 0.55),
        n_wedges=rng.randint(6, 10),
        wedge_size=rng.uniform(0.07, 0.12),
        ring_rotation_rate_rad_per_sec=rng.uniform(-0.6, 0.6),
        wedge_ior=rng.uniform(1.45, 1.55),
        wedge_cauchy_b=rng.uniform(18_000.0, 50_000.0),
        wedge_fill=rng.uniform(*GLASS_FILL_RANGE),
        wedge_roughness=rng.uniform(0.0, 0.015),
        wall_albedo=wall_albedo,
        lights=lights,
        branch=branch,
        look_exposure=_exposure_for(wall_albedo, len(lights)) + rng.uniform(-0.15, 0.15),
        look_gamma=rng.uniform(1.4, 2.0),
        look_contrast=rng.uniform(1.0, 1.1),
        look_shadows=rng.uniform(-0.2, 0.2),
        look_vignette=rng.uniform(0.1, 0.5),
        look_vignette_radius=rng.uniform(1.5, 1.8),
    )


# ── Scene ─────────────────────────────────────────────────────────────


def _spectrum_for(color: str) -> LightSpectrum:
    if color == "warm":
        return LightSpectrum.range(wavelength_min=580, wavelength_max=650)
    return LightSpectrum.range(wavelength_min=380, wavelength_max=780)


def _light_position_and_dir(L: LightDef):
    """Wall position + direction aimed at the (always-centered) ring."""
    if L.side == "left":
        pos = (-CHAMBER_HW + 0.08, L.offset_tangent)
    elif L.side == "right":
        pos = (CHAMBER_HW - 0.08, L.offset_tangent)
    elif L.side == "top":
        pos = (L.offset_tangent, CHAMBER_HH - 0.08)
    else:
        pos = (L.offset_tangent, -CHAMBER_HH + 0.08)
    a = math.atan2(-pos[1], -pos[0])
    return pos, (math.cos(a), math.sin(a))


def _projectors(p: Params) -> list[ProjectorLight]:
    out: list[ProjectorLight] = []
    for i, L in enumerate(p.lights):
        pos, dir_ = _light_position_and_dir(L)
        spectrum = _spectrum_for(L.color)
        out.append(
            ProjectorLight(
                id=f"beam_{i}",
                position=list(pos),
                direction=list(dir_),
                source_radius=L.source_radius,
                spread=L.spread,
                source=L.source,
                intensity=intensity_for_spectrum(L.intensity, spectrum),
                spectrum=spectrum,
            )
        )
    return out


def _wedge_shapes(p: Params, t_seconds: float):
    ring_angle = p.ring_rotation_rate_rad_per_sec * t_seconds
    return [
        prism(
            center=(
                p.ring_radius * math.cos(ring_angle + 2 * math.pi * i / p.n_wedges),
                p.ring_radius * math.sin(ring_angle + 2 * math.pi * i / p.n_wedges),
            ),
            size=p.wedge_size,
            material_id=WEDGE_ID,
            rotation=ring_angle + 2 * math.pi * i / p.n_wedges,
            id_prefix=f"wedge_{i}",
        )
        for i in range(p.n_wedges)
    ]


def build(p: Params):
    """Family.build: return the per-frame animate callback."""
    materials = {
        WALL_ID: _wall_material(p.wall_albedo),
        WEDGE_ID: glass(
            ior=p.wedge_ior,
            cauchy_b=p.wedge_cauchy_b,
            color=(0.97, 0.97, 0.98),
            fill=p.wedge_fill,
            roughness=p.wedge_roughness,
        ),
    }
    warm_frac = sum(1 for L in p.lights if L.color == "warm") / max(1, len(p.lights))
    # Per-frame look as a *dict* so vignette and other render-only fields
    # set on the base shot can flow through to the final render but stay
    # absent from the probe shot.
    look = dict(
        exposure=p.look_exposure,
        gamma=p.look_gamma,
        contrast=p.look_contrast,
        shadows=p.look_shadows,
        tonemap="reinhardx",
        white_point=0.5,
        normalize="rays",
        temperature=0.25 * warm_frac,
    )

    def animate(ctx):
        # Stills use a fixed midpoint pose so single-frame previews are
        # stable across requested durations.
        t_seconds = ctx.time if ctx.total_frames > 1 else DURATION / 2
        scene = Scene(
            materials=materials,
            shapes=[
                *mirror_box(CHAMBER_HW, CHAMBER_HH, WALL_ID, id_prefix="chamber"),
                *_wedge_shapes(p, t_seconds),
            ],
            lights=_projectors(p),
        )
        return Frame(scene=scene, look=look)

    return animate


# ── Quality gates ─────────────────────────────────────────────────────

GATE_MEAN_LUMA = (0.425, 0.575)
GATE_RMS_CONTRAST_MIN = 0.25
GATE_CLIPPED_MAX = 0.40
GATE_P05_LUMA_MAX = 0.20
GATE_MIN_PASSING_FRAC = 0.30


def check(animate) -> Verdict:
    """Reject probes that miss the mean-luma + RMS-contrast band.

    Probes the module's nominal DURATION at fps=4. Rotation rate is in
    rad/s, so a longer render covers more total rotation at the same
    on-screen speed — probe stats sampled over DURATION remain
    representative of any clip length.
    """
    frames = probe(animate, DURATION, fps=4, camera=CAMERA)
    n = len(frames)
    passing = sum(
        1
        for f in frames
        if GATE_MEAN_LUMA[0] <= f.mean_luma <= GATE_MEAN_LUMA[1]
        and f.rms_contrast >= GATE_RMS_CONTRAST_MIN
        and f.clipped_channel_fraction <= GATE_CLIPPED_MAX
        and f.analysis.image.p05_luma <= GATE_P05_LUMA_MAX
    )
    mean_luma = sum(f.mean_luma for f in frames) / n
    rms = sum(f.rms_contrast for f in frames) / n
    clipped = sum(f.clipped_channel_fraction for f in frames) / n
    p05 = sum(f.analysis.image.p05_luma for f in frames) / n
    ok = passing >= int(GATE_MIN_PASSING_FRAC * n)
    return Verdict(
        ok=ok,
        summary=(
            f"passes={passing}/{n} mean={mean_luma:.3f} rms={rms:.3f} "
            f"p05={p05:.3f} clipped={clipped:.3f}"
        ),
    )


# ── Family wiring ─────────────────────────────────────────────────────


def describe(p: Params) -> str:
    return (
        f"branch={p.branch} iris={p.iris_composition} n={p.n_wedges} "
        f"r={p.ring_radius:.2f} alb={p.wall_albedo:.2f} exp={p.look_exposure:.2f}"
    )


def tag(p: Params) -> str:
    return f"{p.branch}_{p.iris_composition.replace('iris_', '')}"


def final_look(p: Params) -> dict:
    """Vignette is on the *render* shot only (probes stay clean)."""
    return dict(vignette=p.look_vignette, vignette_radius=p.look_vignette_radius)


FAMILY = Family(
    "iris",
    DURATION,
    Params,
    sample,
    build,
    check=check,
    describe=describe,
    tag=tag,
    final_look=final_look,
    camera=CAMERA,
)


if __name__ == "__main__":
    FAMILY.main()
