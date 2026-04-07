"""Crystal Pendulum — oscillating glass shapes swinging through a beam.

Two or three glass prisms hang on pendulum-like sinusoidal paths, swinging
through a stationary projector beam. As each crystal passes through the light,
it refracts the beam into a momentary rainbow fan. The interplay of multiple
pendulums at different frequencies creates an organic, almost musical rhythm.

The beam is stationary. All motion comes from the swinging crystals.
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
    color_stats,
    glass,
    mirror_box,
    prism,
    regular_polygon,
    render,
)
from anim.renderer import RenderSession, _resolve_frame_shot

# ---------------------------------------------------------------------------
# Scene constants
# ---------------------------------------------------------------------------

WALL = Material(metallic=1.0, roughness=0.1, transmission=0.0, cauchy_b=0.0, albedo=1.0)
CAMERA = Camera2D(center=[0, 0], width=3.2)
DURATION = 8.0

# Different glass types for each pendulum crystal
GLASSES = [
    glass(1.52, cauchy_b=28_000, color=(0.968, 0.968, 0.968), fill=0.15),
    glass(1.62, cauchy_b=35_000, color=(0.93, 0.95, 1.0), fill=0.12),
    glass(1.45, cauchy_b=22_000, color=(1.0, 0.95, 0.92), fill=0.10),
]

# ---------------------------------------------------------------------------
# Parameter space
# ---------------------------------------------------------------------------


@dataclass
class PendulumDef:
    """One oscillating crystal."""

    rest_x: float  # center of oscillation
    rest_y: float  # vertical position
    amplitude: float  # horizontal swing amplitude
    phase: float  # phase offset (radians)
    frequency: float  # oscillations per duration (>0)
    size: float  # crystal size
    n_sides: int  # polygon sides (3=prism, 4=square, 5=pentagon, 6=hex)
    rotation_speed: float  # crystal self-rotation over duration
    glass_idx: int  # index into GLASSES


@dataclass
class AnimParams:
    """Degrees of freedom for one crystal pendulum variant."""

    pendulums: list[PendulumDef]
    beam_x: float  # projector position
    beam_y: float  # projector vertical position
    beam_angle: float  # fixed beam direction
    beam_spread: float  # cone width


# ---------------------------------------------------------------------------
# Scene builder
# ---------------------------------------------------------------------------


def build_animate(p: AnimParams):
    """Return an animate(ctx) -> Frame callable."""

    def animate(ctx: FrameContext) -> Frame:
        t = ctx.time
        crystal_shapes = []

        for i, pend in enumerate(p.pendulums):
            # Sinusoidal horizontal oscillation
            x = pend.rest_x + pend.amplitude * math.sin(
                pend.frequency * math.tau * t / DURATION + pend.phase
            )
            y = pend.rest_y
            rot = pend.rotation_speed * t / DURATION

            mat = GLASSES[pend.glass_idx % len(GLASSES)]
            if pend.n_sides == 3:
                shape = prism(
                    center=(x, y), size=pend.size, material=mat,
                    rotation=rot, id_prefix=f"crystal_{i}",
                )
            else:
                shape = regular_polygon(
                    center=(x, y), radius=pend.size, n=pend.n_sides,
                    material=mat, rotation=rot, id_prefix=f"crystal_{i}",
                )
            crystal_shapes.append(shape)

        scene = Scene(
            shapes=[
                *mirror_box(1.6, 0.9, WALL, id_prefix="wall"),
                *crystal_shapes,
            ],
            lights=[
                ProjectorLight(
                    id="beam",
                    position=[p.beam_x, p.beam_y],
                    direction=[math.cos(p.beam_angle), math.sin(p.beam_angle)],
                    source_radius=0.01,
                    spread=p.beam_spread,
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
    """Sample random crystal pendulum parameters."""
    n_pendulums = rng.randint(2, 3)
    pendulums = []

    for i in range(n_pendulums):
        rest_x = rng.uniform(-0.6, 0.6)
        rest_y = rng.uniform(-0.4, 0.4)
        amplitude = rng.uniform(0.3, 0.7)
        phase = rng.uniform(0, math.tau)
        frequency = rng.uniform(1.0, 2.5)
        size = rng.uniform(0.15, 0.30)
        n_sides = rng.choice([3, 3, 4, 5, 6])  # bias toward prisms
        rotation_speed = rng.uniform(-math.pi, math.pi) * 2
        glass_idx = i % len(GLASSES)

        pendulums.append(PendulumDef(
            rest_x=rest_x,
            rest_y=rest_y,
            amplitude=amplitude,
            phase=phase,
            frequency=frequency,
            size=size,
            n_sides=n_sides,
            rotation_speed=rotation_speed,
            glass_idx=glass_idx,
        ))

    # Beam from left, aimed roughly toward center
    beam_x = -1.45
    beam_y = rng.uniform(-0.3, 0.3)
    beam_angle = math.atan2(-beam_y, 1.4) + rng.uniform(-0.1, 0.1)
    beam_spread = rng.uniform(0.04, 0.07)

    return AnimParams(
        pendulums=pendulums,
        beam_x=beam_x,
        beam_y=beam_y,
        beam_angle=beam_angle,
        beam_spread=beam_spread,
    )


# ---------------------------------------------------------------------------
# Beauty check
# ---------------------------------------------------------------------------


def make_probe_shot() -> Shot:
    shot = Shot.preset("draft", width=PROBE_W, height=PROBE_H, rays=200_000, depth=10)
    shot.camera = CAMERA
    shot.look = shot.look.with_overrides(
        exposure=-5.0, gamma=2.0, tonemap="reinhardx",
        white_point=0.5, normalize="rays", temperature=0.1,
    )
    return shot


def check_beauty(p: AnimParams) -> tuple[bool, int, float]:
    """Render low-res frames and count colorful ones."""
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
        render_result = session.render_shot(cpp_shot, fi)
        cs = color_stats(render_result.pixels, PROBE_W, PROBE_H)
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
        exposure=-5.0, gamma=2.0, tonemap="reinhardx",
        white_point=0.5, normalize="rays", temperature=0.1,
    )
    return shot


def _params_to_dict(p: AnimParams) -> dict:
    d = {
        "beam_x": p.beam_x,
        "beam_y": p.beam_y,
        "beam_angle": p.beam_angle,
        "beam_spread": p.beam_spread,
        "pendulums": [asdict(pd) for pd in p.pendulums],
    }
    return d


def render_and_save(p: AnimParams, out_dir: Path, width: int = 1920, height: int = 1080, rays: int = 5_000_000) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)

    params_path = out_dir / "params.json"
    params_path.write_text(json.dumps(_params_to_dict(p), indent=2))
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
    seed = int(time.time()) if "--seed" not in sys.argv else int(sys.argv[sys.argv.index("--seed") + 1])
    target_count = int(sys.argv[sys.argv.index("-n") + 1]) if "-n" in sys.argv else 1
    hq = "--hq" in sys.argv
    width = 1920 if hq else 320
    height = 1080 if hq else 180
    rays = 5_000_000 if hq else 2_000_000
    rng = random.Random(seed)
    print(f"seed={seed} target={target_count} hq={hq}")

    base_dir = Path("renders/families/crystal_pendulum")
    found = 0

    for attempt in range(1, MAX_ATTEMPTS + 1):
        p = random_params(rng)

        print(
            f"[{attempt}] pendulums={len(p.pendulums)} — checking...",
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
        print(f"  done.\n")

        if found >= target_count:
            break

    if found == 0:
        print(f"No valid animation found in {MAX_ATTEMPTS} attempts.")


if __name__ == "__main__":
    main()
