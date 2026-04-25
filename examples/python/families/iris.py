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
from typing import Any, Callable

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

# ── Motion-budget data tables ─────────────────────────────────────────
#
# A variant's motion is described by three orthogonal authored choices:
#
#   pace       ∈ PACES          — categorical "speed budget"
#   light_kind ∈ LIGHT_KINDS    — what the light does (always animated)
#   geom_kind  ∈ GEOM_KINDS     — what the geometry does on top of the ring spin
#
# Numeric ranges live entirely as data in RANGES — every speed-affecting
# parameter has a "slow" and "fast" entry. PACE_BINS chooses which one to
# draw from for each family of params at sample time:
#
#   slow_light → light from "slow", everything else from "fast"
#   fast_light → light from "fast", everything else from "slow"
#
# Adding a new param is one row in RANGES; adding a new pace is one row in
# PACE_BINS; adding a new motion is a new entry in LIGHT_KINDS / GEOM_KINDS.
# The |ω| floor is implicit in the data: the lowest "slow" lower bound on
# RANGES["ring_rate_abs"] sets it. Keep it consistent if you tune.

PACES = ("slow_light", "fast_light")

PACE_BINS: dict[str, dict[str, str]] = {
    "slow_light": {"light": "slow", "geom": "fast"},
    "fast_light": {"light": "fast", "geom": "slow"},
}

# Each entry: {"slow": (lo, hi), "fast": (lo, hi)}. All inclusive ranges.
RANGES: dict[str, dict[str, tuple[float, float]]] = {
    # Light-channel — slide and yaw are sinusoidal back-and-forths so they
    # are video-length-independent like the ring rotation.
    "slide_amp_frac":     {"slow": (0.30, 0.50), "fast": (0.80, 1.00)},
    "slide_period_sec":   {"slow": (15.0, 25.0), "fast": (6.0, 12.0)},
    "yaw_amp_rad":        {"slow": (0.06, 0.10), "fast": (0.14, 0.22)},
    "yaw_period_sec":     {"slow": (12.0, 20.0), "fast": (4.0, 8.0)},
    # Geom-channel
    "ring_rate_abs":      {"slow": (0.12, 0.27), "fast": (0.30, 0.54)},
    "counter_rot_rate":   {"slow": (0.30, 0.60), "fast": (0.80, 1.20)},
    "breathe_amp":        {"slow": (0.12, 0.18), "fast": (0.18, 0.25)},
    "breathe_period_sec": {"slow": (7.0, 10.0),  "fast": (4.0, 6.0)},
    "pulse_amp":          {"slow": (0.06, 0.10), "fast": (0.10, 0.14)},
    "pulse_period_sec":   {"slow": (9.0, 12.0),  "fast": (5.0, 8.0)},
}

# Geom kinds that pull the ring rate down by 10% (anything other than "none").
_GEOM_RING_DAMP = 0.9


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
    wall_roughness: float
    lights: list[LightDef] = field(default_factory=list)
    branch: str = "solo_white"
    look_exposure: float = -3.6
    look_gamma: float = 1.7
    look_contrast: float = 1.05
    look_shadows: float = 0.0
    look_vignette: float = 0.3
    look_vignette_radius: float = 1.65
    # Motion authoring (always set by sample()).
    pace: str = "slow_light"           # one of PACES
    light_kind: str = "slide"          # one of LIGHT_KINDS
    geom_kind: str = "none"            # one of GEOM_KINDS
    # Per-kind numeric params. Defaults are no-ops so that omitting a kind
    # leaves the scene untouched. All periodic motions share the same
    # ``offset = center + amp * sin(2π t / period)`` shape.
    slide_center: float = 0.0
    slide_amp: float = 0.0
    slide_period_sec: float = 8.0
    yaw_amplitude_rad: float = 0.0
    yaw_period_sec: float = 8.0
    counter_rot_rate_rad_per_sec: float = 0.0
    wedge_breathe_amp: float = 0.0
    wedge_breathe_period_sec: float = 8.0
    ring_pulse_amp: float = 0.0
    ring_pulse_period_sec: float = 8.0


# ── Sampling ──────────────────────────────────────────────────────────


def _wall_material(albedo: float, roughness: float) -> Material:
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


