"""Mirror Constellation — dense arc of shattered mirror fragments.

Many small mirror segments (30-80) arranged roughly along an arc or partial
disc. Each mirror has a slight random offset from the perfect arc position,
creating a shattered-mirror field. A projector light positioned inside or
near the arc rotates slowly, sweeping across the fragments and producing a
dense web of geometric reflections that shift as the beam moves.
"""

from __future__ import annotations

import json
import math
import random
import sys
import time
from dataclasses import dataclass
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
    mirror_box,
    render,
)
from anim.renderer import RenderSession, _resolve_frame_shot

# ---------------------------------------------------------------------------
# Scene constants
# ---------------------------------------------------------------------------

WALL = Material(metallic=1.0, roughness=0.1, transmission=0.0, cauchy_b=0.0, albedo=1.0)
MIRROR = Material(metallic=1.0, roughness=0.02, transmission=0.0, cauchy_b=0.0, albedo=0.95)
CAMERA = Camera2D(center=[0, 0], width=3.2)
DURATION = 8.0
WALL_ID = "wall"
MIRROR_ID = "mirror"
MATERIALS = {WALL_ID: WALL, MIRROR_ID: MIRROR}


# ---------------------------------------------------------------------------
# Parameter space
# ---------------------------------------------------------------------------


@dataclass
class MirrorFragment:
    """A single mirror shard along the constellation arc."""

    cx: float
    cy: float
    length: float
    angle: float  # radians


@dataclass
class AnimParams:
    """Degrees of freedom for one mirror constellation variant."""

    arc_center_x: float
    arc_center_y: float
    arc_radius: float
    arc_start_angle: float
    arc_sweep: float
    n_mirrors: int
    mirror_scatter: float
    mirrors: list[MirrorFragment]
    beam_x: float
    beam_y: float
    beam_angle_start: float
    beam_angle_end: float
    beam_spread: float


# ---------------------------------------------------------------------------
# Track builders
# ---------------------------------------------------------------------------


def beam_angle_track(p: AnimParams) -> Track:
    """Back-and-forth beam rotation with sinusoidal easing."""
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


