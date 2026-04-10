"""Waveguide Spiral — light trapped in a glass maze.

A spiral-shaped waveguide made of thick glass segments slowly rotates inside
a mirror box.  A white projector beam enters from the outside edge and
refracts at each bend, painting rainbow patterns along the spiral path.

The Archimedean spiral (r = a + b*theta) runs ~1.5 turns and is rebuilt
every frame with a rotation offset, giving a smooth rotation animation.
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
    glass,
    mirror_box,
    render,
    waveguide,
)
from anim.renderer import RenderSession, _resolve_frame_shot

# ---------------------------------------------------------------------------
# Scene constants
# ---------------------------------------------------------------------------

WALL = Material(metallic=1.0, roughness=0.1, transmission=0.0, cauchy_b=0.0, albedo=1.0)
CAMERA = Camera2D(center=[0, 0], width=3.2)

DURATION = 8.0

# Spiral glass: moderate dispersion, slight green tint, subtle fill
SPIRAL_GLASS = glass(1.50, cauchy_b=22_000, color=(0.9, 0.95, 0.9), fill=0.08)
WALL_ID = "wall"
SPIRAL_GLASS_ID = "spiral_glass"
MATERIALS = {WALL_ID: WALL, SPIRAL_GLASS_ID: SPIRAL_GLASS}

# ---------------------------------------------------------------------------
# Spiral geometry
# ---------------------------------------------------------------------------


def archimedean_spiral_points(
    n_points: int,
    inner_radius: float,
    outer_radius: float,
    max_theta: float,
    rotation: float,
) -> list[tuple[float, float]]:
    """Sample an Archimedean spiral r = a + b*theta.

    *inner_radius* at theta=0, *outer_radius* at theta=max_theta.
    *rotation* rotates the entire spiral (radians).
    Returns *n_points* evenly spaced in theta.
    """
    a = inner_radius
    b = (outer_radius - inner_radius) / max_theta
    points: list[tuple[float, float]] = []
    for i in range(n_points):
        theta = max_theta * i / (n_points - 1)
        r = a + b * theta
        angle = theta + rotation
        points.append((r * math.cos(angle), r * math.sin(angle)))
    return points


# ---------------------------------------------------------------------------
# Parameter space
# ---------------------------------------------------------------------------


@dataclass
class AnimParams:
    """Degrees of freedom for one waveguide spiral variant."""

    n_points: int  # spiral sample count (20-30)
    inner_radius: float  # spiral inner radius
    outer_radius: float  # spiral outer radius
    max_theta: float  # total angular extent (radians)
    wg_width: float  # waveguide thickness
    rotation_start: float  # initial rotation offset (radians)
    rotation_end: float  # final rotation offset (radians)
    beam_angle: float  # beam direction angle (radians)
    beam_distance: float  # beam distance from origin
    beam_offset: float  # perpendicular offset along mirror-box edge
    beam_spread: float  # projector cone width
    beam_drift: float  # angular drift amplitude


# ---------------------------------------------------------------------------
# Track builders
# ---------------------------------------------------------------------------


def rotation_track(p: AnimParams) -> Track:
    """Smooth rotation over the full duration."""
    return Track(
        [
            Key(0.0, p.rotation_start),
            Key(DURATION, p.rotation_end, ease="ease_in_out_sine"),
        ],
        wrap=Wrap.CLAMP,
    )


def beam_drift_track(base_angle: float, drift: float) -> Track:
    """Gentle beam angular drift — back and forth."""
    return Track(
        [
            Key(0.0, base_angle - drift / 2),
            Key(DURATION / 2, base_angle + drift / 2, ease="ease_in_out_sine"),
            Key(DURATION, base_angle - drift / 2, ease="ease_in_out_sine"),
        ],
        wrap=Wrap.CLAMP,
    )


# ---------------------------------------------------------------------------
# Scene builder
# ---------------------------------------------------------------------------


def build_animate(p: AnimParams):
    """Return an animate(ctx) -> Frame callable."""
    rot_trk = rotation_track(p)
    angle_trk = beam_drift_track(p.beam_angle, p.beam_drift)

    def animate(ctx: FrameContext) -> Frame:
        rot = float(rot_trk(ctx.time))
        beam_angle = float(angle_trk(ctx.time))

        spiral_pts = archimedean_spiral_points(
            n_points=p.n_points,
            inner_radius=p.inner_radius,
            outer_radius=p.outer_radius,
            max_theta=p.max_theta,
            rotation=rot,
        )

        wg_shapes = waveguide(spiral_pts, p.wg_width, SPIRAL_GLASS_ID, id_prefix="spiral")

        # Beam source position: on the mirror-box edge, aimed inward
        bx = p.beam_distance * math.cos(p.beam_angle)
        by = p.beam_distance * math.sin(p.beam_angle)
        # Offset perpendicular to beam direction for variety
        perp_angle = p.beam_angle + math.pi / 2
        bx += p.beam_offset * math.cos(perp_angle)
        by += p.beam_offset * math.sin(perp_angle)

        scene = Scene(
            materials=MATERIALS,
            shapes=[
                *mirror_box(1.6, 0.9, WALL_ID, id_prefix="wall"),
                *wg_shapes,
            ],
            lights=[
                ProjectorLight(
                    id="beam",
                    position=[bx, by],
                    direction=[math.cos(beam_angle), math.sin(beam_angle)],
                    source_radius=0.015,
                    spread=0.10,
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

# Combined beauty: contrast (interesting light patterns) AND color richness
MIN_CONTRAST_STD = 20.0
RICHNESS_THRESHOLD = 0.05
MIN_GOOD_FRAMES_FRACTION = 0.50


# ---------------------------------------------------------------------------
# Smart parameter sampling
# ---------------------------------------------------------------------------


def random_params(rng: random.Random) -> AnimParams:
    """Sample random waveguide spiral parameters."""
    n_points = rng.randint(20, 30)
    inner_radius = rng.uniform(0.08, 0.12)
    outer_radius = rng.uniform(0.50, 0.65)
    max_theta = rng.uniform(2.8 * math.pi, 3.2 * math.pi)  # ~1.5 turns
    wg_width = rng.uniform(0.03, 0.05)

    # Rotation: gentle oscillation, +/- pi/4 from a random start
    rotation_start = rng.uniform(0, math.tau)
    rotation_dir = rng.choice([-1, 1])
    rotation_end = rotation_start + rotation_dir * rng.uniform(math.pi / 6, math.pi / 4)

    # Beam from the outside of the spiral, aimed inward at the outer edge.
    # Pick a random radial direction, place the beam near the mirror-box wall.
    beam_base_angle = rng.uniform(0, math.tau)
    beam_distance = rng.uniform(1.2, 1.45)
    beam_offset = rng.uniform(-0.2, 0.2)

    # Aim approximately toward the center with a small random jitter
    aim_angle = beam_base_angle + math.pi + rng.uniform(-0.15, 0.15)

    beam_spread = rng.uniform(0.06, 0.12)
    beam_drift = rng.uniform(0.05, 0.15)

    return AnimParams(
        n_points=n_points,
        inner_radius=inner_radius,
        outer_radius=outer_radius,
        max_theta=max_theta,
        wg_width=wg_width,
        rotation_start=rotation_start,
        rotation_end=rotation_end,
        beam_angle=aim_angle,
        beam_distance=beam_distance,
        beam_offset=beam_offset,
        beam_spread=beam_spread,
        beam_drift=beam_drift,
    )


# ---------------------------------------------------------------------------
# Beauty check
# ---------------------------------------------------------------------------


def make_probe_shot() -> Shot:
    """Low-res shot for beauty evaluation."""
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


def check_beauty(p: AnimParams) -> tuple[bool, int, float, float]:
    """Render low-res frames; check contrast AND color richness.

    Returns (ok, n_good, avg_std, avg_richness).
    A frame is "good" if it has both sufficient contrast and color richness.
    At least MIN_GOOD_FRAMES_FRACTION of frames must be good.
    """
    animate = build_animate(p)
    shot = make_probe_shot()
    timeline = Timeline(DURATION, fps=PROBE_FPS)
    session = RenderSession(PROBE_W, PROBE_H, False)

    n_frames = timeline.total_frames
    good = 0
    total_std = 0.0
    total_richness = 0.0

    for fi in range(n_frames):
        ctx = timeline.context_at(fi)
        result = animate(ctx)
        cpp_shot = _resolve_frame_shot(shot, result, None)
        render_result = session.render_shot(cpp_shot, fi, True)

        fs = render_result.metrics
        cs = render_result.analysis.color
        total_std += fs.contrast_std
        total_richness += cs.richness
        if fs.contrast_std > MIN_CONTRAST_STD and cs.richness > RICHNESS_THRESHOLD:
            good += 1

    avg_std = total_std / n_frames if n_frames > 0 else 0.0
    avg_richness = total_richness / n_frames if n_frames > 0 else 0.0
    return good >= int(n_frames * MIN_GOOD_FRAMES_FRACTION), good, avg_std, avg_richness


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

    base_dir = Path("renders/families/waveguide_spiral")
    found = 0

    for attempt in range(1, MAX_ATTEMPTS + 1):
        p = random_params(rng)

        print(
            f"[{attempt}] pts={p.n_points} r=[{p.inner_radius:.2f},{p.outer_radius:.2f}] "
            f"w={p.wg_width:.3f} — checking beauty...",
            flush=True,
        )

        beauty_ok, n_good, avg_std, avg_richness = check_beauty(p)
        n_frames = Timeline(DURATION, fps=PROBE_FPS).total_frames
        print(
            f"  good={n_good}/{n_frames} avg_std={avg_std:.1f} avg_richness={avg_richness:.3f}",
            flush=True,
        )

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
        print("Try adjusting parameter ranges or lowering thresholds.")


if __name__ == "__main__":
    main()
