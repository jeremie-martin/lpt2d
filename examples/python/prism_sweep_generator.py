"""Automated prism sweep animation generator.

Randomly samples animation parameters and verifies two constraints:

1. **Geometric** (analytical): beam on prism for the majority of the animation.
   Enters at t ∈ [0.5, 1.0]s, exits at t ∈ [9.0, 9.5]s.
2. **Beauty** (render-based): ≥ 3 seconds of frames with high spectral color richness.

When a valid animation is found, renders it in HQ and saves parameters + video.

Design
------
The beam starts just outside the prism.  ease_in_out_sine means velocity is near
zero at the endpoints — so the beam *lingers* as it enters and exits the prism,
and rushes through the empty space at the midpoint.  This makes the on-prism
portion feel slow and meditative.

The beam sweep is back-and-forth (same start/end angle).  The prism rotates
smoothly in one direction over the full duration (simple eased arc).

Parameter space
---------------
- beam position: top-left quadrant, Y spans most of the vertical range
- beam angles: start just outside prism hit-range, peak well past it
- prism rotation: random start, smooth arc to start + delta
"""

from __future__ import annotations

import json
import math
import random
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np

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

PRISM_CENTER = (0.0, 0.0)
PRISM_SIZE = 0.35
PRISM_GLASS = glass(1.52, cauchy_b=28_000, color=(0.968, 0.968, 0.968), fill=0.15)
WALL = Material(metallic=1.0, roughness=0.1, transmission=0.0, cauchy_b=0.0, albedo=1.0)
CAMERA = Camera2D(bounds=[-1.6, -0.9, 1.6, 0.9])

DURATION = 10.0
BEAM_BASE_X = -1.4

# ---------------------------------------------------------------------------
# Search tuning
# ---------------------------------------------------------------------------

MAX_ATTEMPTS = 2000
RICHNESS_THRESHOLD = 0.4
MIN_COLORFUL_SECONDS = 3.0
PROBE_FPS = 4
PROBE_W, PROBE_H = 640, 360

# Geometry: beam enters prism at t ∈ [ENTER_MIN, ENTER_MAX],
#           beam exits  prism at t ∈ [EXIT_MIN, EXIT_MAX].
ENTER_MIN, ENTER_MAX = 0.5, 1.0
EXIT_MIN, EXIT_MAX = 9.0, 9.5

# ---------------------------------------------------------------------------
# Parameter space
# ---------------------------------------------------------------------------


@dataclass
class AnimParams:
    """All degrees of freedom for one animation variant."""

    beam_x_offset: float  # small horizontal jitter from BEAM_BASE_X
    beam_y: float  # vertical position (full range with wall margin)
    beam_angle_start: float  # angle at t=0 and t=10 (just outside prism)
    beam_angle_peak: float  # angle at t=5 (farthest from prism)
    prism_rot_start: float  # initial prism rotation (rad)
    prism_rot_delta: float  # total rotation over 10 s (one direction)


def hit_range(bx: float, by: float, rotation: float) -> tuple[float, float] | None:
    """Find the angular range of beam directions that hit the prism.

    Returns (angle_lo, angle_hi) or None if no hit is possible.
    """
    verts = prism_vertices(rotation)
    # Sweep angles, find which ones hit
    hits = []
    for i in range(2000):
        a = -math.pi + i * math.tau / 2000
        dx, dy = math.cos(a), math.sin(a)
        if ray_hits_triangle(bx, by, dx, dy, verts):
            hits.append(a)
    if not hits:
        return None
    return (hits[0], hits[-1])


