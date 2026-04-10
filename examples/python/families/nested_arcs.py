"""Nested Arcs — concentric glass rainbows.

3-4 thick glass arc segments arranged concentrically like a target, each
rotating at a different speed and direction.  A beam from outside passes
through all layers, creating compound refraction that evolves as the arcs
align and misalign.
"""

from __future__ import annotations

import json
import math
import random
import sys
import time
from dataclasses import asdict, dataclass, field
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
    thick_arc,
)
from anim.renderer import RenderSession, _resolve_frame_shot

# ---------------------------------------------------------------------------
# Scene constants
# ---------------------------------------------------------------------------

WALL = Material(metallic=1.0, roughness=0.1, transmission=0.0, cauchy_b=0.0, albedo=1.0)
CAMERA = Camera2D(center=[0, 0], width=3.2)

DURATION = 8.0

# Arc glass: moderate Cauchy for clear dispersion, subtle fill for visibility
ARC_GLASS = glass(1.55, cauchy_b=30_000, color=(0.95, 0.97, 1.0), fill=0.10)
WALL_ID = "wall"
ARC_GLASS_ID = "arc_glass"
MATERIALS = {WALL_ID: WALL, ARC_GLASS_ID: ARC_GLASS}

# ---------------------------------------------------------------------------
# Parameter space
# ---------------------------------------------------------------------------


@dataclass
class ArcLayer:
    """Parameters for one concentric arc layer."""

    radius: float  # mid-line radius
    thickness: float  # annular thickness
    sweep: float  # angular extent (rad)
    base_start: float  # initial angle_start (rad)
    rotation_speed: float  # total rotation over duration (rad, signed)


@dataclass
class AnimParams:
    """Degrees of freedom for one nested-arcs animation variant."""

    layers: list[ArcLayer] = field(default_factory=list)
    beam_x: float = -1.45
    beam_y: float = 0.0
    beam_angle: float = 0.0  # base angle (toward center)
    beam_drift: float = 0.10  # angular drift amplitude
    beam_spread: float = 0.05  # projector spread


# ---------------------------------------------------------------------------
# Track builders
# ---------------------------------------------------------------------------


def layer_rotation_track(layer: ArcLayer) -> Track:
    """Smooth rotation for one arc layer over the full duration."""
    return Track(
        [
            Key(0.0, layer.base_start),
            Key(DURATION, layer.base_start + layer.rotation_speed, ease="ease_in_out_sine"),
        ],
        wrap=Wrap.CLAMP,
    )


def beam_drift_track(base_angle: float, drift: float) -> Track:
    """Gentle beam angular drift -- back and forth."""
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
    rot_tracks = [layer_rotation_track(layer) for layer in p.layers]
    angle_trk = beam_drift_track(p.beam_angle, p.beam_drift)

    def animate(ctx: FrameContext) -> Frame:
        beam_angle = float(angle_trk(ctx.time))

        arc_shapes = []
        for i, layer in enumerate(p.layers):
            rot = float(rot_tracks[i](ctx.time))
            arcs = thick_arc(
                center=(0.0, 0.0),
                radius=layer.radius,
                thickness=layer.thickness,
                angle_start=rot,
                sweep=layer.sweep,
                material_id=ARC_GLASS_ID,
                id_prefix=f"arc_{i}",
            )
            arc_shapes.extend(arcs)

        scene = Scene(
            materials=MATERIALS,
            shapes=[
                *mirror_box(1.6, 0.9, WALL_ID, id_prefix="wall"),
                *arc_shapes,
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
        return Frame(scene=scene, look=Look(exposure=-5.2))

    return animate


# ---------------------------------------------------------------------------
# Search tuning
# ---------------------------------------------------------------------------

MAX_ATTEMPTS = 500
RICHNESS_THRESHOLD = 0.25
MIN_COLORFUL_SECONDS = 2.0
PROBE_FPS = 4
PROBE_W, PROBE_H = 640, 360


# ---------------------------------------------------------------------------
# Smart parameter sampling
# ---------------------------------------------------------------------------


def random_params(rng: random.Random) -> AnimParams:
    """Sample random nested-arcs animation parameters."""
    n_layers = rng.randint(3, 4)
    base_radii = [0.15, 0.30, 0.45, 0.60][:n_layers]

    layers = []
    for i, base_r in enumerate(base_radii):
        radius = base_r + rng.uniform(-0.02, 0.02)
        thickness = rng.uniform(0.03, 0.05)
        sweep = rng.uniform(math.pi * 0.6, math.pi * 1.4)
        base_start = rng.uniform(0, math.tau)
        # Each layer rotates at a different speed and direction
        speed_options = [math.pi / 4, -math.pi / 3, math.pi / 2, -math.pi / 5, math.pi / 3]
        rotation_speed = speed_options[i % len(speed_options)] * rng.uniform(0.8, 1.3)
        layers.append(
            ArcLayer(
                radius=radius,
                thickness=thickness,
                sweep=sweep,
                base_start=base_start,
                rotation_speed=rotation_speed,
            )
        )

    # Beam enters from the left side
    beam_x = -1.45
    beam_y = rng.uniform(-0.35, 0.35)
    beam_angle = math.atan2(-beam_y, -beam_x) + rng.uniform(-0.10, 0.10)
    beam_drift = rng.uniform(0.06, 0.15)
    beam_spread = rng.uniform(0.04, 0.07)

    return AnimParams(
        layers=layers,
        beam_x=beam_x,
        beam_y=beam_y,
        beam_angle=beam_angle,
        beam_drift=beam_drift,
        beam_spread=beam_spread,
    )


# ---------------------------------------------------------------------------
# Beauty check
# ---------------------------------------------------------------------------


def make_probe_shot() -> Shot:
    """Low-res shot for color evaluation."""
    shot = Shot.preset("draft", width=PROBE_W, height=PROBE_H, rays=200_000, depth=10)
    shot.camera = CAMERA
    shot.look = shot.look.with_overrides(
        exposure=-5.2,
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
        exposure=-5.2,
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
        "layers": [asdict(layer) for layer in p.layers],
        "beam_x": p.beam_x,
        "beam_y": p.beam_y,
        "beam_angle": p.beam_angle,
        "beam_drift": p.beam_drift,
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

    from anim import render

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

    base_dir = Path("renders/families/nested_arcs")
    found = 0

    for attempt in range(1, MAX_ATTEMPTS + 1):
        p = random_params(rng)

        n_layers = len(p.layers)
        radii_str = ", ".join(f"{layer.radius:.2f}" for layer in p.layers)
        print(
            f"[{attempt}] layers={n_layers} radii=[{radii_str}] -- checking beauty...", flush=True
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
