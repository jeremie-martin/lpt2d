"""Frame statistics for automated analysis and agent workflows.

Computes numeric summaries from raw RGB8 frame data without requiring
image file I/O or visual inspection.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from .types import FrameReport

_LUM_WEIGHTS = np.array([218, 732, 74], dtype=np.uint32)


@dataclass(frozen=True)
class FrameStats:
    """Numeric summary of a rendered frame (0-255 scale).

    All metrics except pct_clipped use BT.709 luminance.
    pct_clipped uses raw RGB channels (any channel == 255).
    """

    mean: float  # mean luminance
    max: int  # brightest pixel luminance
    min: int  # darkest pixel luminance
    std: float  # standard deviation of luminance
    pct_black: float  # fraction of pixels with luminance < 1
    pct_clipped: float  # fraction of pixels with any RGB channel == 255
    p05: float  # 5th percentile luminance
    p50: float  # median luminance
    p95: float  # 95th percentile luminance
    width: int
    height: int

    def summary(self) -> str:
        """One-line human-readable summary."""
        return (
            f"mean={self.mean:.1f} med={self.p50:.0f} "
            f"range=[{self.min},{self.max}] std={self.std:.1f} "
            f"black={self.pct_black:.1%} clipped={self.pct_clipped:.1%}"
        )

    def is_underexposed(self, threshold: float = 0.6) -> bool:
        """True if most of the frame is very dark."""
        return self.pct_black > threshold

    def is_overexposed(self, threshold: float = 0.1) -> bool:
        """True if significant portion of the frame is clipped to white."""
        return self.pct_clipped > threshold


def frame_stats(rgb: bytes, width: int, height: int) -> FrameStats:
    """Compute statistics from raw RGB8 pixel data.

    Args:
        rgb: Raw RGB8 bytes (width * height * 3).
        width: Frame width in pixels.
        height: Frame height in pixels.

    Returns:
        FrameStats with luminance and exposure metrics.
    """
    n_pixels = width * height
    if n_pixels == 0:
        raise ValueError("Cannot compute stats for a 0-pixel frame")
    if len(rgb) != n_pixels * 3:
        raise ValueError(f"Expected {n_pixels * 3} bytes, got {len(rgb)}")

    arr = np.frombuffer(rgb, dtype=np.uint8).reshape(n_pixels, 3)

    # BT.709 luminance via matrix multiply (uint32 intermediate, >>10)
    lum = (arr.astype(np.uint32) @ _LUM_WEIGHTS >> 10).astype(np.uint8)

    # Histogram-based stats (256 bins, exact for uint8)
    hist = np.bincount(lum, minlength=256)
    bins = np.arange(256, dtype=np.float64)
    total = float(n_pixels)

    mean = float(np.dot(hist, bins) / total)
    variance = float(np.dot(hist, bins * bins) / total) - mean * mean
    std = variance**0.5 if variance > 0 else 0.0

    nonzero = np.nonzero(hist)[0]
    lum_min = int(nonzero[0])
    lum_max = int(nonzero[-1])

    pct_black = float(hist[0] / total)
    pct_clipped = float(
        np.count_nonzero((arr[:, 0] == 255) | (arr[:, 1] == 255) | (arr[:, 2] == 255)) / total
    )

    # Percentiles from cumulative histogram
    cdf = np.cumsum(hist)

    def _percentile(p: float) -> float:
        target = p * total
        idx = np.searchsorted(cdf, target)
        return float(min(idx, 255))

    p05 = _percentile(0.05)
    p50 = _percentile(0.50)
    p95 = _percentile(0.95)

    return FrameStats(
        mean=mean,
        max=lum_max,
        min=lum_min,
        std=std,
        pct_black=pct_black,
        pct_clipped=pct_clipped,
        p05=p05,
        p50=p50,
        p95=p95,
        width=width,
        height=height,
    )


# --- Quality gates ---


@dataclass
class QualityGate:
    """Threshold configuration for automated quality checks.

    ``min_mean`` uses 0-1 scale (mapped from the 0-255 mean luminance).
    ``max_pct_clipped`` and ``max_pct_black`` are already fractions (0-1).
    """

    max_pct_clipped: float = 0.05  # warn if clipping > 5%
    min_mean: float = 0.3  # warn if mean brightness < 0.3
    max_pct_black: float = 0.8  # warn if > 80% black pixels


def check_quality(report: FrameReport, gate: QualityGate) -> list[str]:
    """Check live metrics from a FrameReport against quality thresholds.

    Returns a list of warning strings (empty means all checks passed).
    Gracefully returns empty if live metrics are not available.
    """
    warnings: list[str] = []
    if report.mean is None:
        return warnings
    if report.pct_clipped is not None and report.pct_clipped > gate.max_pct_clipped:
        warnings.append(f"clipping {report.pct_clipped:.1%} > {gate.max_pct_clipped:.1%}")
    if report.mean / 255.0 < gate.min_mean:
        warnings.append(f"mean brightness {report.mean / 255.0:.2f} < {gate.min_mean}")
    if report.pct_black is not None and report.pct_black > gate.max_pct_black:
        warnings.append(f"black pixels {report.pct_black:.1%} > {gate.max_pct_black:.1%}")
    return warnings


# --- A/B comparison ---


@dataclass(frozen=True)
class StatsDiff:
    """Per-field difference between two FrameStats (b - a)."""

    mean: float
    pct_black: float
    pct_clipped: float
    p50: float
    p95: float

    def summary(self) -> str:
        """One-line summary with signed deltas."""

        def _fmt(name: str, val: float) -> str:
            return f"{name}={val:+.2f}"

        return " ".join(
            [
                _fmt("mean", self.mean),
                _fmt("black", self.pct_black),
                _fmt("clip", self.pct_clipped),
                _fmt("p50", self.p50),
                _fmt("p95", self.p95),
            ]
        )


def compare_stats(
    a: list[tuple[int, float, FrameStats]],
    b: list[tuple[int, float, FrameStats]],
) -> list[tuple[int, float, StatsDiff]]:
    """Compare two render_stats() results frame-by-frame.

    Both lists must have the same length and frame indices.
    Returns per-frame StatsDiff (b - a).
    """
    if len(a) != len(b):
        raise ValueError(f"Mismatched frame counts: {len(a)} vs {len(b)}")
    diffs: list[tuple[int, float, StatsDiff]] = []
    for (fi_a, t_a, sa), (fi_b, _, sb) in zip(a, b, strict=True):
        if fi_a != fi_b:
            raise ValueError(f"Frame index mismatch: {fi_a} vs {fi_b}")
        diffs.append(
            (
                fi_a,
                t_a,
                StatsDiff(
                    mean=sb.mean - sa.mean,
                    pct_black=sb.pct_black - sa.pct_black,
                    pct_clipped=sb.pct_clipped - sa.pct_clipped,
                    p50=sb.p50 - sa.p50,
                    p95=sb.p95 - sa.p95,
                ),
            )
        )
    return diffs


def compare_summary(diffs: list[tuple[int, float, StatsDiff]]) -> str:
    """Multi-line summary of an A/B stats comparison."""
    if not diffs:
        return "(no frames to compare)"
    lines = [f"A/B comparison ({len(diffs)} frames):"]
    for fi, t, d in diffs:
        lines.append(f"  frame {fi} ({t:.2f}s): {d.summary()}")
    # Aggregate
    n = len(diffs)
    avg_mean = sum(d.mean for _, _, d in diffs) / n
    avg_clip = sum(d.pct_clipped for _, _, d in diffs) / n
    lines.append(f"  average: mean={avg_mean:+.2f} clip={avg_clip:+.4f}")
    return "\n".join(lines)
