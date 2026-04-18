"""Iris — a rotating ring of prism wedges forming an aperture.

Six to ten glass wedges sit in a ring at a fixed radius from the chamber
centre. A projector shines through from one side. Rays passing near the
centre escape unrefracted; rays grazing the ring hit wedges and fan out
into spectrum. As the ring rotates, the pattern of emitted beams rotates
with it, so the chamber continually shifts colour.

Branches (explicit per-branch params):

- solo_white      : one full-spectrum projector
- solo_warm       : one orange projector
- duet_contrast   : warm + white from opposite sides

Iris composition:

- iris_horizontal : projector on a side wall, ring spins horizontally
- iris_vertical   : medieval inversion — projector on top/bottom, ring spins vertically
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
WEDGE_ID = "iris_glass"

IRIS_LAYOUTS = {"iris_horizontal", "iris_vertical"}


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
    iris_composition: str
    ring_cx: float
    ring_cy: float
    ring_radius: float
    n_wedges: int
    wedge_size: float
    ring_rotation_rate: float
    wedge_ior: float
    wedge_cauchy_b: float
    wedge_fill: float
    lights: list[LightDef] = field(default_factory=list)
    branch: str = "solo_white"
    look_exposure: float = -4.55


def _light_position_and_dir(L, target):
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
    return pos, (math.cos(a), math.sin(a))


def _spectrum_for(color):
    if color == "warm":
        return LightSpectrum.range(wavelength_min=580, wavelength_max=650)
    if color == "white":
        return LightSpectrum.range(wavelength_min=380, wavelength_max=780)
    raise ValueError(color)


def _projectors(p):
    out = []
    for i, L in enumerate(p.lights):
        pos, dir_ = _light_position_and_dir(L, (p.ring_cx, p.ring_cy))
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


def _wedge_shapes(p, progress):
    ring_angle = p.ring_rotation_rate * progress
    shapes = []
    for i in range(p.n_wedges):
        a = ring_angle + 2 * math.pi * i / p.n_wedges
        wx = p.ring_cx + p.ring_radius * math.cos(a)
        wy = p.ring_cy + p.ring_radius * math.sin(a)
        shapes.append(prism(
            center=(wx, wy),
            size=p.wedge_size,
            material_id=WEDGE_ID,
            rotation=a,  # point outward from ring center
            id_prefix=f"wedge_{i}",
        ))
    return shapes


def build_animate(p):
    mats = {
        WALL_ID: WALL,
        WEDGE_ID: glass(ior=p.wedge_ior, cauchy_b=p.wedge_cauchy_b,
                         color=(0.97, 0.97, 0.98), fill=p.wedge_fill),
    }

    def animate(ctx):
        progress = ctx.progress if ctx.total_frames > 1 else 0.5
        scene = Scene(
            materials=mats,
            shapes=[
                *mirror_box(CHAMBER_HW, CHAMBER_HH, WALL_ID, id_prefix="chamber"),
                *_wedge_shapes(p, progress),
            ],
            lights=_projectors(p),
        )
        warm_frac = sum(1 for L in p.lights if L.color == "warm") / max(1, len(p.lights))
        look = Look(exposure=p.look_exposure, gamma=2.0, tonemap="reinhardx",
                    white_point=0.5, normalize="rays", temperature=0.25 * warm_frac)
        return Frame(scene=scene, look=look)

    return animate


def _sides_for(orientation):
    if orientation == "iris_horizontal":
        return ("left", "right")
    return ("top", "bottom")


def _tangent_range(orientation):
    if orientation == "iris_horizontal":
        return (-0.25, 0.25)
    return (-0.45, 0.45)


def _sample_light(rng, *, side, color, intensity, tangent_range):
    return LightDef(
        side=side,
        offset_tangent=rng.uniform(*tangent_range),
        spread=rng.uniform(0.05, 0.10),
        source=rng.choice(["ball", "line"]),
        source_radius=rng.uniform(0.008, 0.020),
        intensity=intensity,
        color=color,
    )


def _sample_solo_white(rng, orientation):
    side = rng.choice(_sides_for(orientation))
    return [_sample_light(rng, side=side, color="white",
                          intensity=rng.uniform(0.55, 0.82),
                          tangent_range=_tangent_range(orientation))]


def _sample_solo_warm(rng, orientation):
    side = rng.choice(_sides_for(orientation))
    return [_sample_light(rng, side=side, color="warm",
                          intensity=rng.uniform(0.20, 0.34),
                          tangent_range=_tangent_range(orientation))]


def _sample_duet_contrast(rng, orientation):
    a, b = _sides_for(orientation)
    return [
        _sample_light(rng, side=a, color="warm", intensity=rng.uniform(0.14, 0.20),
                      tangent_range=_tangent_range(orientation)),
        _sample_light(rng, side=b, color="white", intensity=rng.uniform(0.40, 0.58),
                      tangent_range=_tangent_range(orientation)),
    ]


_BRANCH_SAMPLERS = {"solo_white": _sample_solo_white, "solo_warm": _sample_solo_warm, "duet_contrast": _sample_duet_contrast}
_BRANCH_WEIGHTS = {"solo_white": 1.2, "solo_warm": 1.0, "duet_contrast": 1.4}


def _pick_branch(rng):
    names = list(_BRANCH_WEIGHTS.keys())
    return rng.choices(names, weights=[_BRANCH_WEIGHTS[n] for n in names], k=1)[0]


def random_params(rng):
    branch = _pick_branch(rng)
    orientation = rng.choice(list(IRIS_LAYOUTS))
    ring_cx = rng.uniform(-0.15, 0.15)
    ring_cy = rng.uniform(-0.10, 0.10)
    ring_radius = rng.uniform(0.35, 0.55)
    n_wedges = rng.randint(6, 10)
    wedge_size = rng.uniform(0.07, 0.12)
    ring_rotation_rate = rng.uniform(-math.tau, math.tau)
    wedge_ior = rng.uniform(1.50, 1.62)
    wedge_cauchy_b = rng.uniform(18_000.0, 34_000.0)
    wedge_fill = rng.uniform(0.06, 0.12)
    lights = _BRANCH_SAMPLERS[branch](rng, orientation)
    base_exp = -4.5 if len(lights) == 1 else -4.72
    look_exposure = base_exp + rng.uniform(-0.20, 0.15)
    return AnimParams(
        iris_composition=orientation, ring_cx=ring_cx, ring_cy=ring_cy,
        ring_radius=ring_radius, n_wedges=n_wedges, wedge_size=wedge_size,
        ring_rotation_rate=ring_rotation_rate, wedge_ior=wedge_ior,
        wedge_cauchy_b=wedge_cauchy_b, wedge_fill=wedge_fill,
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
    base_dir = Path("renders/families/iris")
    found = 0
    for attempt in range(1, MAX_ATTEMPTS + 1):
        p = random_params(rng)
        print(f"[{attempt}] branch={p.branch} iris={p.iris_composition} n={p.n_wedges} "
              f"r={p.ring_radius:.2f} exp={p.look_exposure:.2f} — checking...", flush=True)
        ok, s = check_beauty(p)
        print(f"  passes={s['passing_frames']}/{s['total_frames']} "
              f"mean_luma={s['mean_luma']:.3f} color={s['color']:.3f} "
              f"idr={s['idr']:.3f} near_black={s['near_black']:.2f} clipped={s['clipped']:.3f}",
              flush=True)
        if not ok:
            continue
        found += 1
        tag = f"{found:03d}_{p.branch}_{p.iris_composition.replace('iris_','')}"
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
