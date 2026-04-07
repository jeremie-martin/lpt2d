"""Evaluation harness for ``lpt2d``: fidelity comparison and timing measurement."""

from .baseline import load_baseline, load_baseline_set, save_baseline, save_baseline_set
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
from .timing import (
    CaseBenchmark,
    RatioSummary,
    SceneBenchmark,
    SpeedupResult,
    TimedFrame,
    TimingSummary,
    benchmark,
    benchmark_scene,
    classify_speedup,
    summarize_times,
)

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
    "load_baseline_set",
    "max_abs_diff",
    "pct_pixels_changed",
    "save_baseline",
    "save_baseline_set",
    "CaseBenchmark",
    "RatioSummary",
    "SceneBenchmark",
    "SpeedupResult",
    "TimedFrame",
    "TimingSummary",
    "benchmark",
    "benchmark_scene",
    "classify_speedup",
    "summarize_times",
]
