"""Shared test fixtures for ImageStats-consuming unit tests.

The real ``_lpt2d.ImageStats`` is a C++ binding that cannot be constructed
with explicit field values, so pure-math tests (compare_stats, LookProfile,
auto_look, ...) rely on this dataclass with matching field names instead.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, cast


@dataclass
class FakeMetrics:
    width: int = 100
    height: int = 100
    mean_luma: float = 0.0
    median_luma: float = 0.0
    p05_luma: float = 0.0
    p95_luma: float = 0.0
    near_black_fraction: float = 0.0
    near_white_fraction: float = 0.0
    clipped_channel_fraction: float = 0.0
    rms_contrast: float = 0.0
    interdecile_luma_range: float = 0.0
    interdecile_luma_contrast: float = 0.0
    local_contrast: float = 0.0
    mean_saturation: float = 0.0
    p95_saturation: float = 0.0
    colorfulness: float = 0.0
    bright_neutral_fraction: float = 0.0


@dataclass
class FakeDebugStats:
    p01_luma: float = 0.0
    p10_luma: float = 0.0
    p90_luma: float = 0.0
    p99_luma: float = 0.0
    luma_entropy: float = 0.0
    luma_entropy_normalized: float = 0.0
    hue_entropy: float = 0.0
    colored_fraction: float = 0.0
    mean_saturation_colored: float = 0.0
    saturation_coverage: float = 0.0
    colorfulness_raw: float = 0.0
    luma_histogram: list[int] | None = None
    saturation_histogram: list[int] | None = None
    hue_histogram: list[int] | None = None


def fake_metrics(**overrides: Any) -> Any:
    """Return a FakeMetrics cast to Any so strict type checkers accept it
    where the stats APIs expect the real ``ImageStats``."""
    return cast(Any, FakeMetrics(**overrides))


def fake_debug_stats(**overrides: Any) -> Any:
    return cast(Any, FakeDebugStats(**overrides))
