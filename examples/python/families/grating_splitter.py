"""Grating Splitter — a diffraction grating splits a beam into a fan of downstream prisms.

A thick metallic grating sits across the chamber with several narrow slits.
A projector behind it casts one broad beam; the grating lets through only the
slit-aligned rays as a fan of parallel sub-beams. A row of small prisms is
placed downstream, one per slit, so each sub-beam hits its own prism and
explodes into spectrum. The chamber reads as a small spectral choir.

Branches (explicit per-branch params):

- solo_white      : one full-spectrum projector
- solo_warm       : one orange projector
- duet_contrast   : warm + white behind the grating at different angles

Fan composition:

- fan_right  : grating on left, prisms on right
- fan_left   : medieval inversion
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
    grating,
    mirror_box,
    prism,
    render,
)
from anim.renderer import RenderSession, _resolve_frame_shot

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

FAN_LAYOUTS = {"fan_right": +1, "fan_left": -1}


@dataclass
class LightDef:
    offset_perp: float
    angle_drift_rate: float
    base_angle_offset: float
    spread: float
    source: str
    source_radius: float
    intensity: float
    color: str


@dataclass
class AnimParams:
    fan_composition: str
    grating_x_abs: float         # absolute x of grating (positive; signed by layout)
    grating_n: int
    grating_spacing: float       # distance between slit centers
    grating_gap: float           # opening width
    grating_width: float         # total barrier width
    grating_thickness: float
    prism_row_offset: float      # distance from grating to prism row
    prism_size: float
    prism_rotation_speed: float
    prism_glass_idx: int
    projector_offset: float      # distance from grating, on the far side
    lights: list[LightDef] = field(default_factory=list)
    branch: str = "solo_white"
    look_exposure: float = -4.55


def _fan_sign(p) -> int:
    return FAN_LAYOUTS[p.fan_composition]


def _grating_center(p) -> tuple[float, float]:
    sign = _fan_sign(p)
    return (-sign * p.grating_x_abs, 0.0)


def _grating_shape_list(p):
    # The built-in grating() returns segments aligned with a horizontal barrier by default.
    # For a vertical grating (perpendicular to horizontal beam), we transpose by using
    # orientation = "vertical" isn't part of the API — so we rotate by 90° by swapping
    # the placement convention: build a horizontal grating around a reference center then
    # apply our own vertical orientation by constructing it sideways.
    #
    # Simplest: call grating at a virtual center with width along Y. Since grating produces
    # segments along X at y=center_y, we fake vertical orientation by constructing our own
    # vertical barrier from thick_segments between slit openings.
    #
    # We do this by hand for clarity and to guarantee vertical orientation.
    from anim.builders import thick_segment  # local import to stay explicit

    cx, cy = _grating_center(p)
    half_w = p.grating_width / 2
    half_gap = p.grating_gap / 2

    # Slit centers along the vertical barrier (y coordinates around cy).
    n = p.grating_n
    total_span = (n - 1) * p.grating_spacing
    y0 = cy - total_span / 2
    slit_ys = [y0 + i * p.grating_spacing for i in range(n)]

    # Build the vertical barrier as a series of thick segments between the slit gaps.
    # Start from y=cy-half_w (top of barrier if we think of it as vertical extent y).
    ys_top = cy + half_w
    ys_bot = cy - half_w
    segments = []
    prev_y = ys_top
    for si, sy in enumerate(sorted(slit_ys, reverse=True)):
        # Segment from prev_y down to (sy + half_gap)
        top_of_gap = sy + half_gap
        if top_of_gap < prev_y:
            segments.append(thick_segment(
                (cx, prev_y), (cx, top_of_gap), p.grating_thickness, WALL_ID,
                id_prefix=f"grating_seg_{si}_a",
            ))
        prev_y = sy - half_gap
    # Final segment from last prev_y to ys_bot
    if prev_y > ys_bot:
        segments.append(thick_segment(
            (cx, prev_y), (cx, ys_bot), p.grating_thickness, WALL_ID,
            id_prefix=f"grating_seg_bot",
        ))
    # If slit_ys was empty (shouldn't happen), just build the whole barrier.
    if not segments:
        segments.append(thick_segment(
            (cx, ys_top), (cx, ys_bot), p.grating_thickness, WALL_ID,
            id_prefix="grating_full",
        ))
    # Suppress unused symbol
    _ = grating  # keep import in case we want to swap strategies later
    return segments


def _downstream_prism_shapes(p, rotation: float):
    """One small prism per slit, positioned downstream of the slit."""
    sign = _fan_sign(p)
    gx, gy = _grating_center(p)
    n = p.grating_n
    total_span = (n - 1) * p.grating_spacing
    y0 = gy - total_span / 2
    shapes = []
    for i in range(n):
        sy = y0 + i * p.grating_spacing
        px = gx + sign * p.prism_row_offset
        shapes.append(prism(
            center=(px, sy),
            size=p.prism_size,
            material_id=PRISM_IDS[p.prism_glass_idx % len(PRISM_IDS)],
            rotation=rotation + 0.15 * (i - (n - 1) / 2),  # slight per-prism tilt jitter
            id_prefix=f"downstream_prism_{i}",
        ))
    return shapes


def _spectrum_for(color):
    if color == "warm":
        return LightSpectrum.range(wavelength_min=580, wavelength_max=650)
    if color == "white":
        return LightSpectrum.range(wavelength_min=380, wavelength_max=780)
    raise ValueError(color)


def _projectors(p, progress):
    sign = _fan_sign(p)
    gx, gy = _grating_center(p)
    out = []
    for i, L in enumerate(p.lights):
        lx = gx - sign * p.projector_offset
        ly = gy + L.offset_perp
        # Aim at the grating center.
        aim_dx = gx - lx
        aim_dy = gy - ly
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
    def animate(ctx):
        progress = ctx.progress if ctx.total_frames > 1 else 0.5
        t = ctx.time
        rot = p.prism_rotation_speed * t / DURATION
        scene = Scene(
            materials=MATERIALS,
            shapes=[
                *mirror_box(CHAMBER_HW, CHAMBER_HH, WALL_ID, id_prefix="chamber"),
                *_grating_shape_list(p),
                *_downstream_prism_shapes(p, rot),
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
        angle_drift_rate=rng.uniform(-0.08, 0.08),
        base_angle_offset=rng.uniform(-0.03, 0.03),
        spread=rng.uniform(0.08, 0.14),   # broader beam to cover the grating
        source=rng.choice(["ball", "line"]),
        source_radius=rng.uniform(0.015, 0.030),
        intensity=intensity,
        color=color,
    )


def _sample_solo_white(rng): return [_sample_light(rng, color="white", intensity=rng.uniform(0.65, 0.95))]
def _sample_solo_warm(rng): return [_sample_light(rng, color="warm", intensity=rng.uniform(0.24, 0.38))]


def _sample_duet_contrast(rng):
    w = _sample_light(rng, color="warm", intensity=rng.uniform(0.16, 0.22))
    wh = _sample_light(rng, color="white", intensity=rng.uniform(0.50, 0.70))
    w.offset_perp = rng.uniform(-0.05, -0.01)
    w.base_angle_offset = rng.uniform(-0.04, 0.0)
    wh.offset_perp = rng.uniform(0.01, 0.05)
    wh.base_angle_offset = rng.uniform(0.0, 0.04)
    return [w, wh]


_BRANCH_SAMPLERS = {"solo_white": _sample_solo_white, "solo_warm": _sample_solo_warm, "duet_contrast": _sample_duet_contrast}
_BRANCH_WEIGHTS = {"solo_white": 1.4, "solo_warm": 1.0, "duet_contrast": 1.3}


def _pick_branch(rng):
    names = list(_BRANCH_WEIGHTS.keys())
    return rng.choices(names, weights=[_BRANCH_WEIGHTS[n] for n in names], k=1)[0]


def random_params(rng):
    branch = _pick_branch(rng)
    fan = rng.choice(list(FAN_LAYOUTS.keys()))
    grating_x_abs = rng.uniform(0.40, 0.65)
    grating_n = rng.randint(4, 7)
    grating_spacing = rng.uniform(0.14, 0.22)
    grating_gap = rng.uniform(0.035, 0.060)
    grating_width = grating_n * grating_spacing + 0.10
    grating_thickness = rng.uniform(0.03, 0.06)
    prism_row_offset = rng.uniform(0.35, 0.55)
    prism_size = rng.uniform(0.075, 0.12)
    prism_rotation_speed = rng.uniform(-math.pi, math.pi) * 0.3
    prism_glass_idx = rng.randint(0, 1)
    projector_offset = rng.uniform(0.55, 0.80)
    lights = _BRANCH_SAMPLERS[branch](rng)
    base_exp = -4.5 if len(lights) == 1 else -4.72
    look_exposure = base_exp + rng.uniform(-0.20, 0.15)
    return AnimParams(
        fan_composition=fan, grating_x_abs=grating_x_abs,
        grating_n=grating_n, grating_spacing=grating_spacing, grating_gap=grating_gap,
        grating_width=grating_width, grating_thickness=grating_thickness,
        prism_row_offset=prism_row_offset, prism_size=prism_size,
        prism_rotation_speed=prism_rotation_speed, prism_glass_idx=prism_glass_idx,
        projector_offset=projector_offset,
        lights=lights, branch=branch, look_exposure=look_exposure,
    )


PROBE_FPS = 4
PROBE_W, PROBE_H = 640, 360
GATE_MEAN_LUMA = (0.08, 0.42)
GATE_CLIPPED_MAX = 0.10
GATE_NEAR_BLACK_MAX = 0.80
GATE_IDR_MIN = 35.0 / 255.0
GATE_COLORFULNESS_MIN_WARM_DOMINANT = 0.08
GATE_COLORFULNESS_MIN_OTHER = 0.010
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
    base_dir = Path("renders/families/grating_splitter")
    found = 0
    for attempt in range(1, MAX_ATTEMPTS + 1):
        p = random_params(rng)
        print(f"[{attempt}] branch={p.branch} {p.fan_composition} n_slits={p.grating_n} "
              f"exp={p.look_exposure:.2f} — checking...", flush=True)
        ok, s = check_beauty(p)
        print(f"  passes={s['passing_frames']}/{s['total_frames']} "
              f"mean_luma={s['mean_luma']:.3f} color={s['color']:.3f} "
              f"idr={s['idr']:.3f} near_black={s['near_black']:.2f} clipped={s['clipped']:.3f}",
              flush=True)
        if not ok:
            continue
        found += 1
        tag = f"{found:03d}_{p.branch}_{p.fan_composition.replace('fan_','')}"
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
