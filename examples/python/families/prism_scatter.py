"""Prism Scatter — a table of loose prisms with a sliding projector beam.

4-6 glass prisms of varying sizes are scattered at random positions and
rotations inside a mirror box.  A projector beam translates vertically
along the left wall, sweeping past each prism in turn.  As the beam
passes a prism it fans out a momentary rainbow, producing a sequential
cascade of color bursts — like light dominoes.
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

# Prism glass: moderate dispersion, subtle fill for shape visibility
PRISM_GLASS = glass(1.52, cauchy_b=28_000, color=(0.968, 0.968, 0.968), fill=0.15)
WALL_ID = "wall"
PRISM_GLASS_ID = "prism_glass"
MATERIALS = {WALL_ID: WALL, PRISM_GLASS_ID: PRISM_GLASS}

# ---------------------------------------------------------------------------
# Parameter space
# ---------------------------------------------------------------------------


@dataclass
class PrismSpec:
    """One scattered prism."""

    cx: float
    cy: float
    size: float
    rotation: float


@dataclass
class AnimParams:
    """Degrees of freedom for one prism scatter variant."""

    prisms: list[PrismSpec]
    beam_y_bottom: float  # lowest beam y
    beam_y_top: float  # highest beam y
    beam_spread: float  # projector angular spread


# ---------------------------------------------------------------------------
# Track builders
# ---------------------------------------------------------------------------


def beam_y_track(p: AnimParams) -> Track:
    """Beam slides bottom -> top -> bottom over the full duration."""
    return Track(
        [
            Key(0.0, p.beam_y_bottom),
            Key(DURATION / 2, p.beam_y_top, ease="ease_in_out_sine"),
            Key(DURATION, p.beam_y_bottom, ease="ease_in_out_sine"),
        ],
        wrap=Wrap.CLAMP,
    )


# ---------------------------------------------------------------------------
# Scene builder
# ---------------------------------------------------------------------------


def build_animate(p: AnimParams):
    """Return an animate(ctx) -> Frame callable."""
    y_trk = beam_y_track(p)

    def animate(ctx: FrameContext) -> Frame:
        beam_y = float(y_trk(ctx.time))

        prism_shapes = [
            prism(
                center=(ps.cx, ps.cy),
                size=ps.size,
                material_id=PRISM_GLASS_ID,
                rotation=ps.rotation,
                corner_radius=0.005,
                id_prefix=f"prism_{i}",
            )
            for i, ps in enumerate(p.prisms)
        ]

        scene = Scene(
            materials=MATERIALS,
            shapes=[
                *mirror_box(1.6, 0.9, WALL_ID, id_prefix="wall"),
                *prism_shapes,
            ],
            lights=[
                ProjectorLight(
                    id="beam",
                    position=[-1.45, beam_y],
                    direction=[1.0, 0.0],
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
RICHNESS_THRESHOLD = 0.30
MIN_COLORFUL_SECONDS = 2.0
PROBE_FPS = 4
PROBE_W, PROBE_H = 640, 360


# ---------------------------------------------------------------------------
# Smart parameter sampling
# ---------------------------------------------------------------------------


def _overlaps(cx: float, cy: float, size: float, existing: list[PrismSpec]) -> bool:
    """Check whether a candidate prism overlaps any existing prism."""
    for ps in existing:
        dx = cx - ps.cx
        dy = cy - ps.cy
        min_dist = (size + ps.size) * 0.75  # generous margin
        if dx * dx + dy * dy < min_dist * min_dist:
            return True
    return False


def random_params(rng: random.Random) -> AnimParams:
    """Sample random prism scatter parameters."""
    n_prisms = rng.randint(4, 6)
    prisms: list[PrismSpec] = []

    for _ in range(n_prisms):
        size = rng.uniform(0.12, 0.30)
        # Place prisms within the mirror box, leaving margin from walls
        for _try in range(50):
            cx = rng.uniform(-1.1, 1.1)
            cy = rng.uniform(-0.55, 0.55)
            if not _overlaps(cx, cy, size, prisms):
                break
        rotation = rng.uniform(0, math.tau)
        prisms.append(PrismSpec(cx=cx, cy=cy, size=size, rotation=rotation))

    beam_y_bottom = rng.uniform(-0.65, -0.55)
    beam_y_top = rng.uniform(0.55, 0.65)
    beam_spread = rng.uniform(0.08, 0.14)

    return AnimParams(
        prisms=prisms,
        beam_y_bottom=beam_y_bottom,
        beam_y_top=beam_y_top,
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
        exposure=-5.0,
        gamma=2.0,
        tonemap="reinhardx",
        white_point=0.5,
        normalize="rays",
        temperature=0.1,
    )
    return shot


def _params_to_dict(p: AnimParams) -> dict:
    """Serialize AnimParams including nested PrismSpec list."""
    d = asdict(p)
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

    base_dir = Path("renders/families/prism_scatter")
    found = 0

    for attempt in range(1, MAX_ATTEMPTS + 1):
        p = random_params(rng)
        n = len(p.prisms)
        sizes = ", ".join(f"{ps.size:.2f}" for ps in p.prisms)

        print(f"[{attempt}] prisms={n} sizes=[{sizes}] — checking beauty...", flush=True)

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
