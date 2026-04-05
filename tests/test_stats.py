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
    frame_stats_from_report,
)
from anim.types import Canvas, FrameReport, Scene, Shot

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


def test_frame_stats_from_report_uses_histogram():
    report = _report(
        mean=82.0,
        pct_black=0.25,
        pct_clipped=0.5,
        p50=64.0,
        p95=200.0,
        histogram=[1, *([0] * 63), 2, *([0] * 135), 1, *([0] * 55)],
    )

    stats = frame_stats_from_report(report, width=2, height=2)

    assert stats is not None
    assert stats.mean == pytest.approx(82.0)
    assert stats.min == 0
    assert stats.max == 200
    assert stats.p05 == pytest.approx(0.0)
    assert stats.p50 == pytest.approx(64.0)
    assert stats.p95 == pytest.approx(200.0)
    assert stats.pct_black == pytest.approx(0.25)
    assert stats.pct_clipped == pytest.approx(0.5)


def test_renderer_histogram_is_opt_in(monkeypatch):
    commands = []

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
        commands.append(cmd)
        return DummyProc()

    monkeypatch.setattr(renderer_mod.subprocess, "Popen", fake_popen)
    renderer = renderer_mod.Renderer(fast=True)
    renderer.close()
    renderer = renderer_mod.Renderer(fast=True, histogram=True)
    renderer.close()

    assert "--histogram" not in commands[0]
    assert "--histogram" in commands[1]


def test_render_stats_prefers_report_histogram(monkeypatch):
    sample_histogram = [1, *([0] * 63), 2, *([0] * 135), 1, *([0] * 55)]

    class DummyRenderer:
        def __init__(self, shot=None, binary=renderer_mod.DEFAULT_BINARY, fast=False, histogram=False):
            assert histogram is True
            self.last_report = None

        def render_frame(self, wire_json: str) -> bytes:
            self.last_report = _report(
                mean=82.0,
                pct_black=0.25,
                pct_clipped=0.5,
                p50=64.0,
                p95=200.0,
                histogram=sample_histogram,
            )
            return bytes(2 * 2 * 3)

        def close(self):
            pass

    monkeypatch.setattr(renderer_mod, "Renderer", DummyRenderer)
    monkeypatch.setattr(
        renderer_mod,
        "frame_stats",
        lambda *args, **kwargs: pytest.fail("render_stats() should reuse report histogram"),
    )

    results = renderer_mod.render_stats(
        lambda ctx: Scene(),
        1.0,
        frames=0,
        settings=Shot(canvas=Canvas(width=2, height=2)),
    )

    assert len(results) == 1
    _, _, stats = results[0]
    assert stats.mean == pytest.approx(82.0)
    assert stats.max == 200
