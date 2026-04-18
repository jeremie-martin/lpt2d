"""Cathedral Aperture — one dramatic shaft of light through a wall-slit.

A thick metallic wall divides the chamber. A single projector behind the wall
throws one shaft of light through a narrow opening. The shaft strikes a glass
prism in the foreground and breaks into a spectrum that paints the far wall.

Two light branches (explicit per-branch parameters, never mixed within a scene):

- warm: narrow orange projector, warm look temperature.
- white: full-spectrum projector, neutral look temperature.

Intent sentence (hero moment):
    A bright shaft is clearly visible passing through the slit, the prism
    catches it and casts a readable spectrum on the far wall, the rest of
    the chamber is dim but not black.
"""

from __future__ import annotations

import json
import math
import random
import sys
import time
from dataclasses import asdict, dataclass
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

# ---------------------------------------------------------------------------
# Scene constants (chamber walls + camera lifted from Crystal Field anchors)
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


# ---------------------------------------------------------------------------
# Parameter space
# ---------------------------------------------------------------------------


@dataclass
class AnimParams:
    """One cathedral-aperture variant."""

    # Slit wall
    slit_x: float
    slit_cy: float
    slit_gap: float
    wall_thickness: float

    # Prism
    prism_x: float
    prism_y: float
    prism_size: float
    prism_rotation_speed: float  # radians per DURATION
    prism_glass_idx: int

    # Projector (behind the wall, i.e. x < slit_x)
    beam_x: float
    beam_y: float
    beam_spread: float
    beam_source: str  # "line" or "ball"
    beam_source_radius: float
    beam_intensity: float

    # Branch selects spectrum + look temperature
    branch: str  # "warm" or "white"


# ---------------------------------------------------------------------------
# Scene builder
# ---------------------------------------------------------------------------


def _slit_wall_shapes(p: AnimParams) -> list:
    """Two thick vertical bars at slit_x leaving a horizontal opening."""
    half_g = p.slit_gap / 2
    top = thick_segment(
        (p.slit_x, p.slit_cy + half_g),
        (p.slit_x, CHAMBER_HH),
        p.wall_thickness,
        WALL_ID,
    )
    bot = thick_segment(
        (p.slit_x, -CHAMBER_HH),
        (p.slit_x, p.slit_cy - half_g),
        p.wall_thickness,
        WALL_ID,
    )
    top.id = "slit_top"
    bot.id = "slit_bot"
    return [top, bot]


def _projector(p: AnimParams) -> ProjectorLight:
    if p.branch == "warm":
        spectrum = LightSpectrum.range(wavelength_min=580, wavelength_max=650)
    elif p.branch == "white":
        spectrum = LightSpectrum.range(wavelength_min=380, wavelength_max=780)
    else:
        raise ValueError(f"unknown branch {p.branch!r}")
    return ProjectorLight(
        id="beam",
        position=[p.beam_x, p.beam_y],
        direction=[1.0, 0.0],
        source_radius=p.beam_source_radius,
        spread=p.beam_spread,
        source=p.beam_source,
        intensity=p.beam_intensity,
        spectrum=spectrum,
    )


def build_animate(p: AnimParams):
    def animate(ctx: FrameContext) -> Frame:
        t = ctx.time
        rot = p.prism_rotation_speed * t / DURATION
        prism_shape = prism(
            center=(p.prism_x, p.prism_y),
            size=p.prism_size,
            material_id=PRISM_IDS[p.prism_glass_idx % len(PRISM_IDS)],
            rotation=rot,
            id_prefix="prism",
        )
        scene = Scene(
            materials=MATERIALS,
            shapes=[
                *mirror_box(CHAMBER_HW, CHAMBER_HH, WALL_ID, id_prefix="chamber"),
                *_slit_wall_shapes(p),
                prism_shape,
            ],
            lights=[_projector(p)],
        )
        temp = 0.35 if p.branch == "warm" else 0.0
        look = Look(
            exposure=-5.0,
            gamma=2.0,
            tonemap="reinhardx",
            white_point=0.5,
            normalize="rays",
            temperature=temp,
        )
        return Frame(scene=scene, look=look)

    return animate


