"""Cathedral Aperture — shafts of light through a wall-slit.

A thick metallic wall divides the chamber at a golden-ratio position. One to
three projectors sit behind the wall and throw narrow shafts through the slit,
striking a glass prism in the big chamber and breaking into spectra on the
far wall.

Branches (explicit per-branch parameters, never mixed within a scene):

- solo_warm          : one narrow orange projector
- solo_white         : one full-spectrum projector
- duet_warm          : two matched orange projectors, slight angular divergence
- duet_white         : two matched full-spectrum projectors
- duet_contrast      : one orange + one full-spectrum, classic warm/cool pair
- trio_warm_accent   : two full-spectrum + one orange accent (careful)

Wall composition (explicit per-scene):

- golden_small_left  : small chamber on the left (wall at x = -0.378)
- golden_small_right : small chamber on the right (wall at x = +0.378), medieval
                       inversion; beam direction flips accordingly

Intent sentence (hero moment):
    Bright shafts are clearly visible passing through the slit, the prism
    catches them and casts readable spectra on the far wall, the chamber
    reads as architectural rather than flooded.
"""

from __future__ import annotations

import json
import math
import random
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from anim import (
    Camera2D,
    Frame,
    FrameContext,
    LightSpectrum,
    Look,
    Material,
    ProjectorLight,
    Scene,
    Shot,
    Timeline,
    glass,
    mirror_box,
    prism,
    render,
    thick_segment,
)
from anim.renderer import RenderSession, _resolve_frame_shot

# ---------------------------------------------------------------------------
# Scene constants
# ---------------------------------------------------------------------------

WALL = Material(metallic=1.0, roughness=0.1, transmission=0.0, cauchy_b=0.0, albedo=1.0)
CAMERA = Camera2D(center=[0, 0], width=3.2)
DURATION = 6.0
CHAMBER_HW, CHAMBER_HH = 1.6, 0.9

# Golden-ratio wall position. The short chamber takes 1/phi^2 of the width.
PHI = (1.0 + 5.0 ** 0.5) / 2.0
_SHORT_FRAC = 1.0 / (PHI * PHI)  # ~0.382
_GOLDEN_WALL_X_LEFT = -CHAMBER_HW + 2.0 * CHAMBER_HW * _SHORT_FRAC   # ~ -0.378
_GOLDEN_WALL_X_RIGHT = -CHAMBER_HW + 2.0 * CHAMBER_HW * (1.0 - _SHORT_FRAC)  # ~ +0.378

WALL_LAYOUTS: dict[str, dict] = {
    "golden_small_left": {"wall_x": _GOLDEN_WALL_X_LEFT, "beam_dir_sign": +1.0},
    "golden_small_right": {"wall_x": _GOLDEN_WALL_X_RIGHT, "beam_dir_sign": -1.0},
}

WALL_ID = "wall"

PRISM_GLASSES = [
    glass(1.52, cauchy_b=28_000, color=(0.97, 0.97, 0.97), fill=0.10),
    glass(1.60, cauchy_b=35_000, color=(0.95, 0.96, 1.0), fill=0.10),
]
PRISM_IDS = ["prism_a", "prism_b"]

MATERIALS = {
    WALL_ID: WALL,
    PRISM_IDS[0]: PRISM_GLASSES[0],
    PRISM_IDS[1]: PRISM_GLASSES[1],
}


# ---------------------------------------------------------------------------
# Parameter space
# ---------------------------------------------------------------------------


@dataclass
class LightDef:
    offset_perp: float       # vertical offset from slit_cy
    offset_along: float      # distance from wall toward the light (positive = away from wall)
    angle_jitter: float      # radians of deviation from aim-at-prism
    spread: float
    source: str              # "ball" or "line"
    source_radius: float
    intensity: float
    color: str               # "warm" or "white"


@dataclass
class AnimParams:
    wall_composition: str            # key of WALL_LAYOUTS
    slit_cy: float
    slit_gap: float
    wall_thickness: float
    prism_offset_along: float        # distance from wall into the big chamber
    prism_y: float
    prism_size: float
    prism_rotation_speed: float
    prism_glass_idx: int
    lights: list[LightDef] = field(default_factory=list)
    branch: str = "solo_warm"
    look_exposure: float = -4.6


