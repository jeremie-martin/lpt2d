"""Iris — a rotating ring of prism wedges forming an aperture.

A projector shines through a ring of glass wedges. Rays passing near the
centre escape unrefracted; rays grazing the ring hit wedges and fan out
into spectrum. As the ring rotates, the chamber continually shifts colour.

Branches:
- solo_white      : one full-spectrum projector
- solo_warm       : one orange projector
- duet_contrast   : warm + white from independent regime trajectories

Light motion (one regime per variant; see :mod:`iris_motion` for details):
- loop      : deterministic inv-sines, exact density on the path
- patrol    : waypoint hops with optional dwell
- two_well  : two attractors, light swings between them
- chase     : light tracks a slowly-drifting attractor
- wander2d  : 2D underdamped Langevin in the annular region
- polar     : angular loop + radial breathing

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

from examples.python.families import iris_motion

# ── Constants ─────────────────────────────────────────────────────────

# Portrait 9:16 chamber. Camera width matches CHAMBER_HW * 2; with a 9:16
# canvas the auto-derived camera height (= width * 16/9 = 3.2) lines up
# exactly with CHAMBER_HH * 2.
CAMERA = Camera2D(center=[0, 0], width=1.8)
DURATION = 6.0
CHAMBER_HW, CHAMBER_HH = 0.9, 1.6

WALL_ID = "wall"
WEDGE_ID = "iris_glass"

# Aesthetic ranges
WALL_ALBEDO_RANGE = (0.9, 1.0)
GLASS_FILL_RANGE = (0.075, 0.15)
INTENSITY_RANGE = (0.8, 1.2)

# Motion sampling ranges (curator-chosen, per latest tuning session).
W_CORNER_RANGE = (0.00, 0.225)
W_VERT_RANGE = (0.00, 0.075)
A_Y_RANGE = (0.82, 1.10)
DRIFT_RANGE = (0.09, 0.11)
SMOOTHNESS_RANGE = (0.90, 0.97)
SPEED_SCALE_RANGE = (0.10, 0.40)

# Secondary motion ranges (used by the stochastic regimes).
NOISE_AMP_RANGE = (0.20, 0.50)
N_SINES_RANGE = (2, 4)
D_RANGE = (0.20, 0.50)
GAMMA_RANGE = (2.0, 4.0)
DWELL_RANGE = (0.0, 1.0)
BASE_PERIOD = 4.0

# Active light-motion regimes for production. wander2d drifts too fast under
# the family's speed_scale; polar didn't read well in 15s shorts after
# iteration. Both stay defined in iris_motion so manual experiments can still
# pin them via `iris_batch.py --regime <name>`.
#
# Define the production set EXPLICITLY (rather than as an exclusion). A
# rename in iris_motion now raises a loud KeyError instead of silently
# re-enabling a regime we curated out.
LIGHT_REGIMES = ("loop", "patrol", "two_well", "chase")
assert all(n in iris_motion.REGIME_NAMES for n in LIGHT_REGIMES), (
    "production regimes drifted from iris_motion: "
    f"{[n for n in LIGHT_REGIMES if n not in iris_motion.REGIME_NAMES]}"
)

# Geom kinds dampen the ring rotation when active so the wedges don't blur.
_GEOM_RING_DAMP = 0.9


# ── Params ────────────────────────────────────────────────────────────


@dataclass
class LightDef:
    """One projector. Position + direction come from a :class:`iris_motion.RegimeRunner`
    constructed from ``regime`` and ``seed`` at build-time."""
    regime: str
    seed: int
    spread: float
    source: str
    source_radius: float
    intensity: float
    color: str  # "warm" | "white"


@dataclass
class Params:
    # Ring + chamber
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
    # Branch + regime + geom-kind
    branch: str = "solo_white"
    regime: str = "loop"
    geom_kind: str = "none"
    lights: list[LightDef] = field(default_factory=list)
    # Light-motion params (shared across all lights in a variant)
    w_corner: float = 0.30
    w_vert: float = 0.10
    a_y: float = 1.00
    drift: float = 0.10
    smoothness: float = 0.90
    speed_scale: float = 0.75
    noise_amp: float = 0.30
    n_sines: int = 3
    D: float = 0.30
    gamma: float = 3.0
    dwell: float = 0.0
    # Geom-channel params (per geom_kind; defaults are no-ops)
    counter_rot_rate_rad_per_sec: float = 0.0
    wedge_breathe_amp: float = 0.0
    wedge_breathe_period_sec: float = 8.0
    ring_pulse_amp: float = 0.0
    ring_pulse_period_sec: float = 8.0
    # Look
    look_exposure: float = -3.6
    look_gamma: float = 1.7
    look_contrast: float = 1.05
    look_shadows: float = 0.0
    look_vignette: float = 0.3
    look_vignette_radius: float = 1.65


# ── Helpers ───────────────────────────────────────────────────────────


def _wall_material(albedo: float, roughness: float) -> Material:
    return Material(
        metallic=1.0, roughness=roughness, transmission=0.0, cauchy_b=0.0, albedo=albedo
    )


def _exposure_for(albedo: float, n_lights: int) -> float:
    base = -1.10 * albedo - 2.55
    return base + (0.0 if n_lights == 1 else -0.45)


def _spectrum_for(color: str) -> LightSpectrum:
    if color == "warm":
        return LightSpectrum.range(wavelength_min=580, wavelength_max=650)
    return LightSpectrum.range(wavelength_min=380, wavelength_max=780)


# ── Geom strategies (ring/wedge motion on top of the always-on spin) ────

def _no_radius_factor(p: "Params", t: float) -> float:
    return 1.0


def _no_size_factor(p: "Params", i: int, t: float) -> float:
    return 1.0


def _no_rotation_offset(p: "Params", t: float) -> float:
    return 0.0


@dataclass(frozen=True)
class GeomStrategy:
    """How the ring/wedges move on top of the always-on spin."""
    sample: Callable[[random.Random], dict[str, Any]]
    radius_factor: Callable[["Params", float], float] = _no_radius_factor
    size_factor: Callable[["Params", int, float], float] = _no_size_factor
    rotation_offset: Callable[["Params", float], float] = _no_rotation_offset


def _sample_geom_none(rng: random.Random) -> dict[str, Any]:
    return {}


def _sample_counter_rot(rng: random.Random) -> dict[str, Any]:
    return {"counter_rot_rate_rad_per_sec": rng.uniform(0.4, 0.9) * rng.choice([-1.0, 1.0])}


def _counter_rot_rotation_offset(p: "Params", t: float) -> float:
    return p.counter_rot_rate_rad_per_sec * t


def _sample_wedge_breathe(rng: random.Random) -> dict[str, Any]:
    return {
        "wedge_breathe_amp": rng.uniform(0.12, 0.22),
        "wedge_breathe_period_sec": rng.uniform(5.0, 8.0),
    }


def _wedge_breathe_size_factor(p: "Params", i: int, t: float) -> float:
    if p.wedge_breathe_amp <= 0.0:
        return 1.0
    phase = 2.0 * math.pi * i / p.n_wedges
    return 1.0 + p.wedge_breathe_amp * math.sin(
        2.0 * math.pi * t / p.wedge_breathe_period_sec + phase
    )


def _sample_ring_pulse(rng: random.Random) -> dict[str, Any]:
    return {
        "ring_pulse_amp": rng.uniform(0.08, 0.14),
        "ring_pulse_period_sec": rng.uniform(7.0, 11.0),
    }


def _ring_pulse_radius_factor(p: "Params", t: float) -> float:
    if p.ring_pulse_amp <= 0.0:
        return 1.0
    return 1.0 + p.ring_pulse_amp * math.sin(2.0 * math.pi * t / p.ring_pulse_period_sec)


GEOM_KINDS: dict[str, GeomStrategy] = {
    "none":          GeomStrategy(sample=_sample_geom_none),
    "counter_rot":   GeomStrategy(sample=_sample_counter_rot,
                                  rotation_offset=_counter_rot_rotation_offset),
    "wedge_breathe": GeomStrategy(sample=_sample_wedge_breathe,
                                  size_factor=_wedge_breathe_size_factor),
    "ring_pulse":    GeomStrategy(sample=_sample_ring_pulse,
                                  radius_factor=_ring_pulse_radius_factor),
}


# ── Branches ──────────────────────────────────────────────────────────

# (sampler, weight)
_BRANCHES: dict[str, tuple[Callable[[random.Random, str], list[LightDef]], float]] = {}


def _sample_one_light(rng: random.Random, *, regime: str, color: str) -> LightDef:
    return LightDef(
        regime=regime,
        seed=int(rng.randrange(1 << 31)),
        spread=rng.uniform(0.05, 0.09),
        source=rng.choice(["ball", "line"]),
        source_radius=rng.uniform(0.008, 0.020),
        intensity=rng.uniform(*INTENSITY_RANGE),
        color=color,
    )


def _branch_solo_white(rng: random.Random, regime: str) -> list[LightDef]:
    return [_sample_one_light(rng, regime=regime, color="white")]


def _branch_solo_warm(rng: random.Random, regime: str) -> list[LightDef]:
    return [_sample_one_light(rng, regime=regime, color="warm")]


def _branch_duet_contrast(rng: random.Random, regime: str) -> list[LightDef]:
    # Both lights share the same regime but have independent seeds → they
    # evolve as two distinct trajectories of the same character.
    return [
        _sample_one_light(rng, regime=regime, color="warm"),
        _sample_one_light(rng, regime=regime, color="white"),
    ]


# Random sampling weights. Only solo_white runs in production — solo_warm
# and duet_contrast read muddier in shorts. Their samplers stay defined so
# `iris_batch.py --branch solo_warm` still works for offline experiments.
_BRANCHES = {
    "solo_white": (_branch_solo_white, 1.0),
    "solo_warm": (_branch_solo_warm, 0.0),
    "duet_contrast": (_branch_duet_contrast, 0.0),
}
assert {n for n, (_, w) in _BRANCHES.items() if w > 0} == {"solo_white"}, (
    "production constraint: solo_white must be the only branch with non-zero "
    "weight; flip the weight intentionally if you really want a different mix"
)


# ── Sampling ──────────────────────────────────────────────────────────


def sample(
    rng: random.Random,
    *,
    branch: str | None = None,
    regime: str | None = None,
    geom_kind: str | None = None,
) -> Params:
    """Sample a variant. Any axis can be pinned by the caller; unpinned
    axes are drawn uniformly at random."""
    branch_names = list(_BRANCHES)
    chosen_branch = branch or rng.choices(
        branch_names, weights=[_BRANCHES[n][1] for n in branch_names], k=1
    )[0]
    chosen_regime = regime or rng.choice(LIGHT_REGIMES)
    chosen_geom = geom_kind or rng.choice(list(GEOM_KINDS))

    # Motion params (curator-chosen ranges)
    w_corner = rng.uniform(*W_CORNER_RANGE)
    w_vert = rng.uniform(*W_VERT_RANGE)
    a_y = rng.uniform(*A_Y_RANGE)
    drift = rng.uniform(*DRIFT_RANGE)
    smoothness = rng.uniform(*SMOOTHNESS_RANGE)
    speed_scale = rng.uniform(*SPEED_SCALE_RANGE)
    noise_amp = rng.uniform(*NOISE_AMP_RANGE)
    n_sines = rng.randint(*N_SINES_RANGE)
    D = rng.uniform(*D_RANGE)
    gamma = rng.uniform(*GAMMA_RANGE)
    dwell = rng.uniform(*DWELL_RANGE) if chosen_regime == "patrol" else 0.0

    # Ring rotation: |ω| ∈ [0.10, 0.40] rad/s, damped 10% if any geom motion is on.
    ring_rate_abs = rng.uniform(0.10, 0.40)
    if chosen_geom != "none":
        ring_rate_abs *= _GEOM_RING_DAMP
    ring_rate = ring_rate_abs * rng.choice([-1.0, 1.0])

    # Wall + ring sampling
    wall_albedo = rng.uniform(*WALL_ALBEDO_RANGE)
    n_wedges = rng.randint(6, 10)

    # Lights from branch
    lights = _BRANCHES[chosen_branch][0](rng, chosen_regime)

    # Geom kwargs
    geom_kwargs = GEOM_KINDS[chosen_geom].sample(rng)

    return Params(
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
        branch=chosen_branch,
        regime=chosen_regime,
        geom_kind=chosen_geom,
        lights=lights,
        w_corner=w_corner, w_vert=w_vert, a_y=a_y,
        drift=drift, smoothness=smoothness, speed_scale=speed_scale,
        noise_amp=noise_amp, n_sines=n_sines,
        D=D, gamma=gamma, dwell=dwell,
        look_exposure=_exposure_for(wall_albedo, len(lights)) + rng.uniform(-0.15, 0.15),
        look_gamma=rng.uniform(1.4, 2.0),
        look_contrast=rng.uniform(1.0, 1.1),
        look_shadows=rng.uniform(-0.2, 0.2),
        look_vignette=rng.uniform(0.1, 0.5),
        look_vignette_radius=rng.uniform(1.5, 1.8),
        **geom_kwargs,
    )


# ── Build / animate ───────────────────────────────────────────────────


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
    """Family.build: return the per-frame animate callback.

    Construction-time work: build materials, look dict, motion params and
    one :class:`iris_motion.RegimeRunner` per light. Each runner drives the
    light's position on every frame call.
    """
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

    motion_params = iris_motion.MotionParams(
        w_corner=p.w_corner, w_vert=p.w_vert, a_y=p.a_y,
        ring_radius=p.ring_radius, drift=p.drift,
        noise_amp=p.noise_amp, n_sines=p.n_sines, base_period=BASE_PERIOD,
        D=p.D, gamma=p.gamma, dwell=p.dwell,
        smoothness=p.smoothness, speed_scale=p.speed_scale,
    )
    runners = [
        iris_motion.RegimeRunner(L.regime, motion_params, L.seed)
        for L in p.lights
    ]

    def animate(ctx):
        # Stills use a fixed midpoint pose so single-frame previews are
        # stable across requested durations.
        t_seconds = ctx.time if ctx.total_frames > 1 else DURATION / 2

        projectors: list[ProjectorLight] = []
        for i, (L, runner) in enumerate(zip(p.lights, runners)):
            x, y = runner.at(t_seconds)
            r = math.hypot(x, y)
            if r < 1e-6:
                dx, dy = 1.0, 0.0
            else:
                dx, dy = -x / r, -y / r
            spectrum = _spectrum_for(L.color)
            projectors.append(
                ProjectorLight(
                    id=f"beam_{i}",
                    position=[x, y],
                    direction=[dx, dy],
                    source_radius=L.source_radius,
                    spread=L.spread,
                    source=L.source,
                    intensity=intensity_for_spectrum(L.intensity, spectrum),
                    spectrum=spectrum,
                )
            )

        scene = Scene(
            materials=materials,
            shapes=[
                *mirror_box(CHAMBER_HW, CHAMBER_HH, WALL_ID, id_prefix="chamber"),
                *_wedge_shapes(p, t_seconds),
            ],
            lights=projectors,
        )
        return Frame(scene=scene, look=look)

    return animate


# ── Quality gates ─────────────────────────────────────────────────────

GATE_MEAN_LUMA = (0.425, 0.575)
GATE_RMS_CONTRAST_MIN = 0.25
GATE_CLIPPED_MAX = 0.40
GATE_P05_LUMA_MAX = 0.20
GATE_MIN_PASSING_FRAC = 0.30


PROBE_DEPTH = 12  # match the render presets — depth affects brightness, so
                  # the gate must judge an image of the same brightness as ships


def check(animate) -> Verdict:
    """Reject probes that miss the mean-luma + RMS-contrast band.

    Probes the module's nominal DURATION at fps=4. With the regime-runner
    architecture, the probe's lower fps means fewer internal regime steps
    per probe-frame than render frames — but the runner advances at a
    fixed internal rate (60 Hz), so the same external time always yields
    the same world position. Probe stats remain representative.

    Depth matches the render so the gate's brightness/contrast metrics
    reflect what the user will actually see.
    """
    frames = probe(animate, DURATION, fps=4, camera=CAMERA, depth=PROBE_DEPTH)
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
        f"branch={p.branch} regime={p.regime} geom={p.geom_kind} "
        f"n={p.n_wedges} r={p.ring_radius:.2f} ω={p.ring_rotation_rate_rad_per_sec:+.3f} "
        f"alb={p.wall_albedo:.2f} exp={p.look_exposure:.2f} "
        f"w_c={p.w_corner:.2f} w_v={p.w_vert:.2f} a_y={p.a_y:.2f} "
        f"drift={p.drift:.2f} ss={p.speed_scale:.2f} sm={p.smoothness:.2f}"
    )


def tag(p: Params) -> str:
    return f"{p.branch}_{p.regime}_{p.geom_kind}"


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
