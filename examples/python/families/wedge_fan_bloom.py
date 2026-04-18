"""Wedge Fan Bloom — a cluster of dispersive prism wedges blooms outward over time.

Four to seven glass wedges sit around a center point. Over the animation, they
drift radially outward while rotating, so the cluster opens like a flower. A
projector lights the center; as the wedges open, each one catches more of the
beam and flings its own spectral streak outward, forming a growing rainbow
fan.

Branches (explicit per-branch params):

- solo_white      : one full-spectrum projector
- solo_warm       : one orange projector
- duet_contrast   : warm + white projectors at opposite sides

Bloom composition:

- bloom_center  : bloom centered in the chamber
- bloom_offset  : bloom pivoted to one side (medieval inversion equivalent)
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
)
from anim.renderer import RenderSession, _resolve_frame_shot

WALL = Material(metallic=1.0, roughness=0.1, transmission=0.0, cauchy_b=0.0, albedo=1.0)
CAMERA = Camera2D(center=[0, 0], width=3.2)
DURATION = 6.0
CHAMBER_HW, CHAMBER_HH = 1.6, 0.9

WALL_ID = "wall"
WEDGE_ID = "wedge_glass"

BLOOM_LAYOUTS = {"bloom_center", "bloom_offset"}


@dataclass
class LightDef:
    side: str
    offset_tangent: float
    spread: float
    source: str
    source_radius: float
    intensity: float
    color: str


@dataclass
class AnimParams:
    bloom_composition: str
    bloom_cx: float
    bloom_cy: float
    n_wedges: int
    wedge_size: float
    inner_radius: float
    outer_radius: float
    wedge_rotation_rate: float     # radians per DURATION for each wedge's self-rotation
    wedge_phase_jitter: float      # radians (max random offset per wedge)
    wedge_ior: float
    wedge_cauchy_b: float
    wedge_fill: float
    lights: list[LightDef] = field(default_factory=list)
    branch: str = "solo_white"
    look_exposure: float = -4.55


def _light_position_and_dir(L: LightDef, target: tuple[float, float]) -> tuple[tuple[float, float], tuple[float, float]]:
    if L.side == "left":
        pos = (-CHAMBER_HW + 0.08, L.offset_tangent)
    elif L.side == "right":
        pos = (CHAMBER_HW - 0.08, L.offset_tangent)
    elif L.side == "top":
        pos = (L.offset_tangent, CHAMBER_HH - 0.08)
    else:
        pos = (L.offset_tangent, -CHAMBER_HH + 0.08)
    tx, ty = target
    a = math.atan2(ty - pos[1], tx - pos[0])
    return (pos, (math.cos(a), math.sin(a)))


def _spectrum_for(color: str) -> LightSpectrum:
    if color == "warm":
        return LightSpectrum.range(wavelength_min=580, wavelength_max=650)
    if color == "white":
        return LightSpectrum.range(wavelength_min=380, wavelength_max=780)
    raise ValueError(color)


def _projectors(p: AnimParams) -> list[ProjectorLight]:
    out = []
    for i, L in enumerate(p.lights):
        pos, dir_ = _light_position_and_dir(L, (p.bloom_cx, p.bloom_cy))
        out.append(ProjectorLight(
            id=f"beam_{i}",
            position=list(pos),
            direction=list(dir_),
            source_radius=L.source_radius,
            spread=L.spread,
            source=L.source,
            intensity=L.intensity,
            spectrum=_spectrum_for(L.color),
        ))
    return out


def _wedge_shapes(p: AnimParams, progress: float, rng_seeded: random.Random):
    radius = p.inner_radius + (p.outer_radius - p.inner_radius) * progress
    shapes = []
    for i in range(p.n_wedges):
        base_angle = 2 * math.pi * i / p.n_wedges
        # Per-wedge phase jitter is drawn from a seeded rng so it stays deterministic per-frame.
        phase = rng_seeded.uniform(-p.wedge_phase_jitter, p.wedge_phase_jitter)
        angle = base_angle + phase
        cx = p.bloom_cx + radius * math.cos(angle)
        cy = p.bloom_cy + radius * math.sin(angle)
        # Each wedge points outward from the bloom center.
        wedge_rotation = angle + p.wedge_rotation_rate * progress
        shapes.append(prism(
            center=(cx, cy),
            size=p.wedge_size,
            material_id=WEDGE_ID,
            rotation=wedge_rotation,
            id_prefix=f"wedge_{i}",
        ))
    return shapes


def build_animate(p: AnimParams):
    # Seeded RNG for per-frame wedge phases (deterministic per AnimParams).
    mats = {
        WALL_ID: WALL,
        WEDGE_ID: glass(ior=p.wedge_ior, cauchy_b=p.wedge_cauchy_b,
                         color=(0.97, 0.97, 0.98), fill=p.wedge_fill),
    }

    def animate(ctx: FrameContext) -> Frame:
        progress = ctx.progress if ctx.total_frames > 1 else 0.5
        rng = random.Random(13 + int(p.n_wedges) * 101)  # same seed each frame: phases don't wiggle
        scene = Scene(
            materials=mats,
            shapes=[
                *mirror_box(CHAMBER_HW, CHAMBER_HH, WALL_ID, id_prefix="chamber"),
                *_wedge_shapes(p, progress, rng),
            ],
            lights=_projectors(p),
        )
        warm_frac = sum(1 for L in p.lights if L.color == "warm") / max(1, len(p.lights))
        look = Look(exposure=p.look_exposure, gamma=2.0, tonemap="reinhardx",
                    white_point=0.5, normalize="rays", temperature=0.25 * warm_frac)
        return Frame(scene=scene, look=look)

    return animate


def _sample_light(rng, *, side, color, intensity):
    if side in ("left", "right"):
        off = rng.uniform(-0.4, 0.4)
    else:
        off = rng.uniform(-0.6, 0.6)
    return LightDef(
        side=side, offset_tangent=off,
        spread=rng.uniform(0.04, 0.09),
        source=rng.choice(["ball", "line"]),
        source_radius=rng.uniform(0.008, 0.020),
        intensity=intensity,
        color=color,
    )


def _sample_solo_white(rng):
    return [_sample_light(rng, side=rng.choice(["left", "right", "top", "bottom"]),
                          color="white", intensity=rng.uniform(0.55, 0.82))]


def _sample_solo_warm(rng):
    return [_sample_light(rng, side=rng.choice(["left", "right", "top", "bottom"]),
                          color="warm", intensity=rng.uniform(0.20, 0.34))]


def _sample_duet_contrast(rng):
    a = rng.choice(["left", "right", "top", "bottom"])
    b = {"left": "right", "right": "left", "top": "bottom", "bottom": "top"}[a]
    return [
        _sample_light(rng, side=a, color="warm", intensity=rng.uniform(0.14, 0.20)),
        _sample_light(rng, side=b, color="white", intensity=rng.uniform(0.38, 0.56)),
    ]


_BRANCH_SAMPLERS = {"solo_white": _sample_solo_white, "solo_warm": _sample_solo_warm, "duet_contrast": _sample_duet_contrast}
_BRANCH_WEIGHTS = {"solo_white": 1.2, "solo_warm": 1.0, "duet_contrast": 1.4}


def _pick_branch(rng):
    names = list(_BRANCH_WEIGHTS.keys())
    return rng.choices(names, weights=[_BRANCH_WEIGHTS[n] for n in names], k=1)[0]


def random_params(rng):
    branch = _pick_branch(rng)
    bloom_composition = rng.choice(list(BLOOM_LAYOUTS))
    if bloom_composition == "bloom_center":
        bloom_cx = rng.uniform(-0.15, 0.15)
        bloom_cy = rng.uniform(-0.10, 0.10)
    else:
        bloom_cx = rng.choice([-1.0, 1.0]) * rng.uniform(0.30, 0.55)
        bloom_cy = rng.uniform(-0.25, 0.25)
    n_wedges = rng.randint(4, 7)
    wedge_size = rng.uniform(0.10, 0.16)
    inner_radius = rng.uniform(0.05, 0.15)
    outer_radius = rng.uniform(0.40, 0.65)
    wedge_rotation_rate = rng.uniform(-math.pi, math.pi) * 0.6
    wedge_phase_jitter = rng.uniform(0.0, 0.25)
    wedge_ior = rng.uniform(1.50, 1.62)
    wedge_cauchy_b = rng.uniform(18_000.0, 35_000.0)
    wedge_fill = rng.uniform(0.06, 0.12)
    lights = _BRANCH_SAMPLERS[branch](rng)
    base_exp = -4.5 if len(lights) == 1 else -4.72
    look_exposure = base_exp + rng.uniform(-0.20, 0.15)
    return AnimParams(
        bloom_composition=bloom_composition, bloom_cx=bloom_cx, bloom_cy=bloom_cy,
        n_wedges=n_wedges, wedge_size=wedge_size,
        inner_radius=inner_radius, outer_radius=outer_radius,
        wedge_rotation_rate=wedge_rotation_rate, wedge_phase_jitter=wedge_phase_jitter,
        wedge_ior=wedge_ior, wedge_cauchy_b=wedge_cauchy_b, wedge_fill=wedge_fill,
        lights=lights, branch=branch, look_exposure=look_exposure,
    )


PROBE_FPS = 4
PROBE_W, PROBE_H = 640, 360
GATE_MEAN_LUMA = (0.10, 0.42)
GATE_CLIPPED_MAX = 0.09
GATE_NEAR_BLACK_MAX = 0.75
GATE_IDR_MIN = 40.0 / 255.0
GATE_COLORFULNESS_MIN_WARM_DOMINANT = 0.08
GATE_COLORFULNESS_MIN_OTHER = 0.015
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
    base_dir = Path("renders/families/wedge_fan_bloom")
    found = 0
    for attempt in range(1, MAX_ATTEMPTS + 1):
        p = random_params(rng)
        print(f"[{attempt}] branch={p.branch} bloom={p.bloom_composition} n={p.n_wedges} "
              f"exp={p.look_exposure:.2f} — checking...", flush=True)
        ok, s = check_beauty(p)
        print(f"  passes={s['passing_frames']}/{s['total_frames']} "
              f"mean_luma={s['mean_luma']:.3f} color={s['color']:.3f} "
              f"idr={s['idr']:.3f} near_black={s['near_black']:.2f} clipped={s['clipped']:.3f}",
              flush=True)
        if not ok:
            continue
        found += 1
        tag = f"{found:03d}_{p.branch}_{p.bloom_composition.replace('bloom_','')}"
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
