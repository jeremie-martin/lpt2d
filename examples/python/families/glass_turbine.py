"""Glass Turbine — rotating dispersive glass wheel with a single white projector.

A turbine-like structure (hub + radial spokes) made of high-dispersion glass
rotates slowly inside a mirror box.  A single full-spectrum white beam
illuminates the turbine from a randomly chosen side, creating continuously
shifting refraction and rainbow patterns as the spokes pass through the beam.

The animation is meditative: the rotation speed eases in and out, and the
beam has a gentle angular drift to prevent static illumination.
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
    Circle,
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
)
from anim.renderer import RenderSession, _resolve_frame_shot

# ---------------------------------------------------------------------------
# Scene constants
# ---------------------------------------------------------------------------

WALL = Material(metallic=1.0, roughness=0.1, transmission=0.0, cauchy_b=0.0, albedo=1.0)
CAMERA = Camera2D(center=[0, 0], width=3.2)

DURATION = 8.0

# Turbine glass: high Cauchy for strong dispersion, slight fill for visibility
TURBINE_GLASS = glass(1.65, cauchy_b=35_000, color=(0.92, 0.95, 1.0), fill=0.12)
WALL_ID = "wall"
TURBINE_GLASS_ID = "turbine_glass"
MATERIALS = {WALL_ID: WALL, TURBINE_GLASS_ID: TURBINE_GLASS}

# ---------------------------------------------------------------------------
# Turbine builder
# ---------------------------------------------------------------------------


def build_turbine(
    center: tuple[float, float],
    hub_radius: float,
    spoke_length: float,
    spoke_width: float,
    n_spokes: int,
    rotation: float,
    material_id: str,
    *,
    corner_radius: float = 0.01,
) -> list[Circle | Polygon]:
    """Build a turbine: central hub + radial rectangular spokes."""
    cx, cy = center
    shapes: list[Circle | Polygon] = [
        Circle(id="turbine_hub", center=[cx, cy], radius=hub_radius, material_id=material_id),
    ]

    for i in range(n_spokes):
        angle = rotation + i * math.tau / n_spokes
        # Spoke extends from just outside hub to spoke_length
        r_inner = hub_radius * 0.9
        r_outer = hub_radius + spoke_length
        hw = spoke_width / 2

        # Four corners of the spoke rectangle in local frame, then rotate
        cos_a, sin_a = math.cos(angle), math.sin(angle)
        perp_x, perp_y = -sin_a * hw, cos_a * hw

        p1 = [cx + cos_a * r_inner + perp_x, cy + sin_a * r_inner + perp_y]
        p2 = [cx + cos_a * r_outer + perp_x, cy + sin_a * r_outer + perp_y]
        p3 = [cx + cos_a * r_outer - perp_x, cy + sin_a * r_outer - perp_y]
        p4 = [cx + cos_a * r_inner - perp_x, cy + sin_a * r_inner - perp_y]

        shapes.append(
            Polygon(
                id=f"turbine_spoke_{i}",
                vertices=[p1, p2, p3, p4],
                material_id=material_id,
                corner_radius=corner_radius,
            )
        )
    return shapes


# ---------------------------------------------------------------------------
# Parameter space
# ---------------------------------------------------------------------------


@dataclass
class AnimParams:
    """Degrees of freedom for one turbine animation variant."""

    n_spokes: int  # 4-7
    hub_radius: float  # hub size
    spoke_length: float  # how far spokes extend
    spoke_width: float  # spoke thickness
    rotation_start: float  # initial rotation (rad)
    rotation_speed: float  # total rotation over duration (rad, signed)
    beam_x: float  # beam source x
    beam_y: float  # beam source y
    beam_angle: float  # beam base angle (toward center)
    beam_drift: float  # angular drift amplitude for beam


# ---------------------------------------------------------------------------
# Track builders
# ---------------------------------------------------------------------------


def rotation_track(p: AnimParams) -> Track:
    """Smooth rotation over the full duration."""
    return Track(
        [
            Key(0.0, p.rotation_start),
            Key(DURATION, p.rotation_start + p.rotation_speed, ease="ease_in_out_sine"),
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

        turbine_shapes = build_turbine(
            center=(0.0, 0.0),
            hub_radius=p.hub_radius,
            spoke_length=p.spoke_length,
            spoke_width=p.spoke_width,
            n_spokes=p.n_spokes,
            rotation=rot,
            material_id=TURBINE_GLASS_ID,
        )

        scene = Scene(
            materials=MATERIALS,
            shapes=[
                *mirror_box(1.6, 0.9, WALL_ID, id_prefix="wall"),
                *turbine_shapes,
            ],
            lights=[
                ProjectorLight(
                    id="beam",
                    position=[p.beam_x, p.beam_y],
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
COLORFULNESS_THRESHOLD = 0.20
MIN_COLORFUL_SECONDS = 3.0
PROBE_FPS = 4
PROBE_W, PROBE_H = 640, 360


# ---------------------------------------------------------------------------
# Smart parameter sampling
# ---------------------------------------------------------------------------


def random_params(rng: random.Random) -> AnimParams:
    """Sample random turbine animation parameters."""
    n_spokes = rng.randint(4, 6)
    hub_radius = rng.uniform(0.10, 0.18)
    spoke_length = rng.uniform(0.22, 0.40)
    spoke_width = rng.uniform(0.06, 0.10)
    rotation_start = rng.uniform(0, math.tau)
    rotation_speed = rng.choice([-1, 1]) * rng.uniform(math.pi * 0.5, math.pi * 2.0)

    # Beam enters from a random side of the mirror box
    side = rng.choice(["left", "right", "top", "bottom"])
    jitter = rng.uniform(-0.08, 0.08)

    if side == "left":
        beam_x = -1.45
        beam_y = rng.uniform(-0.5, 0.5)
        beam_angle = math.atan2(-beam_y, -beam_x) + jitter  # aimed right toward center
    elif side == "right":
        beam_x = 1.45
        beam_y = rng.uniform(-0.5, 0.5)
        beam_angle = math.atan2(-beam_y, -beam_x) + jitter  # aimed left toward center
    elif side == "top":
        beam_x = rng.uniform(-0.8, 0.8)
        beam_y = 0.85
        beam_angle = math.atan2(-beam_y, -beam_x) + jitter  # aimed down toward center
    else:  # bottom
        beam_x = rng.uniform(-0.8, 0.8)
        beam_y = -0.85
        beam_angle = math.atan2(-beam_y, -beam_x) + jitter  # aimed up toward center

    beam_drift = rng.uniform(0.05, 0.2)

    return AnimParams(
        n_spokes=n_spokes,
        hub_radius=hub_radius,
        spoke_length=spoke_length,
        spoke_width=spoke_width,
        rotation_start=rotation_start,
        rotation_speed=rotation_speed,
        beam_x=beam_x,
        beam_y=beam_y,
        beam_angle=beam_angle,
        beam_drift=beam_drift,
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
    """Render low-res frames and count colorful ones. Returns (ok, n_colorful, avg_colorfulness)."""
    animate = build_animate(p)
    shot = make_probe_shot()
    timeline = Timeline(DURATION, fps=PROBE_FPS)
    session = RenderSession(PROBE_W, PROBE_H, False)

    n_frames = timeline.total_frames
    colorful = 0
    total_colorfulness = 0.0

    for fi in range(n_frames):
        ctx = timeline.context_at(fi)
        result = animate(ctx)
        cpp_shot = _resolve_frame_shot(shot, result, None)
        render_result = session.render_shot(cpp_shot, fi, True)
        stats = render_result.analysis.image
        total_colorfulness += stats.colorfulness
        if stats.colorfulness > COLORFULNESS_THRESHOLD:
            colorful += 1

    avg_colorfulness = total_colorfulness / n_frames if n_frames > 0 else 0.0
    min_colorful_frames = int(MIN_COLORFUL_SECONDS * PROBE_FPS)
    return colorful >= min_colorful_frames, colorful, avg_colorfulness


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

    base_dir = Path("renders/families/glass_turbine")
    found = 0

    for attempt in range(1, MAX_ATTEMPTS + 1):
        p = random_params(rng)

        print(
            f"[{attempt}] spokes={p.n_spokes} hub={p.hub_radius:.3f} len={p.spoke_length:.3f} — checking beauty...",
            flush=True,
        )

        beauty_ok, n_colorful, avg_colorfulness = check_beauty(p)
        colorful_seconds = n_colorful / PROBE_FPS
        print(f"  colorful={colorful_seconds:.1f}s avg_colorfulness={avg_colorfulness:.3f}", flush=True)

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
        print("Try adjusting parameter ranges or lowering COLORFULNESS_THRESHOLD.")


if __name__ == "__main__":
    main()
