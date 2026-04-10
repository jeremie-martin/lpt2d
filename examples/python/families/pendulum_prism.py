"""Pendulum Prism — a crystal on a string swinging through a stationary beam.

One large glass prism swings back and forth like a pendulum through a fixed
white projector beam.  The prism's horizontal position oscillates sinusoidally,
and it also rotates slowly on its own axis.  When the crystal passes through
the beam a pulsing rainbow fan appears and disappears, creating a breathing
rhythm of dispersion.

The beam is stationary.  All drama comes from the moving prism.
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

# ---------------------------------------------------------------------------
# Scene constants
# ---------------------------------------------------------------------------

WALL = Material(metallic=1.0, roughness=0.1, transmission=0.0, cauchy_b=0.0, albedo=1.0)
CAMERA = Camera2D(center=[0, 0], width=3.2)
DURATION = 8.0

# High-dispersion crown glass with subtle fill for visibility
PRISM_GLASS = glass(1.52, cauchy_b=30_000, color=(0.968, 0.968, 0.968), fill=0.15)
WALL_ID = "wall"
PRISM_GLASS_ID = "prism_glass"
MATERIALS = {WALL_ID: WALL, PRISM_GLASS_ID: PRISM_GLASS}

# ---------------------------------------------------------------------------
# Parameter space
# ---------------------------------------------------------------------------


@dataclass
class AnimParams:
    """Degrees of freedom for one pendulum prism variant."""

    prism_size: float  # equilateral triangle size (0.25-0.40)
    rest_x: float  # center of horizontal oscillation
    rest_y: float  # fixed vertical position
    amplitude: float  # horizontal swing amplitude
    phase: float  # oscillation phase offset (rad)
    frequency: float  # oscillation cycles per duration
    rotation_start: float  # initial prism orientation (rad)
    rotation_speed: float  # self-rotation over full duration (rad)
    beam_y: float  # projector vertical position (x is fixed at -1.45)
    beam_angle: float  # fixed beam direction (rad)


# ---------------------------------------------------------------------------
# Scene builder
# ---------------------------------------------------------------------------


def build_animate(p: AnimParams):
    """Return an animate(ctx) -> Frame callable."""

    def animate(ctx: FrameContext) -> Frame:
        t = ctx.time

        # Sinusoidal horizontal oscillation
        x = p.rest_x + p.amplitude * math.sin(p.frequency * math.tau * t / DURATION + p.phase)
        y = p.rest_y

        # Slow self-rotation
        rot = p.rotation_start + p.rotation_speed * t / DURATION

        crystal = prism(
            center=(x, y),
            size=p.prism_size,
            material_id=PRISM_GLASS_ID,
            rotation=rot,
            id_prefix="pendulum",
        )

        scene = Scene(
            materials=MATERIALS,
            shapes=[
                *mirror_box(1.6, 0.9, WALL_ID, id_prefix="wall"),
                crystal,
            ],
            lights=[
                ProjectorLight(
                    id="beam",
                    position=[-1.45, p.beam_y],
                    direction=[math.cos(p.beam_angle), math.sin(p.beam_angle)],
                    source_radius=0.01,
                    spread=0.05,
                    source="ball",
                    intensity=1.0,
                ),
            ],
        )
        return Frame(scene=scene, look=Look(exposure=-5.0))

    return animate


# ---------------------------------------------------------------------------
# Search tuning
# ---------------------------------------------------------------------------

MAX_ATTEMPTS = 500
PROBE_FPS = 4
PROBE_W, PROBE_H = 640, 360

RICHNESS_THRESHOLD = 0.30
MIN_COLORFUL_SECONDS = 2.0


# ---------------------------------------------------------------------------
# Smart parameter sampling
# ---------------------------------------------------------------------------


def random_params(rng: random.Random) -> AnimParams:
    """Sample random pendulum prism parameters."""
    prism_size = rng.uniform(0.25, 0.40)
    rest_x = rng.uniform(-0.2, 0.2)
    rest_y = rng.uniform(-0.25, 0.25)
    amplitude = rng.uniform(0.35, 0.75)
    phase = rng.uniform(0, math.tau)
    frequency = rng.uniform(1.0, 2.5)
    rotation_start = rng.uniform(0, math.tau)
    rotation_speed = rng.choice([-1, 1]) * rng.uniform(math.pi * 0.3, math.pi * 1.5)

    # Beam enters from the left wall, aimed roughly toward center
    beam_y = rng.uniform(-0.3, 0.3)
    beam_angle = math.atan2(-beam_y, 1.4) + rng.uniform(-0.08, 0.08)

    return AnimParams(
        prism_size=prism_size,
        rest_x=rest_x,
        rest_y=rest_y,
        amplitude=amplitude,
        phase=phase,
        frequency=frequency,
        rotation_start=rotation_start,
        rotation_speed=rotation_speed,
        beam_y=beam_y,
        beam_angle=beam_angle,
    )


# ---------------------------------------------------------------------------
# Beauty check
# ---------------------------------------------------------------------------


def make_probe_shot() -> Shot:
    """Low-res shot for color evaluation."""
    shot = Shot.preset("draft", width=PROBE_W, height=PROBE_H, rays=200_000, depth=10)
    shot.camera = CAMERA
    shot.look = shot.look.with_overrides(
        exposure=-5.0,
        gamma=2.0,
        tonemap="reinhardx",
        white_point=0.5,
        normalize="rays",
        temperature=0.1,
    )
    return shot


def check_beauty(p: AnimParams) -> tuple[bool, int, float]:
    """Render low-res frames and count colorful ones. Returns (ok, n_colorful, avg_richness)."""
    animate = build_animate(p)
    shot = make_probe_shot()
    timeline = Timeline(DURATION, fps=PROBE_FPS)
    session = RenderSession(PROBE_W, PROBE_H, False)

    n_frames = timeline.total_frames
    colorful = 0
    total_richness = 0.0

    for fi in range(n_frames):
        ctx = timeline.context_at(fi)
        result = animate(ctx)
        cpp_shot = _resolve_frame_shot(shot, result, None)
        render_result = session.render_shot(cpp_shot, fi, True)
        cs = render_result.analysis.color
        total_richness += cs.color_richness
        if cs.color_richness > RICHNESS_THRESHOLD:
            colorful += 1

    avg_richness = total_richness / n_frames if n_frames > 0 else 0.0
    min_colorful_frames = int(MIN_COLORFUL_SECONDS * PROBE_FPS)
    return colorful >= min_colorful_frames, colorful, avg_richness


# ---------------------------------------------------------------------------
# HQ render
# ---------------------------------------------------------------------------


def make_hq_shot(width: int = 1920, height: int = 1080, rays: int = 5_000_000) -> Shot:
    shot = Shot.preset("production", width=width, height=height, rays=rays, depth=12)
    shot.camera = CAMERA
    shot.look = shot.look.with_overrides(
        exposure=-5.0,
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

    base_dir = Path("renders/families/pendulum_prism")
    found = 0

    for attempt in range(1, MAX_ATTEMPTS + 1):
        p = random_params(rng)

        print(
            f"[{attempt}] size={p.prism_size:.3f} amp={p.amplitude:.3f} freq={p.frequency:.2f} — checking...",
            flush=True,
        )

        beauty_ok, n_colorful, avg_richness = check_beauty(p)
        colorful_seconds = n_colorful / PROBE_FPS
        print(f"  colorful={colorful_seconds:.1f}s avg_richness={avg_richness:.3f}", flush=True)

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
        print("Try adjusting parameter ranges or lowering RICHNESS_THRESHOLD.")


if __name__ == "__main__":
    main()