# ---------------------------------------------------------------------------
# Layout helpers
# ---------------------------------------------------------------------------


def _layout(p: AnimParams) -> tuple[float, float]:
    info = WALL_LAYOUTS[p.wall_composition]
    return info["wall_x"], info["beam_dir_sign"]


def _prism_world(p: AnimParams) -> tuple[float, float]:
    wall_x, sign = _layout(p)
    return (wall_x + sign * p.prism_offset_along, p.prism_y)


def _light_world_pos(p: AnimParams, L: LightDef) -> tuple[float, float]:
    wall_x, sign = _layout(p)
    # Lights sit on the opposite side of the wall from the prism.
    return (wall_x - sign * L.offset_along, p.slit_cy + L.offset_perp)


def _light_world_dir(p: AnimParams, L: LightDef) -> tuple[float, float]:
    pw = _prism_world(p)
    lw = _light_world_pos(p, L)
    base = math.atan2(pw[1] - lw[1], pw[0] - lw[0])
    a = base + L.angle_jitter
    return (math.cos(a), math.sin(a))


# ---------------------------------------------------------------------------
# Scene builder
# ---------------------------------------------------------------------------


def _slit_wall_shapes(p: AnimParams) -> list:
    wall_x, _ = _layout(p)
    half_g = p.slit_gap / 2
    top = thick_segment(
        (wall_x, p.slit_cy + half_g),
        (wall_x, CHAMBER_HH),
        p.wall_thickness,
        WALL_ID,
    )
    bot = thick_segment(
        (wall_x, -CHAMBER_HH),
        (wall_x, p.slit_cy - half_g),
        p.wall_thickness,
        WALL_ID,
    )
    top.id = "slit_top"
    bot.id = "slit_bot"
    return [top, bot]


def _spectrum_for(color: str) -> LightSpectrum:
    if color == "warm":
        return LightSpectrum.range(wavelength_min=580, wavelength_max=650)
    if color == "white":
        return LightSpectrum.range(wavelength_min=380, wavelength_max=780)
    raise ValueError(f"unknown light color {color!r}")


def _projectors(p: AnimParams) -> list[ProjectorLight]:
    out: list[ProjectorLight] = []
    for i, L in enumerate(p.lights):
        pos = _light_world_pos(p, L)
        dir_ = _light_world_dir(p, L)
        out.append(
            ProjectorLight(
                id=f"beam_{i}",
                position=list(pos),
                direction=list(dir_),
                source_radius=L.source_radius,
                spread=L.spread,
                source=L.source,
                intensity=L.intensity,
                spectrum=_spectrum_for(L.color),
            )
        )
    return out


def build_animate(p: AnimParams):
    def animate(ctx: FrameContext) -> Frame:
        t = ctx.time
        rot = p.prism_rotation_speed * t / DURATION
        px, py = _prism_world(p)
        prism_shape = prism(
            center=(px, py),
            size=p.prism_size,
            material_id=PRISM_IDS[p.prism_glass_idx % len(PRISM_IDS)],
            rotation=rot,
            id_prefix="prism",
        )
        scene = Scene(
            materials=MATERIALS,
            shapes=[
                *mirror_box(CHAMBER_HW, CHAMBER_HH, WALL_ID, id_prefix="chamber"),
                *_slit_wall_shapes(p),
                prism_shape,
            ],
            lights=_projectors(p),
        )
        # Warm-dominant scenes get a gentle temperature push.
        warm_count = sum(1 for L in p.lights if L.color == "warm")
        warm_frac = warm_count / max(1, len(p.lights))
        temp = 0.30 * warm_frac
        look = Look(
            exposure=p.look_exposure,
            gamma=2.0,
            tonemap="reinhardx",
            white_point=0.5,
            normalize="rays",
            temperature=temp,
        )
        return Frame(scene=scene, look=look)

    return animate


# ---------------------------------------------------------------------------
# Per-branch light sampling
# ---------------------------------------------------------------------------
#
# Each branch defines its own inline ranges. No hoisting. Per-light intensity
# scales inversely with light count so total chamber energy doesn't explode.


