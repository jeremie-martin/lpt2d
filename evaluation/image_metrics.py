"""Pixel-level image fidelity metrics (SSIM, PSNR, MSE, max diff).

All functions operate on numpy arrays with shape (H, W, 3) and dtype uint8.
"""

from __future__ import annotations

import math

import numpy as np


def _box_filter(img: np.ndarray, win: int) -> np.ndarray:
    """Fast O(n) box filter via cumulative sum. Input: (H, W) float64."""
    pad = win // 2
    padded = np.pad(img, pad, mode="reflect")
    cs = np.cumsum(padded, axis=0)
    cs = cs[win:] - cs[:-win]
    cs = np.cumsum(cs, axis=1)
    cs = cs[:, win:] - cs[:, :-win]
    return cs / (win * win)


def compute_mse(a: np.ndarray, b: np.ndarray) -> float:
    """Mean squared error across all channels."""
    diff = a.astype(np.float64) - b.astype(np.float64)
    return float(np.mean(diff**2))


def compute_psnr(a: np.ndarray, b: np.ndarray) -> float:
    """Peak signal-to-noise ratio in dB. Returns inf for identical images."""
    mse = compute_mse(a, b)
    if mse < 1e-10:
        return float("inf")
    return 10.0 * math.log10(255.0**2 / mse)


def compute_ssim(a: np.ndarray, b: np.ndarray, win: int = 11) -> float:
    """SSIM (Wang 2004) with box filter, computed per-channel then averaged."""
    C1 = (0.01 * 255) ** 2
    C2 = (0.03 * 255) ** 2

    af = a.astype(np.float64)
    bf = b.astype(np.float64)

    ssim_channels = []
    for ch in range(af.shape[2]):
        ac = af[:, :, ch]
        bc = bf[:, :, ch]

        mu_a = _box_filter(ac, win)
        mu_b = _box_filter(bc, win)

        sigma_a2 = _box_filter(ac * ac, win) - mu_a * mu_a
        sigma_b2 = _box_filter(bc * bc, win) - mu_b * mu_b
        sigma_ab = _box_filter(ac * bc, win) - mu_a * mu_b

        num = (2 * mu_a * mu_b + C1) * (2 * sigma_ab + C2)
        den = (mu_a**2 + mu_b**2 + C1) * (sigma_a2 + sigma_b2 + C2)

        ssim_map = num / den
        ssim_channels.append(float(np.mean(ssim_map)))

    return float(np.mean(ssim_channels))


def max_abs_diff(a: np.ndarray, b: np.ndarray) -> int:
    """Maximum absolute per-channel pixel difference."""
    diff = np.abs(a.astype(np.int16) - b.astype(np.int16))
    return int(np.max(diff))


def pct_pixels_changed(a: np.ndarray, b: np.ndarray, threshold: int = 1) -> float:
    """Fraction of pixels where any channel differs by more than ``threshold``.

    The comparison is strict: with the default ``threshold=1``, an absolute
    channel delta of exactly 1 does not count as changed.
    """
    diff = np.abs(a.astype(np.int16) - b.astype(np.int16))
    return float(np.mean(np.any(diff > threshold, axis=2)))
