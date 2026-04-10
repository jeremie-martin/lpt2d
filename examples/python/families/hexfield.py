"""Hex Field — stained glass honeycomb with a scanning beam.

Many small glass hexagons arranged in a honeycomb grid fill a mirror box.
A single white beam from the top slides horizontally across the grid,
creating a wave of tiny rainbow refractions as it passes each hexagon.

The effect resembles light sweeping across a stained glass window.
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

# Stained glass: moderate dispersion, gentle fill for visibility
HEX_GLASS = glass(1.50, cauchy_b=25_000, color=(0.96, 0.96, 0.96), fill=0.12)
WALL_ID = "wall"
HEX_GLASS_ID = "hex_glass"
MATERIALS = {WALL_ID: WALL, HEX_GLASS_ID: HEX_GLASS}

# ---------------------------------------------------------------------------
# Honeycomb builder
# ---------------------------------------------------------------------------


def build_honeycomb(
    hex_radius: float,
    rows: int,
    cols: int,
    material_id: str,
    *,
    rotation_offset: float = 0.0,
    corner_radius: float = 0.0,
) -> list[Polygon]:
    """Build a honeycomb grid of hexagons centered near the origin.

    *hex_radius* is the circumscribed radius (center to vertex).
    *rows* and *cols* control the grid extent.
    *rotation_offset* rotates every hexagon by the same amount (radians).
    """
    # Flat-top hexagon spacing
    col_spacing = hex_radius * 1.5
    row_spacing = hex_radius * math.sqrt(3)

    # Center the grid
    grid_w = (cols - 1) * col_spacing
    grid_h = (rows - 1) * row_spacing
    x_offset = -grid_w / 2
    y_offset = -grid_h / 2

    shapes: list[Polygon] = []
    idx = 0
    for col in range(cols):
        for row in range(rows):
            cx = x_offset + col * col_spacing
            cy = y_offset + row * row_spacing
            # Odd columns shift up by half a row
            if col % 2 == 1:
                cy += row_spacing / 2
            shapes.append(
                regular_polygon(
                    center=(cx, cy),
                    radius=hex_radius,
                    n=6,
                    material_id=material_id,
                    rotation=rotation_offset,
                    corner_radius=corner_radius,
                    id_prefix=f"hex_{idx}",
                )
            )
            idx += 1
    return shapes


# ---------------------------------------------------------------------------
# Parameter space
# ---------------------------------------------------------------------------


@dataclass
class AnimParams:
    """Degrees of freedom for one hex field animation variant."""

    hex_radius: float  # 0.07-0.10
    rows: int  # grid rows
    cols: int  # grid columns
    hex_rotation: float  # rotation of each hexagon (rad)
    beam_x_start: float  # beam sweep start x
    beam_x_end: float  # beam sweep end x
    beam_y: float  # beam y position (top of box)
    beam_angle_drift: float  # small angular drift amplitude (rad)
    spread: float  # beam spread


# ---------------------------------------------------------------------------
# Track builders
# ---------------------------------------------------------------------------


def beam_x_track(p: AnimParams) -> Track:
    """Horizontal sweep: left -> right -> left over the full duration."""
    return Track(
        [
            Key(0.0, p.beam_x_start),
            Key(DURATION / 2, p.beam_x_end, ease="ease_in_out_sine"),
            Key(DURATION, p.beam_x_start, ease="ease_in_out_sine"),
        ],
        wrap=Wrap.CLAMP,
    )


def beam_angle_track(p: AnimParams) -> Track:
    """Gentle angular drift around straight-down (-pi/2)."""
    base = -math.pi / 2
    return Track(
        [
            Key(0.0, base - p.beam_angle_drift / 2),
            Key(DURATION / 3, base + p.beam_angle_drift / 2, ease="ease_in_out_sine"),
            Key(DURATION * 2 / 3, base - p.beam_angle_drift / 2, ease="ease_in_out_sine"),
            Key(DURATION, base + p.beam_angle_drift / 2, ease="ease_in_out_sine"),
        ],
        wrap=Wrap.CLAMP,
    )


# ---------------------------------------------------------------------------
# Scene builder
# ---------------------------------------------------------------------------


def build_animate(p: AnimParams):
    """Return an animate(ctx) -> Frame callable."""
    x_trk = beam_x_track(p)
    angle_trk = beam_angle_track(p)

    hex_shapes = build_honeycomb(
        hex_radius=p.hex_radius,
        rows=p.rows,
        cols=p.cols,
        material_id=HEX_GLASS_ID,
        rotation_offset=p.hex_rotation,
        corner_radius=0.005,
    )

    wall_shapes = mirror_box(1.6, 0.9, WALL_ID, id_prefix="wall")

    def animate(ctx: FrameContext) -> Frame:
        bx = float(x_trk(ctx.time))
        beam_angle = float(angle_trk(ctx.time))

        scene = Scene(
            materials=MATERIALS,
            shapes=[
                *wall_shapes,
                *hex_shapes,
            ],
            lights=[
                ProjectorLight(
                    id="beam",
                    position=[bx, p.beam_y],
                    direction=[math.cos(beam_angle), math.sin(beam_angle)],
                    source_radius=0.015,
                    spread=p.spread,
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
RICHNESS_THRESHOLD = 0.20
MIN_COLORFUL_SECONDS = 2.0
PROBE_FPS = 4
PROBE_W, PROBE_H = 640, 360


# ---------------------------------------------------------------------------
# Smart parameter sampling
# ---------------------------------------------------------------------------


def random_params(rng: random.Random) -> AnimParams:
    """Sample random hex field animation parameters."""
    hex_radius = rng.uniform(0.07, 0.10)

    # Compute rows/cols to fill roughly (-0.8, -0.5) to (0.8, 0.5)
    col_spacing = hex_radius * 1.5
    row_spacing = hex_radius * math.sqrt(3)
    cols = max(4, int(1.6 / col_spacing) + 1)
    rows = max(3, int(1.0 / row_spacing) + 1)

    hex_rotation = rng.choice([0.0, math.pi / 6])  # flat-top or pointy-top
    beam_x_start = rng.uniform(-0.9, -0.6)
    beam_x_end = rng.uniform(0.6, 0.9)
    beam_y = 0.85
    beam_angle_drift = rng.uniform(0.03, 0.15)
    spread = rng.uniform(0.06, 0.14)

    return AnimParams(
        hex_radius=hex_radius,
        rows=rows,
        cols=cols,
        hex_rotation=hex_rotation,
        beam_x_start=beam_x_start,
        beam_x_end=beam_x_end,
        beam_y=beam_y,
        beam_angle_drift=beam_angle_drift,
        spread=spread,
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
        total_richness += cs.richness
        if cs.richness > RICHNESS_THRESHOLD:
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

    base_dir = Path("renders/families/hexfield")
    found = 0

    for attempt in range(1, MAX_ATTEMPTS + 1):
        p = random_params(rng)
        n_hexes = p.rows * p.cols

        print(
            f"[{attempt}] radius={p.hex_radius:.3f} grid={p.rows}x{p.cols} ({n_hexes} hexes) "
            f"spread={p.spread:.3f} -- checking beauty...",
            flush=True,
        )

        beauty_ok, n_colorful, avg_richness = check_beauty(p)
        colorful_seconds = n_colorful / PROBE_FPS
        print(f"  colorful={colorful_seconds:.1f}s avg_richness={avg_richness:.3f}", flush=True)

        if not beauty_ok:
            continue

        found += 1
        out_dir = base_dir / f"{found:03d}"
        print(f"  FOUND #{found} -- rendering...")
        render_and_save(p, out_dir, width, height, rays)
        print("  done.\n")

        if found >= target_count:
            break

    if found == 0:
        print(f"No valid animation found in {MAX_ATTEMPTS} attempts.")
        print("Try adjusting parameter ranges or lowering RICHNESS_THRESHOLD.")


if __name__ == "__main__":
    main()
