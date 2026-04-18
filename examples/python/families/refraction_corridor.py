"""Refraction Corridor — a chain of glass blocks the beam threads through in sequence.

Three to six thick glass blocks sit in a row across the chamber, each slightly
tilted at a different angle. A projector at one end sends a beam that enters
the first block, refracts at two surfaces, exits into the gap, and repeats
through each subsequent block. By the end of the corridor the beam has
accumulated several refraction events and the spectrum is visibly fanned out.

Branches (explicit per-branch params):

- solo_white      : one full-spectrum projector
- solo_warm       : one orange projector
- duet_contrast   : warm + white entering the corridor side-by-side

Corridor composition:

- corridor_h  : horizontal row, beam from the left (standard)
- corridor_v  : vertical stack, beam from above (medieval inversion)
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
    polygon,
    render,
)
from anim.renderer import RenderSession, _resolve_frame_shot

WALL = Material(metallic=1.0, roughness=0.1, transmission=0.0, cauchy_b=0.0, albedo=1.0)
CAMERA = Camera2D(center=[0, 0], width=3.2)
DURATION = 6.0
CHAMBER_HW, CHAMBER_HH = 1.6, 0.9

WALL_ID = "wall"
BLOCK_ID = "corridor_glass"

CORRIDOR_LAYOUTS = {"corridor_h", "corridor_v"}


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
    corridor_composition: str
    n_blocks: int
    block_width: float
    block_height: float
    block_spacing: float
    block_tilt_max: float       # max per-block rotation in radians
    block_ior: float
    block_cauchy_b: float
    block_fill: float
    lights: list[LightDef] = field(default_factory=list)
    branch: str = "solo_white"
    look_exposure: float = -4.55


def _rotated_rect_vertices(cx, cy, w, h, angle):
    hw, hh = w / 2, h / 2
    corners = [(-hw, -hh), (+hw, -hh), (+hw, +hh), (-hw, +hh)]
    ca, sa = math.cos(angle), math.sin(angle)
    return [[ca * x - sa * y + cx, sa * x + ca * y + cy] for x, y in corners]


def _block_positions_and_tilts(p: AnimParams, rng_seeded: random.Random) -> list[tuple[float, float, float]]:
    positions = []
    total = p.n_blocks * p.block_width + (p.n_blocks - 1) * p.block_spacing
    start = -total / 2 + p.block_width / 2
    for i in range(p.n_blocks):
        tilt = rng_seeded.uniform(-p.block_tilt_max, p.block_tilt_max)
        along = start + i * (p.block_width + p.block_spacing)
        if p.corridor_composition == "corridor_h":
            positions.append((along, 0.0, tilt))
        else:
            positions.append((0.0, along, tilt + math.pi / 2))
    return positions


def _block_shapes(p):
    rng = random.Random(31 + int(p.n_blocks) * 13 + int(p.block_height * 1000))
    shapes = []
    for i, (cx, cy, tilt) in enumerate(_block_positions_and_tilts(p, rng)):
        verts = _rotated_rect_vertices(cx, cy, p.block_width, p.block_height, tilt)
        shapes.append(polygon(verts, BLOCK_ID, id_prefix=f"block_{i}"))
    return shapes


def _spectrum_for(color):
    if color == "warm":
        return LightSpectrum.range(wavelength_min=580, wavelength_max=650)
    if color == "white":
        return LightSpectrum.range(wavelength_min=380, wavelength_max=780)
    raise ValueError(color)


def _projectors(p, progress):
    out = []
    # Projector sits outside the first block, aimed toward the corridor axis.
    if p.corridor_composition == "corridor_h":
        base_pos = (-CHAMBER_HW + 0.08, 0.0)
        base_dir = (1.0, 0.0)
    else:
        base_pos = (0.0, CHAMBER_HH - 0.08)
        base_dir = (0.0, -1.0)
    base_angle = math.atan2(base_dir[1], base_dir[0])
    for i, L in enumerate(p.lights):
        if p.corridor_composition == "corridor_h":
            lx = base_pos[0]
            ly = base_pos[1] + L.offset_perp
        else:
            lx = base_pos[0] + L.offset_perp
            ly = base_pos[1]
        drift = L.angle_drift_rate * (progress - 0.5)
        a = base_angle + L.base_angle_offset + drift
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
        BLOCK_ID: glass(ior=p.block_ior, cauchy_b=p.block_cauchy_b,
                        color=(0.97, 0.97, 0.98), fill=p.block_fill),
    }

    def animate(ctx):
        progress = ctx.progress if ctx.total_frames > 1 else 0.5
        scene = Scene(
            materials=mats,
            shapes=[
                *mirror_box(CHAMBER_HW, CHAMBER_HH, WALL_ID, id_prefix="chamber"),
                *_block_shapes(p),
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
        offset_perp=rng.uniform(-0.15, 0.15),
        angle_drift_rate=rng.uniform(-0.10, 0.10),
        base_angle_offset=rng.uniform(-0.08, 0.08),
        spread=rng.uniform(0.04, 0.08),
        source=rng.choice(["ball", "line"]),
        source_radius=rng.uniform(0.008, 0.020),
        intensity=intensity,
        color=color,
    )


def _sample_solo_white(rng): return [_sample_light(rng, color="white", intensity=rng.uniform(0.55, 0.82))]
def _sample_solo_warm(rng): return [_sample_light(rng, color="warm", intensity=rng.uniform(0.20, 0.34))]


def _sample_duet_contrast(rng):
    w = _sample_light(rng, color="warm", intensity=rng.uniform(0.14, 0.20))
    w.offset_perp = rng.uniform(-0.15, -0.05)
    w.base_angle_offset = rng.uniform(-0.06, 0.02)
    wh = _sample_light(rng, color="white", intensity=rng.uniform(0.38, 0.56))
    wh.offset_perp = rng.uniform(0.05, 0.15)
    wh.base_angle_offset = rng.uniform(-0.02, 0.06)
    return [w, wh]


_BRANCH_SAMPLERS = {"solo_white": _sample_solo_white, "solo_warm": _sample_solo_warm, "duet_contrast": _sample_duet_contrast}
_BRANCH_WEIGHTS = {"solo_white": 1.4, "solo_warm": 1.0, "duet_contrast": 1.2}


def _pick_branch(rng):
    names = list(_BRANCH_WEIGHTS.keys())
    return rng.choices(names, weights=[_BRANCH_WEIGHTS[n] for n in names], k=1)[0]


def random_params(rng):
    branch = _pick_branch(rng)
    corridor = rng.choice(list(CORRIDOR_LAYOUTS))
    n_blocks = rng.randint(3, 5)
    block_width = rng.uniform(0.18, 0.28)
    block_height = rng.uniform(0.55, 0.80)
    block_spacing = rng.uniform(0.06, 0.14)
    block_tilt_max = rng.uniform(0.05, 0.20)
    block_ior = rng.uniform(1.48, 1.60)
    block_cauchy_b = rng.uniform(10_000.0, 28_000.0)
    block_fill = rng.uniform(0.05, 0.10)
    lights = _BRANCH_SAMPLERS[branch](rng)
    base_exp = -4.5 if len(lights) == 1 else -4.72
    look_exposure = base_exp + rng.uniform(-0.20, 0.15)
    return AnimParams(
        corridor_composition=corridor, n_blocks=n_blocks,
        block_width=block_width, block_height=block_height, block_spacing=block_spacing,
        block_tilt_max=block_tilt_max, block_ior=block_ior,
        block_cauchy_b=block_cauchy_b, block_fill=block_fill,
        lights=lights, branch=branch, look_exposure=look_exposure,
    )


PROBE_FPS = 4
PROBE_W, PROBE_H = 640, 360
GATE_MEAN_LUMA = (0.10, 0.42)
GATE_CLIPPED_MAX = 0.09
GATE_NEAR_BLACK_MAX = 0.75
GATE_IDR_MIN = 40.0 / 255.0
GATE_COLORFULNESS_MIN_WARM_DOMINANT = 0.08
GATE_COLORFULNESS_MIN_OTHER = 0.012
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
    base_dir = Path("renders/families/refraction_corridor")
    found = 0
    for attempt in range(1, MAX_ATTEMPTS + 1):
        p = random_params(rng)
        print(f"[{attempt}] branch={p.branch} {p.corridor_composition} n={p.n_blocks} "
              f"exp={p.look_exposure:.2f} — checking...", flush=True)
        ok, s = check_beauty(p)
        print(f"  passes={s['passing_frames']}/{s['total_frames']} "
              f"mean_luma={s['mean_luma']:.3f} color={s['color']:.3f} "
              f"idr={s['idr']:.3f} near_black={s['near_black']:.2f} clipped={s['clipped']:.3f}",
              flush=True)
        if not ok:
            continue
        found += 1
        tag = f"{found:03d}_{p.branch}_{p.corridor_composition.replace('corridor_','')}"
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
