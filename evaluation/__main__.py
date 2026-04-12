"""Entry point for evaluation: build, render, compare, print verdict.

Usage:
    python -m evaluation                  Build + evaluate against baseline
    python -m evaluation capture          Build + save current as baseline
    python -m evaluation --skip-build     Evaluate without rebuilding
    python -m evaluation --frames 5       Timed deterministic benchmark cases
    python -m evaluation --launches 5     Fresh RenderSession sweeps per scene
    python -m evaluation --warmup 1       Base-scene warm-up renders per session
    python -m evaluation --resolution 1280x720 --rays 2000000

Artifacts are saved to runs/<timestamp>/ with rendered images, a JSON report,
and a human-readable summary. The path is printed at the end.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
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
WARMUP_MODE = "base_scene"


def _warmup_label(warmup: int) -> str:
    render_word = "render" if warmup == 1 else "renders"
    return f"{warmup} base-scene {render_word} per fresh session"


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

    # Configure explicitly so this command stays consistent and enforces a
    # Release-grade build on single-config generators.
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


def _timing_total_ms(summary) -> float:
    return float(sum(summary.times_ms))


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


class EvaluationSetupError(RuntimeError):
    """Raised when the evaluation harness contract is not satisfied."""


def _replace_directory(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        shutil.rmtree(target)
    shutil.move(str(source), str(target))


def _write_case_json_artifacts(
    scene_dir: Path, *, case_scene_jsons: dict[int, str], warmup_scene_json: str
) -> dict:
    warmup_name = "warmup.json"
    (scene_dir / warmup_name).write_text(warmup_scene_json)

    case_paths: dict[str, str] = {}
    for case_index, scene_json in sorted(case_scene_jsons.items()):
        case_name = f"case_{case_index:04d}.json"
        (scene_dir / case_name).write_text(scene_json)
        case_paths[str(case_index)] = case_name

    return {
        "warmup": warmup_name,
        "cases": case_paths,
    }


def _load_and_validate_baseline_corpus(
    scenes: list[Path],
    *,
    frames: int,
    launches: int,
    warmup: int,
    settings: dict,
):
    from .baseline import load_baseline_set

    if not BASELINES_DIR.is_dir():
        raise EvaluationSetupError("no baselines found. Run `python -m evaluation capture` first.")

    baseline_sets: dict[str, dict] = {}
    errors: list[str] = []
    expected_case_indexes = list(range(frames))

    for scene_path in scenes:
        name = scene_path.stem
        baseline_path = BASELINES_DIR / name
        if not baseline_path.is_dir():
            errors.append(f"{name}: no baseline at {baseline_path}")
            continue

        try:
            baseline_set = load_baseline_set(baseline_path)
        except Exception as exc:
            errors.append(f"{name}: failed to load baseline: {exc}")
            continue

        baseline_cases = baseline_set["cases"]
        baseline_meta = baseline_set.get("metadata") or {}
        config_mismatches: list[str] = []
        for key, expected in (
            ("frames", frames),
            ("launches", launches),
            ("warmup", warmup),
            ("warmup_mode", WARMUP_MODE),
        ):
            actual = baseline_meta.get(key)
            if actual != expected:
                config_mismatches.append(f"{key}={actual!r} (expected {expected!r})")
        if baseline_meta.get("render_settings") != settings:
            config_mismatches.append(
                f"render_settings={baseline_meta.get('render_settings')!r} (expected {settings!r})"
            )
        if config_mismatches:
            errors.append(
                f"{name}: baseline contract differs from requested evaluation contract: "
                + ", ".join(config_mismatches)
            )
            continue

        actual_case_indexes = sorted(baseline_cases)
        if actual_case_indexes != expected_case_indexes:
            errors.append(
                f"{name}: baseline cases are {actual_case_indexes}, expected {expected_case_indexes}"
            )
            continue

        baseline_render_summaries: dict[int, object] = {}
        baseline_wall_summaries: dict[int, object] = {}
        case_error = False
        for case_index in expected_case_indexes:
            baseline_case = baseline_cases[case_index]
            if (
                baseline_case["width"] != settings["width"]
                or baseline_case["height"] != settings["height"]
            ):
                errors.append(
                    f"{name}: baseline case {case_index} resolution "
                    f"{baseline_case['width']}x{baseline_case['height']}"
                    f" does not match requested {settings['resolution']}"
                )
                case_error = True
                break

            render_summary = _summary_from_timing_dict(baseline_case.get("render_timing"))
            if render_summary is None:
                errors.append(
                    f"{name}: baseline case {case_index} missing render_timing; "
                    "recapture with `python -m evaluation capture`"
                )
                case_error = True
                break
            wall_summary = _summary_from_timing_dict(baseline_case.get("wall_timing"))
            if wall_summary is None:
                errors.append(
                    f"{name}: baseline case {case_index} missing wall_timing; "
                    "recapture with `python -m evaluation capture`"
                )
                case_error = True
                break

            baseline_render_summaries[case_index] = render_summary
            baseline_wall_summaries[case_index] = wall_summary

        if case_error:
            continue

        baseline_set["baseline_render_summaries"] = baseline_render_summaries
        baseline_set["baseline_wall_summaries"] = baseline_wall_summaries
        baseline_sets[name] = baseline_set

    if errors:
        raise EvaluationSetupError("\n".join(errors))

    return baseline_sets


# ── Capture ──────────────────────────────────────────────────────────────


def _run_capture(
    skip_build: bool, frames: int, launches: int, warmup: int, width: int, height: int, rays: int
) -> None:
    if not skip_build:
        if not _build():
            sys.exit(2)

    from .baseline import save_baseline_set
    from .timing import benchmark_scene

    scenes = _discover_scenes()
    build_contract = _build_contract()
    settings = _render_settings(width, height, rays)

    print("=" * 60)
    print("  CAPTURE BASELINE")
    print(f"  scenes:    {len(scenes)}")
    print(f"  manifest:  {SCENE_MANIFEST}")
    print(f"  frames:    {frames}")
    print(f"  launches:  {launches}")
    print(f"  warmup:    {_warmup_label(warmup)}")
    print(f"  render:    {settings['resolution']} @ {settings['rays']} rays")
    print(f"  build:     {build_contract['requested_configuration']} requested")
    print("=" * 60)

    try:
        with tempfile.TemporaryDirectory(
            prefix="evaluation-capture-", dir=str(PROJECT_DIR)
        ) as tmpdir:
            staging_root = Path(tmpdir)

            for scene_path in scenes:
                name = scene_path.stem
                print(f"\n  [{name}]", flush=True)
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
                except Exception as exc:
                    raise EvaluationSetupError(f"{name}: capture failed: {exc}") from exc

                results_by_case: dict[int, object] = {}
                for sample in measurement.samples:
                    results_by_case.setdefault(sample.frame, sample.result)

                timing_by_case = {
                    case_index: {
                        "render_timing": _timing_dict(case_benchmark.render_summary),
                        "wall_timing": _timing_dict(case_benchmark.wall_summary),
                    }
                    for case_index, case_benchmark in measurement.cases.items()
                }
                scene_render_sample_total_ms = _timing_total_ms(measurement.pooled_render_summary)
                scene_wall_sample_total_ms = _timing_total_ms(measurement.pooled_wall_summary)

                print("    cases:", flush=True)
                for case_index in range(frames):
                    case_benchmark = measurement.cases[case_index]
                    print(
                        f"    case {case_index:02d}:"
                        f" render={case_benchmark.render_summary.median_ms:.1f}ms"
                        f" wall={case_benchmark.wall_summary.median_ms:.1f}ms"
                        f" samples={case_benchmark.repeats}"
                    )

                print(
                    f"    totals:     render={scene_render_sample_total_ms:.1f}ms"
                    f" wall={scene_wall_sample_total_ms:.1f}ms"
                )

                save_baseline_set(
                    staging_root / name,
                    results_by_case,
                    metadata={
                        "scene": name,
                        "frames": frames,
                        "launches": launches,
                        "warmup": warmup,
                        "warmup_mode": WARMUP_MODE,
                        "render_settings": settings,
                        "case_render_timing": _timing_dict(measurement.case_render_summary),
                        "case_wall_timing": _timing_dict(measurement.case_wall_summary),
                        "pooled_render_timing": _timing_dict(measurement.pooled_render_summary),
                        "pooled_wall_timing": _timing_dict(measurement.pooled_wall_summary),
                    },
                    timing_by_case=timing_by_case,
                    scene_json_by_case=measurement.case_scene_jsons,
                    warmup_scene_json=measurement.warmup_scene_json,
                )
                print(f"    staged:     {name}/")

            BASELINES_DIR.mkdir(parents=True, exist_ok=True)
            for scene_path in scenes:
                name = scene_path.stem
                _replace_directory(staging_root / name, BASELINES_DIR / name)
    except EvaluationSetupError as exc:
        print(f"\nCapture failed: {exc}", file=sys.stderr)
        sys.exit(2)

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

    from .compare import compare_to_baseline
    from .timing import benchmark_scene, classify_speedup, summarize_ratios, summarize_times

    scenes = _discover_scenes()
    build_contract = _build_contract()
    settings = _render_settings(width, height, rays)

    try:
        baseline_sets = _load_and_validate_baseline_corpus(
            scenes,
            frames=frames,
            launches=launches,
            warmup=warmup,
            settings=settings,
        )
    except EvaluationSetupError as exc:
        message = str(exc)
        if message.startswith("no baselines found."):
            print(f"Error: {message}", file=sys.stderr)
            sys.exit(3)

        print("Evaluation setup error:", file=sys.stderr)
        for line in message.splitlines():
            print(f"  - {line}", file=sys.stderr)
        sys.exit(2)

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    git = _git_info()
    commit = git.get("commit", "unknown")
    run_name = f"{timestamp}_{commit}"
    final_run_dir = RUNS_DIR / run_name

    print("=" * 60)
    print("  EVALUATE")
    print(f"  commit:   {commit}")
    print(f"  branch:   {git.get('branch', 'unknown')}")
    print(f"  dirty:    {'yes' if git.get('dirty') else 'no'}")
    print(f"  scenes:   {len(scenes)}")
    print(f"  manifest: {SCENE_MANIFEST}")
    print(f"  frames:   {frames}")
    print(f"  launches: {launches}")
    print(f"  warmup:   {_warmup_label(warmup)}")
    print(f"  render:   {settings['resolution']} @ {settings['rays']} rays")
    print(f"  build:    {build_contract['requested_configuration']} requested")
    print(f"  run_dir:  {final_run_dir}/")
    print("=" * 60)

    report_scenes: dict = {}
    all_cases_report: list[dict] = []
    scene_verdicts: list[str] = []
    all_render_case_ratios: list[float] = []
    all_wall_case_ratios: list[float] = []
    all_pooled_render_times: list[float] = []
    all_pooled_wall_times: list[float] = []
    all_baseline_render_sample_total_ms = 0.0
    all_baseline_wall_sample_total_ms = 0.0

    try:
        with tempfile.TemporaryDirectory(prefix="evaluation-run-", dir=str(PROJECT_DIR)) as tmpdir:
            staging_run_dir = Path(tmpdir) / run_name
            staging_run_dir.mkdir(parents=True, exist_ok=True)

            for scene_path in scenes:
                name = scene_path.stem
                baseline_set = baseline_sets[name]
                baseline_cases = baseline_set["cases"]
                baseline_render_summaries = baseline_set["baseline_render_summaries"]
                baseline_wall_summaries = baseline_set["baseline_wall_summaries"]

                print(f"\n  [{name}]", flush=True)
                print(f"    resolution: {settings['resolution']}", flush=True)
                print(f"    rays:       {settings['rays']}", flush=True)

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
                except Exception as exc:
                    raise EvaluationSetupError(f"{name}: render failed: {exc}") from exc

                scene_dir = staging_run_dir / name
                scene_dir.mkdir(parents=True, exist_ok=True)
                scene_json_artifacts = _write_case_json_artifacts(
                    scene_dir,
                    case_scene_jsons=measurement.case_scene_jsons,
                    warmup_scene_json=measurement.warmup_scene_json,
                )

                case_samples: dict[int, list[dict]] = {
                    case_index: [] for case_index in range(frames)
                }
                case_verdicts: dict[int, list[str]] = {
                    case_index: [] for case_index in range(frames)
                }
                sample_verdicts: list[str] = []
                sample_non_pass: list[str] = []

                for sample in measurement.samples:
                    img_name = f"launch_{sample.launch_index:02d}_case_{sample.frame:04d}.png"
                    img_path = scene_dir / img_name
                    _save_image(
                        sample.result.pixels, sample.result.width, sample.result.height, img_path
                    )

                    fidelity = compare_to_baseline(
                        sample.result, baseline_cases[sample.frame]
                    )
                    verdict_value = fidelity.verdict.value
                    sample_verdicts.append(verdict_value)
                    case_verdicts[sample.frame].append(verdict_value)

                    sample_entry: dict = {
                        "launch_index": sample.launch_index,
                        "case_index": sample.frame,
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
                            "mean_luma_delta": fidelity.metrics.mean_luma_delta,
                            "histogram_overlap": fidelity.metrics.histogram_overlap,
                            "median_luma_delta": fidelity.metrics.median_luma_delta,
                            "p95_luma_delta": fidelity.metrics.p95_luma_delta,
                            "near_black_fraction_delta": (
                                fidelity.metrics.near_black_fraction_delta
                            ),
                            "clipped_channel_fraction_delta": (
                                fidelity.metrics.clipped_channel_fraction_delta
                            ),
                            "warnings": fidelity.metrics.warnings,
                        }
                    case_samples[sample.frame].append(sample_entry)

                    if verdict_value != "pass":
                        sample_non_pass.append(
                            f"launch={sample.launch_index} case={sample.frame} verdict={verdict_value}"
                        )

                scene_verdict = _combine_verdicts(sample_verdicts)
                scene_verdicts.append(scene_verdict)

                all_pooled_render_times.extend(measurement.pooled_render_summary.times_ms)
                all_pooled_wall_times.extend(measurement.pooled_wall_summary.times_ms)
                scene_render_sample_total_ms = _timing_total_ms(measurement.pooled_render_summary)
                scene_wall_sample_total_ms = _timing_total_ms(measurement.pooled_wall_summary)
                scene_baseline_render_sample_total_ms = sum(
                    _timing_total_ms(summary) for summary in baseline_render_summaries.values()
                )
                scene_baseline_wall_sample_total_ms = sum(
                    _timing_total_ms(summary) for summary in baseline_wall_summaries.values()
                )
                all_baseline_render_sample_total_ms += scene_baseline_render_sample_total_ms
                all_baseline_wall_sample_total_ms += scene_baseline_wall_sample_total_ms

                case_reports: dict[str, dict] = {}
                scene_render_case_ratios: list[float] = []
                scene_wall_case_ratios: list[float] = []
                print("    cases:", flush=True)
                for case_index in range(frames):
                    case_benchmark = measurement.cases[case_index]
                    baseline_render_summary = baseline_render_summaries[case_index]
                    baseline_wall_summary = baseline_wall_summaries[case_index]
                    case_verdict = _combine_verdicts(case_verdicts[case_index])
                    render_ratio = (
                        case_benchmark.render_summary.median_ms / baseline_render_summary.median_ms
                    )
                    wall_ratio = (
                        case_benchmark.wall_summary.median_ms / baseline_wall_summary.median_ms
                    )
                    scene_render_case_ratios.append(render_ratio)
                    scene_wall_case_ratios.append(wall_ratio)
                    all_render_case_ratios.append(render_ratio)
                    all_wall_case_ratios.append(wall_ratio)

                    render_speedup = classify_speedup(
                        baseline_render_summary, case_benchmark.render_summary
                    )
                    wall_speedup = classify_speedup(
                        baseline_wall_summary, case_benchmark.wall_summary
                    )
                    render_sample_total_ms = _timing_total_ms(case_benchmark.render_summary)
                    baseline_render_sample_total_ms = _timing_total_ms(baseline_render_summary)
                    wall_sample_total_ms = _timing_total_ms(case_benchmark.wall_summary)
                    baseline_wall_sample_total_ms = _timing_total_ms(baseline_wall_summary)

                    print(
                        f"    case {case_index:02d}: {case_verdict.upper()}"
                        f" render={case_benchmark.render_summary.median_ms:.1f}/{baseline_render_summary.median_ms:.1f}ms"
                        f" ratio={render_ratio:.4f}"
                        f" wall={case_benchmark.wall_summary.median_ms:.1f}/{baseline_wall_summary.median_ms:.1f}ms"
                    )

                    case_reports[str(case_index)] = {
                        "case_index": case_index,
                        "verdict": case_verdict,
                        "scene_json": f"{name}/{scene_json_artifacts['cases'][str(case_index)]}",
                        "render_median_ms": case_benchmark.render_summary.median_ms,
                        "baseline_render_median_ms": baseline_render_summary.median_ms,
                        "render_sample_total_ms": render_sample_total_ms,
                        "baseline_render_sample_total_ms": baseline_render_sample_total_ms,
                        "render_timing": _timing_dict(case_benchmark.render_summary),
                        "baseline_render_timing": _timing_dict(baseline_render_summary),
                        "wall_median_ms": case_benchmark.wall_summary.median_ms,
                        "baseline_wall_median_ms": baseline_wall_summary.median_ms,
                        "wall_sample_total_ms": wall_sample_total_ms,
                        "baseline_wall_sample_total_ms": baseline_wall_sample_total_ms,
                        "wall_timing": _timing_dict(case_benchmark.wall_summary),
                        "baseline_wall_timing": _timing_dict(baseline_wall_summary),
                        "render_ratio": render_ratio,
                        "render_speedup": render_speedup.speedup,
                        "render_comparison": _speedup_dict(render_speedup),
                        "wall_ratio": wall_ratio,
                        "wall_speedup": wall_speedup.speedup,
                        "wall_comparison": _speedup_dict(wall_speedup),
                        "samples": case_samples[case_index],
                    }
                    all_cases_report.append(
                        {
                            "scene": name,
                            "case_index": case_index,
                            "verdict": case_verdict,
                            "render_median_ms": case_benchmark.render_summary.median_ms,
                            "baseline_render_median_ms": baseline_render_summary.median_ms,
                            "render_sample_total_ms": render_sample_total_ms,
                            "baseline_render_sample_total_ms": baseline_render_sample_total_ms,
                            "render_ratio": render_ratio,
                            "render_speedup": render_speedup.speedup,
                            "wall_median_ms": case_benchmark.wall_summary.median_ms,
                            "baseline_wall_median_ms": baseline_wall_summary.median_ms,
                            "wall_sample_total_ms": wall_sample_total_ms,
                            "baseline_wall_sample_total_ms": baseline_wall_sample_total_ms,
                            "wall_ratio": wall_ratio,
                            "wall_speedup": wall_speedup.speedup,
                        }
                    )

                comparison_counts = {
                    "pass": sum(1 for verdict in sample_verdicts if verdict == "pass"),
                    "warn": sum(1 for verdict in sample_verdicts if verdict == "warn"),
                    "fail": sum(1 for verdict in sample_verdicts if verdict == "fail"),
                }
                scene_render_ratio_summary = summarize_ratios(scene_render_case_ratios)
                scene_wall_ratio_summary = summarize_ratios(scene_wall_case_ratios)

                print(
                    f"    score:      ratio_gmean={scene_render_ratio_summary.geometric_mean:.4f}"
                    f" speedup_gmean={scene_render_ratio_summary.speedup_gmean:.4f}x"
                )
                print(
                    f"    wall score: ratio_gmean={scene_wall_ratio_summary.geometric_mean:.4f}"
                    f" speedup_gmean={scene_wall_ratio_summary.speedup_gmean:.4f}x"
                )
                print(
                    f"    totals:     render={scene_render_sample_total_ms:.1f}ms"
                    f" baseline_render={scene_baseline_render_sample_total_ms:.1f}ms"
                    f" wall={scene_wall_sample_total_ms:.1f}ms"
                    f" baseline_wall={scene_baseline_wall_sample_total_ms:.1f}ms"
                )
                print(
                    f"    verdict:    {scene_verdict.upper()}"
                    f" across {measurement.sample_count} sample(s)"
                )
                for entry in sample_non_pass[:8]:
                    print(f"    sample:     {entry}")

                report_scenes[name] = {
                    "verdict": scene_verdict,
                    "case_count": measurement.case_count,
                    "sample_count": measurement.sample_count,
                    "frames_per_scene": frames,
                    "launches": launches,
                    "warmup": warmup,
                    "warmup_mode": WARMUP_MODE,
                    "render_settings": settings,
                    "warmup_scene_json": f"{name}/{scene_json_artifacts['warmup']}",
                    "comparison_counts": comparison_counts,
                    "pooled_render_timing": _timing_dict(measurement.pooled_render_summary),
                    "pooled_wall_timing": _timing_dict(measurement.pooled_wall_summary),
                    "totals": {
                        "render_sample_total_ms": scene_render_sample_total_ms,
                        "baseline_render_sample_total_ms": scene_baseline_render_sample_total_ms,
                        "wall_sample_total_ms": scene_wall_sample_total_ms,
                        "baseline_wall_sample_total_ms": scene_baseline_wall_sample_total_ms,
                    },
                    "render_ratio": _ratio_dict(scene_render_ratio_summary),
                    "wall_ratio": _ratio_dict(scene_wall_ratio_summary),
                    "cases": case_reports,
                }

            overall_verdict = _combine_verdicts(scene_verdicts) if scene_verdicts else "fail"
            overall_pooled_render_summary = summarize_times(all_pooled_render_times)
            overall_pooled_wall_summary = summarize_times(all_pooled_wall_times)
            overall_render_ratio_summary = summarize_ratios(all_render_case_ratios)
            overall_wall_ratio_summary = summarize_ratios(all_wall_case_ratios)
            overall_render_sample_total_ms = _timing_total_ms(overall_pooled_render_summary)
            overall_wall_sample_total_ms = _timing_total_ms(overall_pooled_wall_summary)

            report = {
                "schema_version": 1,
                "timestamp": timestamp,
                "commit": commit,
                "branch": git.get("branch"),
                "dirty": git.get("dirty"),
                "verdict": overall_verdict,
                "scene_manifest": str(SCENE_MANIFEST),
                "scene_names": [scene_path.stem for scene_path in scenes],
                "scene_count": len(report_scenes),
                "frames_per_scene": frames,
                "launches": launches,
                "warmup": warmup,
                "warmup_mode": WARMUP_MODE,
                "render_settings": settings,
                "case_count": len(all_render_case_ratios),
                "sample_count": len(all_pooled_render_times),
                "totals": {
                    "render_sample_total_ms": overall_render_sample_total_ms,
                    "baseline_render_sample_total_ms": all_baseline_render_sample_total_ms,
                    "wall_sample_total_ms": overall_wall_sample_total_ms,
                    "baseline_wall_sample_total_ms": all_baseline_wall_sample_total_ms,
                },
                "render_ratio_gmean": overall_render_ratio_summary.geometric_mean,
                "render_speedup_gmean": overall_render_ratio_summary.speedup_gmean,
                "wall_ratio_gmean": overall_wall_ratio_summary.geometric_mean,
                "wall_speedup_gmean": overall_wall_ratio_summary.speedup_gmean,
                "overall": {
                    "pooled_render_timing": _timing_dict(overall_pooled_render_summary),
                    "pooled_wall_timing": _timing_dict(overall_pooled_wall_summary),
                    "render_ratio": _ratio_dict(overall_render_ratio_summary),
                    "wall_ratio": _ratio_dict(overall_wall_ratio_summary),
                },
                "build": {
                    "requested_configuration": build_contract["requested_configuration"],
                    "configure_command": build_contract["configure_command"],
                    "build_command": build_contract["build_command"],
                },
                "all_cases": all_cases_report,
                "scenes": report_scenes,
            }

            report_path = staging_run_dir / "report.json"
            report_path.write_text(json.dumps(report, indent=2, default=str) + "\n")

            RUNS_DIR.mkdir(parents=True, exist_ok=True)
            _replace_directory(staging_run_dir, final_run_dir)
    except EvaluationSetupError as exc:
        print(f"Evaluation failed: {exc}", file=sys.stderr)
        sys.exit(2)

    final_report_path = final_run_dir / "report.json"

    print(f"\n{'=' * 60}")
    print("  SUMMARY")
    print(f"{'=' * 60}")
    print()
    print(
        f"overall:    {overall_verdict.upper()}"
        f" ratio={overall_render_ratio_summary.geometric_mean:.4f}"
        f" speedup={overall_render_ratio_summary.speedup_gmean:.4f}x"
        f" scenes={len(report_scenes)}"
        f" cases={len(all_render_case_ratios)}"
        f" samples={len(all_pooled_render_times)}"
    )
    print(f"verdict:    {overall_verdict}")
    print(f"scenes:     {len(report_scenes)}")
    print(f"cases:      {len(all_render_case_ratios)}")
    print(f"frames:     {frames}")
    print(f"launches:   {launches}")
    print(f"warmup:     {_warmup_label(warmup)}")
    print(f"resolution: {settings['resolution']}")
    print(f"rays:       {settings['rays']}")
    print(f"samples:    {len(all_pooled_render_times)}")
    print(f"render_sample_total_ms: {overall_render_sample_total_ms:.1f}")
    print(f"baseline_render_sample_total_ms: {all_baseline_render_sample_total_ms:.1f}")
    print(f"wall_sample_total_ms: {overall_wall_sample_total_ms:.1f}")
    print(f"baseline_wall_sample_total_ms: {all_baseline_wall_sample_total_ms:.1f}")
    print(f"render_ratio_gmean: {overall_render_ratio_summary.geometric_mean:.6f}")
    print(f"render_speedup_gmean: {overall_render_ratio_summary.speedup_gmean:.6f}")
    print(f"wall_ratio_gmean: {overall_wall_ratio_summary.geometric_mean:.6f}")
    print(f"wall_speedup_gmean: {overall_wall_ratio_summary.speedup_gmean:.6f}")
    print(f"run_dir:    {final_run_dir}/")
    print(f"report:     {final_report_path}")
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
        elif args[i] == "--launches" and i + 1 < len(args):
            i += 1
            launches = int(args[i])
        elif args[i] == "--warmup" and i + 1 < len(args):
            i += 1
            warmup = int(args[i])
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
