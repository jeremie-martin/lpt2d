"""Fractal Tree — L-system binary tree with traveling light.

A binary fractal tree built from thick glass segments sits in a mirror box.
A projector beam slowly sweeps across the canopy, refracting through the
semi-transparent branches and creating intricate light patterns on the walls.

The tree doesn't move — the drama comes from the beam traveling across the
branching structure, progressively revealing and hiding different refraction
paths.
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
    Polygon,
    ProjectorLight,
    Scene,
    Shot,
    Timeline,
    Track,
    Wrap,
    glass,
    mirror_box,
    render,
    thick_segment,
)
from anim.renderer import RenderSession, _resolve_frame_shot

# ---------------------------------------------------------------------------
# Scene constants
# ---------------------------------------------------------------------------

WALL = Material(metallic=1.0, roughness=0.15, transmission=0.3, cauchy_b=0.0, albedo=1.0)
CAMERA = Camera2D(center=[0, 0], width=3.2)
DURATION = 8.0

# Semi-transparent glass for branches: light passes through, some dispersion
BRANCH_GLASS = glass(1.45, cauchy_b=18_000, color=(0.85, 0.92, 0.80), fill=0.08)
WALL_ID = "wall"
BRANCH_GLASS_ID = "branch_glass"
MATERIALS = {WALL_ID: WALL, BRANCH_GLASS_ID: BRANCH_GLASS}

# ---------------------------------------------------------------------------
# L-system tree builder
# ---------------------------------------------------------------------------


def build_tree(
    base: tuple[float, float],
    trunk_length: float,
    trunk_angle: float,
    branch_ratio: float,
    spread_angle: float,
    depth: int,
    thickness: float,
    material_id: str,
    seed: int = 42,
) -> list[Polygon]:
    """Build an asymmetric binary fractal tree from thick segments.

    Each branch splits into two children at ``spread_angle`` from parent
    direction.  Small per-branch random variations in length (+-15%), angle
    (+-10%), and thickness reduction rate make the tree look organic while
    remaining deterministic for a given *seed*.
    """
    rng = random.Random(seed)
    shapes: list[Polygon] = []
    idx = [0]

    def _branch(x: float, y: float, angle: float, length: float, thick: float, level: int):
        if level > depth or length < 0.005:
            return

        # Per-branch random variations
        len_factor = rng.uniform(0.85, 1.15)
        actual_length = length * len_factor

        ex = x + actual_length * math.cos(angle)
        ey = y + actual_length * math.sin(angle)

        seg = thick_segment(
            (x, y),
            (ex, ey),
            thick,
            material_id,
            corner_radius=thick * 0.3,
            id_prefix=f"branch_{idx[0]}",
        )
        shapes.append(seg)
        idx[0] += 1

        child_len = actual_length * branch_ratio
        # Slight variation in thickness reduction (0.80 – 0.90 instead of fixed 0.85)
        thick_decay = rng.uniform(0.80, 0.90)
        child_thick = thick * branch_ratio * thick_decay

        # Angle variation: +-10% of spread_angle per child
        angle_var_l = spread_angle * rng.uniform(-0.10, 0.10)
        angle_var_r = spread_angle * rng.uniform(-0.10, 0.10)

        _branch(ex, ey, angle + spread_angle + angle_var_l, child_len, child_thick, level + 1)
        _branch(ex, ey, angle - spread_angle + angle_var_r, child_len, child_thick, level + 1)

    _branch(*base, trunk_angle, trunk_length, thickness, 0)
    return shapes


# ---------------------------------------------------------------------------
# Parameter space
# ---------------------------------------------------------------------------


@dataclass
class AnimParams:
    """Degrees of freedom for one fractal tree animation variant."""

    tree_base_x: float  # horizontal offset from center
    tree_base_y: float  # vertical position (bottom of trunk)
    trunk_length: float  # length of first segment
    trunk_angle: float  # initial growth direction (rad, pi/2 = straight up)
    branch_ratio: float  # length ratio per generation
    spread_angle: float  # half-angle between children
    depth: int  # recursion depth
    trunk_thickness: float  # initial thickness
    tree_seed: int  # seed for deterministic asymmetric branching
    beam_x: float  # projector x position (left side of box)
    beam_y: float  # projector y position
    beam_angle_start: float  # beam angle at t=0
    beam_angle_end: float  # beam angle at t=DURATION
    beam_spread: float  # projector cone width


# ---------------------------------------------------------------------------
# Track builders
# ---------------------------------------------------------------------------


def beam_angle_track(p: AnimParams) -> Track:
    """Back-and-forth sweep across the tree — lingers at endpoints."""
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


def build_animate(p: AnimParams):
    """Return an animate(ctx) -> Frame callable."""
    angle_trk = beam_angle_track(p)

    tree_shapes = build_tree(
        base=(p.tree_base_x, p.tree_base_y),
        trunk_length=p.trunk_length,
        trunk_angle=p.trunk_angle,
        branch_ratio=p.branch_ratio,
        spread_angle=p.spread_angle,
        depth=p.depth,
        thickness=p.trunk_thickness,
        material_id=BRANCH_GLASS_ID,
        seed=p.tree_seed,
    )

    def animate(ctx: FrameContext) -> Frame:
        angle = float(angle_trk(ctx.time))

        scene = Scene(
            materials=MATERIALS,
            shapes=[
                *mirror_box(1.6, 0.9, WALL_ID, id_prefix="wall"),
                *tree_shapes,
            ],
            lights=[
                ProjectorLight(
                    id="beam",
                    position=[p.beam_x, p.beam_y],
                    direction=[math.cos(angle), math.sin(angle)],
                    source_radius=0.012,
                    spread=p.beam_spread,
                    source="ball",
                    intensity=1.0,
                ),
            ],
        )
        return Frame(scene=scene, look=Look(exposure=-4.8))

    return animate


# ---------------------------------------------------------------------------
# Search tuning
# ---------------------------------------------------------------------------

MAX_ATTEMPTS = 500
PROBE_FPS = 4
PROBE_W, PROBE_H = 640, 360

# For trees, we care about illumination coverage rather than spectral richness
# since the glass is thin. We check that frames aren't too dark.
MIN_BRIGHT_FRACTION = 0.6  # at least 60% of frames should have mean luminance > 30


# ---------------------------------------------------------------------------
# Smart parameter sampling
# ---------------------------------------------------------------------------


def random_params(rng: random.Random) -> AnimParams:
    """Sample random fractal tree parameters."""
    tree_base_x = rng.uniform(-0.3, 0.3)
    tree_base_y = rng.uniform(-0.75, -0.55)
    trunk_length = rng.uniform(0.25, 0.40)
    trunk_angle = math.pi / 2 + rng.uniform(-0.15, 0.15)
    branch_ratio = rng.uniform(0.62, 0.75)
    spread_angle = rng.uniform(0.30, 0.55)
    depth = rng.randint(7, 9)
    trunk_thickness = rng.uniform(0.04, 0.07)
    tree_seed = rng.randint(0, 2**31)

    # Beam from left side, roughly level with tree canopy
    beam_x = -1.45
    beam_y = rng.uniform(-0.2, 0.3)

    # Compute angle range to sweep across the tree
    tree_top_y = tree_base_y + trunk_length * 2.0
    angle_to_base = math.atan2(tree_base_y - beam_y, tree_base_x - beam_x)
    angle_to_top = math.atan2(tree_top_y - beam_y, tree_base_x - beam_x)

    # Tighter sweep centered on the tree canopy
    beam_angle_start = angle_to_base + rng.uniform(-0.05, 0.05)
    beam_angle_end = angle_to_top + rng.uniform(-0.03, 0.08)

    beam_spread = rng.uniform(0.04, 0.08)

    return AnimParams(
        tree_base_x=tree_base_x,
        tree_base_y=tree_base_y,
        trunk_length=trunk_length,
        trunk_angle=trunk_angle,
        branch_ratio=branch_ratio,
        spread_angle=spread_angle,
        depth=depth,
        trunk_thickness=trunk_thickness,
        tree_seed=tree_seed,
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
    shot = Shot.preset("draft", width=PROBE_W, height=PROBE_H, rays=200_000, depth=10)
    shot.camera = CAMERA
    shot.look = shot.look.with_overrides(
        exposure=-4.8,
        gamma=2.0,
        tonemap="reinhardx",
        white_point=0.5,
        normalize="rays",
        temperature=0.1,
    )
    return shot


def check_beauty(p: AnimParams) -> tuple[bool, float]:
    """Render low-res frames, check illumination coverage. Returns (ok, avg_mean_lum)."""
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
        fs = render_result.metrics
        total_mean += fs.mean_lum
        if fs.mean_lum > 30:
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
        exposure=-4.8,
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

    base_dir = Path("renders/families/fractal_tree")
    found = 0

    for attempt in range(1, MAX_ATTEMPTS + 1):
        p = random_params(rng)

        print(
            f"[{attempt}] depth={p.depth} trunk={p.trunk_length:.3f} "
            f"spread={math.degrees(p.spread_angle):.0f}deg — checking...",
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
        print("  done.\n")

        if found >= target_count:
            break

    if found == 0:
        print(f"No valid animation found in {MAX_ATTEMPTS} attempts.")


if __name__ == "__main__":
    main()
