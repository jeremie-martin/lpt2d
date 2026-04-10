"""Lens Caustics — ball lens with sweeping beam creating focused light patterns.

A single ball lens (or biconvex lens) sits in a mirror box. A projector beam
slowly sweeps past, and the lens focuses the light into beautiful caustic
patterns that dance across the walls. The simplicity is the point: one lens,
one beam, pure physics.

The camera has a subtle slow zoom to add gentle dynamism.
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
    Key,
    Look,
    Material,
    ProjectorLight,
    Scene,
    Shot,
    Timeline,
    Track,
    Wrap,
    ball_lens,
    glass,
    mirror_box,
    render,
)
from anim.renderer import RenderSession, _resolve_frame_shot

# ---------------------------------------------------------------------------
# Scene constants
# ---------------------------------------------------------------------------

WALL = Material(metallic=1.0, roughness=0.1, transmission=0.0, cauchy_b=0.0, albedo=1.0)
DURATION = 8.0

# High-dispersion glass for strong rainbow caustics
LENS_GLASS = glass(1.52, cauchy_b=35_000, color=(0.95, 0.97, 1.0), fill=0.12)
WALL_ID = "wall"
LENS_GLASS_ID = "lens_glass"
MATERIALS = {WALL_ID: WALL, LENS_GLASS_ID: LENS_GLASS}

# ---------------------------------------------------------------------------
# Parameter space
# ---------------------------------------------------------------------------


@dataclass
class AnimParams:
    """Degrees of freedom for one lens caustics variant."""

    lens_x: float  # lens center x
    lens_y: float  # lens center y
    lens_radius: float  # ball lens radius
    beam_x: float  # projector x position
    beam_y: float  # projector y position
    beam_angle_start: float  # angle at t=0
    beam_angle_mid: float  # angle at t=DURATION/2
    beam_angle_end: float  # angle at t=DURATION
    beam_spread: float  # projector cone width
    cam_width_start: float  # camera zoom start
    cam_width_end: float  # camera zoom end (subtle)


# ---------------------------------------------------------------------------
# Track builders
# ---------------------------------------------------------------------------


def beam_angle_track(p: AnimParams) -> Track:
    """Three-key sweep: start -> mid -> end."""
    return Track(
        [
            Key(0.0, p.beam_angle_start),
            Key(DURATION / 2, p.beam_angle_mid, ease="ease_in_out_sine"),
            Key(DURATION, p.beam_angle_end, ease="ease_in_out_sine"),
        ],
        wrap=Wrap.CLAMP,
    )


def cam_width_track(p: AnimParams) -> Track:
    """Subtle camera zoom."""
    return Track(
        [
            Key(0.0, p.cam_width_start),
            Key(DURATION, p.cam_width_end, ease="ease_in_out_sine"),
        ],
        wrap=Wrap.CLAMP,
    )


# ---------------------------------------------------------------------------
# Scene builder
# ---------------------------------------------------------------------------


def build_animate(p: AnimParams):
    """Return an animate(ctx) -> Frame callable."""
    angle_trk = beam_angle_track(p)
    cam_trk = cam_width_track(p)

    lens_shapes = ball_lens(
        center=(p.lens_x, p.lens_y),
        radius=p.lens_radius,
        material_id=LENS_GLASS_ID,
        id_prefix="lens",
    )

    def animate(ctx: FrameContext) -> Frame:
        angle = float(angle_trk(ctx.time))
        cam_w = float(cam_trk(ctx.time))

        scene = Scene(
            materials=MATERIALS,
            shapes=[
                *mirror_box(1.6, 0.9, WALL_ID, id_prefix="wall"),
                *lens_shapes,
            ],
            lights=[
                ProjectorLight(
                    id="beam",
                    position=[p.beam_x, p.beam_y],
                    direction=[math.cos(angle), math.sin(angle)],
                    source_radius=0.01,
                    spread=p.beam_spread,
                    source="ball",
                    intensity=1.0,
                ),
            ],
        )
        return Frame(
            scene=scene,
            camera=Camera2D(center=[0, 0], width=cam_w),
            look=Look(exposure=-5.5),
        )

    return animate


# ---------------------------------------------------------------------------
# Search tuning
# ---------------------------------------------------------------------------

MAX_ATTEMPTS = 500
PROBE_FPS = 4
PROBE_W, PROBE_H = 640, 360

# For caustics, the beauty is in focused light patterns, not necessarily color.
# Check for good contrast (high std dev = interesting patterns)
MIN_CONTRAST_STD = 30.0
MIN_GOOD_FRAMES_FRACTION = 0.6


# ---------------------------------------------------------------------------
# Smart parameter sampling
# ---------------------------------------------------------------------------


def random_params(rng: random.Random) -> AnimParams:
    """Sample random lens caustics parameters."""
    lens_x = rng.uniform(-0.2, 0.2)
    lens_y = rng.uniform(-0.2, 0.2)
    lens_radius = rng.uniform(0.20, 0.35)

    # Beam from left side, offset vertically from lens
    beam_x = -1.45
    beam_y = rng.uniform(-0.6, 0.6)

    # Angle to aim at lens center
    angle_to_lens = math.atan2(lens_y - beam_y, lens_x - beam_x)

    # Wide sweep across the lens — beam moves from one side to the other
    sweep_half = rng.uniform(0.15, 0.35)
    beam_angle_start = angle_to_lens - sweep_half
    beam_angle_mid = angle_to_lens + rng.uniform(-0.05, 0.05)
    beam_angle_end = angle_to_lens + sweep_half

    beam_spread = rng.uniform(0.04, 0.07)

    # Subtle camera zoom: ±5% around 3.2
    cam_width_start = 3.2 * rng.uniform(0.95, 1.02)
    cam_width_end = 3.2 * rng.uniform(0.93, 1.0)

    return AnimParams(
        lens_x=lens_x,
        lens_y=lens_y,
        lens_radius=lens_radius,
        beam_x=beam_x,
        beam_y=beam_y,
        beam_angle_start=beam_angle_start,
        beam_angle_mid=beam_angle_mid,
        beam_angle_end=beam_angle_end,
        beam_spread=beam_spread,
        cam_width_start=cam_width_start,
        cam_width_end=cam_width_end,
    )


# ---------------------------------------------------------------------------
# Beauty check
# ---------------------------------------------------------------------------


def make_probe_shot() -> Shot:
    shot = Shot.preset("draft", width=PROBE_W, height=PROBE_H, rays=200_000, depth=10)
    shot.camera = Camera2D(center=[0, 0], width=3.2)
    shot.look = shot.look.with_overrides(
        exposure=-5.5,
        gamma=2.0,
        tonemap="reinhardx",
        white_point=0.5,
        normalize="rays",
        temperature=0.1,
    )
    return shot


def check_beauty(p: AnimParams) -> tuple[bool, int, float]:
    """Render low-res frames and check contrast. Returns (ok, n_good, avg_std)."""
    animate = build_animate(p)
    shot = make_probe_shot()
    timeline = Timeline(DURATION, fps=PROBE_FPS)
    session = RenderSession(PROBE_W, PROBE_H, False)

    n_frames = timeline.total_frames
    good = 0
    total_std = 0.0

    for fi in range(n_frames):
        ctx = timeline.context_at(fi)
        result = animate(ctx)
        cpp_shot = _resolve_frame_shot(shot, result, None)
        render_result = session.render_shot(cpp_shot, fi)
        fs = render_result.metrics
        total_std += fs.std_dev
        if fs.std_dev > MIN_CONTRAST_STD:
            good += 1

    avg_std = total_std / n_frames if n_frames > 0 else 0.0
    return good >= int(n_frames * MIN_GOOD_FRAMES_FRACTION), good, avg_std


# ---------------------------------------------------------------------------
# HQ render
# ---------------------------------------------------------------------------


def make_hq_shot(width: int = 1920, height: int = 1080, rays: int = 5_000_000) -> Shot:
    shot = Shot.preset("production", width=width, height=height, rays=rays, depth=12)
    shot.camera = Camera2D(center=[0, 0], width=3.2)
    shot.look = shot.look.with_overrides(
        exposure=-5.5,
        gamma=2.0,
        tonemap="reinhardx",
        white_point=0.5,
        normalize="rays",
        temperature=0.1,
    )
    return shot


def render_and_save(
    p: AnimParams, out_dir: Path, width: int = 1920, height: int = 1080, rays: int = 5_000_000
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)

    params_path = out_dir / "params.json"
    params_path.write_text(json.dumps(asdict(p), indent=2))
    print(f"  params -> {params_path}")

    animate = build_animate(p)
    settings = make_hq_shot(width, height, rays)
    timeline = Timeline(DURATION, fps=60)
    video_path = out_dir / "video.mp4"
    render(animate, timeline, str(video_path), settings=settings, crf=16)
    print(f"  video  -> {video_path}")


# ---------------------------------------------------------------------------
# Main search loop
# ---------------------------------------------------------------------------


def main() -> None:
    seed = (
        int(time.time())
        if "--seed" not in sys.argv
        else int(sys.argv[sys.argv.index("--seed") + 1])
    )
    target_count = int(sys.argv[sys.argv.index("-n") + 1]) if "-n" in sys.argv else 1
    hq = "--hq" in sys.argv
    width = 1920 if hq else 320
    height = 1080 if hq else 180
    rays = 5_000_000 if hq else 2_000_000
    rng = random.Random(seed)
    print(f"seed={seed} target={target_count} hq={hq}")

    base_dir = Path("renders/families/lens_caustics")
    found = 0

    for attempt in range(1, MAX_ATTEMPTS + 1):
        p = random_params(rng)

        print(
            f"[{attempt}] lens_r={p.lens_radius:.3f} pos=({p.lens_x:.2f},{p.lens_y:.2f}) — checking...",
            flush=True,
        )

        beauty_ok, n_good, avg_std = check_beauty(p)
        print(f"  good_frames={n_good} avg_std={avg_std:.1f}", flush=True)

        if not beauty_ok:
            continue

        found += 1
        out_dir = base_dir / f"{found:03d}"
        print(f"  FOUND #{found} — rendering...")
        render_and_save(p, out_dir, width, height, rays)
        print("  done.\n")

        if found >= target_count:
            break

    if found == 0:
        print(f"No valid animation found in {MAX_ATTEMPTS} attempts.")


if __name__ == "__main__":
    main()
