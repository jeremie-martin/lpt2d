"""Double-Slit Dispersion — a barrier with two slits, each exit beam through a tinted wedge.

A thick metallic barrier has two horizontal openings at different heights. A
projector behind the barrier floods it; two narrow shafts of light escape
through the slits. Each shaft then passes through its own tinted glass wedge,
so the upper and lower shafts are differently coloured by the time they
reach the far wall. The two tinted stripes cross on the opposite side of
the chamber.

Branches (explicit per-branch params):

- solo_white      : one full-spectrum projector
- solo_warm       : one orange projector (extra warm with warm wedge tints)
- duet_contrast   : warm + white projectors entering behind the barrier

Barrier composition:

- slit_left  : barrier on the left, wedges and projection toward the right
- slit_right : medieval inversion
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

WALL = Material(metallic=1.0, roughness=0.1, transmission=0.0, cauchy_b=0.0, albedo=1.0)
CAMERA = Camera2D(center=[0, 0], width=3.2)
DURATION = 6.0
CHAMBER_HW, CHAMBER_HH = 1.6, 0.9

WALL_ID = "wall"
WEDGE_TOP_ID = "wedge_top"
WEDGE_BOT_ID = "wedge_bot"

SLIT_LAYOUTS = {"slit_left": +1, "slit_right": -1}


@dataclass
class LightDef:
    offset_perp: float
    offset_along: float
    angle_drift_rate: float
    base_angle_offset: float
    spread: float
    source: str
    source_radius: float
    intensity: float
    color: str


@dataclass
class AnimParams:
    slit_composition: str
    barrier_x_abs: float
    barrier_thickness: float
    slit_separation: float    # center-to-center distance between the two slits
    slit_gap: float
    slit_cy_shift: float      # vertical shift of both slits together
    wedge_top_color: tuple[float, float, float]
    wedge_bot_color: tuple[float, float, float]
    wedge_fill: float
    wedge_ior: float
    wedge_cauchy_b: float
    wedge_size: float
    wedge_offset: float       # distance from barrier where wedges sit
    wedge_rotation_speed: float
    lights: list[LightDef] = field(default_factory=list)
    branch: str = "solo_white"
    look_exposure: float = -4.55


def _slit_sign(p) -> int:
    return SLIT_LAYOUTS[p.slit_composition]


def _barrier_x(p) -> float:
    return -_slit_sign(p) * p.barrier_x_abs


def _slit_y_centers(p) -> tuple[float, float]:
    c = p.slit_cy_shift
    return (c + p.slit_separation / 2, c - p.slit_separation / 2)


def _barrier_shapes(p):
    cx = _barrier_x(p)
    cy_top, cy_bot = _slit_y_centers(p)
    hg = p.slit_gap / 2
    segs = []
    # Top of chamber → top of upper slit
    if CHAMBER_HH > cy_top + hg:
        segs.append(thick_segment((cx, CHAMBER_HH), (cx, cy_top + hg),
                                   p.barrier_thickness, WALL_ID, id_prefix="barrier_top"))
    # Between the two slits
    if cy_top - hg > cy_bot + hg:
        segs.append(thick_segment((cx, cy_top - hg), (cx, cy_bot + hg),
                                   p.barrier_thickness, WALL_ID, id_prefix="barrier_mid"))
    # Bottom of lower slit → bottom of chamber
    if cy_bot - hg > -CHAMBER_HH:
        segs.append(thick_segment((cx, cy_bot - hg), (cx, -CHAMBER_HH),
                                   p.barrier_thickness, WALL_ID, id_prefix="barrier_bot"))
    return segs


def _wedge_shapes(p, rotation: float):
    sign = _slit_sign(p)
    cx = _barrier_x(p)
    wx = cx + sign * p.wedge_offset
    cy_top, cy_bot = _slit_y_centers(p)
    return [
        prism(
            center=(wx, cy_top),
            size=p.wedge_size,
            material_id=WEDGE_TOP_ID,
            rotation=rotation,
            id_prefix="wedge_top",
        ),
        prism(
            center=(wx, cy_bot),
            size=p.wedge_size,
            material_id=WEDGE_BOT_ID,
            rotation=-rotation,
            id_prefix="wedge_bot",
        ),
    ]


def _spectrum_for(color):
    if color == "warm":
        return LightSpectrum.range(wavelength_min=580, wavelength_max=650)
    if color == "white":
        return LightSpectrum.range(wavelength_min=380, wavelength_max=780)
    raise ValueError(color)


def _projectors(p, progress):
    sign = _slit_sign(p)
    cx = _barrier_x(p)
    out = []
    for i, L in enumerate(p.lights):
        lx = cx - sign * L.offset_along
        ly = p.slit_cy_shift + L.offset_perp
        aim_dx = cx - lx
        aim_dy = 0.0 - ly
        base = math.atan2(aim_dy, aim_dx)
        drift = L.angle_drift_rate * (progress - 0.5)
        a = base + L.base_angle_offset + drift
        out.append(ProjectorLight(
            id=f"beam_{i}",
            position=[lx, ly],
            direction=[math.cos(a), math.sin(a)],
            source_radius=L.source_radius,
            spread=L.spread,
            source=L.source,
            intensity=L.intensity,
            spectrum=_spectrum_for(L.color),
        ))
    return out


def build_animate(p):
    mats = {
        WALL_ID: WALL,
        WEDGE_TOP_ID: glass(ior=p.wedge_ior, cauchy_b=p.wedge_cauchy_b,
                             color=p.wedge_top_color, fill=p.wedge_fill),
        WEDGE_BOT_ID: glass(ior=p.wedge_ior, cauchy_b=p.wedge_cauchy_b,
                             color=p.wedge_bot_color, fill=p.wedge_fill),
    }

    def animate(ctx):
        progress = ctx.progress if ctx.total_frames > 1 else 0.5
        t = ctx.time
        rot = p.wedge_rotation_speed * t / DURATION
        scene = Scene(
            materials=mats,
            shapes=[
                *mirror_box(CHAMBER_HW, CHAMBER_HH, WALL_ID, id_prefix="chamber"),
                *_barrier_shapes(p),
                *_wedge_shapes(p, rot),
            ],
            lights=_projectors(p, progress),
        )
        warm_frac = sum(1 for L in p.lights if L.color == "warm") / max(1, len(p.lights))
        look = Look(exposure=p.look_exposure, gamma=2.0, tonemap="reinhardx",
                    white_point=0.5, normalize="rays", temperature=0.25 * warm_frac)
        return Frame(scene=scene, look=look)

    return animate


def _sample_light(rng, *, color, intensity):
    return LightDef(
        offset_perp=rng.uniform(-0.05, 0.05),
        offset_along=rng.uniform(0.20, 0.40),
        angle_drift_rate=rng.uniform(-0.10, 0.10),
        base_angle_offset=rng.uniform(-0.03, 0.03),
        spread=rng.uniform(0.12, 0.20),
        source=rng.choice(["ball", "line"]),
        source_radius=rng.uniform(0.010, 0.025),
        intensity=intensity,
        color=color,
    )


def _sample_solo_white(rng): return [_sample_light(rng, color="white", intensity=rng.uniform(0.55, 0.85))]
def _sample_solo_warm(rng): return [_sample_light(rng, color="warm", intensity=rng.uniform(0.20, 0.34))]


def _sample_duet_contrast(rng):
    w = _sample_light(rng, color="warm", intensity=rng.uniform(0.14, 0.20))
    wh = _sample_light(rng, color="white", intensity=rng.uniform(0.40, 0.56))
    w.offset_perp = rng.uniform(-0.05, -0.01)
    wh.offset_perp = rng.uniform(0.01, 0.05)
    return [w, wh]


_BRANCH_SAMPLERS = {"solo_white": _sample_solo_white, "solo_warm": _sample_solo_warm, "duet_contrast": _sample_duet_contrast}
_BRANCH_WEIGHTS = {"solo_white": 1.5, "solo_warm": 1.0, "duet_contrast": 1.3}


def _pick_branch(rng):
    names = list(_BRANCH_WEIGHTS.keys())
    return rng.choices(names, weights=[_BRANCH_WEIGHTS[n] for n in names], k=1)[0]


def random_params(rng):
    branch = _pick_branch(rng)
    slit = rng.choice(list(SLIT_LAYOUTS.keys()))
    barrier_x_abs = rng.uniform(0.50, 0.80)
    barrier_thickness = rng.uniform(0.03, 0.06)
    slit_separation = rng.uniform(0.28, 0.50)
    slit_gap = rng.uniform(0.06, 0.10)
    slit_cy_shift = rng.uniform(-0.10, 0.10)
    wedge_top_color = rng.choice([(1.0, 0.6, 0.3), (1.0, 0.4, 0.2), (1.0, 0.9, 0.4)])
    wedge_bot_color = rng.choice([(0.4, 0.6, 1.0), (0.5, 0.9, 1.0), (0.6, 0.4, 1.0)])
    wedge_fill = rng.uniform(0.10, 0.18)
    wedge_ior = rng.uniform(1.50, 1.60)
    wedge_cauchy_b = rng.uniform(5_000.0, 18_000.0)
    wedge_size = rng.uniform(0.08, 0.14)
    wedge_offset = rng.uniform(0.22, 0.38)
    wedge_rotation_speed = rng.uniform(-math.pi, math.pi) * 0.4
    lights = _BRANCH_SAMPLERS[branch](rng)
    base_exp = -4.5 if len(lights) == 1 else -4.72
    look_exposure = base_exp + rng.uniform(-0.20, 0.15)
    return AnimParams(
        slit_composition=slit, barrier_x_abs=barrier_x_abs,
        barrier_thickness=barrier_thickness, slit_separation=slit_separation,
        slit_gap=slit_gap, slit_cy_shift=slit_cy_shift,
        wedge_top_color=wedge_top_color, wedge_bot_color=wedge_bot_color,
        wedge_fill=wedge_fill, wedge_ior=wedge_ior, wedge_cauchy_b=wedge_cauchy_b,
        wedge_size=wedge_size, wedge_offset=wedge_offset,
        wedge_rotation_speed=wedge_rotation_speed,
        lights=lights, branch=branch, look_exposure=look_exposure,
    )


PROBE_FPS = 4
PROBE_W, PROBE_H = 640, 360
GATE_MEAN_LUMA = (0.08, 0.42)
GATE_CLIPPED_MAX = 0.10
GATE_NEAR_BLACK_MAX = 0.80
GATE_IDR_MIN = 40.0 / 255.0
GATE_COLORFULNESS_MIN_WARM_DOMINANT = 0.10
GATE_COLORFULNESS_MIN_OTHER = 0.04
GATE_MIN_PASSING_FRAMES_FRAC = 0.25


def _is_warm_dominant(p):
    warm = sum(1 for L in p.lights if L.color == "warm")
    return warm / max(1, len(p.lights)) >= 0.5


def make_probe_shot():
    shot = Shot.preset("draft", width=PROBE_W, height=PROBE_H, rays=300_000, depth=10)
    shot.camera = CAMERA
    shot.look = shot.look.with_overrides(exposure=-4.6, gamma=2.0, tonemap="reinhardx",
                                          white_point=0.5, normalize="rays", temperature=0.0)
    return shot


def check_beauty(p):
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
        rr = session.render_shot(cpp_shot, fi, True)
        st = rr.analysis.image
        for k, v in [("mean_luma", st.mean_luma), ("clipped", st.clipped_channel_fraction),
                     ("near_black", st.near_black_fraction), ("idr", st.interdecile_luma_range),
                     ("color", st.colorfulness)]:
            agg[k].append(v)
        if (GATE_MEAN_LUMA[0] <= st.mean_luma <= GATE_MEAN_LUMA[1]
                and st.clipped_channel_fraction <= GATE_CLIPPED_MAX
                and st.near_black_fraction <= GATE_NEAR_BLACK_MAX
                and st.interdecile_luma_range >= GATE_IDR_MIN
                and st.colorfulness >= color_min):
            passes += 1
    def avg(k): return sum(agg[k]) / max(1, len(agg[k]))
    s = {k: avg(k) for k in agg}
    s["passing_frames"] = passes; s["total_frames"] = n_frames
    return passes >= int(GATE_MIN_PASSING_FRAMES_FRAC * n_frames), s


def make_preview_shot(width, height, rays):
    shot = Shot.preset("preview", width=width, height=height, rays=rays, depth=10)
    shot.camera = CAMERA
    shot.look = shot.look.with_overrides(exposure=-4.6, gamma=2.0, tonemap="reinhardx",
                                          white_point=0.5, normalize="rays", temperature=0.0)
    return shot


def _params_to_dict(p): return asdict(p)


def render_and_save(p, out_dir, *, width, height, rays, fps):
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "params.json").write_text(json.dumps(_params_to_dict(p), indent=2))
    animate = build_animate(p)
    settings = make_preview_shot(width, height, rays)
    timeline = Timeline(DURATION, fps=fps)
    video_path = out_dir / "video.mp4"
    render(animate, timeline, str(video_path), settings=settings, crf=18)
    print(f"  video  -> {video_path}")


MAX_ATTEMPTS = 250


def main():
    seed = int(time.time()) if "--seed" not in sys.argv else int(sys.argv[sys.argv.index("--seed") + 1])
    target_count = int(sys.argv[sys.argv.index("-n") + 1]) if "-n" in sys.argv else 3
    hq = "--hq" in sys.argv
    width, height, rays = (1280, 720, 3_000_000) if hq else (640, 360, 800_000)
    fps = 30
    rng = random.Random(seed)
    print(f"seed={seed} target={target_count} hq={hq}")
    base_dir = Path("renders/families/double_slit_dispersion")
    found = 0
    for attempt in range(1, MAX_ATTEMPTS + 1):
        p = random_params(rng)
        print(f"[{attempt}] branch={p.branch} {p.slit_composition} sep={p.slit_separation:.2f} "
              f"exp={p.look_exposure:.2f} — checking...", flush=True)
        ok, s = check_beauty(p)
        print(f"  passes={s['passing_frames']}/{s['total_frames']} "
              f"mean_luma={s['mean_luma']:.3f} color={s['color']:.3f} "
              f"idr={s['idr']:.3f} near_black={s['near_black']:.2f} clipped={s['clipped']:.3f}",
              flush=True)
        if not ok:
            continue
        found += 1
        tag = f"{found:03d}_{p.branch}_{p.slit_composition.replace('slit_','')}"
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
