"""Frame statistics for automated analysis and agent workflows.

Computes numeric summaries from raw RGB8 frame data without requiring
image file I/O or visual inspection.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FrameStats:
    """Numeric summary of a rendered frame's pixel values (0-255 scale)."""

    mean: float  # mean luminance
    max: int  # brightest pixel channel value
    min: int  # darkest pixel channel value
    std: float  # standard deviation of luminance
    pct_black: float  # fraction of pixels with luminance < 1
    pct_clipped: float  # fraction of pixels with any channel == 255
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
    if len(rgb) != n_pixels * 3:
        raise ValueError(f"Expected {n_pixels * 3} bytes, got {len(rgb)}")

    # Compute luminance for each pixel: 0.2126*R + 0.7152*G + 0.0722*B
    # Use integer math for speed (coefficients scaled by 1024)
    lum_r, lum_g, lum_b = 218, 732, 74  # ~0.2126, ~0.7152, ~0.0722 scaled by 1024

    luminances = bytearray(n_pixels)
    max_val = 0
    min_val = 255
    lum_sum = 0
    lum_sq_sum = 0
    black_count = 0
    clipped_count = 0

    for i in range(n_pixels):
        off = i * 3
        r, g, b = rgb[off], rgb[off + 1], rgb[off + 2]
        lum = (r * lum_r + g * lum_g + b * lum_b) >> 10
        if lum > 255:
            lum = 255
        luminances[i] = lum
        lum_sum += lum
        lum_sq_sum += lum * lum
        if lum > max_val:
            max_val = lum
        if lum < min_val:
            min_val = lum
        if lum < 1:
            black_count += 1
        if r == 255 or g == 255 or b == 255:
            clipped_count += 1

    # Also track raw channel max/min
    raw_max = 0
    raw_min = 255
    for byte in rgb:
        if byte > raw_max:
            raw_max = byte
        if byte < raw_min:
            raw_min = byte

    mean = lum_sum / n_pixels
    variance = lum_sq_sum / n_pixels - mean * mean
    std = variance**0.5 if variance > 0 else 0.0

    # Percentiles via histogram (256 bins, exact for 8-bit)
    histogram = [0] * 256
    for lum in luminances:
        histogram[lum] += 1

    def percentile(p: float) -> float:
        target = p * n_pixels
        cumulative = 0
        for val, count in enumerate(histogram):
            cumulative += count
            if cumulative >= target:
                return float(val)
        return 255.0

    return FrameStats(
        mean=mean,
        max=raw_max,
        min=raw_min,
        std=std,
        pct_black=black_count / n_pixels,
        pct_clipped=clipped_count / n_pixels,
        p05=percentile(0.05),
        p50=percentile(0.50),
        p95=percentile(0.95),
        width=width,
        height=height,
    )
