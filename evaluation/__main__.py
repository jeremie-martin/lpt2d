"""Entry point for evaluation: build, render, compare, print verdict.

Usage:
    python -m evaluation                  Build + evaluate against baseline
    python -m evaluation capture          Build + save current as baseline
    python -m evaluation --skip-build     Evaluate without rebuilding
    python -m evaluation --frames 5       Timed deterministic frames per launch
    python -m evaluation --launches 3     Fresh render sessions per scene
    python -m evaluation --warmup 1       Warm-up frames discarded per launch

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
BASELINES_DIR = PROJECT_DIR / "baselines"
RUNS_DIR = PROJECT_DIR / "runs"

DEFAULT_FRAMES = 5
DEFAULT_LAUNCHES = 3
DEFAULT_WARMUP = 1


# ── Build ────────────────────────────────────────────────────────────────


def _nproc() -> int:
    import os

    return os.cpu_count() or 1


def _build() -> bool:
    """Build C++ and reinstall Python package. Returns True on success."""
    t0 = time.monotonic()

    print("=" * 60)
    print("  BUILD")
    print("=" * 60)

    # cmake build — stream output so compiler errors are visible
    print("\n[cmake] Building C++...\n", flush=True)
    r = subprocess.run(
        ["cmake", "--build", str(BUILD_DIR), f"-j{_nproc()}"],
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
    if not SCENES_DIR.is_dir():
        print(f"Error: no scenes directory at {SCENES_DIR}", file=sys.stderr)
        sys.exit(2)
    scenes = sorted(SCENES_DIR.glob("*.json"))
    if not scenes:
        print(f"Error: no .json files in {SCENES_DIR}", file=sys.stderr)
        sys.exit(2)
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
    except FileNotFoundError:
        pass
    return info


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


def _summary_from_metadata(metadata: dict | None, key: str):
    from .timing import summarize_times

    if not metadata:
        return None

    timing = metadata.get(f"{key}_timing")
    if timing and timing.get("times_ms"):
        return summarize_times([float(t) for t in timing["times_ms"]])

    if key == "render":
        legacy_times = metadata.get("times_ms")
        if legacy_times:
            return summarize_times([float(t) for t in legacy_times])

    return None


def _speedup_dict(result) -> dict:
    return {
        "speedup": result.speedup,
        "confidence": result.confidence,
        "baseline_median_ms": result.baseline.median_ms,
    }


# ── Capture ──────────────────────────────────────────────────────────────


def _run_capture(skip_build: bool, frames: int, launches: int, warmup: int) -> None:
    if not skip_build:
        if not _build():
            sys.exit(2)

    import _lpt2d

    from .baseline import save_baseline_set
    from .timing import benchmark_scene

    scenes = _discover_scenes()
    BASELINES_DIR.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print("  CAPTURE BASELINE")
    print(f"  scenes:    {len(scenes)}")
    print(f"  frames:    {frames}")
    print(f"  launches:  {launches}")
    print(f"  warmup:    {warmup} per launch")
    print("=" * 60)

    for scene_path in scenes:
        name = scene_path.stem
        print(f"\n  [{name}]", flush=True)

        try:
            shot = _lpt2d.load_shot(str(scene_path))
            res = f"{shot.canvas.width}x{shot.canvas.height}"
        except Exception as e:
            print(f"    LOAD ERROR: {e}", file=sys.stderr)
            continue

        print(f"    resolution: {res}", flush=True)
        print(f"    measuring:  {launches} launch(es) x {frames} frame(s)...", flush=True)

        try:
            measurement = benchmark_scene(str(scene_path), frames=frames, launches=launches, warmup=warmup)
        except Exception as e:
            print(f"    RENDER ERROR: {e}", file=sys.stderr)
            continue

        print(
            f"    render:     {measurement.render_summary.median_ms:.1f} ms"
            f" (mean={measurement.render_summary.mean_ms:.1f},"
            f" std={measurement.render_summary.std_ms:.1f},"
            f" min={measurement.render_summary.min_ms:.1f},"
            f" max={measurement.render_summary.max_ms:.1f})"
        )
        print(
            f"    wall:       {measurement.wall_summary.median_ms:.1f} ms"
            f" (mean={measurement.wall_summary.mean_ms:.1f},"
            f" std={measurement.wall_summary.std_ms:.1f})"
        )

        results_by_frame: dict[int, object] = {}
        for sample in measurement.samples:
            results_by_frame.setdefault(sample.frame_index, sample.result)

        save_baseline_set(
            BASELINES_DIR / name,
            results_by_frame,
            metadata={
                "scene": name,
                "frames": frames,
                "launches": launches,
                "warmup": warmup,
                "render_timing": _timing_dict(measurement.render_summary),
                "wall_timing": _timing_dict(measurement.wall_summary),
            },
        )
        print(f"    saved:      {BASELINES_DIR / name}/")

    print(f"\n{'=' * 60}")
    print(f"  Baselines saved to {BASELINES_DIR}/")
    print(f"{'=' * 60}")


# ── Evaluate ─────────────────────────────────────────────────────────────


def _run_evaluate(skip_build: bool, frames: int, launches: int, warmup: int) -> None:
    if not skip_build:
        if not _build():
            sys.exit(2)

    import _lpt2d

    from .baseline import load_baseline_set
    from .compare import compare_to_baseline
    from .timing import benchmark_scene, classify_speedup, summarize_times

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

    print("=" * 60)
    print("  EVALUATE")
    print(f"  commit:   {commit}")
    print(f"  branch:   {git.get('branch', 'unknown')}")
    print(f"  scenes:   {len(scenes)}")
    print(f"  frames:   {frames}")
    print(f"  launches: {launches}")
    print(f"  warmup:   {warmup} per launch")
    print(f"  run_dir:  {run_dir}/")
    print("=" * 60)

    report_scenes: dict = {}
    errors: list[str] = []
    scene_verdicts: list[str] = []
    all_render_times: list[float] = []
    all_wall_times: list[float] = []
    all_baseline_render_times: list[float] = []
    all_baseline_wall_times: list[float] = []
    can_compute_render_speedup = True
    can_compute_wall_speedup = True

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
            shot = _lpt2d.load_shot(str(scene_path))
            res = f"{shot.canvas.width}x{shot.canvas.height}"
            print(f"    resolution: {res}", flush=True)
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

        baseline_timing_compatible = True
        config_mismatches: list[str] = []
        for key, expected in (("frames", frames), ("launches", launches), ("warmup", warmup)):
            actual = baseline_meta.get(key)
            if actual is not None and actual != expected:
                baseline_timing_compatible = False
                config_mismatches.append(f"{key}={actual} (expected {expected})")

        missing_frames = [frame_index for frame_index in range(frames) if frame_index not in baseline_frames]
        if missing_frames:
            msg = f"{name}: baseline missing frame(s) {missing_frames}"
            print(f"    BASELINE ERROR: missing frame(s) {missing_frames}", file=sys.stderr)
            errors.append(msg)
            scene_verdicts.append("fail")
            continue

        try:
            measurement = benchmark_scene(str(scene_path), frames=frames, launches=launches, warmup=warmup)
        except Exception as e:
            msg = f"{name}: render failed: {e}"
            print(f"    RENDER ERROR: {e}", file=sys.stderr)
            errors.append(msg)
            scene_verdicts.append("fail")
            continue

        all_render_times.extend(measurement.render_summary.times_ms)
        all_wall_times.extend(measurement.wall_summary.times_ms)

        print(
            f"    render:     {measurement.render_summary.median_ms:.1f} ms"
            f" (mean={measurement.render_summary.mean_ms:.1f},"
            f" std={measurement.render_summary.std_ms:.1f},"
            f" min={measurement.render_summary.min_ms:.1f},"
            f" max={measurement.render_summary.max_ms:.1f})"
        )
        print(
            f"    wall:       {measurement.wall_summary.median_ms:.1f} ms"
            f" (mean={measurement.wall_summary.mean_ms:.1f},"
            f" std={measurement.wall_summary.std_ms:.1f})"
        )

        render_speedup = None
        wall_speedup = None
        baseline_render_summary = _summary_from_metadata(baseline_meta, "render")
        baseline_wall_summary = _summary_from_metadata(baseline_meta, "wall")
        if not baseline_timing_compatible:
            print(
                f"    speedup:    skipped (baseline timing config differs: {', '.join(config_mismatches)})"
            )
            can_compute_render_speedup = False
            can_compute_wall_speedup = False
        elif baseline_render_summary is not None:
            all_baseline_render_times.extend(baseline_render_summary.times_ms)
            render_speedup = classify_speedup(baseline_render_summary, measurement.render_summary)
        else:
            can_compute_render_speedup = False
        if baseline_timing_compatible and baseline_wall_summary is not None:
            all_baseline_wall_times.extend(baseline_wall_summary.times_ms)
            wall_speedup = classify_speedup(baseline_wall_summary, measurement.wall_summary)
        else:
            can_compute_wall_speedup = False

        scene_dir = run_dir / name
        scene_dir.mkdir(parents=True, exist_ok=True)
        frame_samples: dict[int, list[dict]] = {frame_index: [] for frame_index in range(frames)}
        frame_verdicts: dict[int, list[str]] = {frame_index: [] for frame_index in range(frames)}
        frame_render_times: dict[int, list[float]] = {frame_index: [] for frame_index in range(frames)}
        frame_wall_times: dict[int, list[float]] = {frame_index: [] for frame_index in range(frames)}
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
            frame_render_times[sample.frame_index].append(sample.render_time_ms)
            frame_wall_times[sample.frame_index].append(sample.wall_time_ms)

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

        if render_speedup:
            print(f"    speedup:    {render_speedup.speedup:.3f}x ({render_speedup.confidence})")
        if wall_speedup:
            print(f"    wall gain:  {wall_speedup.speedup:.3f}x ({wall_speedup.confidence})")
        print(
            f"    verdict:    {scene_verdict.upper()}"
            f" across {measurement.sample_count} sample(s)"
        )
        for entry in sample_non_pass[:8]:
            print(f"    sample:     {entry}")

        frame_reports: dict[str, dict] = {}
        for frame_index in range(frames):
            frame_reports[str(frame_index)] = {
                "verdict": _combine_verdicts(frame_verdicts[frame_index]),
                "render_timing": _timing_dict(summarize_times(frame_render_times[frame_index])),
                "wall_timing": _timing_dict(summarize_times(frame_wall_times[frame_index])),
                "samples": frame_samples[frame_index],
            }

        comparison_counts = {
            "pass": sum(1 for verdict in sample_verdicts if verdict == "pass"),
            "warn": sum(1 for verdict in sample_verdicts if verdict == "warn"),
            "fail": sum(1 for verdict in sample_verdicts if verdict == "fail"),
        }

        scene_report: dict = {
            "verdict": scene_verdict,
            "samples": measurement.sample_count,
            "frames_per_launch": frames,
            "launches": launches,
            "warmup": warmup,
            "comparison_counts": comparison_counts,
            "render_timing": _timing_dict(measurement.render_summary),
            "wall_timing": _timing_dict(measurement.wall_summary),
            "frames": frame_reports,
        }
        if render_speedup:
            scene_report["speedup"] = _speedup_dict(render_speedup)
        if wall_speedup:
            scene_report["wall_speedup"] = _speedup_dict(wall_speedup)
        report_scenes[name] = scene_report

    overall_verdict = _combine_verdicts(scene_verdicts) if scene_verdicts else "fail"
    overall_render_summary = summarize_times(all_render_times) if all_render_times else None
    overall_wall_summary = summarize_times(all_wall_times) if all_wall_times else None
    overall_render_speedup = None
    overall_wall_speedup = None
    if can_compute_render_speedup and all_baseline_render_times and overall_render_summary is not None:
        overall_render_speedup = classify_speedup(
            summarize_times(all_baseline_render_times),
            overall_render_summary,
        )
    if can_compute_wall_speedup and all_baseline_wall_times and overall_wall_summary is not None:
        overall_wall_speedup = classify_speedup(
            summarize_times(all_baseline_wall_times),
            overall_wall_summary,
        )

    report = {
        "timestamp": timestamp,
        "commit": commit,
        "branch": git.get("branch"),
        "verdict": overall_verdict,
        "scenes_evaluated": len(report_scenes),
        "frames_per_launch": frames,
        "launches": launches,
        "warmup": warmup,
        "samples": len(all_render_times),
        "median_ms": round(overall_render_summary.median_ms, 1) if overall_render_summary else None,
        "wall_median_ms": round(overall_wall_summary.median_ms, 1) if overall_wall_summary else None,
        "total_median_ms": round(overall_render_summary.median_ms, 1)
        if overall_render_summary
        else None,
        "total_speedup": overall_render_speedup.speedup if overall_render_speedup else None,
        "errors": errors,
        "overall": {
            "render_timing": _timing_dict(overall_render_summary) if overall_render_summary else None,
            "wall_timing": _timing_dict(overall_wall_summary) if overall_wall_summary else None,
            "speedup": _speedup_dict(overall_render_speedup) if overall_render_speedup else None,
            "wall_speedup": _speedup_dict(overall_wall_speedup) if overall_wall_speedup else None,
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

    if report_scenes and overall_render_summary and overall_wall_summary:
        print()
        print(
            f"overall:    {overall_verdict.upper()}"
            f" render={overall_render_summary.median_ms:.1f}ms"
            f" wall={overall_wall_summary.median_ms:.1f}ms"
            f" scenes={len(report_scenes)}"
            f" samples={len(all_render_times)}"
        )
        print(f"verdict:    {overall_verdict}")
        print(f"scenes:     {len(report_scenes)}")
        print(f"frames:     {frames}")
        print(f"launches:   {launches}")
        print(f"samples:    {len(all_render_times)}")
        print(f"median_ms:  {overall_render_summary.median_ms:.1f}")
        print(f"wall_ms:    {overall_wall_summary.median_ms:.1f}")
        if overall_render_speedup:
            print(
                f"speedup:    {overall_render_speedup.speedup:.3f}x"
                f" ({overall_render_speedup.confidence})"
            )
        print(f"run_dir:    {run_dir}/")
        print(f"report:     {report_path}")
    else:
        print()
        print("verdict:    fail (no scenes evaluated)")
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
    command = None

    i = 0
    while i < len(args):
        if args[i] == "--skip-build":
            skip_build = True
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

    if command == "capture":
        _run_capture(skip_build, frames, launches, warmup)
    else:
        _run_evaluate(skip_build, frames, launches, warmup)


if __name__ == "__main__":
    main()
