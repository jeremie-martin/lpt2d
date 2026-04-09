"""Quality check — colour richness + light circle measurement."""

from __future__ import annotations

import math
import random

from anim import Camera2D, Shot, Timeline, render_frame
from anim.family import Verdict, probe

from ..light_circle import LightCircle, measure_light_circles
from .grid import build_grid, remove_holes
from .params import DURATION, Params

# ---------------------------------------------------------------------------
# Thresholds
# ---------------------------------------------------------------------------

RICHNESS_THRESHOLD = 0.15
MIN_COLORFUL_SECONDS = 2.5

# Light circle thresholds (at probe resolution 640x360).
MAX_BACKGROUND = 0.92  # reject if scene is washed out
MIN_MOVING_RADIUS_PX = 5.0  # moving light must be a visible blob
MAX_MOVING_RADIUS_PX = 60.0  # not a featureless wash
MAX_RADIUS_RATIO = 3.0  # max moving / ambient circle size ratio
MIN_SHARPNESS = 0.015  # minimum edge definition

PROBE_W, PROBE_H, PROBE_RAYS = 640, 360, 200_000

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _min_object_distance(
    light_pos: tuple[float, float],
    object_positions: list[tuple[float, float]],
) -> float:
    """Minimum Euclidean distance from a light to any object centre."""
    if not object_positions:
        return float("inf")
    return min(
        math.hypot(light_pos[0] - ox, light_pos[1] - oy)
        for ox, oy in object_positions
    )


def _find_clear_frame(
    animate,
    duration: float,
    object_positions: list[tuple[float, float]],
    fps: int = 4,
) -> int:
    """Frame index where moving lights are furthest from objects.

    Calls ``animate()`` without rendering to inspect light positions.
    Returns the single best frame index for circle measurement.
    """
    timeline = Timeline(duration, fps=fps)
    best_idx = 0
    best_clearance = -1.0

    for fi in range(timeline.total_frames):
        ctx = timeline.context_at(fi)
        frame = animate(ctx)
        moving = [
            (l.position[0], l.position[1])
            for l in frame.scene.lights
            if l.id.startswith("light_")
        ]
        if not moving:
            continue
        # Worst-case clearance across all moving lights in this frame.
        clearance = min(_min_object_distance(lp, object_positions) for lp in moving)
        if clearance > best_clearance:
            best_clearance = clearance
            best_idx = fi

    return best_idx


_PROBE_CAMERA = Camera2D(center=[0, 0], width=3.2)


def _measure_circles_at_frame(
    animate,
    frame_idx: int,
    duration: float,
) -> list[LightCircle]:
    """Render one probe-quality frame and measure all light circles."""
    probe_shot = Shot.preset("draft", width=PROBE_W, height=PROBE_H, rays=PROBE_RAYS, depth=10)
    rr = render_frame(
        animate, Timeline(duration, fps=4),
        frame=frame_idx, settings=probe_shot, camera=_PROBE_CAMERA,
    )

    # Extract light positions from the animate callback's scene (call again;
    # render_frame already called it internally, but the result isn't exposed).
    ctx = Timeline(duration, fps=4).context_at(frame_idx)
    frame_result = animate(ctx)
    positions = [(l.position[0], l.position[1]) for l in frame_result.scene.lights]
    labels = [l.id for l in frame_result.scene.lights]

    return measure_light_circles(
        rr.pixels, PROBE_W, PROBE_H, positions,
        camera_center=(float(_PROBE_CAMERA.center[0]), float(_PROBE_CAMERA.center[1])),
        camera_width=float(_PROBE_CAMERA.width),
        labels=labels,
    )


# ---------------------------------------------------------------------------
# Main check
# ---------------------------------------------------------------------------


def check(p: Params, animate) -> Verdict:
    # --- colour richness (existing) ---
    frames = probe(animate, DURATION)
    colorful = sum(1 for f in frames if f.color_richness > RICHNESS_THRESHOLD)
    colorful_s = colorful / 4  # probe runs at 4 fps
    avg = sum(f.color_richness for f in frames) / len(frames)
    if colorful_s < MIN_COLORFUL_SECONDS:
        return Verdict(False, f"color={colorful_s:.1f}s avg={avg:.3f}")

    # --- light circle quality ---
    # Reconstruct object positions (same RNG sequence as build()).
    rng = random.Random(p.build_seed)
    positions = build_grid(p.grid)
    if p.grid.hole_fraction > 0:
        positions = remove_holes(positions, p.grid.hole_fraction, rng)

    best_fi = _find_clear_frame(animate, DURATION, positions)
    circles = _measure_circles_at_frame(animate, best_fi, DURATION)

    moving = [c for c in circles if c.label.startswith("light_")]
    ambient = [c for c in circles if c.label.startswith("amb_")]

    # All moving lights must be distinguishable.
    if not moving:
        return Verdict(False, f"color={colorful_s:.1f}s -- no moving lights")

    # Background saturation check.
    avg_bg = sum(c.background for c in circles) / len(circles) if circles else 0
    if avg_bg > MAX_BACKGROUND:
        return Verdict(False, f"color={colorful_s:.1f}s bg={avg_bg:.2f} (washed)")

    # Moving light radius bounds.
    med_moving_r = sorted(c.radius_px for c in moving)[len(moving) // 2]
    if med_moving_r < MIN_MOVING_RADIUS_PX:
        return Verdict(False, f"color={colorful_s:.1f}s moving_r={med_moving_r:.1f}px (too small)")
    if med_moving_r > MAX_MOVING_RADIUS_PX:
        return Verdict(False, f"color={colorful_s:.1f}s moving_r={med_moving_r:.1f}px (too large)")

    # Sharpness floor.
    min_sharp = min(c.sharpness for c in moving)
    if min_sharp < MIN_SHARPNESS:
        return Verdict(False, f"color={colorful_s:.1f}s sharp={min_sharp:.4f} (too soft)")

    # Ambient/moving ratio (only when ambient lights exist).
    ratio_msg = ""
    if ambient:
        med_amb_r = sorted(c.radius_px for c in ambient)[len(ambient) // 2]
        if med_amb_r > 0:
            ratio = med_moving_r / med_amb_r
            if ratio > MAX_RADIUS_RATIO:
                return Verdict(
                    False,
                    f"color={colorful_s:.1f}s ratio={ratio:.1f} (moving {med_moving_r:.0f}px / amb {med_amb_r:.0f}px)",
                )
            ratio_msg = f" ratio={ratio:.1f}"

    return Verdict(
        True,
        f"color={colorful_s:.1f}s moving_r={med_moving_r:.0f}px sharp={min_sharp:.3f}{ratio_msg}",
    )
