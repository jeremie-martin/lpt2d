"""Lens Chain — a row of magnifying glasses refracting a sweeping beam.

Three biconvex lenses are arranged along a diagonal from upper-left to
lower-right.  A full-spectrum beam enters from the upper-left corner and
sweeps slowly back and forth, threading through the chain.  Each lens
focuses and disperses the light, creating a cascade of overlapping caustic
rainbows that shift as the beam angle changes.
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
    biconvex_lens,
    frame_stats,
    glass,
    mirror_box,
    render,
)
from anim.renderer import RenderSession, _resolve_frame_shot

# ---------------------------------------------------------------------------
# Scene constants
# ---------------------------------------------------------------------------

WALL = Material(metallic=1.0, roughness=0.1, transmission=0.0, cauchy_b=0.0, albedo=1.0)
CAMERA = Camera2D(center=[0, 0], width=3.2)

DURATION = 8.0

# Lens glass: crown glass with moderate dispersion, slight fill for visibility
LENS_GLASS = glass(1.52, cauchy_b=25_000, fill=0.10)

# ---------------------------------------------------------------------------
# Parameter space
# ---------------------------------------------------------------------------


@dataclass
class LensSpec:
    """Geometry for one biconvex lens in the chain."""

    center_x: float
    center_y: float
    aperture: float  # 0.15-0.25
    center_thickness: float  # 0.04-0.08
    left_radius: float  # 0.15-0.30
    right_radius: float  # 0.15-0.30


@dataclass
class AnimParams:
    """Degrees of freedom for one lens-chain animation variant."""

    lenses: list[LensSpec]
    beam_x: float  # beam source position
    beam_y: float
    beam_angle_start: float  # sweep range start (rad)
    beam_angle_end: float  # sweep range end (rad)
    beam_spread: float  # projector spread


# ---------------------------------------------------------------------------
# Track builders
# ---------------------------------------------------------------------------


def beam_sweep_track(angle_start: float, angle_end: float) -> Track:
    """Slow back-and-forth sweep over the full duration."""
    return Track(
        [
            Key(0.0, angle_start),
            Key(DURATION / 2, angle_end, ease="ease_in_out_sine"),
            Key(DURATION, angle_start, ease="ease_in_out_sine"),
        ],
        wrap=Wrap.CLAMP,
    )


# ---------------------------------------------------------------------------
# Scene builder
# ---------------------------------------------------------------------------


def build_animate(p: AnimParams):
    """Return an animate(ctx) -> Frame callable."""
    sweep_trk = beam_sweep_track(p.beam_angle_start, p.beam_angle_end)

    def animate(ctx: FrameContext) -> Frame:
        beam_angle = float(sweep_trk(ctx.time))

        # Build all lenses
        lens_shapes = []
        for i, lens in enumerate(p.lenses):
            lens_shapes.extend(
                biconvex_lens(
                    center=(lens.center_x, lens.center_y),
                    aperture=lens.aperture,
                    center_thickness=lens.center_thickness,
                    left_radius=lens.left_radius,
                    right_radius=lens.right_radius,
                    material=LENS_GLASS,
                    id_prefix=f"lens_{i}",
                )
            )

        scene = Scene(
            shapes=[
                *mirror_box(1.6, 0.9, WALL, id_prefix="wall"),
                *lens_shapes,
            ],
            lights=[
                ProjectorLight(
                    id="beam",
                    position=[p.beam_x, p.beam_y],
                    direction=[math.cos(beam_angle), math.sin(beam_angle)],
                    source_radius=0.015,
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
CONTRAST_THRESHOLD = 25.0  # frame_stats.std must exceed this
MIN_GOOD_FRACTION = 0.60  # at least 60% of probed frames must be good
PROBE_FPS = 4
PROBE_W, PROBE_H = 640, 360


# ---------------------------------------------------------------------------
# Smart parameter sampling
# ---------------------------------------------------------------------------


def random_lens(rng: random.Random, cx: float, cy: float) -> LensSpec:
    """Sample random lens geometry at a given nominal center with slight jitter."""
    jitter_x = rng.uniform(-0.04, 0.04)
    jitter_y = rng.uniform(-0.04, 0.04)
    aperture = rng.uniform(0.12, 0.20)
    center_thickness = rng.uniform(0.03, 0.05)
    # Radii must be >> half aperture to avoid invalid geometry
    min_r = aperture * 0.8
    left_radius = rng.uniform(max(0.20, min_r), 0.40)
    right_radius = rng.uniform(max(0.20, min_r), 0.40)
    return LensSpec(
        center_x=cx + jitter_x,
        center_y=cy + jitter_y,
        aperture=aperture,
        center_thickness=center_thickness,
        left_radius=left_radius,
        right_radius=right_radius,
    )


def random_params(rng: random.Random) -> AnimParams:
    """Sample random lens-chain animation parameters."""
    # Three lenses along a diagonal: upper-left to lower-right
    nominal_positions = [(-0.5, 0.3), (0.0, 0.0), (0.5, -0.3)]
    lenses = [random_lens(rng, cx, cy) for cx, cy in nominal_positions]

    # Beam enters from upper-left corner area
    beam_x = rng.uniform(-1.45, -1.25)
    beam_y = rng.uniform(0.60, 0.85)

    # Aim roughly toward the first lens, with a sweep range
    target_x = lenses[0].center_x
    target_y = lenses[0].center_y
    base_angle = math.atan2(target_y - beam_y, target_x - beam_x)

    sweep_half = rng.uniform(0.08, 0.20)
    beam_angle_start = base_angle - sweep_half
    beam_angle_end = base_angle + sweep_half

    beam_spread = rng.uniform(0.06, 0.14)

    return AnimParams(
        lenses=lenses,
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
    """Low-res shot for contrast evaluation."""
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
    """Render low-res probes and count high-contrast frames.

    Returns (ok, n_good, avg_std).
    """
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
        fs = frame_stats(render_result.pixels, PROBE_W, PROBE_H)
        total_std += fs.std
        if fs.std > CONTRAST_THRESHOLD:
            good += 1

    avg_std = total_std / n_frames if n_frames > 0 else 0.0
    min_good = int(n_frames * MIN_GOOD_FRACTION)
    return good >= min_good, good, avg_std


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


def _serialize_params(p: AnimParams) -> dict:
    """Convert AnimParams to a JSON-safe dict."""
    return {
        "lenses": [asdict(lens) for lens in p.lenses],
        "beam_x": p.beam_x,
        "beam_y": p.beam_y,
        "beam_angle_start": p.beam_angle_start,
        "beam_angle_end": p.beam_angle_end,
        "beam_spread": p.beam_spread,
    }


def render_and_save(
    p: AnimParams, out_dir: Path, width: int = 1920, height: int = 1080, rays: int = 5_000_000
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)

    params_path = out_dir / "params.json"
    params_path.write_text(json.dumps(_serialize_params(p), indent=2))
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

    base_dir = Path("renders/families/lens_chain")
    found = 0

    for attempt in range(1, MAX_ATTEMPTS + 1):
        p = random_params(rng)

        apertures = [f"{lens.aperture:.3f}" for lens in p.lenses]
        print(
            f"[{attempt}] apertures={apertures} spread={p.beam_spread:.3f} — checking beauty...",
            flush=True,
        )

        beauty_ok, n_good, avg_std = check_beauty(p)
        n_frames = Timeline(DURATION, fps=PROBE_FPS).total_frames
        good_pct = 100.0 * n_good / n_frames if n_frames > 0 else 0.0
        print(f"  good={n_good}/{n_frames} ({good_pct:.0f}%) avg_std={avg_std:.1f}", flush=True)

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
        print("Try adjusting parameter ranges or lowering CONTRAST_THRESHOLD.")


if __name__ == "__main__":
    main()