def random_params(rng: random.Random) -> AnimParams | None:
    """Sample random params with beam angles constructed around the hit range."""
    beam_x_offset = rng.uniform(-0.05, 0.05)
    beam_y = rng.uniform(-0.7, 0.75)
    prism_rot_start = rng.uniform(0, math.tau)
    prism_rot_delta = rng.uniform(-0.5, 0.5)

    bx = BEAM_BASE_X + beam_x_offset
    # Check hit range at the initial rotation (approximate — rotation is slow)
    hr = hit_range(bx, beam_y, prism_rot_start)
    if hr is None:
        return None
    lo, hi = hr
    width = hi - lo
    if width < 0.05:
        return None  # too narrow to be interesting

    # beam_angle_start: just outside the hit range (beam enters prism early)
    # Choose which side to start from
    side = rng.choice([-1, 1])
    margin = rng.uniform(0.03, 0.12)
    if side < 0:
        angle_start = lo - margin
        angle_peak = hi + rng.uniform(0.05, 0.4)
    else:
        angle_start = hi + margin
        angle_peak = lo - rng.uniform(0.05, 0.4)

    return AnimParams(
        beam_x_offset=beam_x_offset,
        beam_y=beam_y,
        beam_angle_start=angle_start,
        beam_angle_peak=angle_peak,
        prism_rot_start=prism_rot_start,
        prism_rot_delta=prism_rot_delta,
    )


# ---------------------------------------------------------------------------
# Geometry helpers
# ---------------------------------------------------------------------------


def prism_vertices(rotation: float) -> list[tuple[float, float]]:
    """Equilateral triangle vertices inscribed in circle of PRISM_SIZE."""
    cx, cy = PRISM_CENTER
    return [
        (
            cx + PRISM_SIZE * math.cos(rotation - i * math.tau / 3),
            cy + PRISM_SIZE * math.sin(rotation - i * math.tau / 3),
        )
        for i in range(3)
    ]


def ray_hits_segment(
    px: float, py: float, dx: float, dy: float,
    ax: float, ay: float, bx: float, by: float,
) -> bool:
    """Does ray from (px,py) in direction (dx,dy) intersect segment AB?"""
    denom = dx * (by - ay) - dy * (bx - ax)
    if abs(denom) < 1e-12:
        return False
    t = ((ax - px) * (by - ay) - (ay - py) * (bx - ax)) / denom
    s = ((ax - px) * dy - (ay - py) * dx) / denom
    return t > 0 and 0 <= s <= 1


def ray_hits_triangle(
    px: float, py: float, dx: float, dy: float,
    verts: list[tuple[float, float]],
) -> bool:
    for i in range(3):
        ax, ay = verts[i]
        bx, by = verts[(i + 1) % 3]
        if ray_hits_segment(px, py, dx, dy, ax, ay, bx, by):
            return True
    return False


# ---------------------------------------------------------------------------
# Track builders from params
# ---------------------------------------------------------------------------


def beam_angle_track(p: AnimParams) -> Track:
    """Back-and-forth sweep: start → peak → start, eased."""
    return Track(
        [
            Key(0.0, p.beam_angle_start),
            Key(DURATION / 2, p.beam_angle_peak, ease="ease_in_out_sine"),
            Key(DURATION, p.beam_angle_start, ease="ease_in_out_sine"),
        ],
        wrap=Wrap.CLAMP,
    )


def prism_rot_track(p: AnimParams) -> Track:
    """Smooth one-directional rotation over the full duration."""
    return Track(
        [
            Key(0.0, p.prism_rot_start),
            Key(DURATION, p.prism_rot_start + p.prism_rot_delta, ease="ease_in_out_sine"),
        ],
        wrap=Wrap.CLAMP,
    )


# ---------------------------------------------------------------------------
# Constraint 1: geometric (analytical)
# ---------------------------------------------------------------------------


