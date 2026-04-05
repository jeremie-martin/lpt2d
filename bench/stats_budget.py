#!/usr/bin/env python3
"""Measure stats-pipeline overhead from real streaming renders.

Usage:
    python3 bench/stats_budget.py
    python3 bench/stats_budget.py --repeats 3 --threshold 1.0

The script renders the benchmark scenes through the normal `--stream` path and
uses the renderer's structured `stats_ms` metadata to report how much of each
frame was spent computing CPU-side stats from the readback buffer.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from anim.types import Shot

PROJECT_DIR = Path(__file__).resolve().parents[1]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))
DEFAULT_BINARY = str(PROJECT_DIR / "build" / "lpt2d-cli")


def load_manifest_configs(manifest_path: Path) -> list[dict]:
    manifest = json.loads(manifest_path.read_text())
    defaults = manifest.get("defaults", {})
    return [{**defaults, **scene} for scene in manifest.get("scenes", [])]


def apply_bench_config(shot: Shot, config: dict) -> Shot:
    if "width" in config:
        shot.canvas.width = int(config["width"])
    if "height" in config:
        shot.canvas.height = int(config["height"])
    if "rays" in config:
        shot.trace.rays = int(config["rays"])
    if "batch" in config:
        shot.trace.batch = int(config["batch"])
    if "depth" in config:
        shot.trace.depth = int(config["depth"])
    if "exposure" in config:
        shot.look.exposure = float(config["exposure"])
    if "contrast" in config:
        shot.look.contrast = float(config["contrast"])
    if "gamma" in config:
        shot.look.gamma = float(config["gamma"])
    if "tonemap" in config:
        shot.look.tonemap = str(config["tonemap"])
    if "white_point" in config:
        shot.look.white_point = float(config["white_point"])
    return shot


def measure_scene(path: Path, config: dict, *, binary: str, fast: bool, repeats: int, warmup: int) -> dict:
    from anim.renderer import Renderer, _build_wire_json
    from anim.types import Frame, Shot

    shot = apply_bench_config(Shot.load(path), config)
    wire = _build_wire_json(
        Frame(scene=shot.scene),
        camera=None,
        shot_camera=shot.camera,
        aspect=shot.canvas.aspect,
    )
    total_ms: list[float] = []
    stats_ms: list[float] = []
    ratio_pct: list[float] = []

    with Renderer(shot, binary=binary, fast=fast) as renderer:
        for _ in range(warmup):
            renderer.render_frame(wire)
        for _ in range(repeats):
            renderer.render_frame(wire)
            report = renderer.last_report
            if report is None or report.stats_ms is None:
                raise RuntimeError(f"missing stats_ms in renderer report for {path.name}")
            frame_ms = report.time_ms_exact if report.time_ms_exact is not None else float(report.time_ms)
            total_ms.append(frame_ms)
            stats_ms.append(report.stats_ms)
            ratio_pct.append(100.0 * report.stats_ms / max(frame_ms, 1e-6))

    total_med = statistics.median(total_ms)
    stats_med = statistics.median(stats_ms)
    ratio = statistics.median(ratio_pct)
    return {
        "scene": path.stem,
        "total_ms": total_med,
        "stats_ms": stats_med,
        "ratio_pct": ratio,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", default=DEFAULT_BINARY, help="Path to lpt2d-cli")
    parser.add_argument("--manifest", default="bench/scenes/manifest.json", help="Benchmark manifest")
    parser.add_argument("--repeats", type=int, default=2, help="Measured renders per scene")
    parser.add_argument("--warmup", type=int, default=1, help="Warm-up renders per scene")
    parser.add_argument("--threshold", type=float, default=1.0, help="Maximum acceptable median overhead percent")
    parser.add_argument("--fast", action="store_true", help="Pass --fast to the renderer")
    parser.add_argument("scenes", nargs="*", help="Optional scene names from bench/scenes without .json")
    args = parser.parse_args()

    manifest_path = PROJECT_DIR / args.manifest
    manifest_configs = load_manifest_configs(manifest_path)
    config_by_name = {config["name"]: config for config in manifest_configs}
    scene_names = args.scenes or list(config_by_name)
    scene_entries = [
        (PROJECT_DIR / "bench" / "scenes" / f"{name}.json", config_by_name.get(name, {"name": name}))
        for name in scene_names
    ]

    results = [
        measure_scene(
            path,
            config,
            binary=args.binary,
            fast=args.fast,
            repeats=args.repeats,
            warmup=args.warmup,
        )
        for path, config in scene_entries
    ]

    worst = max(results, key=lambda entry: entry["ratio_pct"])
    average = statistics.mean(entry["ratio_pct"] for entry in results)

    print("scene                     frame_ms  stats_ms  overhead")
    for entry in results:
        print(
            f"{entry['scene']:<24} {entry['total_ms']:>8.0f}  "
            f"{entry['stats_ms']:>8.3f}  {entry['ratio_pct']:>7.3f}%"
        )
    print(
        f"\nworst: {worst['scene']} at {worst['ratio_pct']:.3f}%   "
        f"average: {average:.3f}%   threshold: {args.threshold:.3f}%"
    )

    return 0 if worst["ratio_pct"] <= args.threshold else 1


if __name__ == "__main__":
    raise SystemExit(main())
