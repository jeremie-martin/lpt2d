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
    # FrameMetrics secondary signal
    max_mean_lum_delta: float = 5.0
    min_histogram_overlap: float = 0.98
    max_p50_delta: float = 10.0
    max_p95_delta: float = 15.0
    max_pct_black_delta: float = 0.05
    max_pct_clipped_delta: float = 0.05


DEFAULT_THRESHOLDS = Thresholds()


@dataclass(frozen=True)
class MetricsComparison:
    """Secondary signal: FrameMetrics comparison result."""

    mean_lum_delta: float
    histogram_overlap: float
    p50_delta: float
    p95_delta: float
    pct_black_delta: float
    pct_clipped_delta: float
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


def compare_metrics(
    a_mean: float,
    a_p50: float,
    a_p95: float,
    a_pct_black: float,
    a_pct_clipped: float,
    a_histogram: list[int],
    b_mean: float,
    b_p50: float,
    b_p95: float,
    b_pct_black: float,
    b_pct_clipped: float,
    b_histogram: list[int],
    thresholds: Thresholds = DEFAULT_THRESHOLDS,
) -> MetricsComparison:
    """Compare FrameMetrics as a secondary diagnostic signal."""
    mean_delta = abs(a_mean - b_mean)
    p50_delta = abs(a_p50 - b_p50)
    p95_delta = abs(a_p95 - b_p95)
    pct_black_delta = abs(a_pct_black - b_pct_black)
    pct_clipped_delta = abs(a_pct_clipped - b_pct_clipped)
    hist_overlap = _histogram_overlap(a_histogram, b_histogram)

    warnings: list[str] = []
    if mean_delta > thresholds.max_mean_lum_delta:
        warnings.append(f"mean_lum_delta={mean_delta:.2f} > {thresholds.max_mean_lum_delta}")
    if hist_overlap < thresholds.min_histogram_overlap:
        warnings.append(
            f"histogram_overlap={hist_overlap:.4f} < {thresholds.min_histogram_overlap}"
        )
    if p50_delta > thresholds.max_p50_delta:
        warnings.append(f"p50_delta={p50_delta:.2f} > {thresholds.max_p50_delta}")
    if p95_delta > thresholds.max_p95_delta:
        warnings.append(f"p95_delta={p95_delta:.2f} > {thresholds.max_p95_delta}")
    if pct_black_delta > thresholds.max_pct_black_delta:
        warnings.append(f"pct_black_delta={pct_black_delta:.4f} > {thresholds.max_pct_black_delta}")
    if pct_clipped_delta > thresholds.max_pct_clipped_delta:
        warnings.append(
            f"pct_clipped_delta={pct_clipped_delta:.4f} > {thresholds.max_pct_clipped_delta}"
        )

    return MetricsComparison(
        mean_lum_delta=mean_delta,
        histogram_overlap=hist_overlap,
        p50_delta=p50_delta,
        p95_delta=p95_delta,
        pct_black_delta=pct_black_delta,
        pct_clipped_delta=pct_clipped_delta,
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

    # Secondary signal from FrameMetrics
    mc = None
    a_m = a_result.metrics
    b_m = b_result.metrics
    if a_m is not None and b_m is not None:
        mc = compare_metrics(
            a_mean=a_m.mean_lum,
            a_p50=a_m.p50,
            a_p95=a_m.p95,
            a_pct_black=a_m.pct_black,
            a_pct_clipped=a_m.pct_clipped,
            a_histogram=list(a_m.histogram),
            b_mean=b_m.mean_lum,
            b_p50=b_m.p50,
            b_p95=b_m.p95,
            b_pct_black=b_m.pct_black,
            b_pct_clipped=b_m.pct_clipped,
            b_histogram=list(b_m.histogram),
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

    The baseline should come from ``load_baseline()``. This bridges the gap
    between the persisted baseline format (dict with ndarray pixels) and the
    live render result.
    """
    result_pixels = np.frombuffer(result.pixels, dtype=np.uint8).reshape(
        result.height, result.width, 3
    )
    baseline_pixels = baseline["pixels"]

    cr = compare_images(result_pixels, baseline_pixels, thresholds=thresholds)

    # Secondary signal from FrameMetrics if available
    mc = None
    r_m = result.metrics
    b_m = baseline.get("metrics")
    if r_m is not None and b_m is not None:
        mc = compare_metrics(
            a_mean=r_m.mean_lum,
            a_p50=r_m.p50,
            a_p95=r_m.p95,
            a_pct_black=r_m.pct_black,
            a_pct_clipped=r_m.pct_clipped,
            a_histogram=list(r_m.histogram),
            b_mean=b_m["mean_lum"],
            b_p50=b_m["p50"],
            b_p95=b_m["p95"],
            b_pct_black=b_m["pct_black"],
            b_pct_clipped=b_m["pct_clipped"],
            b_histogram=b_m["histogram"],
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