def _sample_light(
    rng: random.Random,
    *,
    color: str,
    offset_perp: float,
    angle_jitter: float,
    intensity: float,
) -> LightDef:
    return LightDef(
        offset_perp=offset_perp,
        offset_along=rng.uniform(0.20, 0.35),
        angle_jitter=angle_jitter,
        spread=rng.uniform(0.03, 0.06),
        source=rng.choice(["ball", "line"]),
        source_radius=rng.uniform(0.005, 0.015),
        intensity=intensity,
        color=color,
    )


def _sample_solo_warm(rng: random.Random) -> list[LightDef]:
    return [_sample_light(rng, color="warm", offset_perp=rng.uniform(-0.025, 0.025),
                          angle_jitter=0.0, intensity=rng.uniform(0.18, 0.32))]


def _sample_solo_white(rng: random.Random) -> list[LightDef]:
    return [_sample_light(rng, color="white", offset_perp=rng.uniform(-0.025, 0.025),
                          angle_jitter=0.0, intensity=rng.uniform(0.55, 0.80))]


def _sample_duet_warm(rng: random.Random) -> list[LightDef]:
    # Two warm lights spaced vertically, aimed with small angular divergence.
    off = rng.uniform(0.015, 0.030)
    jit = rng.uniform(0.015, 0.035)
    base_i = rng.uniform(0.14, 0.22)
    return [
        _sample_light(rng, color="warm", offset_perp=+off, angle_jitter=-jit, intensity=base_i),
        _sample_light(rng, color="warm", offset_perp=-off, angle_jitter=+jit, intensity=base_i),
    ]


def _sample_duet_white(rng: random.Random) -> list[LightDef]:
    off = rng.uniform(0.015, 0.030)
    jit = rng.uniform(0.015, 0.035)
    base_i = rng.uniform(0.40, 0.60)
    return [
        _sample_light(rng, color="white", offset_perp=+off, angle_jitter=-jit, intensity=base_i),
        _sample_light(rng, color="white", offset_perp=-off, angle_jitter=+jit, intensity=base_i),
    ]


def _sample_duet_contrast(rng: random.Random) -> list[LightDef]:
    # One warm + one white, warm naturally reads brighter, so keep it lower.
    off = rng.uniform(0.015, 0.030)
    jit = rng.uniform(0.015, 0.035)
    warm_on_top = rng.random() < 0.5
    warm = _sample_light(rng, color="warm",
                         offset_perp=(+off if warm_on_top else -off),
                         angle_jitter=(-jit if warm_on_top else +jit),
                         intensity=rng.uniform(0.14, 0.22))
    white = _sample_light(rng, color="white",
                          offset_perp=(-off if warm_on_top else +off),
                          angle_jitter=(+jit if warm_on_top else -jit),
                          intensity=rng.uniform(0.40, 0.55))
    return [warm, white]


def _sample_trio_warm_accent(rng: random.Random) -> list[LightDef]:
    # Two whites framing one warm in the middle. Careful intensities.
    spacing = rng.uniform(0.018, 0.030)
    jit = rng.uniform(0.010, 0.025)
    warm_i = rng.uniform(0.10, 0.16)
    white_i = rng.uniform(0.28, 0.42)
    return [
        _sample_light(rng, color="white", offset_perp=+spacing, angle_jitter=-jit, intensity=white_i),
        _sample_light(rng, color="warm", offset_perp=0.0, angle_jitter=0.0, intensity=warm_i),
        _sample_light(rng, color="white", offset_perp=-spacing, angle_jitter=+jit, intensity=white_i),
    ]


_BRANCH_LIGHT_SAMPLERS = {
    "solo_warm": _sample_solo_warm,
    "solo_white": _sample_solo_white,
    "duet_warm": _sample_duet_warm,
    "duet_white": _sample_duet_white,
    "duet_contrast": _sample_duet_contrast,
    "trio_warm_accent": _sample_trio_warm_accent,
}

# Sampling weights — solo stays common, duets are the interesting middle,
# trios are rare (the user specifically said: careful with three).
_BRANCH_WEIGHTS = {
    "solo_warm": 1.0,
    "solo_white": 1.0,
    "duet_warm": 1.5,
    "duet_white": 1.5,
    "duet_contrast": 2.0,
    "trio_warm_accent": 0.7,
}


