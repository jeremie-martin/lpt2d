"""Mirror Corridor — beam bouncing through angled mirrors.

A series of small angled mirror segments placed inside the mirror box create
a zigzag corridor for a projector beam to bounce through. No glass, no
dispersion — pure metallic reflections creating geometric light paths.

The beam slowly rotates, causing the reflection pattern to shift and
evolve. Some configurations produce intricate multi-bounce patterns
that fill the room with crossing light rays.
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
    Segment,
    Shot,
    Timeline,
    Track,
    Wrap,
    frame_stats,
    mirror_box,
    render,
)
from anim.renderer import RenderSession, _resolve_frame_shot

# ---------------------------------------------------------------------------
# Scene constants
# ---------------------------------------------------------------------------

WALL = Material(metallic=1.0, roughness=0.1, transmission=0.0, cauchy_b=0.0, albedo=1.0)
# Interior mirrors: slightly different from walls — higher albedo, less roughness
MIRROR = Material(metallic=1.0, roughness=0.02, transmission=0.0, cauchy_b=0.0, albedo=0.95)
CAMERA = Camera2D(center=[0, 0], width=3.2)
DURATION = 8.0


# ---------------------------------------------------------------------------
# Parameter space
# ---------------------------------------------------------------------------


@dataclass
class MirrorSegment:
    """A positioned angled mirror."""

    cx: float
    cy: float
    length: float
    angle: float  # radians


@dataclass
class AnimParams:
    """Degrees of freedom for one mirror corridor variant."""

    mirrors: list[MirrorSegment]
    beam_x: float
    beam_y: float
    beam_angle_start: float
    beam_angle_end: float
    beam_spread: float


# ---------------------------------------------------------------------------
# Track builders
# ---------------------------------------------------------------------------


def beam_angle_track(p: AnimParams) -> Track:
    """Back-and-forth beam rotation."""
    return Track(
        [
            Key(0.0, p.beam_angle_start),
            Key(DURATION / 2, p.beam_angle_end, ease="ease_in_out_sine"),
            Key(DURATION, p.beam_angle_start, ease="ease_in_out_sine"),
        ],
        wrap=Wrap.CLAMP,
    )


# ---------------------------------------------------------------------------
# Scene builder
# ---------------------------------------------------------------------------


def build_mirror_shapes(mirrors: list[MirrorSegment]) -> list[Segment]:
    """Convert mirror specifications to Segment shapes."""
    shapes = []
    for i, m in enumerate(mirrors):
        half_len = m.length / 2
        dx = half_len * math.cos(m.angle)
        dy = half_len * math.sin(m.angle)
        shapes.append(
            Segment(
                id=f"mirror_{i}",
                a=[m.cx - dx, m.cy - dy],
                b=[m.cx + dx, m.cy + dy],
                material=MIRROR,
            )
        )
    return shapes


def build_animate(p: AnimParams):
    """Return an animate(ctx) -> Frame callable."""
    angle_trk = beam_angle_track(p)
    mirror_shapes = build_mirror_shapes(p.mirrors)

    def animate(ctx: FrameContext) -> Frame:
        angle = float(angle_trk(ctx.time))

        scene = Scene(
            shapes=[
                *mirror_box(1.6, 0.9, WALL, id_prefix="wall"),
                *mirror_shapes,
            ],
            lights=[
                ProjectorLight(
                    id="beam",
                    position=[p.beam_x, p.beam_y],
                    direction=[math.cos(angle), math.sin(angle)],
                    source_radius=0.008,
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

# Mirror corridors: check for good brightness (beam reaches the mirrors and bounces)
MIN_MEAN_LUM = 35
MIN_BRIGHT_FRACTION = 0.7


# ---------------------------------------------------------------------------
# Smart parameter sampling
# ---------------------------------------------------------------------------


def random_params(rng: random.Random) -> AnimParams:
    """Sample random mirror corridor parameters."""
    n_mirrors = rng.randint(3, 6)
    mirrors = []

    for _ in range(n_mirrors):
        cx = rng.uniform(-1.1, 1.1)
        cy = rng.uniform(-0.6, 0.6)
        length = rng.uniform(0.15, 0.40)
        angle = rng.uniform(0, math.pi)
        mirrors.append(MirrorSegment(cx=cx, cy=cy, length=length, angle=angle))

    # Beam from left side
    beam_x = -1.45
    beam_y = rng.uniform(-0.5, 0.5)

    # Aim roughly toward the mirror cluster
    avg_x = sum(m.cx for m in mirrors) / n_mirrors
    avg_y = sum(m.cy for m in mirrors) / n_mirrors
    base_angle = math.atan2(avg_y - beam_y, avg_x - beam_x)

    sweep = rng.uniform(0.08, 0.25)
    beam_angle_start = base_angle - sweep
    beam_angle_end = base_angle + sweep

    beam_spread = rng.uniform(0.03, 0.06)

    return AnimParams(
        mirrors=mirrors,
        beam_x=beam_x,
        beam_y=beam_y,
        beam_angle_start=beam_angle_start,
        beam_angle_end=beam_angle_end,
        beam_spread=beam_spread,
    )


# ---------------------------------------------------------------------------
# Beauty check
# ---------------------------------------------------------------------------


def make_probe_shot() -> Shot:
    shot = Shot.preset("draft", width=PROBE_W, height=PROBE_H, rays=200_000, depth=12)
    shot.camera = CAMERA
    shot.look = shot.look.with_overrides(
        exposure=-5.0, gamma=2.0, tonemap="reinhardx",
        white_point=0.5, normalize="rays", temperature=0.1,
    )
    return shot


def check_beauty(p: AnimParams) -> tuple[bool, float]:
    """Render low-res frames and check brightness. Returns (ok, avg_mean_lum)."""
    animate = build_animate(p)
    shot = make_probe_shot()
    timeline = Timeline(DURATION, fps=PROBE_FPS)
    session = RenderSession(PROBE_W, PROBE_H, False)

    n_frames = timeline.total_frames
    bright_count = 0
    total_mean = 0.0

    for fi in range(n_frames):
        ctx = timeline.context_at(fi)
        result = animate(ctx)
        cpp_shot = _resolve_frame_shot(shot, result, None)
        render_result = session.render_shot(cpp_shot, fi)
        fs = frame_stats(render_result.pixels, PROBE_W, PROBE_H)
        total_mean += fs.mean
        if fs.mean > MIN_MEAN_LUM:
            bright_count += 1

    avg_mean = total_mean / n_frames if n_frames > 0 else 0.0
    bright_frac = bright_count / n_frames if n_frames > 0 else 0.0
    return bright_frac >= MIN_BRIGHT_FRACTION, avg_mean


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
    """Serialize AnimParams including nested MirrorSegments."""
    d = {
        "beam_x": p.beam_x,
        "beam_y": p.beam_y,
        "beam_angle_start": p.beam_angle_start,
        "beam_angle_end": p.beam_angle_end,
        "beam_spread": p.beam_spread,
        "mirrors": [asdict(m) for m in p.mirrors],
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

    base_dir = Path("renders/families/mirror_corridor")
    found = 0

    for attempt in range(1, MAX_ATTEMPTS + 1):
        p = random_params(rng)

        print(
            f"[{attempt}] mirrors={len(p.mirrors)} — checking...",
            flush=True,
        )

        beauty_ok, avg_lum = check_beauty(p)
        print(f"  avg_luminance={avg_lum:.1f}", flush=True)

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
