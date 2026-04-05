"""Easing functions: [0, 1] -> [0, 1]."""

from __future__ import annotations

import math
from typing import Callable


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


def resolve_easing(ease: str | Callable[[float], float]) -> Callable[[float], float]:
    """Resolve an easing name or callable. Raises ValueError on unknown names."""
    if callable(ease):
        return ease
    if ease not in EASINGS:
        raise ValueError(f"Unknown easing {ease!r}. Available: {', '.join(sorted(EASINGS))}")
    return EASINGS[ease]