# ---------------------------------------------------------------------------
# Parameter sampling — per-branch explicit ranges
# ---------------------------------------------------------------------------


def _sample_warm(rng: random.Random) -> AnimParams:
    slit_x = rng.uniform(-0.80, -0.55)
    slit_cy = rng.uniform(-0.15, 0.15)
    slit_gap = rng.uniform(0.06, 0.12)
    wall_thickness = rng.uniform(0.03, 0.06)

    prism_x = rng.uniform(0.15, 0.75)
    prism_y = slit_cy + rng.uniform(-0.06, 0.06)
    prism_size = rng.uniform(0.15, 0.28)
    prism_rotation_speed = rng.uniform(-math.pi, math.pi) * 0.6
    prism_glass_idx = rng.randint(0, 1)

    beam_x = slit_x - rng.uniform(0.20, 0.35)
    beam_y = slit_cy + rng.uniform(-0.03, 0.03)
    beam_spread = rng.uniform(0.03, 0.06)
    beam_source = rng.choice(["ball", "line"])
    beam_source_radius = rng.uniform(0.005, 0.015)
    beam_intensity = rng.uniform(0.18, 0.38)

    return AnimParams(
        slit_x=slit_x,
        slit_cy=slit_cy,
        slit_gap=slit_gap,
        wall_thickness=wall_thickness,
        prism_x=prism_x,
        prism_y=prism_y,
        prism_size=prism_size,
        prism_rotation_speed=prism_rotation_speed,
        prism_glass_idx=prism_glass_idx,
        beam_x=beam_x,
        beam_y=beam_y,
        beam_spread=beam_spread,
        beam_source=beam_source,
        beam_source_radius=beam_source_radius,
        beam_intensity=beam_intensity,
        branch="warm",
    )


def _sample_white(rng: random.Random) -> AnimParams:
    slit_x = rng.uniform(-0.80, -0.55)
    slit_cy = rng.uniform(-0.15, 0.15)
    slit_gap = rng.uniform(0.06, 0.12)
    wall_thickness = rng.uniform(0.03, 0.06)

    prism_x = rng.uniform(0.15, 0.75)
    prism_y = slit_cy + rng.uniform(-0.06, 0.06)
    prism_size = rng.uniform(0.15, 0.28)
    prism_rotation_speed = rng.uniform(-math.pi, math.pi) * 0.6
    prism_glass_idx = rng.randint(0, 1)

    beam_x = slit_x - rng.uniform(0.20, 0.35)
    beam_y = slit_cy + rng.uniform(-0.03, 0.03)
    beam_spread = rng.uniform(0.03, 0.06)
    beam_source = rng.choice(["ball", "line"])
    beam_source_radius = rng.uniform(0.005, 0.015)
    beam_intensity = rng.uniform(0.55, 0.85)

    return AnimParams(
        slit_x=slit_x,
        slit_cy=slit_cy,
        slit_gap=slit_gap,
        wall_thickness=wall_thickness,
        prism_x=prism_x,
        prism_y=prism_y,
        prism_size=prism_size,
        prism_rotation_speed=prism_rotation_speed,
        prism_glass_idx=prism_glass_idx,
        beam_x=beam_x,
        beam_y=beam_y,
        beam_spread=beam_spread,
        beam_source=beam_source,
        beam_source_radius=beam_source_radius,
        beam_intensity=beam_intensity,
        branch="white",
    )


def random_params(rng: random.Random) -> AnimParams:
    branch = rng.choice(["warm", "white"])
    if branch == "warm":
        return _sample_warm(rng)
    return _sample_white(rng)


# ---------------------------------------------------------------------------
# Probe check
# ---------------------------------------------------------------------------

PROBE_FPS = 4
PROBE_W, PROBE_H = 640, 360