def build_mirror_shapes(mirrors: list[MirrorFragment]) -> list[Segment]:
    """Convert mirror fragment specifications to Segment shapes."""
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
                material_id=MIRROR_ID,
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
            materials=MATERIALS,
            shapes=[
                *mirror_box(1.6, 0.9, WALL_ID, id_prefix="wall"),
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
        return Frame(scene=scene, look=Look(exposure=-5.5))

    return animate


# ---------------------------------------------------------------------------
# Search tuning
# ---------------------------------------------------------------------------

MAX_ATTEMPTS = 500
PROBE_FPS = 4
PROBE_W, PROBE_H = 640, 360

# Constellation check: good contrast (many reflections) and reasonable brightness
MIN_MEAN_LUM = 30.0 / 255.0
MAX_MEAN_LUM = 180.0 / 255.0
MIN_STD_LUM = 15.0 / 255.0
MIN_BRIGHT_FRACTION = 0.6


# ---------------------------------------------------------------------------
# Smart parameter sampling
# ---------------------------------------------------------------------------


def random_params(rng: random.Random) -> AnimParams:
    """Sample random mirror constellation parameters."""
    # Arc geometry
    arc_center_x = rng.uniform(-0.3, 0.3)
    arc_center_y = rng.uniform(-0.2, 0.2)
    arc_radius = rng.uniform(0.4, 0.8)
    arc_start_angle = rng.uniform(0, math.tau)
    arc_sweep = rng.uniform(math.pi / 2, 3 * math.pi / 2)

    # Mirror count and scatter
    n_mirrors = rng.randint(30, 80)
    mirror_scatter = rng.uniform(0.02, 0.08)

    # Place mirror fragments along the arc with jitter
    mirrors: list[MirrorFragment] = []
    for i in range(n_mirrors):
        # Evenly spaced along the arc, then scattered
        t = i / max(n_mirrors - 1, 1)
        theta = arc_start_angle + t * arc_sweep

        # Radial and tangential scatter
        r_offset = rng.gauss(0, mirror_scatter)
        t_offset = rng.gauss(0, mirror_scatter / arc_radius) if arc_radius > 0.01 else 0
        actual_theta = theta + t_offset

        r = arc_radius + r_offset
        cx = arc_center_x + r * math.cos(actual_theta)
        cy = arc_center_y + r * math.sin(actual_theta)

        # Mirror orientation: roughly tangent to the arc, with some randomness
        tangent_angle = actual_theta + math.pi / 2
        angle_jitter = rng.gauss(0, 0.3)
        angle = tangent_angle + angle_jitter

        # Short mirror segments
        length = rng.uniform(0.03, 0.06)

        mirrors.append(MirrorFragment(cx=cx, cy=cy, length=length, angle=angle))

    # Beam position: inside or near the arc center
    beam_offset = rng.uniform(0, arc_radius * 0.5)
    beam_theta = rng.uniform(0, math.tau)
    beam_x = arc_center_x + beam_offset * math.cos(beam_theta)
    beam_y = arc_center_y + beam_offset * math.sin(beam_theta)

    # Clamp beam inside the mirror box
    beam_x = max(-1.4, min(1.4, beam_x))
    beam_y = max(-0.8, min(0.8, beam_y))

    # Beam sweep: aim outward through the arc field
    arc_mid_angle = arc_start_angle + arc_sweep / 2
    sweep_half = rng.uniform(0.3, 0.8)
    beam_angle_start = arc_mid_angle - sweep_half
    beam_angle_end = arc_mid_angle + sweep_half

    beam_spread = rng.uniform(0.04, 0.10)

    return AnimParams(
        arc_center_x=arc_center_x,
        arc_center_y=arc_center_y,
        arc_radius=arc_radius,
        arc_start_angle=arc_start_angle,
        arc_sweep=arc_sweep,
        n_mirrors=n_mirrors,
        mirror_scatter=mirror_scatter,
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
    shot = Shot.preset("draft", width=PROBE_W, height=PROBE_H, rays=200_000, depth=14)
    shot.camera = CAMERA
    shot.look = shot.look.with_overrides(
        exposure=-5.5,
        gamma=2.0,
        tonemap="reinhardx",
        white_point=0.5,
        normalize="rays",
        temperature=0.1,
    )
    return shot


def check_beauty(p: AnimParams) -> tuple[bool, float, float]:
    """Render low-res frames and check brightness and contrast.

    Returns (ok, avg_mean_luma, avg_rms_contrast).
    """
    animate = build_animate(p)
    shot = make_probe_shot()
    timeline = Timeline(DURATION, fps=PROBE_FPS)
    session = RenderSession(PROBE_W, PROBE_H, False)

    n_frames = timeline.total_frames
    bright_count = 0
    total_mean = 0.0
    total_std = 0.0

    for fi in range(n_frames):
        ctx = timeline.context_at(fi)
        result = animate(ctx)
        cpp_shot = _resolve_frame_shot(shot, result, None)
        render_result = session.render_shot(cpp_shot, fi)
        fs = render_result.metrics
        total_mean += fs.mean_luma
        total_std += fs.rms_contrast
        if fs.mean_luma > MIN_MEAN_LUM:
            bright_count += 1

    avg_mean = total_mean / n_frames if n_frames > 0 else 0.0
    avg_std = total_std / n_frames if n_frames > 0 else 0.0
    bright_frac = bright_count / n_frames if n_frames > 0 else 0.0

    ok = (
        bright_frac >= MIN_BRIGHT_FRACTION
        and avg_mean >= MIN_MEAN_LUM
        and avg_mean <= MAX_MEAN_LUM
        and avg_std >= MIN_STD_LUM
    )
    return ok, avg_mean, avg_std


# ---------------------------------------------------------------------------
# HQ render
# ---------------------------------------------------------------------------


def make_hq_shot(width: int = 1920, height: int = 1080, rays: int = 5_000_000) -> Shot:
    shot = Shot.preset("production", width=width, height=height, rays=rays, depth=14)
    shot.camera = CAMERA
    shot.look = shot.look.with_overrides(
        exposure=-5.5,
        gamma=2.0,
        tonemap="reinhardx",
        white_point=0.5,
        normalize="rays",
        temperature=0.1,
    )
    return shot


def _params_to_dict(p: AnimParams) -> dict:
    """Serialize AnimParams for JSON output."""
    return {
        "arc_center_x": p.arc_center_x,
        "arc_center_y": p.arc_center_y,
        "arc_radius": p.arc_radius,
        "arc_start_angle": p.arc_start_angle,
        "arc_sweep": p.arc_sweep,
        "n_mirrors": p.n_mirrors,
        "mirror_scatter": p.mirror_scatter,
        "beam_x": p.beam_x,
        "beam_y": p.beam_y,
        "beam_angle_start": p.beam_angle_start,
        "beam_angle_end": p.beam_angle_end,
        "beam_spread": p.beam_spread,
        "mirrors": [
            {"cx": m.cx, "cy": m.cy, "length": m.length, "angle": m.angle} for m in p.mirrors
        ],
    }


def render_and_save(
    p: AnimParams, out_dir: Path, width: int = 1920, height: int = 1080, rays: int = 5_000_000
) -> None:
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

    base_dir = Path("renders/families/mirror_corridor")
    found = 0

    for attempt in range(1, MAX_ATTEMPTS + 1):
        p = random_params(rng)

        print(
            f"[{attempt}] n_mirrors={p.n_mirrors} arc_r={p.arc_radius:.2f} scatter={p.mirror_scatter:.3f} — checking...",
            flush=True,
        )

        beauty_ok, avg_lum, avg_std = check_beauty(p)
        print(f"  avg_luminance={avg_lum:.3f}  avg_contrast={avg_std:.3f}", flush=True)

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
