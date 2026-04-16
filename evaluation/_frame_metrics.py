"""Shared helpers for evaluation-side metric compatibility."""

from __future__ import annotations

from typing import Any

import numpy as np

_LEGACY_BASELINE_METRIC_KEYS = {
    "mean_luma": "mean",
    "median_luma": "median",
    "p95_luma": "highlight_ceiling",
    "luma_histogram": "histogram",
}


def _pixel_luma_histogram(pixels: Any, width: int, height: int) -> list[int] | None:
    """Rebuild the engine's BT.709 luma histogram from RGB8 pixels."""
    if width <= 0 or height <= 0:
        return None

    rgb = np.frombuffer(pixels, dtype=np.uint8)
    expected = width * height * 3
    if rgb.size < expected:
        return None

    rgb = rgb[:expected].reshape(height, width, 3)
    luminance = (
        218 * rgb[..., 0].astype(np.uint32)
        + 732 * rgb[..., 1].astype(np.uint32)
        + 74 * rgb[..., 2].astype(np.uint32)
    ) >> 10
    histogram = np.bincount(luminance.ravel(), minlength=256)
    return histogram.astype(int).tolist()


def result_luma_histogram(result) -> list[int] | None:
    """Return the best available luma histogram for a RenderResult."""
    debug = getattr(getattr(result, "analysis", None), "debug", None)
    histogram = getattr(debug, "luma_histogram", None)
    if histogram is not None:
        histogram = list(histogram)
        if sum(histogram) > 0:
            return histogram
    return _pixel_luma_histogram(result.pixels, result.width, result.height)


def normalize_baseline_metrics(metrics: dict | None) -> dict | None:
    """Map legacy single-baseline metric keys onto the current names."""
    if metrics is None:
        return None

    normalized = dict(metrics)
    for key, legacy_key in _LEGACY_BASELINE_METRIC_KEYS.items():
        if key not in normalized and legacy_key in normalized:
            normalized[key] = normalized[legacy_key]
    return normalized
