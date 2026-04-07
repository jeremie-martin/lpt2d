"""Entry point for evaluation: build, render, compare, print verdict.

Usage:
    python -m evaluation                  Build + evaluate against baseline
    python -m evaluation capture          Build + save current as baseline
    python -m evaluation --skip-build     Evaluate without rebuilding
    python -m evaluation --frames 5       Timed deterministic benchmark cases
    python -m evaluation --launches 5     Repeated launches per benchmark case
    python -m evaluation --warmup 1       Warm-up frames discarded per launch
    python -m evaluation --resolution 1280x720 --rays 2000000

Artifacts are saved to runs/<timestamp>/ with rendered images, a JSON report,
and a human-readable summary. The path is printed at the end.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import numpy as np
from PIL import Image

PROJECT_DIR = Path(__file__).resolve().parent.parent
BUILD_DIR = PROJECT_DIR / "build"
SCENES_DIR = Path(__file__).resolve().parent / "scenes"
SCENE_MANIFEST = SCENES_DIR / "manifest.json"
BASELINES_DIR = PROJECT_DIR / "baselines"
RUNS_DIR = PROJECT_DIR / "runs"

DEFAULT_FRAMES = 5
DEFAULT_LAUNCHES = 5
DEFAULT_WARMUP = 1
DEFAULT_WIDTH = 1280
DEFAULT_HEIGHT = 720
DEFAULT_RAYS = 2_000_000


# ── Build ────────────────────────────────────────────────────────────────


def _nproc() -> int:
    import os

    return os.cpu_count() or 1


def _build() -> bool:
    """Build C++ and reinstall Python package. Returns True on success."""
    t0 = time.monotonic()
    build_contract = _build_contract()

    print("=" * 60)
    print("  BUILD")
    print("=" * 60)

    # Configure explicitly so this command remains the authoritative path and
    # enforces a Release-grade build on single-config generators.
    print("\n[cmake] Configuring C++ build...\n", flush=True)
    r = subprocess.run(build_contract["configure_command"], cwd=str(PROJECT_DIR))
    if r.returncode != 0:
        print(f"\n[cmake] CONFIGURE FAILED (exit {r.returncode})", file=sys.stderr)
        return False

    # cmake build — stream output so compiler errors are visible
    print("\n[cmake] Building C++...\n", flush=True)
    r = subprocess.run(
        build_contract["build_command"],
        cwd=str(PROJECT_DIR),
    )
    if r.returncode != 0:
        print(f"\n[cmake] FAILED (exit {r.returncode})", file=sys.stderr)
        return False

    # pip install
    print("\n[uv] Installing Python package...", flush=True)
    r = subprocess.run(
        ["uv", "pip", "install", "-e", str(PROJECT_DIR)],
        cwd=str(PROJECT_DIR),
    )
    if r.returncode != 0:
        print(f"\n[uv] FAILED (exit {r.returncode})", file=sys.stderr)
        return False

    elapsed = time.monotonic() - t0
    print(f"\n[build] OK ({elapsed:.1f}s)\n", flush=True)
    return True


# ── Scene discovery ──────────────────────────────────────────────────────


def _discover_scenes() -> list[Path]:
    if not SCENE_MANIFEST.is_file():
        print(f"Error: no scene manifest at {SCENE_MANIFEST}", file=sys.stderr)
        sys.exit(2)
    manifest = json.loads(SCENE_MANIFEST.read_text())
    entries = manifest.get("scenes", [])
    if not entries:
        print(f"Error: no scenes listed in {SCENE_MANIFEST}", file=sys.stderr)
        sys.exit(2)

    scenes: list[Path] = []
    for entry in entries:
        rel_path = entry.get("file")
        if not rel_path:
            print(f"Error: scene manifest entry missing `file`: {entry}", file=sys.stderr)
            sys.exit(2)
        scene_path = SCENES_DIR / rel_path
        if not scene_path.is_file():
            print(f"Error: scene manifest references missing file {scene_path}", file=sys.stderr)
            sys.exit(2)
        scenes.append(scene_path)
    return scenes


def _save_image(pixels: bytes, width: int, height: int, path: Path) -> None:
    arr = np.frombuffer(pixels, dtype=np.uint8).reshape(height, width, 3)
    Image.fromarray(arr, "RGB").save(path)


def _git_info() -> dict:
    """Get current git commit info, if available."""
    info: dict = {}
    try:
        r = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            cwd=str(PROJECT_DIR),
        )
        if r.returncode == 0:
            info["commit"] = r.stdout.strip()
        r = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            cwd=str(PROJECT_DIR),
        )
        if r.returncode == 0:
            info["branch"] = r.stdout.strip()
        r = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True,
            text=True,
            cwd=str(PROJECT_DIR),
        )
        if r.returncode == 0:
            info["dirty"] = bool(r.stdout.strip())
    except FileNotFoundError:
        pass
    return info


def _build_contract() -> dict:
    """Return the build contract this command requests from CMake."""
    return {
        "requested_configuration": "Release",
        "configure_command": [
            "cmake",
            "-S",
            str(PROJECT_DIR),
            "-B",
            str(BUILD_DIR),
            "-DCMAKE_BUILD_TYPE=Release",
        ],
        "build_command": [
            "cmake",
            "--build",
            str(BUILD_DIR),
            "--config",
            "Release",
            f"-j{_nproc()}",
        ],
    }


def _render_settings(width: int, height: int, rays: int) -> dict:
    return {
        "width": width,
        "height": height,
        "resolution": f"{width}x{height}",
        "rays": rays,
    }


def _parse_resolution(value: str) -> tuple[int, int]:
    parts = value.lower().split("x", 1)
    if len(parts) != 2:
        raise ValueError(f"invalid resolution `{value}`; expected WIDTHxHEIGHT")
    width = int(parts[0])
    height = int(parts[1])
    if width < 1 or height < 1:
        raise ValueError(f"invalid resolution `{value}`; width and height must be > 0")
    return width, height


# ── Timing/report helpers ────────────────────────────────────────────────


def _timing_dict(summary) -> dict:
    return {
        "median_ms": summary.median_ms,
        "mean_ms": summary.mean_ms,
        "std_ms": summary.std_ms,
        "min_ms": summary.min_ms,
        "max_ms": summary.max_ms,
        "times_ms": summary.times_ms,
        "repeats": summary.repeats,
        "cv_pct": summary.cv_pct,
    }


def _combine_verdicts(verdicts: list[str]) -> str:
    lowered = [verdict.lower() for verdict in verdicts]
    if any(verdict == "fail" for verdict in lowered):
        return "fail"
    if any(verdict == "warn" for verdict in lowered):
        return "warn"
    return "pass"


def _summary_from_timing_dict(timing: dict | None):
    from .timing import summarize_times

    if not timing:
        return None

    if timing.get("times_ms"):
        return summarize_times([float(t) for t in timing["times_ms"]])

    return None


def _speedup_dict(result) -> dict:
    return {
        "speedup": result.speedup,
        "confidence": result.confidence,
        "baseline_median_ms": result.baseline.median_ms,
    }


def _ratio_dict(summary) -> dict:
    return {
        "ratio_gmean": summary.geometric_mean,
        "speedup_gmean": summary.speedup_gmean,
        "median_ratio": summary.median,
        "min_ratio": summary.min,
        "max_ratio": summary.max,
        "count": summary.count,
        "ratios": summary.ratios,
    }


# ── Capture ──────────────────────────────────────────────────────────────


def _run_capture(skip_build: bool, frames: int, launches: int, warmup: int, width: int, height: int, rays: int) -> None:
    if not skip_build:
        if not _build():
            sys.exit(2)

    import _lpt2d

    from .baseline import save_baseline_set
    from .timing import benchmark_scene

    scenes = _discover_scenes()
    BASELINES_DIR.mkdir(parents=True, exist_ok=True)
    build_contract = _build_contract()
    settings = _render_settings(width, height, rays)

    print("=" * 60)
    print("  CAPTURE BASELINE")
    print(f"  scenes:    {len(scenes)}")
    print(f"  manifest:  {SCENE_MANIFEST}")
    print(f"  frames:    {frames}")
    print(f"  launches:  {launches}")
    print(f"  warmup:    {warmup} per launch")
    print(f"  render:    {settings['resolution']} @ {settings['rays']} rays")
    print(f"  build:     {build_contract['requested_configuration']} requested")
    print("=" * 60)

    for scene_path in scenes:
        name = scene_path.stem
        print(f"\n  [{name}]", flush=True)

        try:
            shot = _lpt2d.load_shot(str(scene_path))
        except Exception as e:
            print(f"    LOAD ERROR: {e}", file=sys.stderr)
            continue

        print(f"    resolution: {settings['resolution']}", flush=True)
        print(f"    rays:       {settings['rays']}", flush=True)
        print(f"    measuring:  {frames} case(s) x {launches} launch(es)...", flush=True)

        try:
            measurement = benchmark_scene(
                str(scene_path),
                frames=frames,
                launches=launches,
                warmup=warmup,
                width=width,
                height=height,
                rays=rays,
            )
        except Exception as e:
            print(f"    RENDER ERROR: {e}", file=sys.stderr)
            continue

        print(
            f"    render:     case medians {measurement.case_render_summary.median_ms:.1f} ms"
            f" (mean={measurement.case_render_summary.mean_ms:.1f},"
            f" min={measurement.case_render_summary.min_ms:.1f},"
            f" max={measurement.case_render_summary.max_ms:.1f})"
        )
        print(
            f"    wall:       case medians {measurement.case_wall_summary.median_ms:.1f} ms"
            f" (mean={measurement.case_wall_summary.mean_ms:.1f},"
            f" min={measurement.case_wall_summary.min_ms:.1f},"
            f" max={measurement.case_wall_summary.max_ms:.1f})"
        )

        results_by_frame: dict[int, object] = {}
        for sample in measurement.samples:
            results_by_frame.setdefault(sample.frame_index, sample.result)

        timing_by_frame = {
            frame_index: {
                "render_timing": _timing_dict(case_benchmark.render_summary),
                "wall_timing": _timing_dict(case_benchmark.wall_summary),
            }
            for frame_index, case_benchmark in measurement.cases.items()
        }

        save_baseline_set(
            BASELINES_DIR / name,
            results_by_frame,
            metadata={
                "schema_version": 2,
                "scene": name,
                "frames": frames,
                "launches": launches,
                "warmup": warmup,
                "render_settings": settings,
                "case_render_timing": _timing_dict(measurement.case_render_summary),
                "case_wall_timing": _timing_dict(measurement.case_wall_summary),
                "pooled_render_timing": _timing_dict(measurement.pooled_render_summary),
                "pooled_wall_timing": _timing_dict(measurement.pooled_wall_summary),
            },
            timing_by_frame=timing_by_frame,
        )
        print(f"    saved:      {BASELINES_DIR / name}/")

    print(f"\n{'=' * 60}")
    print(f"  Baselines saved to {BASELINES_DIR}/")
    print(f"{'=' * 60}")


# ── Evaluate ─────────────────────────────────────────────────────────────


def _run_evaluate(
    skip_build: bool,
    frames: int,
    launches: int,
    warmup: int,
    width: int,
    height: int,
    rays: int,
) -> None:
    if not skip_build:
        if not _build():
            sys.exit(2)

    import _lpt2d

    from .baseline import load_baseline_set
    from .compare import compare_to_baseline
    from .timing import benchmark_scene, classify_speedup, summarize_ratios, summarize_times

    scenes = _discover_scenes()

    if not BASELINES_DIR.is_dir():
        print(
            "Error: no baselines found. Run `python -m evaluation capture` first.",
            file=sys.stderr,
        )
        sys.exit(3)

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    git = _git_info()
    commit = git.get("commit", "unknown")
    run_dir = RUNS_DIR / f"{timestamp}_{commit}"
    run_dir.mkdir(parents=True, exist_ok=True)
    build_contract = _build_contract()
    settings = _render_settings(width, height, rays)

    print("=" * 60)
    print("  EVALUATE")
    print(f"  commit:   {commit}")
    print(f"  branch:   {git.get('branch', 'unknown')}")
    print(f"  dirty:    {'yes' if git.get('dirty') else 'no'}")
    print(f"  scenes:   {len(scenes)}")
    print(f"  manifest: {SCENE_MANIFEST}")
    print(f"  frames:   {frames}")
    print(f"  launches: {launches}")
    print(f"  warmup:   {warmup} per launch")
    print(f"  render:   {settings['resolution']} @ {settings['rays']} rays")
    print(f"  build:    {build_contract['requested_configuration']} requested")
    print(f"  run_dir:  {run_dir}/")
    print("=" * 60)

    report_scenes: dict = {}
    errors: list[str] = []
    notes: list[str] = []
    scene_verdicts: list[str] = []
    all_render_case_ratios: list[float] = []
    all_wall_case_ratios: list[float] = []
    all_render_case_medians: list[float] = []
    all_wall_case_medians: list[float] = []
    all_pooled_render_times: list[float] = []
    all_pooled_wall_times: list[float] = []
    score_cases = 0

    for scene_path in scenes:
        name = scene_path.stem
        baseline_path = BASELINES_DIR / name

        if not baseline_path.is_dir():
            msg = f"{name}: no baseline at {baseline_path}"
            print(f"\n  [{name}] SKIP — no baseline", file=sys.stderr)
            errors.append(msg)
            scene_verdicts.append("fail")
            continue

        print(f"\n  [{name}]", flush=True)

        try:
            _lpt2d.load_shot(str(scene_path))
            print(f"    resolution: {settings['resolution']}", flush=True)
            print(f"    rays:       {settings['rays']}", flush=True)
        except Exception as e:
            msg = f"{name}: failed to load scene: {e}"
            print(f"    LOAD ERROR: {e}", file=sys.stderr)
            errors.append(msg)
            scene_verdicts.append("fail")
            continue

        try:
            baseline_set = load_baseline_set(baseline_path)
            baseline_frames = baseline_set["frames"]
            baseline_meta = baseline_set.get("metadata") or {}
        except Exception as e:
            msg = f"{name}: failed to load baseline: {e}"
            print(f"    BASELINE ERROR: {e}", file=sys.stderr)
            errors.append(msg)
            scene_verdicts.append("fail")
            continue

        config_mismatches: list[str] = []
        for key, expected in (("frames", frames), ("launches", launches), ("warmup", warmup)):
            actual = baseline_meta.get(key)
            if actual is not None and actual != expected:
                config_mismatches.append(f"{key}={actual} (expected {expected})")
        baseline_render_settings = baseline_meta.get("render_settings")
        if baseline_render_settings is not None and baseline_render_settings != settings:
            config_mismatches.append(
                "render_settings="
                f"{baseline_render_settings.get('resolution', 'unknown')} / {baseline_render_settings.get('rays', 'unknown')} rays"
            )
        if config_mismatches:
            msg = (
                f"{name}: baseline contract differs from requested evaluation contract: "
                + ", ".join(config_mismatches)
            )
            print(f"    BASELINE ERROR: {msg}", file=sys.stderr)
            errors.append(msg)
            scene_verdicts.append("fail")
            continue

        missing_frames = [frame_index for frame_index in range(frames) if frame_index not in baseline_frames]
        if missing_frames:
            msg = f"{name}: baseline missing frame(s) {missing_frames}"
            print(f"    BASELINE ERROR: missing frame(s) {missing_frames}", file=sys.stderr)
            errors.append(msg)
            scene_verdicts.append("fail")
            continue
        baseline_frame_zero = baseline_frames[min(baseline_frames)]
        if (
            baseline_frame_zero["width"] != width
            or baseline_frame_zero["height"] != height
        ):
            msg = (
                f"{name}: baseline resolution {baseline_frame_zero['width']}x{baseline_frame_zero['height']}"
                f" does not match requested {width}x{height}"
            )
            print(f"    BASELINE ERROR: {msg}", file=sys.stderr)
            errors.append(msg)
            scene_verdicts.append("fail")
            continue

        try:
            measurement = benchmark_scene(
                str(scene_path),
                frames=frames,
                launches=launches,
                warmup=warmup,
                width=width,
                height=height,
                rays=rays,
            )
        except Exception as e:
            msg = f"{name}: render failed: {e}"
            print(f"    RENDER ERROR: {e}", file=sys.stderr)
            errors.append(msg)
            scene_verdicts.append("fail")
            continue

        baseline_case_render_summaries: dict[int, object] = {}
        baseline_case_wall_summaries: dict[int, object] = {}
        scene_score_note = None
        for frame_index in range(frames):
            baseline_render_summary = _summary_from_timing_dict(
                baseline_frames[frame_index].get("render_timing")
            )
            if baseline_render_summary is None:
                scene_score_note = (
                    f"{name}: baseline missing per-case render timing for frame {frame_index}; "
                    "recapture with `python -m evaluation capture`"
                )
                break
            baseline_case_render_summaries[frame_index] = baseline_render_summary

            baseline_wall_summary = _summary_from_timing_dict(
                baseline_frames[frame_index].get("wall_timing")
            )
            if baseline_wall_summary is not None:
                baseline_case_wall_summaries[frame_index] = baseline_wall_summary

        scene_score_available = scene_score_note is None
        if scene_score_note is not None:
            notes.append(scene_score_note)

        all_render_case_medians.extend(
            case_benchmark.render_summary.median_ms for case_benchmark in measurement.cases.values()
        )
        all_wall_case_medians.extend(
            case_benchmark.wall_summary.median_ms for case_benchmark in measurement.cases.values()
        )
        all_pooled_render_times.extend(measurement.pooled_render_summary.times_ms)
        all_pooled_wall_times.extend(measurement.pooled_wall_summary.times_ms)

        print(
            f"    render:     case medians {measurement.case_render_summary.median_ms:.1f} ms"
            f" (mean={measurement.case_render_summary.mean_ms:.1f},"
            f" min={measurement.case_render_summary.min_ms:.1f},"
            f" max={measurement.case_render_summary.max_ms:.1f})"
        )
        print(
            f"    wall:       case medians {measurement.case_wall_summary.median_ms:.1f} ms"
            f" (mean={measurement.case_wall_summary.mean_ms:.1f},"
            f" min={measurement.case_wall_summary.min_ms:.1f},"
            f" max={measurement.case_wall_summary.max_ms:.1f})"
        )

        scene_dir = run_dir / name
        scene_dir.mkdir(parents=True, exist_ok=True)
        frame_samples: dict[int, list[dict]] = {frame_index: [] for frame_index in range(frames)}
        frame_verdicts: dict[int, list[str]] = {frame_index: [] for frame_index in range(frames)}
        sample_verdicts: list[str] = []
        sample_non_pass: list[str] = []

        for sample in measurement.samples:
            img_name = f"launch_{sample.launch_index:02d}_frame_{sample.frame_index:04d}.png"
            img_path = scene_dir / img_name
            _save_image(sample.result.pixels, sample.result.width, sample.result.height, img_path)

            fidelity = compare_to_baseline(sample.result, baseline_frames[sample.frame_index])
            verdict_value = fidelity.verdict.value
            sample_verdicts.append(verdict_value)
            frame_verdicts[sample.frame_index].append(verdict_value)

            sample_entry: dict = {
                "launch_index": sample.launch_index,
                "frame_index": sample.frame_index,
                "image": f"{name}/{img_name}",
                "verdict": verdict_value,
                "render_time_ms": sample.render_time_ms,
                "wall_time_ms": sample.wall_time_ms,
                "psnr": fidelity.psnr if not fidelity.byte_identical else "inf",
                "ssim": fidelity.ssim,
                "max_diff": fidelity.max_diff,
                "byte_identical": fidelity.byte_identical,
                "pct_changed": fidelity.pct_changed,
            }
            if fidelity.metrics:
                sample_entry["metrics"] = {
                    "mean_lum_delta": fidelity.metrics.mean_lum_delta,
                    "histogram_overlap": fidelity.metrics.histogram_overlap,
                    "p50_delta": fidelity.metrics.p50_delta,
                    "p95_delta": fidelity.metrics.p95_delta,
                    "pct_black_delta": fidelity.metrics.pct_black_delta,
                    "pct_clipped_delta": fidelity.metrics.pct_clipped_delta,
                    "warnings": fidelity.metrics.warnings,
                }
            frame_samples[sample.frame_index].append(sample_entry)

            if verdict_value != "pass":
                sample_non_pass.append(
                    f"launch={sample.launch_index} frame={sample.frame_index} verdict={verdict_value}"
                )

        scene_verdict = _combine_verdicts(sample_verdicts)
        scene_verdicts.append(scene_verdict)
        frame_reports: dict[str, dict] = {}
        scene_render_case_ratios: list[float] = []
        scene_wall_case_ratios: list[float] = []
        scene_wall_score_available = scene_score_available

        for frame_index in range(frames):
            case_benchmark = measurement.cases[frame_index]
            frame_report: dict = {
                "verdict": _combine_verdicts(frame_verdicts[frame_index]),
                "render_timing": _timing_dict(case_benchmark.render_summary),
                "wall_timing": _timing_dict(case_benchmark.wall_summary),
                "samples": frame_samples[frame_index],
            }

            if scene_score_available:
                baseline_render_summary = baseline_case_render_summaries[frame_index]
                render_ratio = case_benchmark.render_summary.median_ms / baseline_render_summary.median_ms
                scene_render_case_ratios.append(render_ratio)
                all_render_case_ratios.append(render_ratio)
                render_speedup = classify_speedup(baseline_render_summary, case_benchmark.render_summary)
                frame_report["baseline_render_timing"] = _timing_dict(baseline_render_summary)
                frame_report["render_ratio"] = render_ratio
                frame_report["render_speedup"] = render_speedup.speedup
                frame_report["render_comparison"] = _speedup_dict(render_speedup)

                baseline_wall_summary = baseline_case_wall_summaries.get(frame_index)
                if baseline_wall_summary is not None:
                    wall_ratio = case_benchmark.wall_summary.median_ms / baseline_wall_summary.median_ms
                    scene_wall_case_ratios.append(wall_ratio)
                    all_wall_case_ratios.append(wall_ratio)
                    wall_speedup = classify_speedup(baseline_wall_summary, case_benchmark.wall_summary)
                    frame_report["baseline_wall_timing"] = _timing_dict(baseline_wall_summary)
                    frame_report["wall_ratio"] = wall_ratio
                    frame_report["wall_speedup"] = wall_speedup.speedup
                    frame_report["wall_comparison"] = _speedup_dict(wall_speedup)
                else:
                    scene_wall_score_available = False

            frame_reports[str(frame_index)] = frame_report

        comparison_counts = {
            "pass": sum(1 for verdict in sample_verdicts if verdict == "pass"),
            "warn": sum(1 for verdict in sample_verdicts if verdict == "warn"),
            "fail": sum(1 for verdict in sample_verdicts if verdict == "fail"),
        }

        scene_render_ratio_summary = None
        if scene_score_available and len(scene_render_case_ratios) == frames:
            scene_render_ratio_summary = summarize_ratios(scene_render_case_ratios)
            score_cases += len(scene_render_case_ratios)
        scene_wall_ratio_summary = None
        if scene_wall_score_available and len(scene_wall_case_ratios) == frames:
            scene_wall_ratio_summary = summarize_ratios(scene_wall_case_ratios)

        if scene_render_ratio_summary is not None:
            print(
                f"    score:      ratio_gmean={scene_render_ratio_summary.geometric_mean:.4f}"
                f" speedup_gmean={scene_render_ratio_summary.speedup_gmean:.4f}x"
            )
        else:
            print("    score:      skipped (baseline lacks per-case timing metadata)")
        if scene_wall_ratio_summary is not None:
            print(
                f"    wall score: ratio_gmean={scene_wall_ratio_summary.geometric_mean:.4f}"
                f" speedup_gmean={scene_wall_ratio_summary.speedup_gmean:.4f}x"
            )
        print(
            f"    verdict:    {scene_verdict.upper()}"
            f" across {measurement.sample_count} sample(s)"
        )
        for entry in sample_non_pass[:8]:
            print(f"    sample:     {entry}")

        scene_report: dict = {
            "verdict": scene_verdict,
            "samples": measurement.sample_count,
            "cases": measurement.case_count,
            "frames_per_launch": frames,
            "launches": launches,
            "warmup": warmup,
            "render_settings": settings,
            "comparison_counts": comparison_counts,
            "render_case_timing": _timing_dict(measurement.case_render_summary),
            "wall_case_timing": _timing_dict(measurement.case_wall_summary),
            "pooled_render_timing": _timing_dict(measurement.pooled_render_summary),
            "pooled_wall_timing": _timing_dict(measurement.pooled_wall_summary),
            "benchmark_score_available": scene_render_ratio_summary is not None,
            "frames": frame_reports,
        }
        if scene_render_ratio_summary is not None:
            scene_report["render_ratio"] = _ratio_dict(scene_render_ratio_summary)
        if scene_wall_ratio_summary is not None:
            scene_report["wall_ratio"] = _ratio_dict(scene_wall_ratio_summary)
        if scene_score_note is not None:
            scene_report["benchmark_note"] = scene_score_note
        report_scenes[name] = scene_report

    overall_verdict = _combine_verdicts(scene_verdicts) if scene_verdicts else "fail"
    overall_render_case_summary = (
        summarize_times(all_render_case_medians) if all_render_case_medians else None
    )
    overall_wall_case_summary = summarize_times(all_wall_case_medians) if all_wall_case_medians else None
    overall_pooled_render_summary = (
        summarize_times(all_pooled_render_times) if all_pooled_render_times else None
    )
    overall_pooled_wall_summary = summarize_times(all_pooled_wall_times) if all_pooled_wall_times else None
    overall_render_ratio_summary = (
        summarize_ratios(all_render_case_ratios) if all_render_case_ratios else None
    )
    overall_wall_ratio_summary = (
        summarize_ratios(all_wall_case_ratios)
        if all_wall_case_ratios and len(all_wall_case_ratios) == len(all_render_case_ratios)
        else None
    )
    corpus_complete = len(report_scenes) == len(scenes)
    benchmark_score_available = corpus_complete and overall_render_ratio_summary is not None

    report = {
        "timestamp": timestamp,
        "commit": commit,
        "branch": git.get("branch"),
        "dirty": git.get("dirty"),
        "verdict": overall_verdict,
        "corpus_complete": corpus_complete,
        "benchmark_score_available": benchmark_score_available,
        "scenes_evaluated": len(report_scenes),
        "scene_manifest": str(SCENE_MANIFEST),
        "scene_names": [scene_path.stem for scene_path in scenes],
        "frames_per_launch": frames,
        "launches": launches,
        "warmup": warmup,
        "render_settings": settings,
        "cases": len(all_render_case_medians),
        "score_cases": score_cases,
        "samples": len(all_pooled_render_times),
        "render_case_median_ms": round(overall_render_case_summary.median_ms, 1)
        if overall_render_case_summary
        else None,
        "wall_case_median_ms": round(overall_wall_case_summary.median_ms, 1)
        if overall_wall_case_summary
        else None,
        "render_ratio_gmean": overall_render_ratio_summary.geometric_mean
        if overall_render_ratio_summary
        else None,
        "render_speedup_gmean": overall_render_ratio_summary.speedup_gmean
        if overall_render_ratio_summary
        else None,
        "wall_ratio_gmean": overall_wall_ratio_summary.geometric_mean
        if overall_wall_ratio_summary
        else None,
        "wall_speedup_gmean": overall_wall_ratio_summary.speedup_gmean
        if overall_wall_ratio_summary
        else None,
        "errors": errors,
        "notes": notes,
        "overall": {
            "render_case_timing": _timing_dict(overall_render_case_summary)
            if overall_render_case_summary
            else None,
            "wall_case_timing": _timing_dict(overall_wall_case_summary)
            if overall_wall_case_summary
            else None,
            "pooled_render_timing": _timing_dict(overall_pooled_render_summary)
            if overall_pooled_render_summary
            else None,
            "pooled_wall_timing": _timing_dict(overall_pooled_wall_summary)
            if overall_pooled_wall_summary
            else None,
            "render_ratio": _ratio_dict(overall_render_ratio_summary)
            if overall_render_ratio_summary
            else None,
            "wall_ratio": _ratio_dict(overall_wall_ratio_summary)
            if overall_wall_ratio_summary
            else None,
        },
        "build": {
            "requested_configuration": build_contract["requested_configuration"],
            "configure_command": build_contract["configure_command"],
            "build_command": build_contract["build_command"],
        },
        "scenes": report_scenes,
    }

    report_path = run_dir / "report.json"
    report_path.write_text(json.dumps(report, indent=2, default=str) + "\n")

    print(f"\n{'=' * 60}")
    print("  SUMMARY")
    print(f"{'=' * 60}")

    if errors:
        print(f"\n  Errors ({len(errors)}):")
        for error in errors:
            print(f"    - {error}")
    if notes:
        print(f"\n  Notes ({len(notes)}):")
        for note in notes:
            print(f"    - {note}")

    if corpus_complete and overall_render_case_summary:
        print()
        if overall_render_ratio_summary is not None:
            print(
                f"overall:    {overall_verdict.upper()}"
                f" ratio={overall_render_ratio_summary.geometric_mean:.4f}"
                f" speedup={overall_render_ratio_summary.speedup_gmean:.4f}x"
                f" render_case={overall_render_case_summary.median_ms:.1f}ms"
                f" scenes={len(report_scenes)}"
                f" cases={len(all_render_case_medians)}"
                f" samples={len(all_pooled_render_times)}"
            )
        else:
            print(
                f"overall:    {overall_verdict.upper()}"
                f" ratio=n/a"
                f" speedup=n/a"
                f" render_case={overall_render_case_summary.median_ms:.1f}ms"
                f" scenes={len(report_scenes)}"
                f" cases={len(all_render_case_medians)}"
                f" samples={len(all_pooled_render_times)}"
            )
        print(f"verdict:    {overall_verdict}")
        print(f"fidelity_verdict: {overall_verdict}")
        print(f"benchmark_score_available: {'yes' if benchmark_score_available else 'no'}")
        print(f"scenes:     {len(report_scenes)}")
        print(f"cases:      {len(all_render_case_medians)}")
        print(f"frames:     {frames}")
        print(f"launches:   {launches}")
        print(f"resolution: {settings['resolution']}")
        print(f"rays:       {settings['rays']}")
        print(f"samples:    {len(all_pooled_render_times)}")
        print(f"render_case_median_ms: {overall_render_case_summary.median_ms:.1f}")
        if overall_wall_case_summary:
            print(f"wall_case_median_ms: {overall_wall_case_summary.median_ms:.1f}")
        if overall_render_ratio_summary is not None:
            print(f"render_ratio_gmean: {overall_render_ratio_summary.geometric_mean:.6f}")
            print(f"render_speedup_gmean: {overall_render_ratio_summary.speedup_gmean:.6f}")
        else:
            print("render_ratio_gmean: unavailable")
            print("render_speedup_gmean: unavailable")
        if overall_wall_ratio_summary is not None:
            print(f"wall_ratio_gmean: {overall_wall_ratio_summary.geometric_mean:.6f}")
            print(f"wall_speedup_gmean: {overall_wall_ratio_summary.speedup_gmean:.6f}")
        else:
            print("wall_ratio_gmean: unavailable")
            print("wall_speedup_gmean: unavailable")
        print(f"run_dir:    {run_dir}/")
        print(f"report:     {report_path}")
    else:
        print()
        print(f"verdict:    {overall_verdict} (corpus incomplete or no scenes evaluated)")
        overall_verdict = "fail"

    print(f"\n{'=' * 60}")
    sys.exit(0 if overall_verdict == "pass" else 1)


# ── Argument parsing ─────────────────────────────────────────────────────


def main() -> None:
    args = sys.argv[1:]

    skip_build = False
    frames = DEFAULT_FRAMES
    launches = DEFAULT_LAUNCHES
    warmup = DEFAULT_WARMUP
    width = DEFAULT_WIDTH
    height = DEFAULT_HEIGHT
    rays = DEFAULT_RAYS
    command = None

    i = 0
    while i < len(args):
        if args[i] == "--skip-build":
            skip_build = True
        elif args[i] == "--resolution" and i + 1 < len(args):
            i += 1
            width, height = _parse_resolution(args[i])
        elif args[i] == "--width" and i + 1 < len(args):
            i += 1
            width = int(args[i])
        elif args[i] == "--height" and i + 1 < len(args):
            i += 1
            height = int(args[i])
        elif args[i] == "--rays" and i + 1 < len(args):
            i += 1
            rays = int(args[i])
        elif args[i] == "--frames" and i + 1 < len(args):
            i += 1
            frames = int(args[i])
        elif args[i] == "--repeats" and i + 1 < len(args):
            i += 1
            frames = int(args[i])
            print("Warning: `--repeats` is deprecated; use `--frames`.", file=sys.stderr)
        elif args[i] == "--launches" and i + 1 < len(args):
            i += 1
            launches = int(args[i])
        elif args[i] == "--warmup" and i + 1 < len(args):
            i += 1
            warmup = int(args[i])
        elif args[i] == "--animate":
            print("`--animate` was removed; use `--frames N` instead.", file=sys.stderr)
            sys.exit(2)
        elif args[i] in ("capture", "evaluate"):
            command = args[i]
        elif args[i] in ("-h", "--help"):
            print(__doc__)
            sys.exit(0)
        else:
            print(f"Unknown argument: {args[i]}", file=sys.stderr)
            print(__doc__, file=sys.stderr)
            sys.exit(2)
        i += 1

    if width < 1 or height < 1:
        print("Resolution width and height must be > 0.", file=sys.stderr)
        sys.exit(2)
    if rays < 1:
        print("Rays must be > 0.", file=sys.stderr)
        sys.exit(2)
    if frames < 1 or launches < 1 or warmup < 0:
        print("Frames and launches must be > 0, and warmup must be >= 0.", file=sys.stderr)
        sys.exit(2)

    if command == "capture":
        _run_capture(skip_build, frames, launches, warmup, width, height, rays)
    else:
        _run_evaluate(skip_build, frames, launches, warmup, width, height, rays)


if __name__ == "__main__":
    main()
