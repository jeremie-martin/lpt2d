"""Veil — a wide thin glass arc acting as a curtain.

A gently curved glass arc spans the chamber like a diaphanous curtain. A
projector behind it shines through; the arc's varying curvature refracts the
beam differently at different heights, painting caustic ripples on the
opposite wall. The beam angle drifts slowly, so the caustics walk and warp
through the animation.

Branches (explicit per-branch params):

- solo_white      : one full-spectrum projector
- solo_warm       : one orange projector
- duet_contrast   : warm + white at slightly different angles, doubled ripples

Veil composition:

- veil_on_right : veil curves on the right, projector from the left
- veil_on_left  : medieval inversion
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
    render,
    thick_arc,
)
from anim.renderer import RenderSession, _resolve_frame_shot

WALL = Material(metallic=1.0, roughness=0.1, transmission=0.0, cauchy_b=0.0, albedo=1.0)
CAMERA = Camera2D(center=[0, 0], width=3.2)
DURATION = 6.0
CHAMBER_HW, CHAMBER_HH = 1.6, 0.9

WALL_ID = "wall"
VEIL_ID = "veil_glass"

VEIL_LAYOUTS = {"veil_on_right": +1, "veil_on_left": -1}


@dataclass
class LightDef:
    offset_perp: float        # vertical offset of projector
    offset_along: float       # distance from veil, on the far side
    angle_drift_rate: float
    base_angle_offset: float
    spread: float
    source: str
    source_radius: float
    intensity: float
    color: str


@dataclass
class AnimParams:
    veil_composition: str
    veil_radius: float        # large so curvature is shallow
    veil_thickness: float
    veil_sweep: float         # radians
    veil_cx_offset: float     # how far beyond the chamber edge the arc center sits
    veil_ior: float
    veil_cauchy_b: float
    veil_fill: float
    lights: list[LightDef] = field(default_factory=list)
    branch: str = "solo_white"
    look_exposure: float = -4.55


def _veil_sign(p: AnimParams) -> int:
    return VEIL_LAYOUTS[p.veil_composition]


def _veil_center(p: AnimParams) -> tuple[float, float]:
    sign = _veil_sign(p)
    # Arc center is OUTSIDE the chamber on the veil side.
    return (sign * (CHAMBER_HW + p.veil_cx_offset), 0.0)


def _veil_shape(p: AnimParams):
    sign = _veil_sign(p)
    cx, cy = _veil_center(p)
    # For veil_on_right (sign=+1), the arc opens to the left (toward the chamber),
    # so angle_start is centered around pi and spans the vertical range.
    if sign > 0:
        angle_start = math.pi - p.veil_sweep / 2
    else:
        angle_start = -p.veil_sweep / 2
    return thick_arc(
        center=(cx, cy),
        radius=p.veil_radius,
        thickness=p.veil_thickness,
        angle_start=angle_start,
        sweep=p.veil_sweep,
        material_id=VEIL_ID,
        id_prefix="veil",
    )


def _spectrum_for(color: str) -> LightSpectrum:
    if color == "warm":
        return LightSpectrum.range(wavelength_min=580, wavelength_max=650)
    if color == "white":
        return LightSpectrum.range(wavelength_min=380, wavelength_max=780)
    raise ValueError(color)


def _projectors(p: AnimParams, progress: float) -> list[ProjectorLight]:
    sign = _veil_sign(p)
    # Projectors on the far side of the chamber from the veil.
    out = []
    for i, L in enumerate(p.lights):
        lx = -sign * (CHAMBER_HW - L.offset_along)
        ly = L.offset_perp
        # Aim toward the veil center, offset by jitter and drift.
        aim_dx = sign * CHAMBER_HW - lx  # aim at the far side where the veil sits
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


def build_animate(p: AnimParams):
    mats = {
        WALL_ID: WALL,
        VEIL_ID: glass(ior=p.veil_ior, cauchy_b=p.veil_cauchy_b,
                       color=(0.97, 0.97, 0.98), fill=p.veil_fill),
    }

    def animate(ctx: FrameContext) -> Frame:
        progress = ctx.progress if ctx.total_frames > 1 else 0.5
        scene = Scene(
            materials=mats,
            shapes=[
                *mirror_box(CHAMBER_HW, CHAMBER_HH, WALL_ID, id_prefix="chamber"),
                *_veil_shape(p),
            ],
            lights=_projectors(p, progress),
        )
        warm_frac = sum(1 for L in p.lights if L.color == "warm") / max(1, len(p.lights))
        look = Look(exposure=p.look_exposure, gamma=2.0, tonemap="reinhardx",
                    white_point=0.5, normalize="rays", temperature=0.25 * warm_frac)
        return Frame(scene=scene, look=look)

    return animate


def _sample_light(rng: random.Random, *, color: str, intensity: float) -> LightDef:
    return LightDef(
        offset_perp=rng.uniform(-0.18, 0.18),
        offset_along=rng.uniform(0.15, 0.35),
        angle_drift_rate=rng.uniform(-0.20, 0.20),
        base_angle_offset=rng.uniform(-0.08, 0.08),
        spread=rng.uniform(0.08, 0.14),
        source=rng.choice(["ball", "line"]),
        source_radius=rng.uniform(0.010, 0.025),
        intensity=intensity,
        color=color,
    )


def _sample_solo_white(rng): return [_sample_light(rng, color="white", intensity=rng.uniform(0.55, 0.85))]
def _sample_solo_warm(rng): return [_sample_light(rng, color="warm", intensity=rng.uniform(0.18, 0.32))]


def _sample_duet_contrast(rng):
    w = _sample_light(rng, color="warm", intensity=rng.uniform(0.12, 0.19))
    w.base_angle_offset = rng.uniform(-0.10, -0.03)
    wh = _sample_light(rng, color="white", intensity=rng.uniform(0.38, 0.55))
    wh.base_angle_offset = rng.uniform(0.03, 0.10)
    return [w, wh]


_BRANCH_SAMPLERS = {"solo_white": _sample_solo_white, "solo_warm": _sample_solo_warm, "duet_contrast": _sample_duet_contrast}
_BRANCH_WEIGHTS = {"solo_white": 1.3, "solo_warm": 1.0, "duet_contrast": 1.4}


def _pick_branch(rng):
    names = list(_BRANCH_WEIGHTS.keys())
    return rng.choices(names, weights=[_BRANCH_WEIGHTS[n] for n in names], k=1)[0]


def random_params(rng):
    branch = _pick_branch(rng)
    veil_composition = rng.choice(list(VEIL_LAYOUTS.keys()))
    veil_radius = rng.uniform(1.6, 2.4)
    veil_thickness = rng.uniform(0.04, 0.08)
    # Sweep is enough to span the chamber height given the radius.
    veil_sweep = rng.uniform(math.pi / 3, math.pi / 2.2)
    veil_cx_offset = rng.uniform(-0.2, 0.4)   # arc center sits this far beyond the chamber wall
    veil_ior = rng.uniform(1.48, 1.60)
    veil_cauchy_b = rng.uniform(10_000.0, 28_000.0)
    veil_fill = rng.uniform(0.04, 0.10)
    lights = _BRANCH_SAMPLERS[branch](rng)
    base_exp = -4.55 if len(lights) == 1 else -4.75
    look_exposure = base_exp + rng.uniform(-0.20, 0.15)
    return AnimParams(
        veil_composition=veil_composition, veil_radius=veil_radius, veil_thickness=veil_thickness,
        veil_sweep=veil_sweep, veil_cx_offset=veil_cx_offset, veil_ior=veil_ior,
        veil_cauchy_b=veil_cauchy_b, veil_fill=veil_fill,
        lights=lights, branch=branch, look_exposure=look_exposure,
    )


PROBE_FPS = 4
PROBE_W, PROBE_H = 640, 360
GATE_MEAN_LUMA = (0.10, 0.42)
GATE_CLIPPED_MAX = 0.09
GATE_NEAR_BLACK_MAX = 0.75
GATE_IDR_MIN = 35.0 / 255.0
GATE_COLORFULNESS_MIN_WARM_DOMINANT = 0.08
GATE_COLORFULNESS_MIN_OTHER = 0.010
GATE_MIN_PASSING_FRAMES_FRAC = 0.30


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
    base_dir = Path("renders/families/veil")
    found = 0
    for attempt in range(1, MAX_ATTEMPTS + 1):
        p = random_params(rng)
        print(f"[{attempt}] branch={p.branch} veil={p.veil_composition} r={p.veil_radius:.2f} "
              f"exp={p.look_exposure:.2f} — checking...", flush=True)
        ok, s = check_beauty(p)
        print(f"  passes={s['passing_frames']}/{s['total_frames']} "
              f"mean_luma={s['mean_luma']:.3f} color={s['color']:.3f} "
              f"idr={s['idr']:.3f} near_black={s['near_black']:.2f} clipped={s['clipped']:.3f}",
              flush=True)
        if not ok:
            continue
        found += 1
        tag = f"{found:03d}_{p.branch}_{p.veil_composition.replace('veil_on_','')}"
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
