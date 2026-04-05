"""Compiled keyframe tracks with per-segment easing."""

from __future__ import annotations

import bisect
from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Callable

from .easing import resolve_easing


class Wrap(Enum):
    CLAMP = "clamp"
    LOOP = "loop"
    PINGPONG = "pingpong"


@dataclass(frozen=True, slots=True)
class Key:
    """A keyframe: time, value, and easing into this key from the previous one.

    The first key's ease is ignored (there is no previous segment).
    """

    t: float
    value: float | tuple[float, ...]
    ease: str | Callable[[float], float] = "linear"


class Track:
    """Interpolates values over time using keyframes with per-segment easing.

    Usage::

        angle = Track([Key(0.0, 0.0), Key(10.0, math.tau, ease=smoothstep)])
        value = angle(ctx.time)

    Scalar tracks return float, N-dimensional tracks return tuple[float, ...].
    """

    __slots__ = ("_times", "_values", "_eases", "_dim", "_wrap")

    def __init__(self, keys: Sequence[Key], wrap: Wrap | str = Wrap.CLAMP) -> None:
        if not keys:
            raise ValueError("Track requires at least one Key")

        if isinstance(wrap, str):
            wrap = Wrap(wrap)
        self._wrap = wrap

        # Sort by time, resolve easings
        sorted_keys = sorted(keys, key=lambda k: k.t)

        # Determine dimensionality from first key
        first_val = sorted_keys[0].value
        if isinstance(first_val, (int, float)):
            self._dim = 0
        elif isinstance(first_val, (tuple, list)):
            self._dim = len(first_val)
        else:
            raise TypeError(f"Key value must be float or tuple, got {type(first_val).__name__}")

        times: list[float] = []
        values: list[float | tuple[float, ...]] = []
        eases: list[Callable[[float], float]] = []

        for k in sorted_keys:
            times.append(k.t)
            eases.append(resolve_easing(k.ease))

            if self._dim == 0:
                if not isinstance(k.value, (int, float)):
                    raise TypeError(f"Scalar track got non-scalar value: {k.value!r}")
                values.append(float(k.value))
            else:
                if isinstance(k.value, (int, float)):
                    raise TypeError(f"{self._dim}D track got scalar value: {k.value!r}")
                val = tuple(float(x) for x in k.value)
                if len(val) != self._dim:
                    raise ValueError(f"Dimension mismatch: expected {self._dim}, got {len(val)}")
                values.append(val)

        for i in range(1, len(times)):
            if times[i] == times[i - 1]:
                raise ValueError(f"Duplicate key time: {times[i]}")

        self._times = tuple(times)
        self._values = tuple(values)
        self._eases = tuple(eases)

    @property
    def dim(self) -> int:
        """0 for scalar, N for N-dimensional."""
        return self._dim

    @property
    def duration(self) -> float:
        """Time span from first to last key."""
        return self._times[-1] - self._times[0]

    def __call__(self, t: float) -> float | tuple[float, ...]:
        return self.at(t)

    def at(self, t: float) -> float | tuple[float, ...]:
        """Evaluate the track at time t."""
        times = self._times
        n = len(times)

        if n == 1:
            return self._values[0]

        # Wrap time
        t = self._remap_time(t)

        # Clamp
        if t <= times[0]:
            return self._values[0]
        if t >= times[-1]:
            return self._values[-1]

        # Binary search for the right bracket
        i = bisect.bisect_right(times, t) - 1
        t0, t1 = times[i], times[i + 1]
        p = (t - t0) / (t1 - t0)
        p = self._eases[i + 1](p)  # easing of destination key

        v0, v1 = self._values[i], self._values[i + 1]
        if self._dim == 0:
            return v0 + (v1 - v0) * p  # type: ignore[operator]
        return tuple(a + (b - a) * p for a, b in zip(v0, v1, strict=True))  # type: ignore[arg-type]

    def _remap_time(self, t: float) -> float:
        if self._wrap == Wrap.CLAMP:
            return t
        t_start = self._times[0]
        span = self._times[-1] - t_start
        if span <= 0:
            return t_start
        rel = t - t_start
        if self._wrap == Wrap.LOOP:
            return t_start + rel % span
        # PINGPONG
        cycle = rel % (2.0 * span)
        if cycle > span:
            cycle = 2.0 * span - cycle
        return t_start + cycle

    def __repr__(self) -> str:
        return f"Track({len(self._times)} keys, dim={self._dim}, wrap={self._wrap.value})"


def sample_scalar(track: Track, t: float) -> float:
    """Evaluate a scalar track with a runtime shape check."""
    value = track(t)
    if not isinstance(value, (int, float)):
        raise TypeError("expected a scalar track")
    return float(value)


def sample_vec2(track: Track, t: float) -> tuple[float, float]:
    """Evaluate a 2D track with a runtime shape check."""
    value = track(t)
    if not isinstance(value, tuple) or len(value) != 2:
        raise TypeError("expected a 2D track")
    return (float(value[0]), float(value[1]))
