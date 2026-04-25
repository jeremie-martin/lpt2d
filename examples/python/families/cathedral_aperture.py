"""Cathedral Aperture — shafts of light through a wall-slit.

A thick metallic wall divides the chamber at a golden-ratio position. One
to three projectors sit behind the wall and throw narrow shafts through
the slit, striking a glass prism in the big chamber and breaking into
spectra on the far wall.

Branches (explicit per-branch parameters, never mixed within a scene):

- solo_warm          : one narrow orange projector
- solo_white         : one full-spectrum projector
- duet_warm          : two matched orange projectors, slight angular divergence
- duet_white         : two matched full-spectrum projectors
- duet_contrast      : one orange + one full-spectrum, classic warm/cool pair
- trio_warm_accent   : two full-spectrum + one orange accent (careful)

Wall layouts:

- golden_small_left  : small chamber on the left (wall at x = -0.378)
- golden_small_right : small chamber on the right (wall at x = +0.378),
                       medieval inversion; beam direction flips accordingly

Wired onto :class:`anim.family.Family`.
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
    thick_segment,
)
from anim.family import Family

# ── Constants ─────────────────────────────────────────────────────────

CAMERA = Camera2D(center=[0, 0], width=3.2)
DURATION = 6.0
CHAMBER_HW, CHAMBER_HH = 1.6, 0.9

PHI = (1.0 + 5.0**0.5) / 2.0
_SHORT_FRAC = 1.0 / (PHI * PHI)
_GOLDEN_LEFT = -CHAMBER_HW + 2.0 * CHAMBER_HW * _SHORT_FRAC
_GOLDEN_RIGHT = -CHAMBER_HW + 2.0 * CHAMBER_HW * (1.0 - _SHORT_FRAC)

WALL_LAYOUTS: dict[str, dict] = {
    "golden_small_left": {"wall_x": _GOLDEN_LEFT, "beam_dir_sign": +1.0},
    "golden_small_right": {"wall_x": _GOLDEN_RIGHT, "beam_dir_sign": -1.0},
}

WALL_ID = "wall"
PRISM_IDS = ("prism_a", "prism_b")

WALL_ALBEDO_RANGE = (0.9, 1.0)
GLASS_FILL_RANGE = (0.075, 0.15)
INTENSITY_RANGE = (0.8, 1.2)


# ── Params ────────────────────────────────────────────────────────────


@dataclass
class LightDef:
    offset_perp: float
    offset_along: float
    angle_jitter: float
    spread: float
    source: str
    source_radius: float
    intensity: float
    color: str  # "warm" | "white"


@dataclass
class Params:
    wall_composition: str
    slit_cy: float
    slit_gap: float
    wall_thickness: float
    prism_offset_along: float
    prism_y: float
    prism_size: float
    prism_rotation_speed: float
    prism_glass_idx: int
    glass_fill: float
    wall_albedo: float
    lights: list[LightDef] = field(default_factory=list)
    branch: str = "solo_warm"
    look_exposure: float = -4.0
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


def _make_prism_glasses(fill: float):
    return [
        glass(1.52, cauchy_b=28_000, color=(0.97, 0.97, 0.97), fill=fill),
        glass(1.60, cauchy_b=35_000, color=(0.95, 0.96, 1.0), fill=fill),
    ]


def _exposure_for(albedo: float, n_lights: int) -> float:
    base = -1.10 * albedo - 2.55
    return base + (0.0 if n_lights == 1 else -0.45 if n_lights == 2 else -0.85)


def _sample_light(
    rng: random.Random,
    *,
    color: str,
    offset_perp: float,
    angle_jitter: float,
) -> LightDef:
    return LightDef(
        offset_perp=offset_perp,
        offset_along=rng.uniform(0.20, 0.35),
        angle_jitter=angle_jitter,
        spread=rng.uniform(0.03, 0.06),
        source=rng.choice(["ball", "line"]),
        source_radius=rng.uniform(0.005, 0.015),
        intensity=rng.uniform(*INTENSITY_RANGE),
        color=color,
    )


# Each branch defines its own inline ranges. No hoisted shared constants.
def _branch_solo_warm(rng: random.Random) -> list[LightDef]:
    return [_sample_light(rng, color="warm", offset_perp=rng.uniform(-0.025, 0.025), angle_jitter=0.0)]


def _branch_solo_white(rng: random.Random) -> list[LightDef]:
    return [_sample_light(rng, color="white", offset_perp=rng.uniform(-0.025, 0.025), angle_jitter=0.0)]


def _branch_duet_warm(rng: random.Random) -> list[LightDef]:
    off = rng.uniform(0.015, 0.030)
    jit = rng.uniform(0.015, 0.035)
    return [
        _sample_light(rng, color="warm", offset_perp=+off, angle_jitter=-jit),
        _sample_light(rng, color="warm", offset_perp=-off, angle_jitter=+jit),
    ]


def _branch_duet_white(rng: random.Random) -> list[LightDef]:
    off = rng.uniform(0.015, 0.030)
    jit = rng.uniform(0.015, 0.035)
    return [
        _sample_light(rng, color="white", offset_perp=+off, angle_jitter=-jit),
        _sample_light(rng, color="white", offset_perp=-off, angle_jitter=+jit),
    ]


def _branch_duet_contrast(rng: random.Random) -> list[LightDef]:
    off = rng.uniform(0.015, 0.030)
    jit = rng.uniform(0.015, 0.035)
    warm_on_top = rng.random() < 0.5
    return [
        _sample_light(
            rng,
            color="warm",
            offset_perp=(+off if warm_on_top else -off),
            angle_jitter=(-jit if warm_on_top else +jit),
        ),
        _sample_light(
            rng,
            color="white",
            offset_perp=(-off if warm_on_top else +off),
            angle_jitter=(+jit if warm_on_top else -jit),
        ),
    ]


def _branch_trio_warm_accent(rng: random.Random) -> list[LightDef]:
    spacing = rng.uniform(0.018, 0.030)
    jit = rng.uniform(0.010, 0.025)
    return [
        _sample_light(rng, color="white", offset_perp=+spacing, angle_jitter=-jit),
        _sample_light(rng, color="warm", offset_perp=0.0, angle_jitter=0.0),
        _sample_light(rng, color="white", offset_perp=-spacing, angle_jitter=+jit),
    ]


# Trios are rare per the user's earlier note: "careful with three".
_BRANCHES = {
    "solo_warm": (_branch_solo_warm, 1.0),
    "solo_white": (_branch_solo_white, 1.0),
    "duet_warm": (_branch_duet_warm, 1.5),
    "duet_white": (_branch_duet_white, 1.5),
    "duet_contrast": (_branch_duet_contrast, 2.0),
    "trio_warm_accent": (_branch_trio_warm_accent, 0.7),
}


def sample(rng: random.Random) -> Params:
    names = list(_BRANCHES)
    branch = rng.choices(names, weights=[_BRANCHES[n][1] for n in names], k=1)[0]
    wall_composition = rng.choice(list(WALL_LAYOUTS.keys()))
    slit_cy = rng.uniform(-0.15, 0.15)
    lights = _BRANCHES[branch][0](rng)
    wall_albedo = rng.uniform(*WALL_ALBEDO_RANGE)
    return Params(
        wall_composition=wall_composition,
        slit_cy=slit_cy,
        slit_gap=rng.uniform(0.07, 0.13),
        wall_thickness=rng.uniform(0.03, 0.06),
        prism_offset_along=rng.uniform(0.55, 1.15),
        prism_y=slit_cy + rng.uniform(-0.08, 0.08),
        prism_size=rng.uniform(0.16, 0.28),
        prism_rotation_speed=rng.uniform(-math.pi, math.pi) * 0.6,
        prism_glass_idx=rng.randint(0, 1),
        glass_fill=rng.uniform(*GLASS_FILL_RANGE),
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


def _layout(p: Params) -> tuple[float, float]:
    info = WALL_LAYOUTS[p.wall_composition]
    return info["wall_x"], info["beam_dir_sign"]


def _prism_world(p: Params) -> tuple[float, float]:
    wall_x, sign = _layout(p)
    return (wall_x + sign * p.prism_offset_along, p.prism_y)


def _light_world_pos(p: Params, L: LightDef) -> tuple[float, float]:
    wall_x, sign = _layout(p)
    return (wall_x - sign * L.offset_along, p.slit_cy + L.offset_perp)


def _light_world_dir(p: Params, L: LightDef) -> tuple[float, float]:
    px, py = _prism_world(p)
    lx, ly = _light_world_pos(p, L)
    a = math.atan2(py - ly, px - lx) + L.angle_jitter
    return (math.cos(a), math.sin(a))


def _slit_wall_shapes(p: Params) -> list:
    wall_x, _ = _layout(p)
    half_g = p.slit_gap / 2
    top = thick_segment((wall_x, p.slit_cy + half_g), (wall_x, CHAMBER_HH), p.wall_thickness, WALL_ID)
    bot = thick_segment((wall_x, -CHAMBER_HH), (wall_x, p.slit_cy - half_g), p.wall_thickness, WALL_ID)
    top.id = "slit_top"
    bot.id = "slit_bot"
    return [top, bot]


def _spectrum_for(color: str) -> LightSpectrum:
    if color == "warm":
        return LightSpectrum.range(wavelength_min=580, wavelength_max=650)
    return LightSpectrum.range(wavelength_min=380, wavelength_max=780)


def _projectors(p: Params) -> list[ProjectorLight]:
    out: list[ProjectorLight] = []
    for i, L in enumerate(p.lights):
        spectrum = _spectrum_for(L.color)
        out.append(
            ProjectorLight(
                id=f"beam_{i}",
                position=list(_light_world_pos(p, L)),
                direction=list(_light_world_dir(p, L)),
                source_radius=L.source_radius,
                spread=L.spread,
                source=L.source,
                intensity=intensity_for_spectrum(L.intensity, spectrum),
                spectrum=spectrum,
            )
        )
    return out


def build(p: Params):
    glasses = _make_prism_glasses(p.glass_fill)
    materials = {
        WALL_ID: _wall_material(p.wall_albedo),
        PRISM_IDS[0]: glasses[0],
        PRISM_IDS[1]: glasses[1],
    }
    warm_frac = sum(1 for L in p.lights if L.color == "warm") / max(1, len(p.lights))
    look = dict(
        exposure=p.look_exposure,
        gamma=p.look_gamma,
        contrast=p.look_contrast,
        shadows=p.look_shadows,
        tonemap="reinhardx",
        white_point=0.5,
        normalize="rays",
        temperature=0.30 * warm_frac,
    )

    def animate(ctx):
        rot = p.prism_rotation_speed * ctx.time / DURATION
        prism_shape = prism(
            center=_prism_world(p),
            size=p.prism_size,
            material_id=PRISM_IDS[p.prism_glass_idx % len(PRISM_IDS)],
            rotation=rot,
            id_prefix="prism",
        )
        scene = Scene(
            materials=materials,
            shapes=[
                *mirror_box(CHAMBER_HW, CHAMBER_HH, WALL_ID, id_prefix="chamber"),
                *_slit_wall_shapes(p),
                prism_shape,
            ],
            lights=_projectors(p),
        )
        return Frame(scene=scene, look=look)

    return animate


# ── Quality gates ─────────────────────────────────────────────────────

GATE_MEAN_LUMA = (0.425, 0.575)
GATE_RMS_CONTRAST_MIN = 0.25
GATE_CLIPPED_MAX = 0.40
GATE_MIN_PASSING_FRAC = 0.30


def check(animate) -> Verdict:
    """Reject probes that miss the mean-luma + RMS-contrast band."""
    frames = probe(animate, DURATION, fps=4, camera=CAMERA)
    n = len(frames)
    passing = sum(
        1
        for f in frames
        if GATE_MEAN_LUMA[0] <= f.mean_luma <= GATE_MEAN_LUMA[1]
        and f.rms_contrast >= GATE_RMS_CONTRAST_MIN
        and f.clipped_channel_fraction <= GATE_CLIPPED_MAX
    )
    avg_mean = sum(f.mean_luma for f in frames) / n
    avg_rms = sum(f.rms_contrast for f in frames) / n
    avg_clip = sum(f.clipped_channel_fraction for f in frames) / n
    return Verdict(
        ok=passing >= int(GATE_MIN_PASSING_FRAC * n),
        summary=(
            f"passes={passing}/{n} mean={avg_mean:.3f} rms={avg_rms:.3f} clipped={avg_clip:.3f}"
        ),
    )


# ── Family wiring ─────────────────────────────────────────────────────


def describe(p: Params) -> str:
    return (
        f"branch={p.branch} wall={p.wall_composition} alb={p.wall_albedo:.2f} "
        f"n_lights={len(p.lights)} prism_d={p.prism_offset_along:.2f} "
        f"exp={p.look_exposure:.2f}"
    )


def tag(p: Params) -> str:
    return f"{p.branch}_{p.wall_composition.replace('golden_small_', '')}"


def final_look(p: Params) -> dict:
    return dict(vignette=p.look_vignette, vignette_radius=p.look_vignette_radius)


FAMILY = Family(
    "cathedral_aperture",
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