def check_geometry(p: AnimParams) -> tuple[bool, float, float, float]:
    """Check beam-prism timing. Returns (ok, t_enter, t_exit, on_fraction)."""
    angle_trk = beam_angle_track(p)
    rot_trk = prism_rot_track(p)
    bx = BEAM_BASE_X + p.beam_x_offset
    by = p.beam_y

    n_steps = 200
    hits: list[float] = []
    for i in range(n_steps + 1):
        t = DURATION * i / n_steps
        angle = float(angle_trk(t))
        rot = float(rot_trk(t))
        dx, dy = math.cos(angle), math.sin(angle)
        verts = prism_vertices(rot)
        if ray_hits_triangle(bx, by, dx, dy, verts):
            hits.append(t)

    if not hits:
        return False, 0.0, 0.0, 0.0

    t_enter = hits[0]
    t_exit = hits[-1]
    on_fraction = len(hits) / (n_steps + 1)

    # Beam enters at [0.5, 1.0]s, exits at [9.0, 9.5]s, on prism majority.
    ok = (
        ENTER_MIN <= t_enter <= ENTER_MAX
        and EXIT_MIN <= t_exit <= EXIT_MAX
        and on_fraction >= 0.5
    )
    return ok, t_enter, t_exit, on_fraction


# ---------------------------------------------------------------------------
# Constraint 2: color richness (render-based)
# ---------------------------------------------------------------------------


def color_richness(rgb_bytes: bytes, w: int, h: int) -> float:
    """Spectral diversity: hue_entropy * mean_saturation."""
    arr = np.frombuffer(rgb_bytes, dtype=np.uint8).reshape(h, w, 3).astype(np.float32) / 255.0
    r, g, b = arr[..., 0], arr[..., 1], arr[..., 2]
    cmax = np.maximum(np.maximum(r, g), b)
    cmin = np.minimum(np.minimum(r, g), b)
    delta = cmax - cmin

    sat = np.where(cmax > 0.01, delta / cmax, 0.0)
    mean_sat = float(np.mean(sat))

    mask = sat > 0.05
    if mask.sum() < 100:
        return 0.0

    rc, gc, bc = r[mask], g[mask], b[mask]
    d = delta[mask]
    cm = cmax[mask]

    mr = cm == rc
    mg = (cm == gc) & ~mr
    mb = ~mr & ~mg

    h_vals = np.zeros(d.shape)
    h_vals[mr] = ((gc[mr] - bc[mr]) / d[mr]) % 6
    h_vals[mg] = ((bc[mg] - rc[mg]) / d[mg]) + 2
    h_vals[mb] = ((rc[mb] - gc[mb]) / d[mb]) + 4
    h_vals = (h_vals / 6.0) % 1.0

    hist, _ = np.histogram(h_vals, bins=36, range=(0, 1))
    hist = hist / hist.sum()
    hist = hist[hist > 0]
    entropy = -float(np.sum(hist * np.log2(hist)))

    return entropy * mean_sat


def build_animate(p: AnimParams):
    """Return an animate(ctx) -> Frame callable for the given params."""
    angle_trk = beam_angle_track(p)
    rot_trk = prism_rot_track(p)
    bx = BEAM_BASE_X + p.beam_x_offset
    by = p.beam_y

    def animate(ctx: FrameContext) -> Frame:
        angle = float(angle_trk(ctx.time))
        rot = float(rot_trk(ctx.time))
        scene = Scene(
            shapes=[
                *mirror_box(1.6, 0.9, WALL, id_prefix="wall"),
                prism(
                    center=PRISM_CENTER,
                    size=PRISM_SIZE,
                    material=PRISM_GLASS,
                    rotation=rot,
                    id_prefix="prism",
                ),
            ],
            lights=[
                ProjectorLight(
                    id="beam",
                    position=[bx, by],
                    direction=[math.cos(angle), math.sin(angle)],
                    source_radius=0.01,
                    spread=0.041,
                    source="ball",
                    intensity=1.0,
                ),
            ],
        )
        return Frame(scene=scene, look=Look(exposure=-4.5))

    return animate