# Gates derived from the intent sentence. The chamber is mostly dim, so we
# allow a high near-black fraction, but we require strong contrast and a
# visible beam.
GATE_MEAN_LUMA = (0.06, 0.35)
GATE_CLIPPED_MAX = 0.06
GATE_NEAR_BLACK_MAX = 0.75
GATE_IDR_MIN = 45.0 / 255.0
# Calibrated against a visually good forced-seed white render (colorfulness ~0.017):
# in this family most pixels are neutral metallic, so the spectrum only lights
# up thin slivers and total colorfulness stays low.
GATE_COLORFULNESS_MIN_WHITE = 0.012
GATE_COLORFULNESS_MIN_WARM = 0.15
GATE_MIN_PASSING_FRAMES_FRAC = 0.4


def make_probe_shot() -> Shot:
    shot = Shot.preset("draft", width=PROBE_W, height=PROBE_H, rays=300_000, depth=10)
    shot.camera = CAMERA
    shot.look = shot.look.with_overrides(
        exposure=-5.0,
        gamma=2.0,
        tonemap="reinhardx",
        white_point=0.5,
        normalize="rays",
        temperature=0.0,
    )
    return shot


def check_beauty(p: AnimParams) -> tuple[bool, dict]:
    animate = build_animate(p)
    shot = make_probe_shot()
    timeline = Timeline(DURATION, fps=PROBE_FPS)
    session = RenderSession(PROBE_W, PROBE_H, False)

    color_min = GATE_COLORFULNESS_MIN_WARM if p.branch == "warm" else GATE_COLORFULNESS_MIN_WHITE

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
# Preview render (low-res, fast)
# ---------------------------------------------------------------------------


def make_preview_shot(width: int, height: int, rays: int) -> Shot:
    shot = Shot.preset("preview", width=width, height=height, rays=rays, depth=10)
    shot.camera = CAMERA
    shot.look = shot.look.with_overrides(
        exposure=-5.0,
        gamma=2.0,
        tonemap="reinhardx",
        white_point=0.5,
        normalize="rays",
        temperature=0.0,
    )
    return shot


def _params_to_dict(p: AnimParams) -> dict:
    return asdict(p)


def render_and_save(
    p: AnimParams,
    out_dir: Path,
    *,
    width: int,
    height: int,
    rays: int,
    fps: int,
) -> None:
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

MAX_ATTEMPTS = 200


def main() -> None:
    seed = (
        int(time.time())
        if "--seed" not in sys.argv
        else int(sys.argv[sys.argv.index("--seed") + 1])
    )
    target_count = int(sys.argv[sys.argv.index("-n") + 1]) if "-n" in sys.argv else 2
    hq = "--hq" in sys.argv
    width = 1280 if hq else 640
    height = 720 if hq else 360
    rays = 3_000_000 if hq else 800_000
    fps = 30
    rng = random.Random(seed)
    print(f"seed={seed} target={target_count} hq={hq}")

    base_dir = Path("renders/families/cathedral_aperture")
    found = 0

    for attempt in range(1, MAX_ATTEMPTS + 1):
        p = random_params(rng)
        print(
            f"[{attempt}] branch={p.branch} slit_x={p.slit_x:.2f} "
            f"prism=({p.prism_x:.2f},{p.prism_y:.2f}) — checking...",
            flush=True,
        )
        ok, summary = check_beauty(p)
        print(
            f"  passes={summary['passing_frames']}/{summary['total_frames']} "
            f"mean_luma={summary['mean_luma']:.3f} color={summary['color']:.3f} "
            f"idr={summary['idr']:.3f} near_black={summary['near_black']:.2f} "
            f"clipped={summary['clipped']:.3f}",
            flush=True,
        )
        if not ok:
            continue

        found += 1
        out_dir = base_dir / f"{found:03d}_{p.branch}"
        print(f"  FOUND #{found} — rendering...")
        render_and_save(p, out_dir, width=width, height=height, rays=rays, fps=fps)
        print("  done.\n")
        if found >= target_count:
            break

    if found == 0:
        print(f"No valid animation found in {MAX_ATTEMPTS} attempts.")


if __name__ == "__main__":
    main()