# ── Motion strategies ─────────────────────────────────────────────────
#
# Each strategy is a tiny dataclass bundling two callables:
#
#   sample(rng, ctx) -> dict[str, Any]
#       Draw the per-kind numeric parameters and return Params kwargs.
#
#   apply(...) -> per-channel deltas
#       Compute the time-varying contribution at time t. Default callables
#       (returning identity values) let a strategy override only the channels
#       it actually affects.
#
# Adding a new motion = add one more entry to LIGHT_KINDS / GEOM_KINDS.


def _no_radius_factor(p: "Params", t: float) -> float:
    return 1.0


def _no_size_factor(p: "Params", i: int, t: float) -> float:
    return 1.0


def _no_rotation_offset(p: "Params", t: float) -> float:
    return 0.0


@dataclass(frozen=True)
class LightStrategy:
    """A way to animate the light. Always one per variant."""
    # rng, layout, light_bin → kwargs for Params
    sample: Callable[[random.Random, str, str], dict[str, Any]]
    # p, L, t → (offset_tangent, yaw)
    apply: Callable[["Params", "LightDef", float], tuple[float, float]]


@dataclass(frozen=True)
class GeomStrategy:
    """A way to animate the ring/wedges on top of the always-on spin."""
    # rng, geom_bin → kwargs for Params
    sample: Callable[[random.Random, str], dict[str, Any]]
    radius_factor: Callable[["Params", float], float] = _no_radius_factor
    size_factor: Callable[["Params", int, float], float] = _no_size_factor
    rotation_offset: Callable[["Params", float], float] = _no_rotation_offset


def _sample_in(rng: random.Random, key: str, bin_: str) -> float:
    lo, hi = RANGES[key][bin_]
    return rng.uniform(lo, hi)


# Light: slide ─ sinusoidal back-and-forth along the wall.
# offset(t) = slide_center + slide_amp · sin(2π t / slide_period_sec).
# Both extrema (center ± |slide_amp|) are guaranteed to sit inside the wall
# tangent range by construction in _sample_slide.

def _sample_slide(rng: random.Random, layout: str, light_bin: str) -> dict[str, Any]:
    amp_frac = _sample_in(rng, "slide_amp_frac", light_bin)
    lo, hi = _tangent_range(layout)
    span = hi - lo
    half_amp = amp_frac * span / 2.0
    # Pick a center such that center ± half_amp stays inside the wall range.
    center_lo, center_hi = lo + half_amp, hi - half_amp
    center = rng.uniform(center_lo, center_hi) if center_hi > center_lo else (lo + hi) / 2.0
    direction = rng.choice([-1.0, 1.0])
    return {
        "slide_center": center,
        "slide_amp": direction * half_amp,
        "slide_period_sec": _sample_in(rng, "slide_period_sec", light_bin),
    }


def _apply_slide(p: "Params", L: "LightDef", t: float) -> tuple[float, float]:
    offset = p.slide_center + p.slide_amp * math.sin(2.0 * math.pi * t / p.slide_period_sec)
    return offset, 0.0


# Light: yaw ─ sinusoidal back-and-forth of the aim direction.

def _sample_yaw(rng: random.Random, layout: str, light_bin: str) -> dict[str, Any]:
    amp = _sample_in(rng, "yaw_amp_rad", light_bin)
    return {
        "yaw_amplitude_rad": amp * rng.choice([-1.0, 1.0]),
        "yaw_period_sec": _sample_in(rng, "yaw_period_sec", light_bin),
    }


def _apply_yaw(p: "Params", L: "LightDef", t: float) -> tuple[float, float]:
    yaw = p.yaw_amplitude_rad * math.sin(2.0 * math.pi * t / p.yaw_period_sec)
    return L.offset_tangent, yaw


# Geom: counter_rot ─ each wedge spins on its own axis at a rate ≠ ring rate.

def _sample_counter_rot(rng: random.Random, geom_bin: str) -> dict[str, Any]:
    rate = _sample_in(rng, "counter_rot_rate", geom_bin)
    return {"counter_rot_rate_rad_per_sec": rate * rng.choice([-1.0, 1.0])}


def _counter_rot_rotation_offset(p: "Params", t: float) -> float:
    return p.counter_rot_rate_rad_per_sec * t


# Geom: wedge_breathe ─ per-wedge size oscillation with phase offsets.

