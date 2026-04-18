"""Parabolic Reflector — a concave metallic dish focuses a parallel beam onto a prism.

A parabolic mirror on one side of the chamber catches near-parallel rays from a
line-source projector on the opposite side. The rays converge at the geometric
focal point, where a glass prism intercepts the focused light and breaks it
into dispersion. The chamber walls are the same soft-edged mirror as the rest
of the family, so reflected and dispersed light bounces around legibly.

Branches (explicit per-branch parameters, never mixed within a scene):

- solo_white       : one full-spectrum projector, axis-aligned
- solo_warm        : one orange projector, axis-aligned
- duet_contrast    : warm + white projectors slightly angularly offset,
                     producing two near-coincident focal spots

Dish composition (explicit per-scene, analogous to Cathedral Aperture's wall
layout):

- dish_left  : parabola on the left, opening to the right, projector on the right
- dish_right : medieval inversion — parabola on the right, opening to the left

Intent sentence (hero moment):
    A bright converging cone arrives at the focal point, the prism shatters it
    into a visible spectrum, the dish itself glows with the reflected beam, and
    the chamber reads architectural rather than flooded.
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
    function_curve,
    glass,
    mirror_box,
    prism,
    render,
)
from anim.renderer import RenderSession, _resolve_frame_shot

# ---------------------------------------------------------------------------
# Scene constants (shared with Cathedral Aperture)
# ---------------------------------------------------------------------------

WALL = Material(metallic=1.0, roughness=0.1, transmission=0.0, cauchy_b=0.0, albedo=1.0)
CAMERA = Camera2D(center=[0, 0], width=3.2)
DURATION = 6.0
CHAMBER_HW, CHAMBER_HH = 1.6, 0.9

WALL_ID = "wall"
DISH_ID = "dish"

PRISM_GLASSES = [
    glass(1.52, cauchy_b=28_000, color=(0.97, 0.97, 0.97), fill=0.10),
    glass(1.60, cauchy_b=35_000, color=(0.95, 0.96, 1.0), fill=0.10),
]
PRISM_IDS = ["prism_a", "prism_b"]

MATERIALS = {
    WALL_ID: WALL,
    DISH_ID: WALL,  # dish shares the wall mirror material
    PRISM_IDS[0]: PRISM_GLASSES[0],
    PRISM_IDS[1]: PRISM_GLASSES[1],
}

# Dish orientation: +1 opens right (dish on left), -1 opens left (dish on right)
DISH_LAYOUTS: dict[str, int] = {
    "dish_left": +1,
    "dish_right": -1,
}


# ---------------------------------------------------------------------------
# Parameter space
# ---------------------------------------------------------------------------


@dataclass
class LightDef:
    offset_perp: float
    offset_along: float   # distance from focal point along axis, on the far side from dish
    angle_jitter: float   # radians, deviation from axis direction
    spread: float
    source_radius: float  # for source='line', this is the half-length of the line
    intensity: float
    color: str            # "warm" or "white"


@dataclass
class AnimParams:
    dish_composition: str          # key of DISH_LAYOUTS
    parabola_vertex_x_abs: float   # absolute x of the vertex (positive value)
    parabola_a: float              # coefficient in x = a*y^2 relative to vertex; larger = tighter focus
    parabola_aperture: float       # half-height of the dish rim
    prism_focal_offset: float      # small jitter off the focal point along the axis
    prism_y_jitter: float
    prism_size: float
    prism_rotation_speed: float
    prism_glass_idx: int
    lights: list[LightDef] = field(default_factory=list)
    branch: str = "solo_white"
    look_exposure: float = -4.6


# ---------------------------------------------------------------------------
# Geometry helpers
# ---------------------------------------------------------------------------


def _axis_sign(p: AnimParams) -> int:
    return DISH_LAYOUTS[p.dish_composition]


def _vertex_xy(p: AnimParams) -> tuple[float, float]:
    sign = _axis_sign(p)
    # dish_left: vertex on the left (x negative). dish_right: vertex on the right (x positive).
    return (-sign * p.parabola_vertex_x_abs, 0.0)


def _focal_xy(p: AnimParams) -> tuple[float, float]:
    """Geometric focal point: one focal length away from vertex along the axis."""
    vx, vy = _vertex_xy(p)
    sign = _axis_sign(p)
    focal_len = 1.0 / (4.0 * p.parabola_a)
    return (vx + sign * focal_len, vy)


def _prism_xy(p: AnimParams) -> tuple[float, float]:
    fx, fy = _focal_xy(p)
    sign = _axis_sign(p)
    return (fx + sign * p.prism_focal_offset, fy + p.prism_y_jitter)


def _dish_shapes(p: AnimParams) -> list:
    """Two path halves for the parabola; normals face into the cavity (toward the projector)."""
    vx, _ = _vertex_xy(p)
    sign = _axis_sign(p)
    a = p.parabola_a
    y_max = p.parabola_aperture
    # x at the rim, measured from vertex along the axis
    dx_rim = a * y_max * y_max
    x_rim = vx + sign * dx_rim

    # For a dish opening to the right (sign=+1), traverse:
    #   upper half from rim (top) inward to vertex — tangent points down-left — normal points INTO cavity (right-facing)
    #   lower half from vertex outward to rim (bottom) — tangent points down-right — normal points INTO cavity (right-facing)
    # For dish opening to the left (sign=-1), directions invert.

    def fn_upper(x: float, _vx: float = vx, _a: float = a, _sign: int = sign) -> float:
        return (max(0.0, _sign * (x - _vx)) / _a) ** 0.5

    def fn_lower(x: float, _vx: float = vx, _a: float = a, _sign: int = sign) -> float:
        return -((max(0.0, _sign * (x - _vx)) / _a) ** 0.5)

    if sign > 0:
        upper = function_curve(fn_upper, (x_rim, vx), DISH_ID, samples=48, id_prefix="dish_upper")
        lower = function_curve(fn_lower, (vx, x_rim), DISH_ID, samples=48, id_prefix="dish_lower")
    else:
        # Dish opens to the left: vertex is to the right of the rim.
        upper = function_curve(fn_upper, (x_rim, vx), DISH_ID, samples=48, id_prefix="dish_upper")
        lower = function_curve(fn_lower, (vx, x_rim), DISH_ID, samples=48, id_prefix="dish_lower")
    return [upper, lower]


def _spectrum_for(color: str) -> LightSpectrum:
    if color == "warm":
        return LightSpectrum.range(wavelength_min=580, wavelength_max=650)
    if color == "white":
        return LightSpectrum.range(wavelength_min=380, wavelength_max=780)
    raise ValueError(f"unknown light color {color!r}")


def _projectors(p: AnimParams) -> list[ProjectorLight]:
    """Line-source projectors on the far side of the focal point, aimed at the dish."""
    fx, fy = _focal_xy(p)
    vx, _ = _vertex_xy(p)
    sign = _axis_sign(p)
    # Projector position: start at focal point, go offset_along in the direction AWAY from the dish.
    out: list[ProjectorLight] = []
    for i, L in enumerate(p.lights):
        lx = fx + sign * L.offset_along
        ly = fy + L.offset_perp
        # Aim back toward the dish vertex with a small jitter
        aim_dx = vx - lx
        aim_dy = 0.0 - ly
        base_angle = math.atan2(aim_dy, aim_dx)
        a_rad = base_angle + L.angle_jitter
        out.append(
            ProjectorLight(
                id=f"beam_{i}",
                position=[lx, ly],
                direction=[math.cos(a_rad), math.sin(a_rad)],
                source_radius=L.source_radius,
                spread=L.spread,
                source="line",
                intensity=L.intensity,
                spectrum=_spectrum_for(L.color),
            )
        )
    return out


# ---------------------------------------------------------------------------
# Scene builder
# ---------------------------------------------------------------------------


def build_animate(p: AnimParams):
    def animate(ctx: FrameContext) -> Frame:
        t = ctx.time
        rot = p.prism_rotation_speed * t / DURATION
        px, py = _prism_xy(p)
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
                *_dish_shapes(p),
                prism_shape,
            ],
            lights=_projectors(p),
        )
        warm_count = sum(1 for L in p.lights if L.color == "warm")
        warm_frac = warm_count / max(1, len(p.lights))
        temp = 0.28 * warm_frac
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
# Per-branch light sampling (explicit per-branch inline ranges)
# ---------------------------------------------------------------------------


def _sample_line_light(
    rng: random.Random,
    *,
    color: str,
    offset_perp: float,
    offset_along: float,
    angle_jitter: float,
    aperture: float,
    intensity: float,
) -> LightDef:
    # Line source half-length stays slightly smaller than the dish aperture so
    # rays land on the mirror rather than splashing past it onto the chamber wall.
    line_half = aperture * rng.uniform(0.65, 0.85)
    return LightDef(
        offset_perp=offset_perp,
        offset_along=offset_along,
        angle_jitter=angle_jitter,
        spread=rng.uniform(0.012, 0.030),
        source_radius=line_half,
        intensity=intensity,
        color=color,
    )


def _sample_solo_white(rng: random.Random, aperture: float) -> list[LightDef]:
    return [_sample_line_light(
        rng,
        color="white",
        offset_perp=rng.uniform(-0.03, 0.03),
        offset_along=rng.uniform(0.80, 1.15),
        angle_jitter=rng.uniform(-0.005, 0.005),
        aperture=aperture,
        intensity=rng.uniform(0.35, 0.55),
    )]


def _sample_solo_warm(rng: random.Random, aperture: float) -> list[LightDef]:
    return [_sample_line_light(
        rng,
        color="warm",
        offset_perp=rng.uniform(-0.03, 0.03),
        offset_along=rng.uniform(0.80, 1.15),
        angle_jitter=rng.uniform(-0.005, 0.005),
        aperture=aperture,
        intensity=rng.uniform(0.12, 0.22),
    )]


def _sample_duet_contrast(rng: random.Random, aperture: float) -> list[LightDef]:
    # Warm + white with small angular offset. Two near-coincident focal spots.
    jit = rng.uniform(0.010, 0.020)
    warm_on_top = rng.random() < 0.5
    warm = _sample_line_light(
        rng,
        color="warm",
        offset_perp=rng.uniform(-0.02, 0.02),
        offset_along=rng.uniform(0.80, 1.10),
        angle_jitter=(-jit if warm_on_top else +jit),
        aperture=aperture,
        intensity=rng.uniform(0.10, 0.16),
    )
    white = _sample_line_light(
        rng,
        color="white",
        offset_perp=rng.uniform(-0.02, 0.02),
        offset_along=rng.uniform(0.80, 1.10),
        angle_jitter=(+jit if warm_on_top else -jit),
        aperture=aperture,
        intensity=rng.uniform(0.28, 0.45),
    )
    return [warm, white]


_BRANCH_SAMPLERS = {
    "solo_white": _sample_solo_white,
    "solo_warm": _sample_solo_warm,
    "duet_contrast": _sample_duet_contrast,
}

_BRANCH_WEIGHTS = {
    "solo_white": 1.0,
    "solo_warm": 1.0,
    "duet_contrast": 1.8,
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
    dish_composition = rng.choice(list(DISH_LAYOUTS.keys()))

    # Parabola shape. Larger a => tighter focus (shorter focal length).
    parabola_a = rng.uniform(0.40, 0.75)
    # Vertex a bit inside the wall so the rim can hang back without clipping.
    parabola_vertex_x_abs = rng.uniform(1.10, 1.40)
    parabola_aperture = rng.uniform(0.40, 0.62)

    prism_focal_offset = rng.uniform(-0.05, 0.05)
    prism_y_jitter = rng.uniform(-0.04, 0.04)
    prism_size = rng.uniform(0.12, 0.22)
    prism_rotation_speed = rng.uniform(-math.pi, math.pi) * 0.5
    prism_glass_idx = rng.randint(0, 1)

    lights = _BRANCH_SAMPLERS[branch](rng, parabola_aperture)

    base_exp = -4.5 if len(lights) == 1 else -4.75
    look_exposure = base_exp + rng.uniform(-0.25, 0.15)

    return AnimParams(
        dish_composition=dish_composition,
        parabola_vertex_x_abs=parabola_vertex_x_abs,
        parabola_a=parabola_a,
        parabola_aperture=parabola_aperture,
        prism_focal_offset=prism_focal_offset,
        prism_y_jitter=prism_y_jitter,
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

GATE_MEAN_LUMA = (0.10, 0.42)
GATE_CLIPPED_MAX = 0.10
GATE_NEAR_BLACK_MAX = 0.70
GATE_IDR_MIN = 40.0 / 255.0
GATE_COLORFULNESS_MIN_WARM_DOMINANT = 0.08
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
    target_count = int(sys.argv[sys.argv.index("-n") + 1]) if "-n" in sys.argv else 4
    hq = "--hq" in sys.argv
    width = 1280 if hq else 640
    height = 720 if hq else 360
    rays = 3_000_000 if hq else 800_000
    fps = 30
    rng = random.Random(seed)
    print(f"seed={seed} target={target_count} hq={hq}")

    base_dir = Path("renders/families/parabolic_reflector")
    found = 0

    for attempt in range(1, MAX_ATTEMPTS + 1):
        p = random_params(rng)
        fx, fy = _focal_xy(p)
        print(
            f"[{attempt}] branch={p.branch} dish={p.dish_composition} "
            f"n_lights={len(p.lights)} a={p.parabola_a:.2f} focal=({fx:.2f},{fy:.2f}) "
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
        tag = f"{found:03d}_{p.branch}_{p.dish_composition.replace('dish_','')}"
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
