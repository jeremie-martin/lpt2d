"""Comparison functions that produce machine-readable verdicts."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

import numpy as np

from .image_metrics import compute_psnr, compute_ssim, max_abs_diff, pct_pixels_changed


class Verdict(Enum):
    PASS = "pass"
    WARN = "warn"
    FAIL = "fail"


@dataclass(frozen=True)
class Thresholds:
    """Configurable fidelity thresholds with sensible defaults."""

    # Primary pixel-level gates
    pass_psnr: float = 45.0
    pass_ssim: float = 0.995
    pass_max_diff: int = 10
    warn_psnr: float = 40.0
    warn_ssim: float = 0.98
    # ImageStats secondary signal
    max_mean_luma_delta: float = 5.0 / 255.0
    min_histogram_overlap: float = 0.98
    max_median_luma_delta: float = 10.0 / 255.0
    max_p95_luma_delta: float = 15.0 / 255.0
    max_near_black_fraction_delta: float = 0.05
    max_clipped_channel_fraction_delta: float = 0.05


DEFAULT_THRESHOLDS = Thresholds()


@dataclass(frozen=True)
class MetricsComparison:
    """Secondary signal: ImageStats comparison result."""

    mean_luma_delta: float
    histogram_overlap: float | None
    median_luma_delta: float
    p95_luma_delta: float
    near_black_fraction_delta: float
    clipped_channel_fraction_delta: float
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class CompareResult:
    """Full comparison result — the machine-readable verdict."""

    verdict: Verdict
    byte_identical: bool
    psnr: float
    ssim: float
    max_diff: int
    pct_changed: float
    metrics: MetricsComparison | None = None
    time_a_ms: float | None = None
    time_b_ms: float | None = None


def _histogram_overlap(a: list[int], b: list[int]) -> float:
    """Intersection coefficient for two histograms (1.0 = identical)."""
    ha = np.asarray(a, dtype=np.float64)
    hb = np.asarray(b, dtype=np.float64)
    total = max(ha.sum(), hb.sum(), 1.0)
    return float(np.minimum(ha, hb).sum() / total)


def _result_luma_histogram(result) -> list[int] | None:
    hist = list(result.analysis.debug.luma_histogram)
    return hist if sum(hist) > 0 else None


def compare_metrics(
    a_mean_luma: float,
    a_median_luma: float,
    a_p95_luma: float,
    a_near_black_fraction: float,
    a_clipped_channel_fraction: float,
    a_luma_histogram: list[int] | None,
    b_mean_luma: float,
    b_median_luma: float,
    b_p95_luma: float,
    b_near_black_fraction: float,
    b_clipped_channel_fraction: float,
    b_luma_histogram: list[int] | None,
    thresholds: Thresholds = DEFAULT_THRESHOLDS,
) -> MetricsComparison:
    """Compare ImageStats as a secondary diagnostic signal."""
    mean_delta = abs(a_mean_luma - b_mean_luma)
    median_delta = abs(a_median_luma - b_median_luma)
    p95_luma_delta = abs(a_p95_luma - b_p95_luma)
    near_black_fraction_delta = abs(a_near_black_fraction - b_near_black_fraction)
    clipped_channel_fraction_delta = abs(
        a_clipped_channel_fraction - b_clipped_channel_fraction
    )
    hist_overlap = (
        _histogram_overlap(a_luma_histogram, b_luma_histogram)
        if a_luma_histogram is not None and b_luma_histogram is not None
        else None
    )

    warnings: list[str] = []
    if mean_delta > thresholds.max_mean_luma_delta:
        warnings.append(f"mean_luma_delta={mean_delta:.4f} > {thresholds.max_mean_luma_delta}")
    if hist_overlap is not None and hist_overlap < thresholds.min_histogram_overlap:
        warnings.append(
            f"histogram_overlap={hist_overlap:.4f} < {thresholds.min_histogram_overlap}"
        )
    if median_delta > thresholds.max_median_luma_delta:
        warnings.append(
            f"median_luma_delta={median_delta:.4f} > {thresholds.max_median_luma_delta}"
        )
    if p95_luma_delta > thresholds.max_p95_luma_delta:
        warnings.append(f"p95_luma_delta={p95_luma_delta:.4f} > {thresholds.max_p95_luma_delta}")
    if near_black_fraction_delta > thresholds.max_near_black_fraction_delta:
        warnings.append(
            "near_black_fraction_delta="
            f"{near_black_fraction_delta:.4f} > {thresholds.max_near_black_fraction_delta}"
        )
    if clipped_channel_fraction_delta > thresholds.max_clipped_channel_fraction_delta:
        warnings.append(
            "clipped_channel_fraction_delta="
            f"{clipped_channel_fraction_delta:.4f} > "
            f"{thresholds.max_clipped_channel_fraction_delta}"
        )

    return MetricsComparison(
        mean_luma_delta=mean_delta,
        histogram_overlap=hist_overlap,
        median_luma_delta=median_delta,
        p95_luma_delta=p95_luma_delta,
        near_black_fraction_delta=near_black_fraction_delta,
        clipped_channel_fraction_delta=clipped_channel_fraction_delta,
        warnings=warnings,
    )


def _classify(psnr: float, ssim: float, max_diff: int, thresholds: Thresholds) -> Verdict:
    if (
        psnr >= thresholds.pass_psnr
        and ssim >= thresholds.pass_ssim
        and max_diff <= thresholds.pass_max_diff
    ):
        return Verdict.PASS
    if psnr >= thresholds.warn_psnr and ssim >= thresholds.warn_ssim:
        return Verdict.WARN
    return Verdict.FAIL


def compare_images(
    a: np.ndarray,
    b: np.ndarray,
    *,
    thresholds: Thresholds = DEFAULT_THRESHOLDS,
) -> CompareResult:
    """Compare two (H, W, 3) uint8 arrays and return a verdict."""
    if a.shape != b.shape:
        raise ValueError(f"Shape mismatch: {a.shape} vs {b.shape}")

    if np.array_equal(a, b):
        return CompareResult(
            verdict=Verdict.PASS,
            byte_identical=True,
            psnr=float("inf"),
            ssim=1.0,
            max_diff=0,
            pct_changed=0.0,
        )

    psnr = compute_psnr(a, b)
    ssim = compute_ssim(a, b)
    md = max_abs_diff(a, b)
    pc = pct_pixels_changed(a, b)

    return CompareResult(
        verdict=_classify(psnr, ssim, md, thresholds),
        byte_identical=False,
        psnr=psnr,
        ssim=ssim,
        max_diff=md,
        pct_changed=pc,
    )


def compare_render_results(
    a_result,
    b_result,
    *,
    thresholds: Thresholds = DEFAULT_THRESHOLDS,
) -> CompareResult:
    """Compare two _lpt2d.RenderResult objects (pixels + metrics + timing).

    This is the primary entry point for an autonomous optimization loop.
    """
    if a_result.width != b_result.width or a_result.height != b_result.height:
        raise ValueError(
            f"Resolution mismatch: {a_result.width}x{a_result.height}"
            f" vs {b_result.width}x{b_result.height}"
        )

    a_pixels = np.frombuffer(a_result.pixels, dtype=np.uint8).reshape(
        a_result.height, a_result.width, 3
    )
    b_pixels = np.frombuffer(b_result.pixels, dtype=np.uint8).reshape(
        b_result.height, b_result.width, 3
    )

    cr = compare_images(a_pixels, b_pixels, thresholds=thresholds)

    # Secondary signal from ImageStats
    mc = None
    a_m = a_result.metrics
    b_m = b_result.metrics
    if a_m is not None and b_m is not None:
        mc = compare_metrics(
            a_mean_luma=a_m.mean_luma,
            a_median_luma=a_m.median_luma,
            a_p95_luma=a_m.p95_luma,
            a_near_black_fraction=a_m.near_black_fraction,
            a_clipped_channel_fraction=a_m.clipped_channel_fraction,
            a_luma_histogram=_result_luma_histogram(a_result),
            b_mean_luma=b_m.mean_luma,
            b_median_luma=b_m.median_luma,
            b_p95_luma=b_m.p95_luma,
            b_near_black_fraction=b_m.near_black_fraction,
            b_clipped_channel_fraction=b_m.clipped_channel_fraction,
            b_luma_histogram=_result_luma_histogram(b_result),
            thresholds=thresholds,
        )

    a_time = a_result.time_ms if a_result.time_ms > 0 else None
    b_time = b_result.time_ms if b_result.time_ms > 0 else None

    return CompareResult(
        verdict=cr.verdict,
        byte_identical=cr.byte_identical,
        psnr=cr.psnr,
        ssim=cr.ssim,
        max_diff=cr.max_diff,
        pct_changed=cr.pct_changed,
        metrics=mc,
        time_a_ms=a_time,
        time_b_ms=b_time,
    )


def compare_to_baseline(
    result,
    baseline: dict,
    *,
    thresholds: Thresholds = DEFAULT_THRESHOLDS,
) -> CompareResult:
    """Compare a RenderResult against a loaded baseline dict.

    The baseline may come from ``load_baseline()`` or from one case entry in
    ``load_baseline_set()["cases"]``. This bridges the gap between the
    persisted baseline format (dict with ndarray pixels) and the live render
    result.
    """
    result_pixels = np.frombuffer(result.pixels, dtype=np.uint8).reshape(
        result.height, result.width, 3
    )
    baseline_pixels = baseline["pixels"]

    cr = compare_images(result_pixels, baseline_pixels, thresholds=thresholds)

    # Secondary signal from ImageStats if available
    mc = None
    r_m = result.metrics
    b_m = baseline.get("metrics")
    if r_m is not None and b_m is not None:
        mc = compare_metrics(
            a_mean_luma=r_m.mean_luma,
            a_median_luma=r_m.median_luma,
            a_p95_luma=r_m.p95_luma,
            a_near_black_fraction=r_m.near_black_fraction,
            a_clipped_channel_fraction=r_m.clipped_channel_fraction,
            a_luma_histogram=_result_luma_histogram(result),
            b_mean_luma=b_m["mean_luma"],
            b_median_luma=b_m["median_luma"],
            b_p95_luma=b_m["p95_luma"],
            b_near_black_fraction=b_m["near_black_fraction"],
            b_clipped_channel_fraction=b_m["clipped_channel_fraction"],
            b_luma_histogram=b_m.get("luma_histogram"),
            thresholds=thresholds,
        )

    result_time = result.time_ms if result.time_ms > 0 else None
    baseline_time = baseline.get("time_ms")

    return CompareResult(
        verdict=cr.verdict,
        byte_identical=cr.byte_identical,
        psnr=cr.psnr,
        ssim=cr.ssim,
        max_diff=cr.max_diff,
        pct_changed=cr.pct_changed,
        metrics=mc,
        time_a_ms=result_time,
        time_b_ms=baseline_time,
    )
