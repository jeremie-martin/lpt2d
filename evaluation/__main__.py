"""Entry point for evaluation: build, render, compare, print verdict.

Usage:
    python -m evaluation                  Build + evaluate against baseline
    python -m evaluation capture          Build + save current as baseline
    python -m evaluation --skip-build     Evaluate without rebuilding
    python -m evaluation --repeats 10     Custom repeat count
    python -m evaluation --animate         Animated mode (varying geometry per frame)

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

DEFAULT_REPEATS = 10
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


# ── Capture ──────────────────────────────────────────────────────────────


def _run_capture(skip_build: bool, repeats: int, warmup: int, animate: bool = False) -> None:
    if not skip_build:
        if not _build():
            sys.exit(2)

    import _lpt2d

    from .baseline import save_baseline
    from .timing import benchmark, benchmark_animated

    scenes = _discover_scenes()
    BASELINES_DIR.mkdir(parents=True, exist_ok=True)

    mode_str = "animated" if animate else "static"
    print("=" * 60)
    print("  CAPTURE BASELINE")
    print(f"  scenes:  {len(scenes)}")
    print(f"  mode:    {mode_str}")
    print(f"  repeats: {repeats} (warmup: {warmup})")
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
        print(f"    mode:       {mode_str}", flush=True)

        try:
            if animate:
                print(f"    frames:     {repeats} animated frames...", flush=True)
                summary, result = benchmark_animated(str(scene_path), frames=repeats, warmup=warmup)
            else:
                session = _lpt2d.RenderSession(shot.canvas.width, shot.canvas.height)
                print(f"    warmup:     {warmup} render(s)...", flush=True)
                summary, result = benchmark(session, shot, repeats=repeats, warmup=warmup)
        except Exception as e:
            print(f"    RENDER ERROR: {e}", file=sys.stderr)
            continue

        print(
            f"    timing:     {summary.median_ms:.1f} ms"
            f" (mean={summary.mean_ms:.1f}, std={summary.std_ms:.1f},"
            f" min={summary.min_ms:.1f}, max={summary.max_ms:.1f})"
        )
        print(f"    times:      [{', '.join(f'{t:.1f}' for t in summary.times_ms)}]")

        save_baseline(
            BASELINES_DIR / name,
            result,
            metadata={
                "scene": name,
                "median_ms": summary.median_ms,
                "mean_ms": summary.mean_ms,
                "std_ms": summary.std_ms,
                "repeats": summary.repeats,
                "times_ms": summary.times_ms,
            },
        )
        print(f"    saved:      {BASELINES_DIR / name}/")

    print(f"\n{'=' * 60}")
    print(f"  Baselines saved to {BASELINES_DIR}/")
    print(f"{'=' * 60}")


# ── Evaluate ─────────────────────────────────────────────────────────────


def _run_evaluate(skip_build: bool, repeats: int, warmup: int, animate: bool = False) -> None:
    if not skip_build:
        if not _build():
            sys.exit(2)

    import _lpt2d

    from .baseline import load_baseline
    from .compare import compare_to_baseline
    from .timing import TimingSummary, benchmark, benchmark_animated, classify_speedup

    scenes = _discover_scenes()

    if not BASELINES_DIR.is_dir():
        print(
            "Error: no baselines found. Run `python -m evaluation capture` first.",
            file=sys.stderr,
        )
        sys.exit(3)

    # Create run directory
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    git = _git_info()
    commit = git.get("commit", "unknown")
    run_dir = RUNS_DIR / f"{timestamp}_{commit}"
    run_dir.mkdir(parents=True, exist_ok=True)

    mode_str = "animated" if animate else "static"
    print("=" * 60)
    print("  EVALUATE")
    print(f"  commit:   {commit}")
    print(f"  branch:   {git.get('branch', 'unknown')}")
    print(f"  scenes:   {len(scenes)}")
    print(f"  mode:     {mode_str}")
    print(f"  repeats:  {repeats} (warmup: {warmup})")
    print(f"  run_dir:  {run_dir}/")
    print("=" * 60)

    all_pass = True
    report_scenes: dict = {}
    errors: list[str] = []

    for scene_path in scenes:
        name = scene_path.stem
        baseline_path = BASELINES_DIR / name

        if not baseline_path.is_dir():
            msg = f"{name}: no baseline at {baseline_path}"
            print(f"\n  [{name}] SKIP — no baseline", file=sys.stderr)
            errors.append(msg)
            continue

        print(f"\n  [{name}]", flush=True)

        # Load scene
        try:
            shot = _lpt2d.load_shot(str(scene_path))
            res = f"{shot.canvas.width}x{shot.canvas.height}"
            print(f"    resolution: {res}", flush=True)
        except Exception as e:
            msg = f"{name}: failed to load scene: {e}"
            print(f"    LOAD ERROR: {e}", file=sys.stderr)
            errors.append(msg)
            all_pass = False
            continue

        # Load baseline
        try:
            baseline = load_baseline(baseline_path)
        except Exception as e:
            msg = f"{name}: failed to load baseline: {e}"
            print(f"    BASELINE ERROR: {e}", file=sys.stderr)
            errors.append(msg)
            all_pass = False
            continue

        # Render
        try:
            if animate:
                print(f"    frames:     {repeats} animated frames...", flush=True)
                summary, result = benchmark_animated(str(scene_path), frames=repeats, warmup=warmup)
            else:
                session = _lpt2d.RenderSession(shot.canvas.width, shot.canvas.height)
                print(f"    warmup:     {warmup} render(s)...", flush=True)
                print(f"    rendering:  {repeats} timed render(s)...", flush=True)
                summary, result = benchmark(session, shot, repeats=repeats, warmup=warmup)
        except Exception as e:
            msg = f"{name}: render failed: {e}"
            print(f"    RENDER ERROR: {e}", file=sys.stderr)
            errors.append(msg)
            all_pass = False
            continue

        print(
            f"    timing:     {summary.median_ms:.1f} ms"
            f" (mean={summary.mean_ms:.1f}, std={summary.std_ms:.1f},"
            f" min={summary.min_ms:.1f}, max={summary.max_ms:.1f})"
        )
        print(f"    times:      [{', '.join(f'{t:.1f}' for t in summary.times_ms)}]")

        # Save rendered image
        img_path = run_dir / f"{name}.png"
        _save_image(result.pixels, result.width, result.height, img_path)
        print(f"    image:      {img_path}")

        # Compare
        try:
            fidelity = compare_to_baseline(result, baseline)
        except Exception as e:
            msg = f"{name}: comparison failed: {e}"
            print(f"    COMPARE ERROR: {e}", file=sys.stderr)
            errors.append(msg)
            all_pass = False
            continue

        # Speedup
        baseline_meta = baseline.get("metadata", {}) or {}
        baseline_times = baseline_meta.get("times_ms")
        speedup_result = None
        if baseline_times and len(baseline_times) >= 2:
            from statistics import mean, median, stdev

            baseline_summary = TimingSummary(
                times_ms=baseline_times,
                median_ms=median(baseline_times),
                mean_ms=mean(baseline_times),
                std_ms=stdev(baseline_times),
                min_ms=min(baseline_times),
                max_ms=max(baseline_times),
                repeats=len(baseline_times),
            )
            speedup_result = classify_speedup(baseline_summary, summary)

        # Print verdict
        verdict_tag = fidelity.verdict.value.upper()
        if fidelity.byte_identical:
            fid_str = "identical"
        else:
            fid_str = (
                f"psnr={fidelity.psnr:.1f}dB ssim={fidelity.ssim:.6f} max_diff={fidelity.max_diff}"
            )
        print(f"    fidelity:   {verdict_tag} ({fid_str})")

        if speedup_result:
            print(f"    speedup:    {speedup_result.speedup:.3f}x ({speedup_result.confidence})")

        if fidelity.metrics and fidelity.metrics.warnings:
            for w in fidelity.metrics.warnings:
                print(f"    warning:    {w}")

        if fidelity.verdict.value != "pass":
            all_pass = False

        # Build report entry
        scene_report: dict = {
            "verdict": fidelity.verdict.value,
            "psnr": fidelity.psnr if not fidelity.byte_identical else "inf",
            "ssim": fidelity.ssim,
            "max_diff": fidelity.max_diff,
            "byte_identical": fidelity.byte_identical,
            "pct_changed": fidelity.pct_changed,
            "timing": {
                "median_ms": summary.median_ms,
                "mean_ms": summary.mean_ms,
                "std_ms": summary.std_ms,
                "min_ms": summary.min_ms,
                "max_ms": summary.max_ms,
                "times_ms": summary.times_ms,
                "repeats": summary.repeats,
                "cv_pct": summary.cv_pct,
            },
            "image": f"{name}.png",
        }
        if speedup_result:
            scene_report["speedup"] = speedup_result.speedup
            scene_report["confidence"] = speedup_result.confidence
            scene_report["baseline_median_ms"] = speedup_result.baseline.median_ms
        if fidelity.metrics:
            scene_report["metrics"] = {
                "mean_lum_delta": fidelity.metrics.mean_lum_delta,
                "histogram_overlap": fidelity.metrics.histogram_overlap,
                "p50_delta": fidelity.metrics.p50_delta,
                "p95_delta": fidelity.metrics.p95_delta,
                "warnings": fidelity.metrics.warnings,
            }
        report_scenes[name] = scene_report

    # ── Write report ─────────────────────────────────────────────────
    total_median = sum(r["timing"]["median_ms"] for r in report_scenes.values())
    total_speedup = None
    if all("baseline_median_ms" in r for r in report_scenes.values()) and report_scenes:
        baseline_total = sum(r["baseline_median_ms"] for r in report_scenes.values())
        if baseline_total > 0:
            total_speedup = baseline_total / total_median

    report = {
        "timestamp": timestamp,
        "commit": commit,
        "branch": git.get("branch"),
        "verdict": "pass" if all_pass else "FAIL",
        "scenes_evaluated": len(report_scenes),
        "total_median_ms": round(total_median, 1),
        "total_speedup": round(total_speedup, 4) if total_speedup else None,
        "repeats": repeats,
        "warmup": warmup,
        "errors": errors,
        "scenes": report_scenes,
    }

    report_path = run_dir / "report.json"
    report_path.write_text(json.dumps(report, indent=2, default=str) + "\n")

    # ── Print summary ────────────────────────────────────────────────
    print(f"\n{'=' * 60}")
    print("  SUMMARY")
    print(f"{'=' * 60}")

    if errors:
        print(f"\n  Errors ({len(errors)}):")
        for e in errors:
            print(f"    - {e}")

    if report_scenes:
        # Grep-friendly key-value output (like autoresearch)
        print()
        print(f"verdict:    {'pass' if all_pass else 'FAIL'}")
        print(f"scenes:     {len(report_scenes)}")
        print(f"median_ms:  {total_median:.1f}")
        if total_speedup:
            print(f"speedup:    {total_speedup:.3f}x")
        print(f"run_dir:    {run_dir}/")
        print(f"report:     {report_path}")
    else:
        print()
        print("verdict:    FAIL (no scenes evaluated)")
        all_pass = False

    print(f"\n{'=' * 60}")
    sys.exit(0 if all_pass else 1)


# ── Argument parsing ─────────────────────────────────────────────────────


def main() -> None:
    args = sys.argv[1:]

    skip_build = False
    repeats = DEFAULT_REPEATS
    warmup = DEFAULT_WARMUP
    animate = False
    command = None

    i = 0
    while i < len(args):
        if args[i] == "--skip-build":
            skip_build = True
        elif args[i] == "--animate":
            animate = True
        elif args[i] == "--repeats" and i + 1 < len(args):
            i += 1
            repeats = int(args[i])
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

    if command == "capture":
        _run_capture(skip_build, repeats, warmup, animate)
    else:
        _run_evaluate(skip_build, repeats, warmup, animate)


if __name__ == "__main__":
    main()
