"""Easing functions: [0, 1] -> [0, 1], with analytical derivatives."""

from __future__ import annotations

import math
from typing import Callable

_HALF_PI = math.pi / 2.0


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
    return 1.0 - math.cos(t * _HALF_PI)


def ease_out_sine(t: float) -> float:
    return math.sin(t * _HALF_PI)


def ease_in_out_sine(t: float) -> float:
    return 0.5 * (1.0 - math.cos(math.pi * t))


def smoothstep(t: float) -> float:
    return t * t * (3.0 - 2.0 * t)


def step(t: float) -> float:
    return 0.0 if t < 1.0 else 1.0


# ─── Analytical derivatives ──────────────────────────────────────


def linear_d(t: float) -> float:
    return 1.0


def ease_in_quad_d(t: float) -> float:
    return 2.0 * t


def ease_out_quad_d(t: float) -> float:
    return 2.0 - 2.0 * t


def ease_in_out_quad_d(t: float) -> float:
    return 4.0 * t if t < 0.5 else 4.0 - 4.0 * t


def ease_in_cubic_d(t: float) -> float:
    return 3.0 * t * t


def ease_out_cubic_d(t: float) -> float:
    u = 1.0 - t
    return 3.0 * u * u


def ease_in_out_cubic_d(t: float) -> float:
    if t < 0.5:
        return 12.0 * t * t
    u = 1.0 - t
    return 12.0 * u * u


def ease_in_sine_d(t: float) -> float:
    return _HALF_PI * math.sin(t * _HALF_PI)


def ease_out_sine_d(t: float) -> float:
    return _HALF_PI * math.cos(t * _HALF_PI)


def ease_in_out_sine_d(t: float) -> float:
    return _HALF_PI * math.sin(math.pi * t)


def smoothstep_d(t: float) -> float:
    return 6.0 * t * (1.0 - t)


def step_d(t: float) -> float:
    return 0.0


# ─── Lookup tables ───────────────────────────────────────────────

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

EASING_DERIVATIVES: dict[str, Callable[[float], float]] = {
    "linear": linear_d,
    "ease_in_quad": ease_in_quad_d,
    "ease_out_quad": ease_out_quad_d,
    "ease_in_out_quad": ease_in_out_quad_d,
    "ease_in_cubic": ease_in_cubic_d,
    "ease_out_cubic": ease_out_cubic_d,
    "ease_in_out_cubic": ease_in_out_cubic_d,
    "ease_in_sine": ease_in_sine_d,
    "ease_out_sine": ease_out_sine_d,
    "ease_in_out_sine": ease_in_out_sine_d,
    "smoothstep": smoothstep_d,
    "step": step_d,
}


def resolve_easing(ease: str | Callable[[float], float]) -> Callable[[float], float]:
    """Resolve an easing name or callable. Raises ValueError on unknown names."""
    if callable(ease):
        return ease
    if ease not in EASINGS:
        raise ValueError(f"Unknown easing {ease!r}. Available: {', '.join(sorted(EASINGS))}")
    return EASINGS[ease]


def resolve_easing_derivative(ease: str | Callable[[float], float]) -> Callable[[float], float]:
    """Resolve the derivative of an easing function.

    For built-in easings, returns the analytical derivative.
    For custom callables, falls back to central finite differences.
    """
    if isinstance(ease, str):
        if ease not in EASING_DERIVATIVES:
            raise ValueError(
                f"Unknown easing {ease!r}. Available: {', '.join(sorted(EASING_DERIVATIVES))}"
            )
        return EASING_DERIVATIVES[ease]

    # Match callable against built-in easings
    for name, func in EASINGS.items():
        if func is ease:
            return EASING_DERIVATIVES[name]

    # Fallback: central finite differences, clamped to [0, 1]
    def _numerical_derivative(t: float, _h: float = 1e-6) -> float:
        t0 = max(0.0, t - _h)
        t1 = min(1.0, t + _h)
        if t1 <= t0:
            return 0.0
        return (ease(t1) - ease(t0)) / (t1 - t0)

    return _numerical_derivative
