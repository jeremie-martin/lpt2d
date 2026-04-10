"""Twin Beams — two perpendicular searchlights crossing through prisms.

Two projector beams enter the mirror box from perpendicular walls: one from the
left, one from the top.  Each beam drifts slowly back-and-forth in angle, and
both pass through one or two prisms near the center.  The perpendicular
geometry creates dual crossing rainbow fans whose intersection point wanders as
the angles change — a composition fundamentally different from single-beam
scenes.
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
    Shot,
    Timeline,
    Track,
    Wrap,
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

# Prism glass: moderate-high dispersion, near-white, slight fill for visibility
PRISM_GLASS = glass(1.52, cauchy_b=28_000, color=(0.968, 0.968, 0.968), fill=0.15)
WALL_ID = "wall"
PRISM_GLASS_ID = "prism_glass"
MATERIALS = {WALL_ID: WALL, PRISM_GLASS_ID: PRISM_GLASS}


# ---------------------------------------------------------------------------
# Parameter space
# ---------------------------------------------------------------------------


@dataclass
class PrismDef:
    """One prism placed near the center."""

    center_x: float
    center_y: float
    size: float  # inscribed-circle radius
    rotation: float  # static rotation (rad)


@dataclass
class AnimParams:
    """Degrees of freedom for one twin-beams variant."""

    # Left-wall beam
    beam_left_y: float  # y position on left wall
    beam_left_angle: float  # base angle (roughly rightward)
    beam_left_drift: float  # angular drift amplitude
    beam_left_spread: float  # cone spread

    # Top-wall beam
    beam_top_x: float  # x position on top wall
    beam_top_angle: float  # base angle (roughly downward)
    beam_top_drift: float  # angular drift amplitude
    beam_top_spread: float  # cone spread

    # Prisms
    prisms: list[PrismDef]


# ---------------------------------------------------------------------------
# Track builders
# ---------------------------------------------------------------------------


def beam_drift_track(base_angle: float, drift: float, phase: float = 0.0) -> Track:
    """Gentle beam angular drift — back and forth over the full duration."""
    return Track(
        [
            Key(0.0, base_angle - drift / 2 * math.cos(phase)),
            Key(DURATION / 2, base_angle + drift / 2 * math.cos(phase), ease="ease_in_out_sine"),
            Key(DURATION, base_angle - drift / 2 * math.cos(phase), ease="ease_in_out_sine"),
        ],
        wrap=Wrap.CLAMP,
    )


# ---------------------------------------------------------------------------
# Scene builder
# ---------------------------------------------------------------------------


def build_animate(p: AnimParams):
    """Return an animate(ctx) -> Frame callable."""
    left_angle_trk = beam_drift_track(p.beam_left_angle, p.beam_left_drift)
    top_angle_trk = beam_drift_track(p.beam_top_angle, p.beam_top_drift, phase=math.pi / 3)

    # Build prism shapes once (they are static)
    prism_shapes = [
        prism(
            center=(pd.center_x, pd.center_y),
            size=pd.size,
            material_id=PRISM_GLASS_ID,
            rotation=pd.rotation,
            corner_radius=0.005,
            id_prefix=f"prism_{i}",
        )
        for i, pd in enumerate(p.prisms)
    ]

    def animate(ctx: FrameContext) -> Frame:
        left_angle = float(left_angle_trk(ctx.time))
        top_angle = float(top_angle_trk(ctx.time))

        scene = Scene(
            materials=MATERIALS,
            shapes=[
                *mirror_box(1.6, 0.9, WALL_ID, id_prefix="wall"),
                *prism_shapes,
            ],
            lights=[
                ProjectorLight(
                    id="beam_left",
                    position=[-1.45, p.beam_left_y],
                    direction=[math.cos(left_angle), math.sin(left_angle)],
                    source_radius=0.015,
                    spread=p.beam_left_spread,
                    source="ball",
                    intensity=1.0,
                ),
                ProjectorLight(
                    id="beam_top",
                    position=[p.beam_top_x, 0.85],
                    direction=[math.cos(top_angle), math.sin(top_angle)],
                    source_radius=0.015,
                    spread=p.beam_top_spread,
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
RICHNESS_THRESHOLD = 0.15
MIN_COLORFUL_SECONDS = 2.0
PROBE_FPS = 4
PROBE_W, PROBE_H = 640, 360


# ---------------------------------------------------------------------------
# Smart parameter sampling
# ---------------------------------------------------------------------------


def random_params(rng: random.Random) -> AnimParams:
    """Sample random twin-beams animation parameters."""
    # Left-wall beam: positioned on the left wall, aimed roughly rightward
    beam_left_y = rng.uniform(-0.4, 0.4)
    jitter_left = rng.uniform(-0.10, 0.10)
    beam_left_angle = math.atan2(-beam_left_y, 1.45) + jitter_left
    beam_left_drift = rng.uniform(0.06, 0.18)
    beam_left_spread = rng.uniform(0.04, 0.06)

    # Top-wall beam: positioned on the top wall, aimed roughly downward
    beam_top_x = rng.uniform(-0.5, 0.5)
    jitter_top = rng.uniform(-0.10, 0.10)
    beam_top_angle = math.atan2(-0.85, -beam_top_x) + jitter_top
    beam_top_drift = rng.uniform(0.06, 0.18)
    beam_top_spread = rng.uniform(0.04, 0.06)

    # 1-2 prisms near center
    n_prisms = rng.randint(1, 2)
    prisms: list[PrismDef] = []
    for _ in range(n_prisms):
        cx = rng.uniform(-0.35, 0.35)
        cy = rng.uniform(-0.25, 0.25)
        size = rng.uniform(0.15, 0.30)
        rotation = rng.uniform(0, math.tau)
        prisms.append(PrismDef(center_x=cx, center_y=cy, size=size, rotation=rotation))

    return AnimParams(
        beam_left_y=beam_left_y,
        beam_left_angle=beam_left_angle,
        beam_left_drift=beam_left_drift,
        beam_left_spread=beam_left_spread,
        beam_top_x=beam_top_x,
        beam_top_angle=beam_top_angle,
        beam_top_drift=beam_top_drift,
        beam_top_spread=beam_top_spread,
        prisms=prisms,
    )


# ---------------------------------------------------------------------------
# Beauty check
# ---------------------------------------------------------------------------


def make_probe_shot() -> Shot:
    """Low-res shot for color evaluation."""
    shot = Shot.preset("draft", width=PROBE_W, height=PROBE_H, rays=200_000, depth=10)
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
        exposure=-5.5,
        gamma=2.0,
        tonemap="reinhardx",
        white_point=0.5,
        normalize="rays",
        temperature=0.1,
    )
    return shot


def _params_to_dict(p: AnimParams) -> dict:
    d = {
        "beam_left_y": p.beam_left_y,
        "beam_left_angle": p.beam_left_angle,
        "beam_left_drift": p.beam_left_drift,
        "beam_left_spread": p.beam_left_spread,
        "beam_top_x": p.beam_top_x,
        "beam_top_angle": p.beam_top_angle,
        "beam_top_drift": p.beam_top_drift,
        "beam_top_spread": p.beam_top_spread,
        "prisms": [
            {
                "center_x": pd.center_x,
                "center_y": pd.center_y,
                "size": pd.size,
                "rotation": pd.rotation,
            }
            for pd in p.prisms
        ],
    }
    return d


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

    base_dir = Path("renders/families/twin_beams")
    found = 0

    for attempt in range(1, MAX_ATTEMPTS + 1):
        p = random_params(rng)

        n_prisms = len(p.prisms)
        print(
            f"[{attempt}] prisms={n_prisms} left_y={p.beam_left_y:.2f} top_x={p.beam_top_x:.2f} — checking beauty...",
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