def _sample_wedge_breathe(rng: random.Random, geom_bin: str) -> dict[str, Any]:
    return {
        "wedge_breathe_amp": _sample_in(rng, "breathe_amp", geom_bin),
        "wedge_breathe_period_sec": _sample_in(rng, "breathe_period_sec", geom_bin),
    }


def _wedge_breathe_size_factor(p: "Params", i: int, t: float) -> float:
    if p.wedge_breathe_amp <= 0.0:
        return 1.0
    phase = 2.0 * math.pi * i / p.n_wedges
    return 1.0 + p.wedge_breathe_amp * math.sin(
        2.0 * math.pi * t / p.wedge_breathe_period_sec + phase
    )


# Geom: ring_pulse ─ ring radius oscillates as a whole.

def _sample_ring_pulse(rng: random.Random, geom_bin: str) -> dict[str, Any]:
    return {
        "ring_pulse_amp": _sample_in(rng, "pulse_amp", geom_bin),
        "ring_pulse_period_sec": _sample_in(rng, "pulse_period_sec", geom_bin),
    }


def _ring_pulse_radius_factor(p: "Params", t: float) -> float:
    if p.ring_pulse_amp <= 0.0:
        return 1.0
    return 1.0 + p.ring_pulse_amp * math.sin(2.0 * math.pi * t / p.ring_pulse_period_sec)


def _sample_geom_none(rng: random.Random, geom_bin: str) -> dict[str, Any]:
    return {}


LIGHT_KINDS: dict[str, LightStrategy] = {
    "slide": LightStrategy(sample=_sample_slide, apply=_apply_slide),
    "yaw":   LightStrategy(sample=_sample_yaw,   apply=_apply_yaw),
}

GEOM_KINDS: dict[str, GeomStrategy] = {
    "none":          GeomStrategy(sample=_sample_geom_none),
    "counter_rot":   GeomStrategy(sample=_sample_counter_rot,
                                  rotation_offset=_counter_rot_rotation_offset),
    "wedge_breathe": GeomStrategy(sample=_sample_wedge_breathe,
                                  size_factor=_wedge_breathe_size_factor),
    "ring_pulse":    GeomStrategy(sample=_sample_ring_pulse,
                                  radius_factor=_ring_pulse_radius_factor),
}


# ── Sampling ──────────────────────────────────────────────────────────


def _sample_ring_rate(rng: random.Random, geom_kind: str, geom_bin: str) -> float:
    """|ω| from RANGES[ring_rate_abs][geom_bin]; ×0.9 if any geom motion is on."""
    abs_rate = _sample_in(rng, "ring_rate_abs", geom_bin)
    if geom_kind != "none":
        abs_rate *= _GEOM_RING_DAMP
    return abs_rate * rng.choice([-1.0, 1.0])


def sample(
    rng: random.Random,
    *,
    branch: str | None = None,
    layout: str | None = None,
    pace: str | None = None,
    light_kind: str | None = None,
    geom_kind: str | None = None,
) -> Params:
    """Sample a variant. Any axis can be pinned by the caller (used by the
    catalog); unpinned axes are drawn uniformly at random."""
    names = list(_BRANCHES)
    chosen_branch = branch or rng.choices(
        names, weights=[_BRANCHES[n][1] for n in names], k=1
    )[0]
    chosen_layout = layout or rng.choice(IRIS_LAYOUTS)
    chosen_pace = pace or rng.choice(PACES)
    chosen_light = light_kind or rng.choice(list(LIGHT_KINDS))
    chosen_geom = geom_kind or rng.choice(list(GEOM_KINDS))

    light_bin = PACE_BINS[chosen_pace]["light"]
    geom_bin = PACE_BINS[chosen_pace]["geom"]

    lights = _BRANCHES[chosen_branch][0](rng, chosen_layout)
    wall_albedo = rng.uniform(*WALL_ALBEDO_RANGE)
    n_wedges = rng.randint(6, 10)
    ring_rate = _sample_ring_rate(rng, chosen_geom, geom_bin)

    light_kwargs = LIGHT_KINDS[chosen_light].sample(rng, chosen_layout, light_bin)
    geom_kwargs = GEOM_KINDS[chosen_geom].sample(rng, geom_bin)

    return Params(
        iris_composition=chosen_layout,
        ring_radius=rng.uniform(0.35, 0.55),
        n_wedges=n_wedges,
        wedge_size=rng.uniform(0.07, 0.12),
        ring_rotation_rate_rad_per_sec=ring_rate,
        wedge_ior=rng.uniform(1.45, 1.55),
        wedge_cauchy_b=rng.uniform(18_000.0, 50_000.0),
        wedge_fill=rng.uniform(*GLASS_FILL_RANGE),
        wedge_roughness=rng.uniform(0.0, 0.015),
        wall_albedo=wall_albedo,
        wall_roughness=rng.uniform(0.075, 0.15),
        lights=lights,
        branch=chosen_branch,
        look_exposure=_exposure_for(wall_albedo, len(lights)) + rng.uniform(-0.15, 0.15),
        look_gamma=rng.uniform(1.4, 2.0),
        look_contrast=rng.uniform(1.0, 1.1),
        look_shadows=rng.uniform(-0.2, 0.2),
        look_vignette=rng.uniform(0.1, 0.5),
        look_vignette_radius=rng.uniform(1.5, 1.8),
        pace=chosen_pace,
        light_kind=chosen_light,
        geom_kind=chosen_geom,
        **light_kwargs,
        **geom_kwargs,
    )