def make_probe_shot() -> Shot:
    """Low-res fast shot for color evaluation."""
    shot = Shot.preset("draft", width=PROBE_W, height=PROBE_H, rays=200_000, depth=10)
    shot.camera = CAMERA
    shot.look = shot.look.with_overrides(
        exposure=-4.5, gamma=2.0, tonemap="reinhardx",
        white_point=0.5, normalize="rays", temperature=0.1,
    )
    return shot


def check_beauty(p: AnimParams) -> tuple[bool, int]:
    """Render low-res frames and count colorful ones."""
    animate = build_animate(p)
    shot = make_probe_shot()
    timeline = Timeline(DURATION, fps=PROBE_FPS)
    session = RenderSession(PROBE_W, PROBE_H, True)

    n_frames = timeline.total_frames
    colorful = 0

    for fi in range(n_frames):
        ctx = timeline.context_at(fi)
        result = animate(ctx)
        cpp_shot = _resolve_frame_shot(shot, result, None)
        render_result = session.render_shot(cpp_shot, fi)
        rich = color_richness(render_result.pixels, PROBE_W, PROBE_H)
        if rich > RICHNESS_THRESHOLD:
            colorful += 1

    min_colorful_frames = int(MIN_COLORFUL_SECONDS * PROBE_FPS)
    return colorful >= min_colorful_frames, colorful


# ---------------------------------------------------------------------------
# HQ render + save
# ---------------------------------------------------------------------------


def make_hq_shot() -> Shot:
    shot = Shot.preset("preview", width=480, height=270, rays=2_000_000, depth=10)
    shot.camera = CAMERA
    shot.look = shot.look.with_overrides(
        exposure=-4.5, gamma=2.0, tonemap="reinhardx",
        white_point=0.5, normalize="rays", temperature=0.1,
    )
    return shot


def render_and_save(p: AnimParams, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)

    # Save parameters
    params_path = out_dir / "params.json"
    params_path.write_text(json.dumps(asdict(p), indent=2))
    print(f"  params → {params_path}")

    # Render HQ video
    animate = build_animate(p)
    settings = make_hq_shot()
    timeline = Timeline(DURATION, fps=60)
    video_path = out_dir / "video.mp4"
    render(animate, timeline, str(video_path), settings=settings, crf=16)
    print(f"  video  → {video_path}")


# ---------------------------------------------------------------------------
# Main search loop
# ---------------------------------------------------------------------------


def main() -> None:
    seed = int(time.time()) if "--seed" not in sys.argv else int(sys.argv[sys.argv.index("--seed") + 1])
    target_count = int(sys.argv[sys.argv.index("-n") + 1]) if "-n" in sys.argv else 1
    rng = random.Random(seed)
    print(f"seed={seed} target={target_count}")

    base_dir = Path("renders/prism_sweep_gen")
    found = 0

    for attempt in range(1, MAX_ATTEMPTS + 1):
        p = random_params(rng)

        # Constraint 1: geometry
        geo_ok, t_enter, t_exit, on_frac = check_geometry(p)
        if not geo_ok:
            continue

        print(
            f"[{attempt}] geometry ok: enter={t_enter:.2f}s exit={t_exit:.2f}s "
            f"on={on_frac:.0%} — checking beauty...",
            flush=True,
        )

        # Constraint 2: beauty
        beauty_ok, n_colorful = check_beauty(p)
        colorful_seconds = n_colorful / PROBE_FPS
        print(f"  colorful={colorful_seconds:.1f}s ({n_colorful} frames)", flush=True)

        if not beauty_ok:
            continue

        found += 1
        out_dir = base_dir / f"{found:03d}"
        print(f"  FOUND #{found} — rendering HQ...")
        render_and_save(p, out_dir)
        print(f"  done.\n")

        if found >= target_count:
            break

    if found == 0:
        print(f"No valid animation found in {MAX_ATTEMPTS} attempts.")
        print("Try adjusting parameter ranges or lowering RICHNESS_THRESHOLD.")


if __name__ == "__main__":
    main()
