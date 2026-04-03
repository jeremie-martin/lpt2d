"""Frame statistics for automated analysis and agent workflows.

Computes numeric summaries from raw RGB8 frame data without requiring
image file I/O or visual inspection.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

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
