"""Beam light orbiting three glass spheres."""

import math
import sys

from anim import (
    BeamLight,
    Camera2D,
    Circle,
    Frame,
    RenderOverrides,
    Scene,
    Segment,
    SegmentLight,
    Timeline,
    glass,
    mirror,
    render,
)

ORBIT_DURATION = 12.0
ORBIT_RADIUS = 1.0
RAMP_DURATION = 2.0
START_ANGLE = math.pi
FULL_TURN = 2.0 * math.pi
BOX_HALF_EXTENT = 1.2
VIEW_MARGIN = 0.1
BOX_BOUNDS = [-BOX_HALF_EXTENT, -BOX_HALF_EXTENT, BOX_HALF_EXTENT, BOX_HALF_EXTENT]
VIEW_BOUNDS = [
    BOX_BOUNDS[0] - VIEW_MARGIN,
    BOX_BOUNDS[1] - VIEW_MARGIN,
    BOX_BOUNDS[2] + VIEW_MARGIN,
    BOX_BOUNDS[3] + VIEW_MARGIN,
]
SEGMENT_LIGHT_WIDTH_RATIO = 0.8
SEGMENT_LIGHT_VERTICAL_PROGRESS = 0.9
SEGMENT_LIGHT_INTENSITY = 1.5

CAMERA = Camera2D(bounds=VIEW_BOUNDS)


def clamp(value, lo, hi):
    return max(lo, min(value, hi))


def lerp(a, b, t):
    return a + (b - a) * t


def vertical_position(bounds, progress):
    """World-space y for a normalized top-to-bottom progress value."""
    _, ymin, _, ymax = bounds
    return lerp(ymax, ymin, clamp(progress, 0.0, 1.0))


def orbit_progress(t):
    """Normalized orbit progress with eased ramp-up/down and steady cruise."""
    u = clamp(t / ORBIT_DURATION, 0.0, 1.0)
    ramp = clamp(RAMP_DURATION / ORBIT_DURATION, 0.0, 0.49)

    if ramp == 0.0:
        return u

    max_speed = 1.0 / (1.0 - ramp)

    if u < ramp:
        x = u / ramp
        return max_speed * ramp * (x / 2.0 - math.sin(math.pi * x) / (2.0 * math.pi))

    if u > 1.0 - ramp:
        x = (1.0 - u) / ramp
        return 1.0 - max_speed * ramp * (x / 2.0 - math.sin(math.pi * x) / (2.0 * math.pi))

    accel_distance = max_speed * ramp * 0.5
    return accel_distance + max_speed * (u - ramp)


def animate(ctx):
    scene = Scene(name="orbiting_beam")

    # Three glass spheres
    for x in (-0.5, 0.0, 0.5):
        scene.shapes.append(
            Circle(
                center=[x, 0],
                radius=0.2,
                material=glass(1.5, cauchy_b=20000, absorption=0.5),
            )
        )

    # Mirror box walls
    wall = mirror(0.95)
    box_min_x, box_min_y, box_max_x, box_max_y = BOX_BOUNDS
    scene.shapes.append(Segment(a=[box_min_x, box_min_y], b=[box_max_x, box_min_y], material=wall))
    scene.shapes.append(Segment(a=[box_max_x, box_max_y], b=[box_min_x, box_max_y], material=wall))
    scene.shapes.append(Segment(a=[box_min_x, box_max_y], b=[box_min_x, box_min_y], material=wall))
    scene.shapes.append(Segment(a=[box_max_x, box_min_y], b=[box_max_x, box_max_y], material=wall))

    segment_half_width = BOX_HALF_EXTENT * SEGMENT_LIGHT_WIDTH_RATIO
    segment_y = vertical_position(BOX_BOUNDS, SEGMENT_LIGHT_VERTICAL_PROGRESS)

    scene.lights.append(
        SegmentLight(
            a=[-segment_half_width, segment_y],
            b=[segment_half_width, segment_y],
            intensity=SEGMENT_LIGHT_INTENSITY,
        )
    )

    # Beam orbiting on a circle, always aimed at center
    angle = START_ANGLE + FULL_TURN * orbit_progress(ctx.time)
    ox = math.cos(angle) * ORBIT_RADIUS
    oy = math.sin(angle) * ORBIT_RADIUS
    dx, dy = -ox, -oy
    length = math.hypot(dx, dy)
    dx /= length
    dy /= length

    scene.lights.append(
        BeamLight(
            origin=[ox, oy],
            direction=[dx, dy],
            angular_width=0.08,
            intensity=0.8,
        )
    )

    return Frame(
        scene=scene,
        render=RenderOverrides(exposure=2.2, tonemap="reinhardx", white_point=0.4),
    )


if __name__ == "__main__":
    preset = "final" if "--hq" in sys.argv else "draft"
    fps = 60 if "--hq" in sys.argv else 2
    render(
        animate,
        Timeline(ORBIT_DURATION, fps=fps),
        f"orbiting_beam_{preset}.mp4",
        settings=preset,
        camera=CAMERA,
    )
