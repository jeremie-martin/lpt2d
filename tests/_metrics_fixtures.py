"""Shared test fixtures for FrameMetrics-consuming unit tests.

The real ``_lpt2d.FrameMetrics`` / ``LuminanceStats`` is a C++ binding that
cannot be constructed with explicit field values, so pure-math tests
(compare_stats, LookProfile, auto_look, ...) rely on this dataclass with
matching field names instead.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, cast


@dataclass
class FakeMetrics:
    mean_lum: float = 0.0
    pct_black: float = 0.0
    pct_clipped: float = 0.0
    p05: float = 0.0
    p50: float = 0.0
    p95: float = 0.0
    p99: float = 0.0
    std_dev: float = 0.0
    lum_min: int = 0
    lum_max: int = 0
    width: int = 100
    height: int = 100


def fake_metrics(**overrides: Any) -> Any:
    """Return a FakeMetrics cast to Any so strict type checkers accept it
    where the stats APIs expect the real ``FrameMetrics``."""
    return cast(Any, FakeMetrics(**overrides))
