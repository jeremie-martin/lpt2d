"""Keyframe interpolation and easing functions."""

from __future__ import annotations

import math
from typing import Callable


# --- Easing functions: [0, 1] -> [0, 1] ---

def linear(t: float) -> float:
    return t

def ease_in_quad(t: float) -> float:
    return t * t

def ease_out_quad(t: float) -> float:
    return t * (2.0 - t)

def ease_in_out_quad(t: float) -> float:
    return 2.0 * t * t if t < 0.5 else -1.0 + (4.0 - 2.0 * t) * t

def ease_in_cubic(t: float) -> float:
    return t * t * t

def ease_out_cubic(t: float) -> float:
    u = t - 1.0
    return u * u * u + 1.0

def ease_in_out_cubic(t: float) -> float:
    if t < 0.5:
        return 4.0 * t * t * t
    u = 2.0 * t - 2.0
    return 0.5 * u * u * u + 1.0

def ease_in_sine(t: float) -> float:
    return 1.0 - math.cos(t * math.pi / 2.0)

def ease_out_sine(t: float) -> float:
    return math.sin(t * math.pi / 2.0)

def ease_in_out_sine(t: float) -> float:
    return 0.5 * (1.0 - math.cos(math.pi * t))

def smoothstep(t: float) -> float:
    return t * t * (3.0 - 2.0 * t)

def step(t: float) -> float:
    return 0.0 if t < 1.0 else 1.0


EASINGS: dict[str, Callable[[float], float]] = {
    "linear": linear,
    "ease_in_quad": ease_in_quad,
    "ease_out_quad": ease_out_quad,
    "ease_in_out_quad": ease_in_out_quad,
    "ease_in_cubic": ease_in_cubic,
    "ease_out_cubic": ease_out_cubic,
    "ease_in_out_cubic": ease_in_out_cubic,
    "ease_in_sine": ease_in_sine,
    "ease_out_sine": ease_out_sine,
    "ease_in_out_sine": ease_in_out_sine,
    "smoothstep": smoothstep,
    "step": step,
}


def keyframe(t: float, points: dict[float, float], easing: str = "linear") -> float:
    """Interpolate between keyframes at time t.

    Args:
        t: Current time in seconds.
        points: {time: value} dict, e.g. {0: -1.0, 2.5: 0.5, 5.0: -1.0}.
        easing: Name of easing function applied to interpolation parameter.

    Returns:
        Interpolated value. Holds first/last value outside keyframe range.
    """
    if not points:
        return 0.0
    times = sorted(points.keys())
    if t <= times[0]:
        return points[times[0]]
    if t >= times[-1]:
        return points[times[-1]]

    # Find bracketing keyframes
    for i in range(len(times) - 1):
        if times[i] <= t <= times[i + 1]:
            t0, t1 = times[i], times[i + 1]
            v0, v1 = points[t0], points[t1]
            p = (t - t0) / (t1 - t0)
            ease_fn = EASINGS.get(easing, linear)
            p = ease_fn(p)
            return v0 + (v1 - v0) * p

    return points[times[-1]]


def keyframe2(t: float, points: dict[float, tuple | list], easing: str = "linear") -> list[float]:
    """Like keyframe() but for 2D vectors. Returns [x, y].

    Args:
        t: Current time in seconds.
        points: {time: (x, y)} dict.
        easing: Name of easing function.
    """
    if not points:
        return [0.0, 0.0]
    px = {k: v[0] for k, v in points.items()}
    py = {k: v[1] for k, v in points.items()}
    return [keyframe(t, px, easing), keyframe(t, py, easing)]
