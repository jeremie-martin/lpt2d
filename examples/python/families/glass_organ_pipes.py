"""Glass Organ Pipes — a row of colored glass rectangles lit by a sweeping projector.

A horizontal row of tall thin glass rectangles, each a different fill color and
slight IOR drift, stands in the chamber. A projector translates across the row;
as the beam passes each pipe, that pipe glows briefly and a tinted shaft exits
into the chamber. The chamber lights up like a bar chart of color.

Branches (explicit per-branch inline params):

- solo_white      : one full-spectrum projector sweeping left to right
- solo_warm       : one orange projector (chamber reads warmer overall)
- duet_contrast   : warm + white sweeping in opposite directions

Row composition:

- pipes_below  : row in the lower half, beam sweeps above
- pipes_above  : medieval inversion — row in upper half, beam sweeps below
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
    rectangle,
    render,
)
from anim.renderer import RenderSession, _resolve_frame_shot

WALL = Material(metallic=1.0, roughness=0.1, transmission=0.0, cauchy_b=0.0, albedo=1.0)
CAMERA = Camera2D(center=[0, 0], width=3.2)
DURATION = 6.0
CHAMBER_HW, CHAMBER_HH = 1.6, 0.9

WALL_ID = "wall"

# Wide palette; each run picks a contiguous slice of this list so the spectrum
# across the row reads rainbow-like rather than random.
PIPE_PALETTE = [
    ("pipe_red",    (1.0, 0.25, 0.22)),
    ("pipe_orange", (1.0, 0.50, 0.20)),
    ("pipe_amber",  (1.0, 0.75, 0.30)),
    ("pipe_yellow", (1.0, 0.90, 0.40)),
    ("pipe_lime",   (0.75, 1.0, 0.40)),
    ("pipe_green",  (0.35, 1.0, 0.50)),
    ("pipe_teal",   (0.35, 0.95, 0.95)),
    ("pipe_blue",   (0.35, 0.55, 1.0)),
    ("pipe_indigo", (0.55, 0.35, 1.0)),
    ("pipe_violet", (0.85, 0.40, 1.0)),
]

ROW_LAYOUTS = {"pipes_below": +1, "pipes_above": -1}


@dataclass
class LightDef:
    y_fraction: float       # vertical position of the projector, fraction of chamber half-height (signed)
    sweep_start_x: float
    sweep_end_x: float
    spread: float
    source: str
    source_radius: float
    intensity: float
    color: str


@dataclass
class AnimParams:
    row_composition: str
    n_pipes: int
    palette_start: int       # index into PIPE_PALETTE (pipes use contiguous slice of n_pipes starting here)
    pipe_width: float
    pipe_height: float
    pipe_gap: float
    pipe_fill: float
    pipe_ior: float
    pipe_cauchy_b: float
    lights: list[LightDef] = field(default_factory=list)
    branch: str = "solo_white"
    look_exposure: float = -4.6


def _pipe_materials(p: AnimParams) -> dict[str, Material]:
    mats: dict[str, Material] = {WALL_ID: WALL}
    end = min(len(PIPE_PALETTE), p.palette_start + p.n_pipes)
    slice_ = PIPE_PALETTE[p.palette_start:end]
    for name, rgb in slice_:
        mats[name] = glass(
            ior=p.pipe_ior,
            cauchy_b=p.pipe_cauchy_b,
            color=rgb,
            fill=p.pipe_fill,
        )
    return mats


def _row_y(p: AnimParams) -> float:
    sign = ROW_LAYOUTS[p.row_composition]
    return -sign * (CHAMBER_HH - p.pipe_height / 2 - 0.05)


def _pipe_shapes(p: AnimParams):
    row_y = _row_y(p)
    total_span = p.n_pipes * p.pipe_width + (p.n_pipes - 1) * p.pipe_gap
    x0 = -total_span / 2 + p.pipe_width / 2
    shapes = []
    end = min(len(PIPE_PALETTE), p.palette_start + p.n_pipes)
    names = [name for name, _ in PIPE_PALETTE[p.palette_start:end]]
    for i, name in enumerate(names):
        cx = x0 + i * (p.pipe_width + p.pipe_gap)
        shapes.append(rectangle(
            center=(cx, row_y),
            width=p.pipe_width,
            height=p.pipe_height,
            material_id=name,
            id_prefix=f"pipe_{i}",
        ))
    return shapes


def _spectrum_for(color: str) -> LightSpectrum:
    if color == "warm":
        return LightSpectrum.range(wavelength_min=580, wavelength_max=650)
    if color == "white":
        return LightSpectrum.range(wavelength_min=380, wavelength_max=780)
    raise ValueError(color)


def _projectors(p: AnimParams, progress: float) -> list[ProjectorLight]:
    sign = ROW_LAYOUTS[p.row_composition]
    out = []
    for i, L in enumerate(p.lights):
        # Projector above the row (if pipes_below) or below (if pipes_above), shining at the row.
        ly = sign * (CHAMBER_HH * L.y_fraction)
        lx = L.sweep_start_x + (L.sweep_end_x - L.sweep_start_x) * progress
        # Aim straight at the row center
        aim_dx = 0.0 - lx
        aim_dy = _row_y(p) - ly
        a = math.atan2(aim_dy, aim_dx)
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
    mats = _pipe_materials(p)

    def animate(ctx: FrameContext) -> Frame:
        progress = ctx.progress if ctx.total_frames > 1 else 0.5
        scene = Scene(
            materials=mats,
            shapes=[
                *mirror_box(CHAMBER_HW, CHAMBER_HH, WALL_ID, id_prefix="chamber"),
                *_pipe_shapes(p),
            ],
            lights=_projectors(p, progress),
        )
        warm_frac = sum(1 for L in p.lights if L.color == "warm") / max(1, len(p.lights))
        look = Look(exposure=p.look_exposure, gamma=2.0, tonemap="reinhardx",
                    white_point=0.5, normalize="rays", temperature=0.25 * warm_frac)
        return Frame(scene=scene, look=look)

    return animate


def _sample_light(rng: random.Random, color: str, intensity: float, reverse: bool) -> LightDef:
    span = rng.uniform(1.6, 2.2)
    if reverse:
        start, end = +span / 2, -span / 2
    else:
        start, end = -span / 2, +span / 2
    return LightDef(
        y_fraction=rng.uniform(0.45, 0.75),
        sweep_start_x=start,
        sweep_end_x=end,
        spread=rng.uniform(0.05, 0.10),
        source=rng.choice(["ball", "line"]),
        source_radius=rng.uniform(0.008, 0.020),
        intensity=intensity,
        color=color,
    )


def _sample_solo_white(rng: random.Random) -> list[LightDef]:
    return [_sample_light(rng, "white", rng.uniform(0.60, 0.90), reverse=rng.random() < 0.5)]


def _sample_solo_warm(rng: random.Random) -> list[LightDef]:
    return [_sample_light(rng, "warm", rng.uniform(0.22, 0.38), reverse=rng.random() < 0.5)]


def _sample_duet_contrast(rng: random.Random) -> list[LightDef]:
    return [
        _sample_light(rng, "warm", rng.uniform(0.14, 0.22), reverse=False),
        _sample_light(rng, "white", rng.uniform(0.40, 0.60), reverse=True),
    ]


_BRANCH_SAMPLERS = {"solo_white": _sample_solo_white, "solo_warm": _sample_solo_warm, "duet_contrast": _sample_duet_contrast}
_BRANCH_WEIGHTS = {"solo_white": 1.6, "solo_warm": 1.0, "duet_contrast": 1.2}


def _pick_branch(rng: random.Random) -> str:
    names = list(_BRANCH_WEIGHTS.keys())
    return rng.choices(names, weights=[_BRANCH_WEIGHTS[n] for n in names], k=1)[0]


def random_params(rng: random.Random) -> AnimParams:
    branch = _pick_branch(rng)
    row_composition = rng.choice(list(ROW_LAYOUTS.keys()))

    n_pipes = rng.randint(6, 9)
    palette_start = rng.randint(0, len(PIPE_PALETTE) - n_pipes)

    pipe_width = rng.uniform(0.10, 0.16)
    pipe_height = rng.uniform(0.55, 0.85)
    pipe_gap = rng.uniform(0.04, 0.09)
    pipe_fill = rng.uniform(0.10, 0.22)
    pipe_ior = rng.uniform(1.45, 1.58)
    pipe_cauchy_b = rng.uniform(0.0, 10_000.0)

    lights = _BRANCH_SAMPLERS[branch](rng)
    base_exp = -4.5 if len(lights) == 1 else -4.7
    look_exposure = base_exp + rng.uniform(-0.20, 0.15)

    return AnimParams(
        row_composition=row_composition,
        n_pipes=n_pipes, palette_start=palette_start,
        pipe_width=pipe_width, pipe_height=pipe_height, pipe_gap=pipe_gap,
        pipe_fill=pipe_fill, pipe_ior=pipe_ior, pipe_cauchy_b=pipe_cauchy_b,
        lights=lights, branch=branch, look_exposure=look_exposure,
    )


PROBE_FPS = 4
PROBE_W, PROBE_H = 640, 360
GATE_MEAN_LUMA = (0.10, 0.45)
GATE_CLIPPED_MAX = 0.10
GATE_NEAR_BLACK_MAX = 0.75
GATE_IDR_MIN = 35.0 / 255.0
GATE_COLORFULNESS_MIN_WARM_DOMINANT = 0.10
GATE_COLORFULNESS_MIN_OTHER = 0.05   # colored pipes give us good color even with white light
GATE_MIN_PASSING_FRAMES_FRAC = 0.30


def _is_warm_dominant(p: AnimParams) -> bool:
    warm = sum(1 for L in p.lights if L.color == "warm")
    return warm / max(1, len(p.lights)) >= 0.5


def make_probe_shot() -> Shot:
    shot = Shot.preset("draft", width=PROBE_W, height=PROBE_H, rays=300_000, depth=10)
    shot.camera = CAMERA
    shot.look = shot.look.with_overrides(exposure=-4.6, gamma=2.0, tonemap="reinhardx",
                                          white_point=0.5, normalize="rays", temperature=0.0)
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
    summary = {k: avg(k) for k in agg}
    summary["passing_frames"] = passes
    summary["total_frames"] = n_frames
    return passes >= int(GATE_MIN_PASSING_FRAMES_FRAC * n_frames), summary


def make_preview_shot(width: int, height: int, rays: int) -> Shot:
    shot = Shot.preset("preview", width=width, height=height, rays=rays, depth=10)
    shot.camera = CAMERA
    shot.look = shot.look.with_overrides(exposure=-4.6, gamma=2.0, tonemap="reinhardx",
                                          white_point=0.5, normalize="rays", temperature=0.0)
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


MAX_ATTEMPTS = 250


def main() -> None:
    seed = int(time.time()) if "--seed" not in sys.argv else int(sys.argv[sys.argv.index("--seed") + 1])
    target_count = int(sys.argv[sys.argv.index("-n") + 1]) if "-n" in sys.argv else 3
    hq = "--hq" in sys.argv
    width, height, rays = (1280, 720, 3_000_000) if hq else (640, 360, 800_000)
    fps = 30
    rng = random.Random(seed)
    print(f"seed={seed} target={target_count} hq={hq}")
    base_dir = Path("renders/families/glass_organ_pipes")
    found = 0
    for attempt in range(1, MAX_ATTEMPTS + 1):
        p = random_params(rng)
        print(f"[{attempt}] branch={p.branch} row={p.row_composition} n_pipes={p.n_pipes} "
              f"exp={p.look_exposure:.2f} — checking...", flush=True)
        ok, s = check_beauty(p)
        print(f"  passes={s['passing_frames']}/{s['total_frames']} "
              f"mean_luma={s['mean_luma']:.3f} color={s['color']:.3f} "
              f"idr={s['idr']:.3f} near_black={s['near_black']:.2f} clipped={s['clipped']:.3f}",
              flush=True)
        if not ok:
            continue
        found += 1
        tag = f"{found:03d}_{p.branch}_{p.row_composition.replace('pipes_','')}"
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
