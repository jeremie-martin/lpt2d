"""Orbital Prism — a fixed projector, a prism orbiting it on a circle.

The projector does not move. A single glass prism orbits a center point on a
slow circular path. Each time the prism crosses the projector beam, it catches
the light for a few frames and fans a spectrum across the chamber; between
crossings the chamber is quiet. The result reads like a lazy lighthouse.

Branches (explicit per-branch parameters):

- solo_warm        : one orange projector
- solo_white       : one full-spectrum projector
- duet_contrast    : warm + white projectors at opposite sides of the chamber,
                     each beam crossed twice per orbit

Beam orientation:

- beam_horizontal  : projector on one side wall, beam crosses horizontally
- beam_vertical    : projector on ceiling / floor, beam crosses vertically
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

BEAM_ORIENTATIONS = {"beam_horizontal", "beam_vertical"}


@dataclass
class LightDef:
    # Fixed-position projector (no motion during animation).
    side: str                # "left", "right", "top", "bottom"
    offset_tangent: float    # offset along the wall relative to center
    spread: float
    source: str
    source_radius: float
    intensity: float
    color: str


@dataclass
class AnimParams:
    beam_orientation: str     # "beam_horizontal" or "beam_vertical"
    orbit_center_x: float
    orbit_center_y: float
    orbit_radius: float
    orbit_rate: float         # revolutions per DURATION
    orbit_phase: float        # initial angle in radians
    prism_size: float
    prism_self_rotation: float
    prism_glass_idx: int
    lights: list[LightDef] = field(default_factory=list)
    branch: str = "solo_white"
    look_exposure: float = -4.6


def _light_position_and_dir(L: LightDef) -> tuple[tuple[float, float], tuple[float, float]]:
    if L.side == "left":
        return ((-CHAMBER_HW + 0.08, L.offset_tangent), (1.0, 0.0))
    if L.side == "right":
        return ((CHAMBER_HW - 0.08, L.offset_tangent), (-1.0, 0.0))
    if L.side == "top":
        return ((L.offset_tangent, CHAMBER_HH - 0.08), (0.0, -1.0))
    if L.side == "bottom":
        return ((L.offset_tangent, -CHAMBER_HH + 0.08), (0.0, 1.0))
    raise ValueError(L.side)


def _spectrum_for(color: str) -> LightSpectrum:
    if color == "warm":
        return LightSpectrum.range(wavelength_min=580, wavelength_max=650)
    if color == "white":
        return LightSpectrum.range(wavelength_min=380, wavelength_max=780)
    raise ValueError(color)


def _projectors(p: AnimParams) -> list[ProjectorLight]:
    out: list[ProjectorLight] = []
    for i, L in enumerate(p.lights):
        pos, dir_ = _light_position_and_dir(L)
        out.append(
            ProjectorLight(
                id=f"beam_{i}",
                position=list(pos),
                direction=list(dir_),
                source_radius=L.source_radius,
                spread=L.spread,
                source=L.source,
                intensity=L.intensity,
                spectrum=_spectrum_for(L.color),
            )
        )
    return out


def build_animate(p: AnimParams):
    def animate(ctx: FrameContext) -> Frame:
        t = ctx.time
        angle = p.orbit_phase + p.orbit_rate * math.tau * t / DURATION
        px = p.orbit_center_x + p.orbit_radius * math.cos(angle)
        py = p.orbit_center_y + p.orbit_radius * math.sin(angle)
        self_rot = p.prism_self_rotation * t / DURATION
        prism_shape = prism(
            center=(px, py),
            size=p.prism_size,
            material_id=PRISM_IDS[p.prism_glass_idx % len(PRISM_IDS)],
            rotation=self_rot + angle * 0.5,
            id_prefix="prism",
        )
        scene = Scene(
            materials=MATERIALS,
            shapes=[
                *mirror_box(CHAMBER_HW, CHAMBER_HH, WALL_ID, id_prefix="chamber"),
                prism_shape,
            ],
            lights=_projectors(p),
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


def _sample_light(rng: random.Random, *, side: str, color: str, intensity: float,
                  offset_tangent_range: tuple[float, float]) -> LightDef:
    return LightDef(
        side=side,
        offset_tangent=rng.uniform(*offset_tangent_range),
        spread=rng.uniform(0.04, 0.08),
        source=rng.choice(["ball", "line"]),
        source_radius=rng.uniform(0.008, 0.020),
        intensity=intensity,
        color=color,
    )


def _sides_for_orientation(orientation: str) -> tuple[str, str]:
    if orientation == "beam_horizontal":
        return ("left", "right")
    return ("top", "bottom")


def _tangent_range(orientation: str) -> tuple[float, float]:
    if orientation == "beam_horizontal":
        return (-0.25, 0.25)
    return (-0.45, 0.45)


def _sample_solo_warm(rng: random.Random, orientation: str) -> list[LightDef]:
    side = rng.choice(_sides_for_orientation(orientation))
    return [_sample_light(rng, side=side, color="warm",
                          intensity=rng.uniform(0.22, 0.38),
                          offset_tangent_range=_tangent_range(orientation))]


def _sample_solo_white(rng: random.Random, orientation: str) -> list[LightDef]:
    side = rng.choice(_sides_for_orientation(orientation))
    return [_sample_light(rng, side=side, color="white",
                          intensity=rng.uniform(0.55, 0.85),
                          offset_tangent_range=_tangent_range(orientation))]


def _sample_duet_contrast(rng: random.Random, orientation: str) -> list[LightDef]:
    a, b = _sides_for_orientation(orientation)
    return [
        _sample_light(rng, side=a, color="warm",
                      intensity=rng.uniform(0.15, 0.22),
                      offset_tangent_range=_tangent_range(orientation)),
        _sample_light(rng, side=b, color="white",
                      intensity=rng.uniform(0.40, 0.60),
                      offset_tangent_range=_tangent_range(orientation)),
    ]


_BRANCH_SAMPLERS = {
    "solo_warm": _sample_solo_warm,
    "solo_white": _sample_solo_white,
    "duet_contrast": _sample_duet_contrast,
}

_BRANCH_WEIGHTS = {"solo_warm": 1.0, "solo_white": 1.0, "duet_contrast": 1.6}


def _pick_branch(rng: random.Random) -> str:
    names = list(_BRANCH_WEIGHTS.keys())
    return rng.choices(names, weights=[_BRANCH_WEIGHTS[n] for n in names], k=1)[0]


def random_params(rng: random.Random) -> AnimParams:
    branch = _pick_branch(rng)
    orientation = rng.choice(list(BEAM_ORIENTATIONS))

    # Orbit center and radius chosen so the prism intersects the beam cleanly.
    orbit_center_x = rng.uniform(-0.30, 0.30)
    orbit_center_y = rng.uniform(-0.20, 0.20)
    orbit_radius = rng.uniform(0.35, 0.65)
    orbit_rate = rng.uniform(0.55, 1.25)
    orbit_phase = rng.uniform(0.0, math.tau)

    prism_size = rng.uniform(0.14, 0.23)
    prism_self_rotation = rng.uniform(-math.pi, math.pi) * 0.7
    prism_glass_idx = rng.randint(0, 1)

    lights = _BRANCH_SAMPLERS[branch](rng, orientation)
    base_exp = -4.5 if len(lights) == 1 else -4.75
    look_exposure = base_exp + rng.uniform(-0.20, 0.15)

    return AnimParams(
        beam_orientation=orientation,
        orbit_center_x=orbit_center_x,
        orbit_center_y=orbit_center_y,
        orbit_radius=orbit_radius,
        orbit_rate=orbit_rate,
        orbit_phase=orbit_phase,
        prism_size=prism_size,
        prism_self_rotation=prism_self_rotation,
        prism_glass_idx=prism_glass_idx,
        lights=lights,
        branch=branch,
        look_exposure=look_exposure,
    )


PROBE_FPS = 4
PROBE_W, PROBE_H = 640, 360
GATE_MEAN_LUMA = (0.10, 0.42)
GATE_CLIPPED_MAX = 0.09
GATE_NEAR_BLACK_MAX = 0.75
GATE_IDR_MIN = 40.0 / 255.0
GATE_COLORFULNESS_MIN_WARM_DOMINANT = 0.08
GATE_COLORFULNESS_MIN_OTHER = 0.010
GATE_MIN_PASSING_FRAMES_FRAC = 0.25  # prism is often outside beam, dimmer frames are fine


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
        agg["mean_luma"].append(st.mean_luma); agg["clipped"].append(st.clipped_channel_fraction)
        agg["near_black"].append(st.near_black_fraction); agg["idr"].append(st.interdecile_luma_range)
        agg["color"].append(st.colorfulness)
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
    width = 1280 if hq else 640
    height = 720 if hq else 360
    rays = 3_000_000 if hq else 800_000
    fps = 30
    rng = random.Random(seed)
    print(f"seed={seed} target={target_count} hq={hq}")
    base_dir = Path("renders/families/orbital_prism")
    found = 0
    for attempt in range(1, MAX_ATTEMPTS + 1):
        p = random_params(rng)
        print(f"[{attempt}] branch={p.branch} {p.beam_orientation} r={p.orbit_radius:.2f} "
              f"rate={p.orbit_rate:.2f} exp={p.look_exposure:.2f} — checking...", flush=True)
        ok, summary = check_beauty(p)
        print(f"  passes={summary['passing_frames']}/{summary['total_frames']} "
              f"mean_luma={summary['mean_luma']:.3f} color={summary['color']:.3f} "
              f"idr={summary['idr']:.3f} near_black={summary['near_black']:.2f} "
              f"clipped={summary['clipped']:.3f}", flush=True)
        if not ok:
            continue
        found += 1
        tag = f"{found:03d}_{p.branch}_{p.beam_orientation.replace('beam_','')}"
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
