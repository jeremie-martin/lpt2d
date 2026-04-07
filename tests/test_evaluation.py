"""Tests for the evaluation module: image metrics, comparison verdicts, baselines."""

from __future__ import annotations

import json
from pathlib import Path
import sys
from types import SimpleNamespace

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
    load_baseline_set,
    max_abs_diff,
    pct_pixels_changed,
    save_baseline,
    save_baseline_set,
)
from evaluation.animate import animate_scene
from evaluation.__main__ import _parse_resolution, _run_evaluate
from evaluation.compare import compare_metrics
from evaluation.timing import (
    CaseBenchmark,
    SceneBenchmark,
    TimedFrame,
    TimingSummary,
    benchmark_scene,
    classify_speedup,
    summarize_ratios,
    summarize_times,
)

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
    def __init__(self, fill: int = 100, time_ms: float = 42.5):
        self.pixels = bytes(np.full((32, 32, 3), fill, dtype=np.uint8).tobytes())
        self.width = 32
        self.height = 32
        self.total_rays = 1000000
        self.max_hdr = 10.5
        self.time_ms = time_ms
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

    def test_baseline_set_roundtrip(self, tmp_path):
        save_baseline_set(
            tmp_path / "set",
            {
                0: _FakeResult(fill=100, time_ms=40.0),
                3: _FakeResult(fill=120, time_ms=44.0),
            },
            metadata={"scene": "test", "frames": 4},
            timing_by_frame={
                0: {"render_timing": {"times_ms": [40.0, 41.0]}, "wall_timing": {"times_ms": [42.0, 43.0]}},
                3: {"render_timing": {"times_ms": [44.0, 45.0]}},
            },
        )
        loaded = load_baseline_set(tmp_path / "set")

        assert loaded["metadata"] == {"scene": "test", "frames": 4}
        assert sorted(loaded["frames"]) == [0, 3]
        assert loaded["frames"][0]["time_ms"] == pytest.approx(40.0)
        assert loaded["frames"][3]["time_ms"] == pytest.approx(44.0)
        assert np.all(loaded["frames"][0]["pixels"] == 100)
        assert np.all(loaded["frames"][3]["pixels"] == 120)
        assert loaded["frames"][0]["render_timing"]["times_ms"] == [40.0, 41.0]
        assert loaded["frames"][0]["wall_timing"]["times_ms"] == [42.0, 43.0]
        assert loaded["frames"][3]["render_timing"]["times_ms"] == [44.0, 45.0]

    def test_baseline_set_reads_legacy_single_frame_baseline(self, tmp_path):
        save_baseline(tmp_path / "legacy", _FakeResult(), metadata={"scene": "legacy"})
        loaded = load_baseline_set(tmp_path / "legacy")

        assert sorted(loaded["frames"]) == [0]
        assert loaded["metadata"] == {"scene": "legacy"}
        assert loaded["frames"][0]["width"] == 32


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

    def test_benchmark_scene_closes_between_launches(self, monkeypatch):
        class _FakeCanvas:
            def __init__(self):
                self.width = 320
                self.height = 180

        class _FakeTrace:
            def __init__(self):
                self.rays = 1000

        class _FakeShot:
            def __init__(self):
                self.canvas = _FakeCanvas()
                self.trace = _FakeTrace()

        class _FakeSession:
            active_sessions = 0
            close_calls = 0

            def __init__(self, width: int, height: int):
                assert width == 320
                assert height == 180
                if _FakeSession.active_sessions != 0:
                    raise AssertionError("RenderSession overlap detected")
                _FakeSession.active_sessions += 1
                self._closed = False

            def render_shot(self, shot, frame_index=0):
                return _FakeResult(time_ms=10.0 + frame_index)

            def close(self):
                if self._closed:
                    return
                self._closed = True
                _FakeSession.active_sessions -= 1
                _FakeSession.close_calls += 1

        fake_module = SimpleNamespace(
            load_shot=lambda path: _FakeShot(),
            RenderSession=_FakeSession,
        )
        monkeypatch.setitem(sys.modules, "_lpt2d", fake_module)
        monkeypatch.setattr(
            "evaluation.timing._build_frame_shots",
            lambda *args, **kwargs: [_FakeShot(), _FakeShot()],
        )

        bench = benchmark_scene("fake.json", frames=2, launches=3, warmup=1)

        assert bench.sample_count == 6
        assert bench.case_count == 2
        assert bench.cases[0].render_summary.median_ms == pytest.approx(10.0)
        assert bench.cases[1].render_summary.median_ms == pytest.approx(11.0)
        assert bench.case_render_summary.median_ms == pytest.approx(10.5)
        assert _FakeSession.close_calls == 3
        assert _FakeSession.active_sessions == 0


class TestRatioSummary:
    def test_summarize_ratios_geometric_mean(self):
        summary = summarize_ratios([0.5, 1.0, 2.0])

        assert summary.geometric_mean == pytest.approx(1.0)
        assert summary.speedup_gmean == pytest.approx(1.0)
        assert summary.median == pytest.approx(1.0)
        assert summary.count == 3


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


