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
    mean: float = 0.0
    percentile_01: float = 0.0
    percentile_10: float = 0.0
    median: float = 0.0
    percentile_90: float = 0.0
    shadow_floor: float = 0.0
    highlight_ceiling: float = 0.0
    highlight_peak: float = 0.0
    contrast_std: float = 0.0
    contrast_spread: float = 0.0
    histogram_entropy: float = 0.0
    histogram_entropy_normalized: float = 0.0
    near_black_fraction: float = 0.0
    near_white_fraction: float = 0.0
    shadow_fraction: float = 0.0
    midtone_fraction: float = 0.0
    highlight_fraction: float = 0.0
    clipped_channel_fraction: float = 0.0
    width: int = 100
    height: int = 100


def fake_metrics(**overrides: Any) -> Any:
    """Return a FakeMetrics cast to Any so strict type checkers accept it
    where the stats APIs expect the real ``FrameMetrics``."""
    return cast(Any, FakeMetrics(**overrides))
