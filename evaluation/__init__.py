"""lpt2d evaluation infrastructure — fidelity comparison and timing measurement."""

from .baseline import load_baseline, save_baseline
from .compare import (
    CompareResult,
    MetricsComparison,
    Thresholds,
    Verdict,
    compare_images,
    compare_render_results,
    compare_to_baseline,
)
from .image_metrics import compute_mse, compute_psnr, compute_ssim, max_abs_diff, pct_pixels_changed
from .timing import SpeedupResult, TimingSummary, benchmark, classify_speedup

__all__ = [
    "CompareResult",
    "MetricsComparison",
    "Thresholds",
    "Verdict",
    "compare_images",
    "compare_render_results",
    "compare_to_baseline",
    "compute_mse",
    "compute_psnr",
    "compute_ssim",
    "load_baseline",
    "max_abs_diff",
    "pct_pixels_changed",
    "save_baseline",
    "SpeedupResult",
    "TimingSummary",
    "benchmark",
    "classify_speedup",
]
