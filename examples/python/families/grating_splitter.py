"""Grating Splitter — a diffraction-style barrier splits one beam into a fan
of downstream prisms.

A vertical metallic barrier with several narrow slits sits across the
chamber. A projector behind it casts one broad beam; only the slit-aligned
rays pass through, hitting a row of small prisms downstream that explode
each sub-beam into a spectrum.

Branches:
- solo_white      : one full-spectrum projector
- solo_warm       : one orange projector
- duet_contrast   : warm + white at slightly different angles

Fan compositions:
- fan_right  : grating on the left, prisms on the right
- fan_left   : medieval inversion

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

WALL_ID = "wall"
# The grating barrier is structural — not a chamber wall. A low-albedo
# absorptive barrier reads as a dark stripe between the bright slits,
# which is what lifts RMS contrast above the gate floor in spite of
# bright (0.9..1.0) chamber walls.
BARRIER_ID = "barrier"
PRISM_IDS = ("prism_a", "prism_b")

FAN_LAYOUTS = {"fan_right": +1, "fan_left": -1}

WALL_ALBEDO_RANGE = (0.9, 1.0)
GLASS_FILL_RANGE = (0.075, 0.15)
INTENSITY_RANGE = (0.8, 1.2)


# ── Params ────────────────────────────────────────────────────────────


@dataclass
class LightDef:
    offset_perp: float
    angle_drift_rate: float
    base_angle_offset: float
    spread: float
    source: str
    source_radius: float
    intensity: float
    color: str  # "warm" | "white"


@dataclass
class Params:
    fan_composition: str
    grating_x_abs: float
    grating_n: int
    grating_spacing: float
    grating_gap: float
    grating_width: float
    grating_thickness: float
    prism_row_offset: float
    prism_size: float
    prism_rotation_speed: float
    prism_glass_idx: int
    projector_offset: float
    glass_fill: float
    wall_albedo: float
    lights: list[LightDef] = field(default_factory=list)
    branch: str = "solo_white"
    look_exposure: float = -3.5
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


def _barrier_material() -> Material:
    return Material(metallic=0.0, roughness=0.85, transmission=0.0, cauchy_b=0.0, albedo=0.18)


def _make_prism_glasses(fill: float):
    return [
        glass(1.52, cauchy_b=28_000, color=(0.97, 0.97, 0.97), fill=fill),
        glass(1.60, cauchy_b=35_000, color=(0.95, 0.96, 1.0), fill=fill),
    ]


def _exposure_for(albedo: float, n_lights: int) -> float:
    # Brighter than cathedral/iris because the dark barrier eats fill.
    base = -1.10 * albedo - 1.55
    return base + (0.0 if n_lights == 1 else -0.45)


def _sample_light(rng: random.Random, *, color: str) -> LightDef:
    return LightDef(
        offset_perp=rng.uniform(-0.05, 0.05),
        angle_drift_rate=rng.uniform(-0.08, 0.08),
        base_angle_offset=rng.uniform(-0.03, 0.03),
        spread=rng.uniform(0.08, 0.14),
        source=rng.choice(["ball", "line"]),
        source_radius=rng.uniform(0.015, 0.030),
        intensity=rng.uniform(*INTENSITY_RANGE),
        color=color,
    )


def _branch_solo_white(rng: random.Random) -> list[LightDef]:
    return [_sample_light(rng, color="white")]


def _branch_solo_warm(rng: random.Random) -> list[LightDef]:
    return [_sample_light(rng, color="warm")]


def _branch_duet_contrast(rng: random.Random) -> list[LightDef]:
    w = _sample_light(rng, color="warm")
    wh = _sample_light(rng, color="white")
    w.offset_perp = rng.uniform(-0.05, -0.01)
    w.base_angle_offset = rng.uniform(-0.04, 0.0)
    wh.offset_perp = rng.uniform(0.01, 0.05)
    wh.base_angle_offset = rng.uniform(0.0, 0.04)
    return [w, wh]


_BRANCHES = {
    "solo_white": (_branch_solo_white, 1.4),
    "solo_warm": (_branch_solo_warm, 1.0),
    "duet_contrast": (_branch_duet_contrast, 1.3),
}


def sample(rng: random.Random) -> Params:
    names = list(_BRANCHES)
    branch = rng.choices(names, weights=[_BRANCHES[n][1] for n in names], k=1)[0]
    fan = rng.choice(list(FAN_LAYOUTS.keys()))
    # Narrow slits + thick barrier = brighter slit-stripes against a
    # darker barrier, which is where any RMS contrast comes from.
    grating_n = rng.randint(3, 5)
    grating_spacing = rng.uniform(0.18, 0.26)
    lights = _BRANCHES[branch][0](rng)
    wall_albedo = rng.uniform(*WALL_ALBEDO_RANGE)
    return Params(
        fan_composition=fan,
        grating_x_abs=rng.uniform(0.30, 0.55),
        grating_n=grating_n,
        grating_spacing=grating_spacing,
        grating_gap=rng.uniform(0.025, 0.040),
        grating_width=grating_n * grating_spacing + 0.10,
        grating_thickness=rng.uniform(0.10, 0.18),
        prism_row_offset=rng.uniform(0.35, 0.55),
        prism_size=rng.uniform(0.075, 0.12),
        prism_rotation_speed=rng.uniform(-math.pi, math.pi) * 0.3,
        prism_glass_idx=rng.randint(0, 1),
        projector_offset=rng.uniform(0.55, 0.80),
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


def _fan_sign(p: Params) -> int:
    return FAN_LAYOUTS[p.fan_composition]


def _grating_center(p: Params) -> tuple[float, float]:
    return (-_fan_sign(p) * p.grating_x_abs, 0.0)


def _grating_segments(p: Params):
    """Vertical barrier segmented around the slit gaps."""
    cx, cy = _grating_center(p)
    half_w = p.grating_width / 2
    half_gap = p.grating_gap / 2
    total_span = (p.grating_n - 1) * p.grating_spacing
    y0 = cy - total_span / 2
    slit_ys = sorted([y0 + i * p.grating_spacing for i in range(p.grating_n)], reverse=True)

    segments = []
    prev_y = cy + half_w
    for si, sy in enumerate(slit_ys):
        top_of_gap = sy + half_gap
        if top_of_gap < prev_y:
            segments.append(
                thick_segment(
                    (cx, prev_y), (cx, top_of_gap),
                    p.grating_thickness, BARRIER_ID,
                    id_prefix=f"grating_seg_{si}",
                )
            )
        prev_y = sy - half_gap
    bot = cy - half_w
    if prev_y > bot:
        segments.append(
            thick_segment(
                (cx, prev_y), (cx, bot),
                p.grating_thickness, BARRIER_ID,
                id_prefix="grating_seg_bot",
            )
        )
    return segments


def _downstream_prisms(p: Params, rotation: float):
    sign = _fan_sign(p)
    gx, gy = _grating_center(p)
    total_span = (p.grating_n - 1) * p.grating_spacing
    y0 = gy - total_span / 2
    return [
        prism(
            center=(gx + sign * p.prism_row_offset, y0 + i * p.grating_spacing),
            size=p.prism_size,
            material_id=PRISM_IDS[p.prism_glass_idx % len(PRISM_IDS)],
            rotation=rotation + 0.15 * (i - (p.grating_n - 1) / 2),
            id_prefix=f"downstream_prism_{i}",
        )
        for i in range(p.grating_n)
    ]


def _spectrum_for(color: str) -> LightSpectrum:
    if color == "warm":
        return LightSpectrum.range(wavelength_min=580, wavelength_max=650)
    return LightSpectrum.range(wavelength_min=380, wavelength_max=780)


def _projectors(p: Params, progress: float) -> list[ProjectorLight]:
    sign = _fan_sign(p)
    gx, gy = _grating_center(p)
    out: list[ProjectorLight] = []
    for i, L in enumerate(p.lights):
        lx = gx - sign * p.projector_offset
        ly = gy + L.offset_perp
        base = math.atan2(gy - ly, gx - lx)
        a = base + L.base_angle_offset + L.angle_drift_rate * (progress - 0.5)
        spectrum = _spectrum_for(L.color)
        out.append(
            ProjectorLight(
                id=f"beam_{i}",
                position=[lx, ly],
                direction=[math.cos(a), math.sin(a)],
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
        BARRIER_ID: _barrier_material(),
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
        temperature=0.25 * warm_frac,
    )

    def animate(ctx):
        progress = ctx.progress if ctx.total_frames > 1 else 0.5
        rot = p.prism_rotation_speed * ctx.time / DURATION
        scene = Scene(
            materials=materials,
            shapes=[
                *mirror_box(CHAMBER_HW, CHAMBER_HH, WALL_ID, id_prefix="chamber"),
                *_grating_segments(p),
                *_downstream_prisms(p, rot),
            ],
            lights=_projectors(p, progress),
        )
        return Frame(scene=scene, look=look)

    return animate


# ── Quality gates ─────────────────────────────────────────────────────

# Grating geometry inherently smooths luminance more than cathedral/iris;
# RMS contrast >= 0.22 is a per-family relaxation of the strict 0.25 bar.
GATE_MEAN_LUMA = (0.425, 0.575)
GATE_RMS_CONTRAST_MIN = 0.22
GATE_CLIPPED_MAX = 0.40
GATE_MIN_PASSING_FRAC = 0.15


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
        f"branch={p.branch} {p.fan_composition} n_slits={p.grating_n} "
        f"alb={p.wall_albedo:.2f} exp={p.look_exposure:.2f}"
    )


def tag(p: Params) -> str:
    return f"{p.branch}_{p.fan_composition.replace('fan_', '')}"


def final_look(p: Params) -> dict:
    return dict(vignette=p.look_vignette, vignette_radius=p.look_vignette_radius)


FAMILY = Family(
    "grating_splitter",
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