def _pick_branch(rng: random.Random) -> str:
    names = list(_BRANCH_WEIGHTS.keys())
    weights = [_BRANCH_WEIGHTS[n] for n in names]
    return rng.choices(names, weights=weights, k=1)[0]


# ---------------------------------------------------------------------------
# Full parameter sampling
# ---------------------------------------------------------------------------


def random_params(rng: random.Random) -> AnimParams:
    branch = _pick_branch(rng)
    wall_composition = rng.choice(list(WALL_LAYOUTS.keys()))

    slit_cy = rng.uniform(-0.15, 0.15)
    slit_gap = rng.uniform(0.07, 0.13)
    wall_thickness = rng.uniform(0.03, 0.06)

    # prism in the big chamber; its distance-from-wall range is explicit per layout
    prism_offset_along = rng.uniform(0.55, 1.15)
    prism_y = slit_cy + rng.uniform(-0.08, 0.08)
    prism_size = rng.uniform(0.16, 0.28)
    prism_rotation_speed = rng.uniform(-math.pi, math.pi) * 0.6
    prism_glass_idx = rng.randint(0, 1)

    lights = _BRANCH_LIGHT_SAMPLERS[branch](rng)

    # Exposure range: brighter baseline than the original single-light pass.
    # Duets and trios bring more total energy so we dial exposure back a touch.
    base_exp = -4.5 if len(lights) == 1 else (-4.7 if len(lights) == 2 else -4.9)
    look_exposure = base_exp + rng.uniform(-0.25, 0.15)

    return AnimParams(
        wall_composition=wall_composition,
        slit_cy=slit_cy,
        slit_gap=slit_gap,
        wall_thickness=wall_thickness,
        prism_offset_along=prism_offset_along,
        prism_y=prism_y,
        prism_size=prism_size,
        prism_rotation_speed=prism_rotation_speed,
        prism_glass_idx=prism_glass_idx,
        lights=lights,
        branch=branch,
        look_exposure=look_exposure,
    )


# ---------------------------------------------------------------------------
# Probe check
# ---------------------------------------------------------------------------

PROBE_FPS = 4
PROBE_W, PROBE_H = 640, 360

# Brighter baseline, but still readable: require some chamber to remain
# darker than the shaft so the composition stays architectural.
GATE_MEAN_LUMA = (0.10, 0.42)
GATE_CLIPPED_MAX = 0.08
GATE_NEAR_BLACK_MAX = 0.75
GATE_IDR_MIN = 40.0 / 255.0
# In warm-only scenes colorfulness is high; in white-dominant scenes the
# spectrum paints thin slivers so we keep the floor low.
GATE_COLORFULNESS_MIN_WARM_DOMINANT = 0.10
GATE_COLORFULNESS_MIN_OTHER = 0.010
GATE_MIN_PASSING_FRAMES_FRAC = 0.35


def _is_warm_dominant(p: AnimParams) -> bool:
    warm = sum(1 for L in p.lights if L.color == "warm")
    return warm / max(1, len(p.lights)) >= 0.5


def make_probe_shot() -> Shot:
    shot = Shot.preset("draft", width=PROBE_W, height=PROBE_H, rays=300_000, depth=10)
    shot.camera = CAMERA
    shot.look = shot.look.with_overrides(
        exposure=-4.6,
        gamma=2.0,
        tonemap="reinhardx",
        white_point=0.5,
        normalize="rays",
        temperature=0.0,
    )
    return shot


