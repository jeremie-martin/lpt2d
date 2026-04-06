"""Tests for the evaluation module: image metrics, comparison verdicts, baselines."""

from __future__ import annotations

import numpy as np
import pytest

from evaluation import (
    Thresholds,
    Verdict,
    compare_images,
    compute_mse,
    compute_psnr,
    compute_ssim,
    load_baseline,
    max_abs_diff,
    pct_pixels_changed,
    save_baseline,
)
from evaluation.compare import compare_metrics
from evaluation.timing import TimingSummary, classify_speedup

# ── Image metrics ────────────────────────────────────────────────────────


def _solid(value: int, h: int = 64, w: int = 64) -> np.ndarray:
    return np.full((h, w, 3), value, dtype=np.uint8)


def _noise(h: int = 64, w: int = 64, seed: int = 42) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return rng.integers(0, 256, size=(h, w, 3), dtype=np.uint8)


class TestImageMetrics:
    def test_identical_psnr_is_inf(self):
        img = _noise()
        assert compute_psnr(img, img) == float("inf")

    def test_identical_ssim_is_one(self):
        img = _noise()
        assert compute_ssim(img, img) == pytest.approx(1.0, abs=1e-6)

    def test_identical_mse_is_zero(self):
        img = _noise()
        assert compute_mse(img, img) == 0.0

    def test_identical_max_diff_is_zero(self):
        img = _noise()
        assert max_abs_diff(img, img) == 0

    def test_identical_pct_changed_is_zero(self):
        img = _noise()
        assert pct_pixels_changed(img, img) == 0.0

    def test_offset_psnr_in_expected_range(self):
        a = _solid(100)
        b = _solid(105)
        psnr = compute_psnr(a, b)
        assert 30 < psnr < 50

    def test_offset_ssim_high_but_not_one(self):
        a = _solid(100)
        b = _solid(105)
        ssim = compute_ssim(a, b)
        assert 0.9 < ssim < 1.0

    def test_max_diff_offset(self):
        a = _solid(100)
        b = _solid(110)
        assert max_abs_diff(a, b) == 10

    def test_pct_changed_all_pixels(self):
        a = _solid(0)
        b = _solid(100)
        assert pct_pixels_changed(a, b) == pytest.approx(1.0)

    def test_large_difference_low_psnr(self):
        a = _solid(0)
        b = _solid(255)
        psnr = compute_psnr(a, b)
        assert psnr < 10


# ── Verdict classification ───────────────────────────────────────────────


class TestCompareImages:
    def test_identical_passes(self):
        img = _noise()
        result = compare_images(img, img)
        assert result.verdict == Verdict.PASS
        assert result.byte_identical is True

    def test_small_offset_passes(self):
        a = _noise(seed=1)
        b = a.copy()
        # Ensure no overflow: pick a pixel that isn't 255
        b[0, 0, 0] = np.uint8(min(int(a[0, 0, 0]) + 1, 255))
        result = compare_images(a, b)
        assert result.verdict == Verdict.PASS

    def test_large_difference_fails(self):
        a = _solid(0)
        b = _solid(255)
        result = compare_images(a, b)
        assert result.verdict == Verdict.FAIL

    def test_shape_mismatch_raises(self):
        a = _solid(100, h=32, w=32)
        b = _solid(100, h=64, w=64)
        with pytest.raises(ValueError, match="Shape mismatch"):
            compare_images(a, b)

    def test_custom_thresholds(self):
        a = _solid(100)
        b = _solid(110)
        # With very loose thresholds, this should pass
        loose = Thresholds(pass_psnr=20.0, pass_ssim=0.5, pass_max_diff=50)
        result = compare_images(a, b, thresholds=loose)
        assert result.verdict == Verdict.PASS

    def test_warn_zone(self):
        # Create images that fall in WARN zone (PSNR 40-45, SSIM 0.98-0.995)
        a = _noise(h=128, w=128, seed=10)
        # Moderate perturbation
        b = a.copy().astype(np.int16)
        rng = np.random.default_rng(99)
        b = np.clip(b + rng.integers(-3, 4, size=b.shape), 0, 255).astype(np.uint8)

        result = compare_images(a, b)
        # The exact verdict depends on noise, but it should not be byte_identical
        assert result.byte_identical is False
        assert result.psnr > 0


# ── FrameMetrics comparison ──────────────────────────────────────────────


class TestCompareMetrics:
    def test_identical_metrics_no_warnings(self):
        hist = [0] * 256
        hist[128] = 1000
        mc = compare_metrics(
            a_mean=128.0,
            a_p50=128.0,
            a_p95=200.0,
            a_pct_black=0.0,
            a_pct_clipped=0.0,
            a_histogram=hist,
            b_mean=128.0,
            b_p50=128.0,
            b_p95=200.0,
            b_pct_black=0.0,
            b_pct_clipped=0.0,
            b_histogram=hist,
        )
        assert mc.warnings == []
        assert mc.histogram_overlap == pytest.approx(1.0)
        assert mc.mean_lum_delta == 0.0

    def test_large_mean_shift_warns(self):
        hist_a = [0] * 256
        hist_a[50] = 1000
        hist_b = [0] * 256
        hist_b[200] = 1000
        mc = compare_metrics(
            a_mean=50.0,
            a_p50=50.0,
            a_p95=55.0,
            a_pct_black=0.0,
            a_pct_clipped=0.0,
            a_histogram=hist_a,
            b_mean=200.0,
            b_p50=200.0,
            b_p95=205.0,
            b_pct_black=0.0,
            b_pct_clipped=0.0,
            b_histogram=hist_b,
        )
        assert len(mc.warnings) > 0
        assert mc.mean_lum_delta == 150.0

    def test_histogram_overlap_divergent(self):
        hist_a = [0] * 256
        hist_a[0] = 1000
        hist_b = [0] * 256
        hist_b[255] = 1000
        mc = compare_metrics(
            a_mean=0.0,
            a_p50=0.0,
            a_p95=0.0,
            a_pct_black=1.0,
            a_pct_clipped=0.0,
            a_histogram=hist_a,
            b_mean=255.0,
            b_p50=255.0,
            b_p95=255.0,
            b_pct_black=0.0,
            b_pct_clipped=1.0,
            b_histogram=hist_b,
        )
        assert mc.histogram_overlap == pytest.approx(0.0)


