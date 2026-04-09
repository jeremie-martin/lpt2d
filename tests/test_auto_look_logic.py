"""Direct tests for auto_look pure decision helpers.

These test exposure calculation and brightness summarization without
any renderer monkeypatching.
"""

from __future__ import annotations

import math

import pytest

from anim.analysis import _choose_initial_exposure, _summarize_brightness
from anim.stats import FrameStats


def _fs(mean: float, pct_clipped: float = 0.0) -> FrameStats:
    """Build a FrameStats with only the fields relevant to auto_look."""
    return FrameStats(
        mean=mean,
        max=int(mean),
        min=0,
        std=0.0,
        pct_black=0.0,
        pct_clipped=pct_clipped,
        p05=0.0,
        p50=mean,
        p95=mean,
        width=100,
        height=100,
    )


# --- _summarize_brightness ---


class TestSummarizeBrightness:
    def test_single_frame(self):
        result = _summarize_brightness([_fs(mean=89.25)])
        assert result == pytest.approx(89.25 / 255.0)

    def test_multiple_uniform_frames(self):
        stats = [_fs(mean=100.0), _fs(mean=100.0), _fs(mean=100.0)]
        result = _summarize_brightness(stats)
        assert result == pytest.approx(100.0 / 255.0)

    def test_high_variance_uses_25th_percentile(self):
        # means: 10, 50, 200, 220 => brightnesses: ~0.039, 0.196, 0.784, 0.863
        # std >> 0.05, sorted 25th percentile = index 1 = 50/255
        stats = [_fs(mean=10.0), _fs(mean=50.0), _fs(mean=200.0), _fs(mean=220.0)]
        result = _summarize_brightness(stats)
        assert result == pytest.approx(50.0 / 255.0)

    def test_low_variance_uses_mean(self):
        stats = [_fs(mean=88.0), _fs(mean=90.0), _fs(mean=89.0), _fs(mean=91.0)]
        result = _summarize_brightness(stats)
        expected = (88 + 90 + 89 + 91) / 4 / 255.0
        assert result == pytest.approx(expected)

    def test_two_frames_high_variance(self):
        # brightnesses: 10/255 ~= 0.039, 230/255 ~= 0.902 => std >> 0.05
        # sorted: [0.039, 0.902], 25th pct = index 0 = 10/255
        stats = [_fs(mean=10.0), _fs(mean=230.0)]
        result = _summarize_brightness(stats)
        assert result == pytest.approx(10.0 / 255.0)


# --- _choose_initial_exposure ---


class TestChooseInitialExposure:
    def test_measured_matches_target(self):
        result = _choose_initial_exposure(0.35, target_mean=0.35, baseline_exposure=-5.0)
        assert result == pytest.approx(-5.0)

    def test_dark_scene_increases_exposure(self):
        # measured=0.035 (10x too dark) => baseline + log2(10) ~= -5 + 3.32
        result = _choose_initial_exposure(0.035, target_mean=0.35, baseline_exposure=-5.0)
        assert result == pytest.approx(-5.0 + math.log2(10.0))

    def test_bright_scene_decreases_exposure(self):
        # measured=0.7 (2x too bright) => baseline + log2(0.5) = -6
        result = _choose_initial_exposure(0.7, target_mean=0.35, baseline_exposure=-5.0)
        assert result == pytest.approx(-6.0)

    def test_near_zero_brightness_returns_default(self):
        result = _choose_initial_exposure(0.0005, target_mean=0.35)
        assert result == -1.0

    def test_zero_brightness_returns_default(self):
        result = _choose_initial_exposure(0.0, target_mean=0.35)
        assert result == -1.0

    def test_clamps_high(self):
        # Very dark => huge exposure, should clamp to 10.0
        # baseline -5 + log2(0.35 / 0.0011) ~= -5 + 8.3 => 3.3 (not enough)
        # Use baseline=5 so: 5 + log2(0.35/0.002) ~= 5 + 7.45 => 12.45, clamped to 10
        result = _choose_initial_exposure(0.002, target_mean=0.35, baseline_exposure=5.0)
        assert result == 10.0

    def test_clamps_low(self):
        # Extremely bright => very negative, should clamp to -15.0
        # baseline -5 + log2(0.35 / 10000) ~= -5 + (-14.8) => -19.8, clamped to -15
        result = _choose_initial_exposure(10000.0, target_mean=0.35, baseline_exposure=-5.0)
        assert result == -15.0

    def test_custom_baseline_exposure(self):
        result = _choose_initial_exposure(0.35, target_mean=0.35, baseline_exposure=-3.0)
        assert result == pytest.approx(-3.0)