def check_beauty(p: AnimParams) -> tuple[bool, dict]:
    animate = build_animate(p)
    shot = make_probe_shot()
    timeline = Timeline(DURATION, fps=PROBE_FPS)
    session = RenderSession(PROBE_W, PROBE_H, False)

    color_min = (
        GATE_COLORFULNESS_MIN_WARM_DOMINANT if _is_warm_dominant(p) else GATE_COLORFULNESS_MIN_OTHER
    )

    n_frames = timeline.total_frames
    passes = 0
    agg = {"mean_luma": [], "clipped": [], "near_black": [], "idr": [], "color": []}

    for fi in range(n_frames):
        ctx = timeline.context_at(fi)
        result = animate(ctx)
        cpp_shot = _resolve_frame_shot(shot, result, None)
        render_result = session.render_shot(cpp_shot, fi, True)
        st = render_result.analysis.image
        agg["mean_luma"].append(st.mean_luma)
        agg["clipped"].append(st.clipped_channel_fraction)
        agg["near_black"].append(st.near_black_fraction)
        agg["idr"].append(st.interdecile_luma_range)
        agg["color"].append(st.colorfulness)

        ok = (
            GATE_MEAN_LUMA[0] <= st.mean_luma <= GATE_MEAN_LUMA[1]
            and st.clipped_channel_fraction <= GATE_CLIPPED_MAX
            and st.near_black_fraction <= GATE_NEAR_BLACK_MAX
            and st.interdecile_luma_range >= GATE_IDR_MIN
            and st.colorfulness >= color_min
        )
        if ok:
            passes += 1

    def avg(k: str) -> float:
        return sum(agg[k]) / max(1, len(agg[k]))

    summary = {k: avg(k) for k in agg}
    summary["passing_frames"] = passes
    summary["total_frames"] = n_frames
    ok = passes >= int(GATE_MIN_PASSING_FRAMES_FRAC * n_frames)
    return ok, summary


# ---------------------------------------------------------------------------
# Preview render
# ---------------------------------------------------------------------------


def make_preview_shot(width: int, height: int, rays: int) -> Shot:
    shot = Shot.preset("preview", width=width, height=height, rays=rays, depth=10)
    shot.camera = CAMERA
    shot.look = shot.look.with_overrides(
        exposure=-4.6,
        gamma=2.0,
        tonemap="reinhardx",
        white_point=0.5,
        normalize="rays",
        temperature=0.0,
    )
    return shot


def _params_to_dict(p: AnimParams) -> dict:
    return asdict(p)


def render_and_save(
    p: AnimParams,
    out_dir: Path,
    *,
    width: int,
    height: int,
    rays: int,
    fps: int,
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "params.json").write_text(json.dumps(_params_to_dict(p), indent=2))

    animate = build_animate(p)
    settings = make_preview_shot(width, height, rays)
    timeline = Timeline(DURATION, fps=fps)
    video_path = out_dir / "video.mp4"
    render(animate, timeline, str(video_path), settings=settings, crf=18)
    print(f"  video  -> {video_path}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

MAX_ATTEMPTS = 250


def main() -> None:
    seed = (
        int(time.time())
        if "--seed" not in sys.argv
        else int(sys.argv[sys.argv.index("--seed") + 1])
    )
    target_count = int(sys.argv[sys.argv.index("-n") + 1]) if "-n" in sys.argv else 3
    hq = "--hq" in sys.argv
    width = 1280 if hq else 640
    height = 720 if hq else 360
    rays = 3_000_000 if hq else 800_000
    fps = 30
    rng = random.Random(seed)
    print(f"seed={seed} target={target_count} hq={hq}")

    base_dir = Path("renders/families/cathedral_aperture")
    found = 0

    for attempt in range(1, MAX_ATTEMPTS + 1):
        p = random_params(rng)
        print(
            f"[{attempt}] branch={p.branch} wall={p.wall_composition} "
            f"n_lights={len(p.lights)} prism_d={p.prism_offset_along:.2f} "
            f"exp={p.look_exposure:.2f} — checking...",
            flush=True,
        )
        ok, summary = check_beauty(p)
        print(
            f"  passes={summary['passing_frames']}/{summary['total_frames']} "
            f"mean_luma={summary['mean_luma']:.3f} color={summary['color']:.3f} "
            f"idr={summary['idr']:.3f} near_black={summary['near_black']:.2f} "
            f"clipped={summary['clipped']:.3f}",
            flush=True,
        )
        if not ok:
            continue

        found += 1
        tag = f"{found:03d}_{p.branch}_{p.wall_composition.replace('golden_small_','')}"
        out_dir = base_dir / tag
        print(f"  FOUND #{found} — rendering...")
        render_and_save(p, out_dir, width=width, height=height, rays=rays, fps=fps)
        print("  done.\n")
        if found >= target_count:
            break

    if found == 0:
        print(f"No valid animation found in {MAX_ATTEMPTS} attempts.")


if __name__ == "__main__":
    main()