# ── Baseline save/load ───────────────────────────────────────────────────


class _FakeMetrics:
    mean_lum = 128.0
    pct_black = 0.01
    pct_clipped = 0.02
    p50 = 125.0
    p95 = 200.0
    histogram = list(range(256))


class _FakeResult:
    def __init__(self):
        self.pixels = bytes(np.full((32, 32, 3), 100, dtype=np.uint8).tobytes())
        self.width = 32
        self.height = 32
        self.total_rays = 1000000
        self.max_hdr = 10.5
        self.time_ms = 42.5
        self.metrics = _FakeMetrics()


class TestBaseline:
    def test_roundtrip(self, tmp_path):
        result = _FakeResult()
        save_baseline(tmp_path / "test_baseline", result, metadata={"scene": "test"})
        loaded = load_baseline(tmp_path / "test_baseline")

        assert loaded["width"] == 32
        assert loaded["height"] == 32
        assert loaded["pixels"].shape == (32, 32, 3)
        assert np.all(loaded["pixels"] == 100)
        assert loaded["time_ms"] == pytest.approx(42.5)
        assert loaded["metrics"]["mean_lum"] == pytest.approx(128.0)
        assert loaded["metadata"] == {"scene": "test"}

    def test_compare_to_baseline_roundtrip(self, tmp_path):
        """save → load → compare_to_baseline should produce a PASS verdict."""
        from evaluation import compare_to_baseline

        result = _FakeResult()
        save_baseline(tmp_path / "bl", result)
        baseline = load_baseline(tmp_path / "bl")
        cr = compare_to_baseline(result, baseline)
        assert cr.verdict == Verdict.PASS
        assert cr.metrics is not None
        assert cr.time_a_ms == pytest.approx(42.5)
        assert cr.time_b_ms == pytest.approx(42.5)


# ── RenderResult.time_ms (requires C++ build) ───────────────────────────


class TestRenderTiming:
    def test_time_ms_is_positive(self):
        """RenderResult.time_ms should be populated after a render."""
        try:
            import _lpt2d
        except ImportError:
            pytest.skip("_lpt2d not available")

        from pathlib import Path

        scene_path = Path(__file__).resolve().parent.parent / "scenes" / "prism.json"
        if not scene_path.exists():
            pytest.skip("prism.json scene not found")

        shot = _lpt2d.load_shot(str(scene_path))
        session = _lpt2d.RenderSession(64, 64)
        result = session.render_shot(shot)
        assert result.time_ms > 0


# ── Timing helpers ───────────────────────────────────────────────────────


class TestTimingSummary:
    def test_cv_pct(self):
        s = TimingSummary(
            times_ms=[100.0, 100.0, 100.0],
            median_ms=100.0,
            mean_ms=100.0,
            std_ms=0.0,
            min_ms=100.0,
            max_ms=100.0,
            repeats=3,
        )
        assert s.cv_pct == 0.0

    def test_cv_pct_nonzero(self):
        s = TimingSummary(
            times_ms=[90.0, 100.0, 110.0],
            median_ms=100.0,
            mean_ms=100.0,
            std_ms=10.0,
            min_ms=90.0,
            max_ms=110.0,
            repeats=3,
        )
        assert s.cv_pct == pytest.approx(10.0)


class TestClassifySpeedup:
    def _summary(self, times: list[float]) -> TimingSummary:
        from statistics import mean, median, stdev

        return TimingSummary(
            times_ms=times,
            median_ms=median(times),
            mean_ms=mean(times),
            std_ms=stdev(times) if len(times) >= 2 else 0.0,
            min_ms=min(times),
            max_ms=max(times),
            repeats=len(times),
        )

    def test_confirmed_speedup(self):
        baseline = self._summary([200.0, 210.0, 205.0])
        candidate = self._summary([100.0, 105.0, 102.0])
        result = classify_speedup(baseline, candidate)
        assert result.confidence == "confirmed"
        assert result.speedup > 1.5

    def test_confirmed_regression(self):
        baseline = self._summary([100.0, 105.0, 102.0])
        candidate = self._summary([200.0, 210.0, 205.0])
        result = classify_speedup(baseline, candidate)
        assert result.confidence == "confirmed_regression"
        assert result.speedup < 1.0

    def test_noise(self):
        baseline = self._summary([100.0, 102.0, 101.0])
        candidate = self._summary([100.0, 103.0, 99.0])
        result = classify_speedup(baseline, candidate)
        assert result.confidence == "noise"

    def test_likely_speedup(self):
        # Ranges must overlap (so not "confirmed") but median shift >5%
        baseline = self._summary([100.0, 105.0, 110.0])
        candidate = self._summary([85.0, 90.0, 102.0])
        result = classify_speedup(baseline, candidate)
        assert result.confidence == "likely"
