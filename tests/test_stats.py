"""Unit tests for the stats pipeline: quality gates and A/B comparison."""

from __future__ import annotations

import pytest

from anim import renderer as renderer_mod
from anim.stats import (
    FrameStats,
    QualityGate,
    StatsDiff,
    check_quality,
    compare_stats,
    compare_summary,
)
from anim.types import FrameReport

# --- QualityGate / check_quality ---


def _report(**kwargs) -> FrameReport:
    """Build a FrameReport with live metrics."""
    defaults: dict = dict(
        frame=0,
        rays=1000,
        time_ms=10,
        max_hdr=1.0,
        total_rays=1000,
        mean=50.0,
        pct_black=0.3,
        pct_clipped=0.01,
        p50=40.0,
        p95=180.0,
    )
    defaults.update(kwargs)
    return FrameReport(**defaults)


def test_quality_gate_passes():
    gate = QualityGate()
    report = _report(mean=100.0, pct_clipped=0.01, pct_black=0.3)
    warnings = check_quality(report, gate)
    assert warnings == []


def test_quality_gate_clipping():
    gate = QualityGate(max_pct_clipped=0.05)
    report = _report(mean=200.0, pct_clipped=0.12)
    warnings = check_quality(report, gate)
    assert len(warnings) == 1
    assert "clipping" in warnings[0]


def test_quality_gate_underexposed():
    gate = QualityGate(min_mean=0.3)
    # mean=10 => 10/255 = 0.039, well below 0.3
    report = _report(mean=10.0)
    warnings = check_quality(report, gate)
    assert any("mean brightness" in w for w in warnings)


def test_quality_gate_too_black():
    gate = QualityGate(max_pct_black=0.5)
    report = _report(pct_black=0.85)
    warnings = check_quality(report, gate)
    assert any("black" in w for w in warnings)


def test_quality_gate_no_metrics():
    """When live metrics are None (old binary), check_quality returns empty."""
    gate = QualityGate()
    report = FrameReport(frame=0, rays=1000, time_ms=10, max_hdr=1.0, total_rays=1000)
    warnings = check_quality(report, gate)
    assert warnings == []


# --- StatsDiff / compare_stats ---


def _frame_stats(**kwargs) -> FrameStats:
    defaults: dict = dict(
        mean=50.0,
        max=200,
        min=0,
        std=30.0,
        pct_black=0.3,
        pct_clipped=0.02,
        p05=5.0,
        p50=40.0,
        p95=180.0,
        width=100,
        height=100,
    )
    defaults.update(kwargs)
    return FrameStats(**defaults)


def test_compare_stats_zero_diff():
    a = [(0, 0.0, _frame_stats())]
    b = [(0, 0.0, _frame_stats())]
    diffs = compare_stats(a, b)
    assert len(diffs) == 1
    _, _, d = diffs[0]
    assert d.mean == 0.0
    assert d.pct_clipped == 0.0


def test_compare_stats_exposure_change():
    a = [(0, 0.0, _frame_stats(mean=50.0, pct_clipped=0.02, p95=180.0))]
    b = [(0, 0.0, _frame_stats(mean=80.0, pct_clipped=0.08, p95=220.0))]
    diffs = compare_stats(a, b)
    _, _, d = diffs[0]
    assert d.mean == pytest.approx(30.0)
    assert d.pct_clipped == pytest.approx(0.06)
    assert d.p95 == pytest.approx(40.0)


def test_compare_stats_length_mismatch():
    a = [(0, 0.0, _frame_stats())]
    b = [(0, 0.0, _frame_stats()), (1, 0.5, _frame_stats())]
    with pytest.raises(ValueError, match="Mismatched"):
        compare_stats(a, b)


def test_compare_summary():
    a = [(0, 0.0, _frame_stats(mean=50.0)), (1, 0.5, _frame_stats(mean=60.0))]
    b = [(0, 0.0, _frame_stats(mean=70.0)), (1, 0.5, _frame_stats(mean=80.0))]
    diffs = compare_stats(a, b)
    summary = compare_summary(diffs)
    assert "A/B comparison" in summary
    assert "2 frames" in summary
    assert "average" in summary


def test_stats_diff_summary():
    d = StatsDiff(mean=5.0, pct_black=-0.1, pct_clipped=0.02, p50=3.0, p95=10.0)
    s = d.summary()
    assert "mean=+5.00" in s
    assert "clip=+0.02" in s


def test_renderer_enables_histogram(monkeypatch):
    captured = {}

    class DummyProc:
        def __init__(self):
            self.stdin = None
            self.stdout = None
            self.stderr = None

        def poll(self):
            return 0

        def wait(self):
            return 0

    def fake_popen(cmd, stdin=None, stdout=None, stderr=None):
        captured["cmd"] = cmd
        return DummyProc()

    monkeypatch.setattr(renderer_mod.subprocess, "Popen", fake_popen)
    renderer = renderer_mod.Renderer(fast=True)
    assert "--histogram" in captured["cmd"]
    renderer.close()