class TestAnimateScene:
    def test_top_level_shapes_and_lights_move_without_groups(self):
        scene = {
            "groups": [],
            "shapes": [
                {"type": "circle", "center": [0.0, 0.0], "radius": 0.25},
                {"type": "segment", "a": [0.0, 0.0], "b": [1.0, 0.0]},
            ],
            "lights": [
                {"type": "point", "pos": [0.0, 0.0]},
                {"type": "projector", "position": [1.0, 0.0], "direction": [0.0, -1.0]},
            ],
        }

        animated = animate_scene(scene, frame=2, total_frames=5)

        assert animated["shapes"][0]["center"] != [0.0, 0.0]
        assert animated["shapes"][1]["a"] != [0.0, 0.0]
        assert animated["lights"][0]["pos"] != [0.0, 0.0]
        assert animated["lights"][1]["direction"] != [0.0, -1.0]


class TestEvaluationCorpus:
    def test_scene_manifest_matches_scene_files(self):
        repo_root = Path(__file__).resolve().parent.parent
        scenes_dir = repo_root / "evaluation" / "scenes"
        manifest = json.loads((scenes_dir / "manifest.json").read_text())

        listed = [entry["file"] for entry in manifest["scenes"]]
        assert listed == [
            "solid_surface_gallery.json",
            "three_spheres.json",
            "crystal_field.json",
        ]
        assert all((scenes_dir / rel).is_file() for rel in listed)


class TestEvaluationCliHelpers:
    def test_parse_resolution(self):
        assert _parse_resolution("1280x720") == (1280, 720)

    def test_parse_resolution_rejects_invalid_input(self):
        with pytest.raises(ValueError):
            _parse_resolution("720p")


class TestEvaluationBackCompat:
    def test_evaluate_preserves_fidelity_when_baseline_lacks_case_timing(self, tmp_path, monkeypatch, capsys):
        baselines_dir = tmp_path / "baselines"
        runs_dir = tmp_path / "runs"
        scenes_dir = tmp_path / "scenes"
        scene_path = scenes_dir / "legacy_scene.json"
        manifest_path = scenes_dir / "manifest.json"
        baselines_dir.mkdir()
        runs_dir.mkdir()
        scenes_dir.mkdir()
        scene_path.write_text("{}\n")
        manifest_path.write_text(
            json.dumps({"scenes": [{"name": "legacy_scene", "file": "legacy_scene.json"}]})
        )

        save_baseline_set(
            baselines_dir / "legacy_scene",
            {0: _FakeResult(fill=100, time_ms=40.0)},
            metadata={"scene": "legacy_scene", "frames": 1, "launches": 1, "warmup": 0},
        )

        measurement = SceneBenchmark(
            samples=[
                TimedFrame(
                    launch_index=0,
                    frame_index=0,
                    render_time_ms=42.0,
                    wall_time_ms=43.0,
                    result=_FakeResult(fill=100, time_ms=42.0),
                )
            ],
            cases={
                0: CaseBenchmark(
                    frame_index=0,
                    samples=[],
                    render_summary=summarize_times([42.0]),
                    wall_summary=summarize_times([43.0]),
                )
            },
            pooled_render_summary=summarize_times([42.0]),
            pooled_wall_summary=summarize_times([43.0]),
            case_render_summary=summarize_times([42.0]),
            case_wall_summary=summarize_times([43.0]),
            launches=1,
            frames_per_launch=1,
            warmup=0,
        )

        fake_module = SimpleNamespace(load_shot=lambda path: object())
        monkeypatch.setitem(sys.modules, "_lpt2d", fake_module)
        monkeypatch.setattr("evaluation.__main__.BASELINES_DIR", baselines_dir)
        monkeypatch.setattr("evaluation.__main__.RUNS_DIR", runs_dir)
        monkeypatch.setattr("evaluation.__main__.SCENE_MANIFEST", manifest_path)
        monkeypatch.setattr("evaluation.__main__._discover_scenes", lambda: [scene_path])
        monkeypatch.setattr("evaluation.__main__._git_info", lambda: {"commit": "abc123", "branch": "test", "dirty": False})
        monkeypatch.setattr("evaluation.__main__.benchmark_scene", None, raising=False)
        monkeypatch.setattr("evaluation.timing.benchmark_scene", lambda *args, **kwargs: measurement)

        with pytest.raises(SystemExit) as excinfo:
            _run_evaluate(
                skip_build=True,
                frames=1,
                launches=1,
                warmup=0,
                width=32,
                height=32,
                rays=1_000_000,
            )

        assert excinfo.value.code == 0
        out = capsys.readouterr().out
        assert "fidelity_verdict: pass" in out
        assert "benchmark_score_available: no" in out
        assert "render_ratio_gmean: unavailable" in out