# ── Scene ─────────────────────────────────────────────────────────────


def _spectrum_for(color: str) -> LightSpectrum:
    if color == "warm":
        return LightSpectrum.range(wavelength_min=580, wavelength_max=650)
    return LightSpectrum.range(wavelength_min=380, wavelength_max=780)


def _light_position_and_dir(side: str, offset_tangent: float, yaw: float = 0.0):
    """Wall position + direction aimed at the (always-centered) ring.

    ``yaw`` rotates the aim by that many radians around the position. Position
    always stays inside the chamber walls.
    """
    if side == "left":
        pos = (-CHAMBER_HW + 0.08, offset_tangent)
    elif side == "right":
        pos = (CHAMBER_HW - 0.08, offset_tangent)
    elif side == "top":
        pos = (offset_tangent, CHAMBER_HH - 0.08)
    else:
        pos = (offset_tangent, -CHAMBER_HH + 0.08)
    a = math.atan2(-pos[1], -pos[0]) + yaw
    return pos, (math.cos(a), math.sin(a))


def _projectors(p: Params, t: float) -> list[ProjectorLight]:
    light_strategy = LIGHT_KINDS[p.light_kind]
    out: list[ProjectorLight] = []
    for i, L in enumerate(p.lights):
        offset, yaw = light_strategy.apply(p, L, t)
        pos, dir_ = _light_position_and_dir(L.side, offset, yaw=yaw)
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


def _wedge_shapes(p: Params, t: float):
    geom = GEOM_KINDS[p.geom_kind]
    ring_angle = p.ring_rotation_rate_rad_per_sec * t
    radius = p.ring_radius * geom.radius_factor(p, t)
    rotation_offset = geom.rotation_offset(p, t)
    out = []
    for i in range(p.n_wedges):
        base_angle = ring_angle + 2.0 * math.pi * i / p.n_wedges
        size = p.wedge_size * geom.size_factor(p, i, t)
        rotation = base_angle + rotation_offset
        out.append(
            prism(
                center=(radius * math.cos(base_angle), radius * math.sin(base_angle)),
                size=size,
                material_id=WEDGE_ID,
                rotation=rotation,
                id_prefix=f"wedge_{i}",
            )
        )
    return out


def build(p: Params):
    """Family.build: return the per-frame animate callback."""
    materials = {
        WALL_ID: _wall_material(p.wall_albedo, p.wall_roughness),
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
            lights=_projectors(p, t_seconds),
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
        f"branch={p.branch} iris={p.iris_composition} pace={p.pace} "
        f"light={p.light_kind} geom={p.geom_kind} "
        f"n={p.n_wedges} r={p.ring_radius:.2f} ω={p.ring_rotation_rate_rad_per_sec:+.3f} "
        f"alb={p.wall_albedo:.2f} exp={p.look_exposure:.2f}"
    )


def tag(p: Params) -> str:
    layout = p.iris_composition.replace("iris_", "")
    return f"{p.branch}_{layout}_{p.pace}_{p.light_kind}_{p.geom_kind}"


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
