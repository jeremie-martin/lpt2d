"""Spectral Staircase — glass rectangles fanned out like playing cards.

A hand of five to nine glass rectangles is spread in a fan, each card
offset in position and angle. A projector grazes the fan from one side;
the cards refract the beam at slightly different angles, and the chamber
lights up with an overlapping stack of spectral strokes — a staircase of
color.

Branches (explicit per-branch params):

- solo_white     : one full-spectrum projector, axis-aligned
- solo_warm      : one orange projector
- duet_contrast  : warm + white at slightly different angles

Fan composition:

- fan_right : pivot on the left, cards fanning out toward the right
- fan_left  : medieval inversion — pivot on the right, cards fanning left
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
CARD_ID = "card_glass"

MATERIALS_BASE = {WALL_ID: WALL}

FAN_LAYOUTS = {"fan_right": +1, "fan_left": -1}


@dataclass
class LightDef:
    side: str          # "left", "right", "top", "bottom"
    offset_tangent: float
    angle_drift_rate: float   # radians per DURATION — beam angle sweeps slightly
    base_angle_offset: float  # radians added to nominal aim-at-pivot direction
    spread: float
    source: str
    source_radius: float
    intensity: float
    color: str


@dataclass
class AnimParams:
    fan_composition: str
    n_cards: int
    fan_radius: float
    fan_angle_span: float        # total angular span of the fan
    card_width: float
    card_height: float
    card_ior: float
    card_cauchy_b: float
    card_fill: float
    pivot_x: float
    pivot_y: float
    lights: list[LightDef] = field(default_factory=list)
    branch: str = "solo_white"
    look_exposure: float = -4.55


def _rotated_rect_vertices(cx: float, cy: float, w: float, h: float, angle: float) -> list[list[float]]:
    hw, hh = w / 2, h / 2
    corners = [(-hw, -hh), (+hw, -hh), (+hw, +hh), (-hw, +hh)]
    ca, sa = math.cos(angle), math.sin(angle)
    return [[ca * x - sa * y + cx, sa * x + ca * y + cy] for x, y in corners]


def _fan_sign(p: AnimParams) -> int:
    return FAN_LAYOUTS[p.fan_composition]


def _card_shapes(p: AnimParams):
    sign = _fan_sign(p)
    shapes = []
    n = p.n_cards
    for i in range(n):
        frac = (i - (n - 1) / 2) / max(1, (n - 1))
        card_angle = frac * p.fan_angle_span
        # Direction the card's face points away from the pivot (outward along axis).
        # For fan_right, pivot is on the left; cards extend outward to the right.
        out_angle = card_angle  # treated as angle from positive x-axis
        cx = p.pivot_x + sign * p.fan_radius * math.cos(out_angle)
        cy = p.pivot_y + p.fan_radius * math.sin(out_angle)
        # Card's long axis is perpendicular to the outward ray, rotated by that angle.
        card_rot = out_angle + math.pi / 2
        verts = _rotated_rect_vertices(cx, cy, p.card_width, p.card_height, card_rot)
        shapes.append(polygon(verts, CARD_ID, id_prefix=f"card_{i}"))
    return shapes


def _spectrum_for(color: str) -> LightSpectrum:
    if color == "warm":
        return LightSpectrum.range(wavelength_min=580, wavelength_max=650)
    if color == "white":
        return LightSpectrum.range(wavelength_min=380, wavelength_max=780)
    raise ValueError(color)


def _light_position(L: LightDef) -> tuple[float, float]:
    if L.side == "left":
        return (-CHAMBER_HW + 0.08, L.offset_tangent)
    if L.side == "right":
        return (CHAMBER_HW - 0.08, L.offset_tangent)
    if L.side == "top":
        return (L.offset_tangent, CHAMBER_HH - 0.08)
    if L.side == "bottom":
        return (L.offset_tangent, -CHAMBER_HH + 0.08)
    raise ValueError(L.side)


def _projectors(p: AnimParams, progress: float) -> list[ProjectorLight]:
    out = []
    for i, L in enumerate(p.lights):
        lx, ly = _light_position(L)
        # Aim roughly at the fan pivot plus a drifting base offset.
        aim_dx = p.pivot_x - lx
        aim_dy = p.pivot_y - ly
        base = math.atan2(aim_dy, aim_dx)
        drift = L.angle_drift_rate * (progress - 0.5)  # drift centered on midpoint
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
    mats = dict(MATERIALS_BASE)
    mats[CARD_ID] = glass(
        ior=p.card_ior,
        cauchy_b=p.card_cauchy_b,
        color=(0.97, 0.97, 0.98),
        fill=p.card_fill,
    )

    def animate(ctx: FrameContext) -> Frame:
        progress = ctx.progress if ctx.total_frames > 1 else 0.5
        scene = Scene(
            materials=mats,
            shapes=[
                *mirror_box(CHAMBER_HW, CHAMBER_HH, WALL_ID, id_prefix="chamber"),
                *_card_shapes(p),
            ],
            lights=_projectors(p, progress),
        )
        warm_frac = sum(1 for L in p.lights if L.color == "warm") / max(1, len(p.lights))
        look = Look(exposure=p.look_exposure, gamma=2.0, tonemap="reinhardx",
                    white_point=0.5, normalize="rays", temperature=0.25 * warm_frac)
        return Frame(scene=scene, look=look)

    return animate


def _sample_light(rng: random.Random, *, side: str, color: str, intensity: float) -> LightDef:
    if side in ("left", "right"):
        offset = rng.uniform(-0.35, 0.35)
    else:
        offset = rng.uniform(-0.6, 0.6)
    return LightDef(
        side=side,
        offset_tangent=offset,
        angle_drift_rate=rng.uniform(-0.15, 0.15),
        base_angle_offset=rng.uniform(-0.05, 0.05),
        spread=rng.uniform(0.04, 0.08),
        source=rng.choice(["ball", "line"]),
        source_radius=rng.uniform(0.008, 0.018),
        intensity=intensity,
        color=color,
    )


def _side_for_fan(fan_composition: str) -> str:
    # Pivot on the left (fan_right) → project from the right or top/bottom looking in.
    return "right" if fan_composition == "fan_right" else "left"


def _sample_solo_white(rng: random.Random, fan_composition: str) -> list[LightDef]:
    return [_sample_light(rng, side=_side_for_fan(fan_composition), color="white",
                          intensity=rng.uniform(0.55, 0.80))]


def _sample_solo_warm(rng: random.Random, fan_composition: str) -> list[LightDef]:
    return [_sample_light(rng, side=_side_for_fan(fan_composition), color="warm",
                          intensity=rng.uniform(0.18, 0.32))]


def _sample_duet_contrast(rng: random.Random, fan_composition: str) -> list[LightDef]:
    side = _side_for_fan(fan_composition)
    warm = _sample_light(rng, side=side, color="warm", intensity=rng.uniform(0.12, 0.18))
    warm.base_angle_offset = rng.uniform(-0.08, -0.03)
    white = _sample_light(rng, side=side, color="white", intensity=rng.uniform(0.38, 0.55))
    white.base_angle_offset = rng.uniform(0.03, 0.08)
    return [warm, white]


_BRANCH_SAMPLERS = {"solo_white": _sample_solo_white, "solo_warm": _sample_solo_warm, "duet_contrast": _sample_duet_contrast}
_BRANCH_WEIGHTS = {"solo_white": 1.5, "solo_warm": 1.0, "duet_contrast": 1.3}


def _pick_branch(rng: random.Random) -> str:
    names = list(_BRANCH_WEIGHTS.keys())
    return rng.choices(names, weights=[_BRANCH_WEIGHTS[n] for n in names], k=1)[0]


def random_params(rng: random.Random) -> AnimParams:
    branch = _pick_branch(rng)
    fan_composition = rng.choice(list(FAN_LAYOUTS.keys()))

    n_cards = rng.randint(5, 8)
    fan_radius = rng.uniform(0.70, 1.00)
    fan_angle_span = rng.uniform(math.pi * 0.35, math.pi * 0.6)
    card_width = rng.uniform(0.08, 0.14)
    card_height = rng.uniform(0.40, 0.58)
    card_ior = rng.uniform(1.48, 1.60)
    card_cauchy_b = rng.uniform(5_000.0, 25_000.0)
    card_fill = rng.uniform(0.05, 0.12)
    sign = FAN_LAYOUTS[fan_composition]
    pivot_x = sign * rng.uniform(1.00, 1.25)
    pivot_y = rng.uniform(-0.15, 0.15)

    lights = _BRANCH_SAMPLERS[branch](rng, fan_composition)
    base_exp = -4.5 if len(lights) == 1 else -4.75
    look_exposure = base_exp + rng.uniform(-0.20, 0.15)

    return AnimParams(
        fan_composition=fan_composition, n_cards=n_cards, fan_radius=fan_radius,
        fan_angle_span=fan_angle_span, card_width=card_width, card_height=card_height,
        card_ior=card_ior, card_cauchy_b=card_cauchy_b, card_fill=card_fill,
        pivot_x=pivot_x, pivot_y=pivot_y,
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
    s = {k: avg(k) for k in agg}
    s["passing_frames"] = passes; s["total_frames"] = n_frames
    return passes >= int(GATE_MIN_PASSING_FRAMES_FRAC * n_frames), s


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
    base_dir = Path("renders/families/spectral_staircase")
    found = 0
    for attempt in range(1, MAX_ATTEMPTS + 1):
        p = random_params(rng)
        print(f"[{attempt}] branch={p.branch} fan={p.fan_composition} n={p.n_cards} "
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
