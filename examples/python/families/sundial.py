"""Sundial — a projector rotates along an overhead arc, aimed at a pedestal prism.

A thick metallic arc spans the upper portion of the chamber like a sky ring. A
single projector travels along the arc, always aimed at a glass prism on a
pedestal below. As the projector sweeps, the refracted spectrum walks across
the opposite side of the chamber like the shadow on a sundial.

Branches (explicit per-branch parameters, never mixed within a scene):

- solo_warm      : one orange projector
- solo_white     : one full-spectrum projector
- duet_contrast  : warm + white projectors at opposite ends of the arc, moving
                   in opposite directions

Arc composition:

- ring_top    : arc at the top, prism pedestal below (standard sundial)
- ring_bottom : medieval inversion — arc below, prism up on a raised platform
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
    rectangle,
    render,
    thick_arc,
)
from anim.renderer import RenderSession, _resolve_frame_shot

# ---------------------------------------------------------------------------
# Scene constants (lifted verbatim from family anchors)
# ---------------------------------------------------------------------------

WALL = Material(metallic=1.0, roughness=0.1, transmission=0.0, cauchy_b=0.0, albedo=1.0)
CAMERA = Camera2D(center=[0, 0], width=3.2)
DURATION = 6.0
CHAMBER_HW, CHAMBER_HH = 1.6, 0.9

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

ARC_LAYOUTS: dict[str, int] = {
    "ring_top": +1,     # arc at top, prism below
    "ring_bottom": -1,  # medieval inversion
}


# ---------------------------------------------------------------------------
# Parameter space
# ---------------------------------------------------------------------------


@dataclass
class LightDef:
    # Fractional position along the arc: 0 = at angle_start, 1 = at angle_start + sweep.
    angle_t0: float
    angle_t1: float
    spread: float
    source: str
    source_radius: float
    intensity: float
    color: str   # "warm" or "white"


@dataclass
class AnimParams:
    arc_composition: str          # key of ARC_LAYOUTS
    arc_radius: float
    arc_thickness: float
    arc_angle_start: float        # radians (as if ring_top); flipped internally for ring_bottom
    arc_sweep: float              # radians (positive)
    pedestal_h: float             # pedestal height from chamber floor
    pedestal_w: float
    prism_size: float
    prism_rotation_speed: float
    prism_glass_idx: int
    lights: list[LightDef] = field(default_factory=list)
    branch: str = "solo_white"
    look_exposure: float = -4.6


# ---------------------------------------------------------------------------
# Geometry helpers
# ---------------------------------------------------------------------------


def _arc_sign(p: AnimParams) -> int:
    return ARC_LAYOUTS[p.arc_composition]


def _arc_center(p: AnimParams) -> tuple[float, float]:
    # Arc center sits just beyond the opposite wall so the arc hangs inside the chamber.
    sign = _arc_sign(p)
    return (0.0, -sign * (CHAMBER_HH - p.arc_radius * 0.35))


def _prism_xy(p: AnimParams) -> tuple[float, float]:
    sign = _arc_sign(p)
    return (0.0, sign * (-CHAMBER_HH + p.pedestal_h))


def _pedestal_shape(p: AnimParams):
    sign = _arc_sign(p)
    pedestal_cy = sign * (-CHAMBER_HH + p.pedestal_h / 2)
    return rectangle(
        center=(0.0, pedestal_cy),
        width=p.pedestal_w,
        height=p.pedestal_h,
        material_id=WALL_ID,
        id_prefix="pedestal",
    )


def _arc_shape(p: AnimParams):
    sign = _arc_sign(p)
    cx, cy = _arc_center(p)
    # For ring_top (sign=+1) the arc is a downward-facing bowl; for ring_bottom (sign=-1)
    # we flip the arc around the horizontal axis so it bowls up toward a raised prism.
    if sign > 0:
        angle_start = p.arc_angle_start
        sweep = p.arc_sweep
    else:
        angle_start = -p.arc_angle_start - p.arc_sweep
        sweep = p.arc_sweep
    return thick_arc(
        center=(cx, cy),
        radius=p.arc_radius,
        thickness=p.arc_thickness,
        angle_start=angle_start,
        sweep=sweep,
        material_id=WALL_ID,
        id_prefix="arc",
    )


def _spectrum_for(color: str) -> LightSpectrum:
    if color == "warm":
        return LightSpectrum.range(wavelength_min=580, wavelength_max=650)
    if color == "white":
        return LightSpectrum.range(wavelength_min=380, wavelength_max=780)
    raise ValueError(color)


def _projector_at(p: AnimParams, L: LightDef, progress: float) -> ProjectorLight:
    """Projector position walks along the arc from angle_t0 to angle_t1 over the animation."""
    sign = _arc_sign(p)
    cx, cy = _arc_center(p)

    t = max(0.0, min(1.0, progress))
    angle_frac = L.angle_t0 + (L.angle_t1 - L.angle_t0) * t

    if sign > 0:
        angle = p.arc_angle_start + p.arc_sweep * angle_frac
    else:
        angle = (-p.arc_angle_start - p.arc_sweep) + p.arc_sweep * angle_frac

    # Sit just inside the arc thickness so the light is "at" the arc.
    r = p.arc_radius - p.arc_thickness * 0.6
    lx = cx + r * math.cos(angle)
    ly = cy + r * math.sin(angle)

    px, py = _prism_xy(p)
    base_angle = math.atan2(py - ly, px - lx)
    return ProjectorLight(
        id=f"beam_{id(L) % 10_000}",
        position=[lx, ly],
        direction=[math.cos(base_angle), math.sin(base_angle)],
        source_radius=L.source_radius,
        spread=L.spread,
        source=L.source,
        intensity=L.intensity,
        spectrum=_spectrum_for(L.color),
    )


# ---------------------------------------------------------------------------
# Scene builder
# ---------------------------------------------------------------------------


def build_animate(p: AnimParams):
    def animate(ctx: FrameContext) -> Frame:
        t = ctx.time
        progress = ctx.progress if ctx.total_frames > 1 else 0.5
        rot = p.prism_rotation_speed * t / DURATION
        px, py = _prism_xy(p)
        prism_shape = prism(
            center=(px, py),
            size=p.prism_size,
            material_id=PRISM_IDS[p.prism_glass_idx % len(PRISM_IDS)],
            rotation=rot,
            id_prefix="prism",
        )
        lights = [_projector_at(p, L, progress) for L in p.lights]
        for i, pl in enumerate(lights):
            pl.id = f"beam_{i}"

        scene = Scene(
            materials=MATERIALS,
            shapes=[
                *mirror_box(CHAMBER_HW, CHAMBER_HH, WALL_ID, id_prefix="chamber"),
                *_arc_shape(p),
                _pedestal_shape(p),
                prism_shape,
            ],
            lights=lights,
        )
        warm_frac = sum(1 for L in p.lights if L.color == "warm") / max(1, len(p.lights))
        look = Look(
            exposure=p.look_exposure,
            gamma=2.0,
            tonemap="reinhardx",
            white_point=0.5,
            normalize="rays",
            temperature=0.28 * warm_frac,
        )
        return Frame(scene=scene, look=look)

    return animate


# ---------------------------------------------------------------------------
# Per-branch light sampling
# ---------------------------------------------------------------------------


def _sample_solo_warm(rng: random.Random) -> list[LightDef]:
    t0 = rng.uniform(0.0, 0.25)
    t1 = rng.uniform(0.75, 1.0)
    return [LightDef(
        angle_t0=t0, angle_t1=t1,
        spread=rng.uniform(0.05, 0.10),
        source=rng.choice(["ball", "line"]),
        source_radius=rng.uniform(0.008, 0.020),
        intensity=rng.uniform(0.20, 0.35),
        color="warm",
    )]


def _sample_solo_white(rng: random.Random) -> list[LightDef]:
    t0 = rng.uniform(0.0, 0.25)
    t1 = rng.uniform(0.75, 1.0)
    return [LightDef(
        angle_t0=t0, angle_t1=t1,
        spread=rng.uniform(0.05, 0.10),
        source=rng.choice(["ball", "line"]),
        source_radius=rng.uniform(0.008, 0.020),
        intensity=rng.uniform(0.55, 0.85),
        color="white",
    )]


def _sample_duet_contrast(rng: random.Random) -> list[LightDef]:
    # Warm and white travel toward each other along the arc.
    warm = LightDef(
        angle_t0=rng.uniform(0.0, 0.18),
        angle_t1=rng.uniform(0.82, 1.0),
        spread=rng.uniform(0.05, 0.09),
        source=rng.choice(["ball", "line"]),
        source_radius=rng.uniform(0.008, 0.018),
        intensity=rng.uniform(0.13, 0.20),
        color="warm",
    )
    white = LightDef(
        angle_t0=rng.uniform(0.82, 1.0),
        angle_t1=rng.uniform(0.0, 0.18),
        spread=rng.uniform(0.05, 0.09),
        source=rng.choice(["ball", "line"]),
        source_radius=rng.uniform(0.008, 0.018),
        intensity=rng.uniform(0.40, 0.60),
        color="white",
    )
    return [warm, white]


_BRANCH_SAMPLERS = {
    "solo_warm": _sample_solo_warm,
    "solo_white": _sample_solo_white,
    "duet_contrast": _sample_duet_contrast,
}

_BRANCH_WEIGHTS = {
    "solo_warm": 1.0,
    "solo_white": 1.0,
    "duet_contrast": 1.6,
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
    arc_composition = rng.choice(list(ARC_LAYOUTS.keys()))

    arc_radius = rng.uniform(1.05, 1.25)
    arc_thickness = rng.uniform(0.025, 0.05)
    arc_angle_start = rng.uniform(math.pi / 8, math.pi / 5)
    arc_sweep = rng.uniform(math.pi * 0.6, math.pi * 0.85)

    pedestal_h = rng.uniform(0.18, 0.32)
    pedestal_w = rng.uniform(0.20, 0.32)

    prism_size = rng.uniform(0.13, 0.22)
    prism_rotation_speed = rng.uniform(-math.pi, math.pi) * 0.4
    prism_glass_idx = rng.randint(0, 1)

    lights = _BRANCH_SAMPLERS[branch](rng)

    base_exp = -4.55 if len(lights) == 1 else -4.75
    look_exposure = base_exp + rng.uniform(-0.20, 0.15)

    return AnimParams(
        arc_composition=arc_composition,
        arc_radius=arc_radius,
        arc_thickness=arc_thickness,
        arc_angle_start=arc_angle_start,
        arc_sweep=arc_sweep,
        pedestal_h=pedestal_h,
        pedestal_w=pedestal_w,
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
GATE_CLIPPED_MAX = 0.09
GATE_NEAR_BLACK_MAX = 0.75
GATE_IDR_MIN = 40.0 / 255.0
GATE_COLORFULNESS_MIN_WARM_DOMINANT = 0.08
GATE_COLORFULNESS_MIN_OTHER = 0.010
GATE_MIN_PASSING_FRAMES_FRAC = 0.30


def _is_warm_dominant(p: AnimParams) -> bool:
    warm = sum(1 for L in p.lights if L.color == "warm")
    return warm / max(1, len(p.lights)) >= 0.5


def make_probe_shot() -> Shot:
    shot = Shot.preset("draft", width=PROBE_W, height=PROBE_H, rays=300_000, depth=10)
    shot.camera = CAMERA
    shot.look = shot.look.with_overrides(
        exposure=-4.6, gamma=2.0, tonemap="reinhardx",
        white_point=0.5, normalize="rays", temperature=0.0,
    )
    return shot


def check_beauty(p: AnimParams) -> tuple[bool, dict]:
    animate = build_animate(p)
    shot = make_probe_shot()
    timeline = Timeline(DURATION, fps=PROBE_FPS)
    session = RenderSession(PROBE_W, PROBE_H, False)

    color_min = GATE_COLORFULNESS_MIN_WARM_DOMINANT if _is_warm_dominant(p) else GATE_COLORFULNESS_MIN_OTHER
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
# Render
# ---------------------------------------------------------------------------


def make_preview_shot(width: int, height: int, rays: int) -> Shot:
    shot = Shot.preset("preview", width=width, height=height, rays=rays, depth=10)
    shot.camera = CAMERA
    shot.look = shot.look.with_overrides(
        exposure=-4.6, gamma=2.0, tonemap="reinhardx",
        white_point=0.5, normalize="rays", temperature=0.0,
    )
    return shot


def _params_to_dict(p: AnimParams) -> dict:
    return asdict(p)


def render_and_save(p: AnimParams, out_dir: Path, *, width: int, height: int, rays: int, fps: int) -> None:
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
    seed = int(time.time()) if "--seed" not in sys.argv else int(sys.argv[sys.argv.index("--seed") + 1])
    target_count = int(sys.argv[sys.argv.index("-n") + 1]) if "-n" in sys.argv else 3
    hq = "--hq" in sys.argv
    width = 1280 if hq else 640
    height = 720 if hq else 360
    rays = 3_000_000 if hq else 800_000
    fps = 30
    rng = random.Random(seed)
    print(f"seed={seed} target={target_count} hq={hq}")

    base_dir = Path("renders/families/sundial")
    found = 0

    for attempt in range(1, MAX_ATTEMPTS + 1):
        p = random_params(rng)
        print(f"[{attempt}] branch={p.branch} arc={p.arc_composition} n={len(p.lights)} "
              f"r={p.arc_radius:.2f} exp={p.look_exposure:.2f} — checking...", flush=True)
        ok, summary = check_beauty(p)
        print(f"  passes={summary['passing_frames']}/{summary['total_frames']} "
              f"mean_luma={summary['mean_luma']:.3f} color={summary['color']:.3f} "
              f"idr={summary['idr']:.3f} near_black={summary['near_black']:.2f} "
              f"clipped={summary['clipped']:.3f}", flush=True)
        if not ok:
            continue
        found += 1
        tag = f"{found:03d}_{p.branch}_{p.arc_composition.replace('ring_','')}"
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
