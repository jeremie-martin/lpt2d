"""Build a clean non-glass white-shot dataset for compensation calibration.

This creates authored white-light shot JSONs from the crystal_field family,
with varied material parameters, shape, look, ambient intensity, and moving
light intensity. A shot is kept only if the rendered white baseline passes the
simple visual envelope used by the compensation study:

    mean luminance in [60, 140]
    mean saturation <= 0.66
    shadow fraction <= 0.20
    moving radius >= 0.010

The output can be fed directly to fixed_compensation_study.py:

    python examples/python/spectral_compensation/build_clean_dataset.py
    python examples/python/spectral_compensation/fixed_compensation_study.py \
      --shot-root renders/brightness_experiment_shots/clean_non_glass_white_dataset
"""

from __future__ import annotations

import argparse
import json
import random
from dataclasses import asdict
from pathlib import Path

import _lpt2d
from anim import Camera2D, Shot
from anim.examples_support import _authored_shot

from examples.python.families.crystal_field.catalog import GRID_SIZES, _entry_sample
from examples.python.families.crystal_field.check import measurement_context
from examples.python.families.crystal_field.scene import build

from spectral_common import OUT_ROOT, measurement_dict, render_measure


OUTCOMES = (
    "black_diffuse",
    "gray_diffuse",
    "colored_diffuse",
    "brushed_metal",
)


def _white_entry(outcome: str, grid_name: str, n_lights: int) -> dict:
    return {
        "outcome": outcome,
        "grid": grid_name,
        "light_color": "white",
        "n_lights": n_lights,
        "grid_cfg": GRID_SIZES[grid_name],
        "wl_min": 380.0,
        "wl_max": 780.0,
    }


def _passes_clean_filter(
    measurement,
    *,
    mean_min: float,
    mean_max: float,
    max_mean_saturation: float,
    max_shadow_fraction: float,
    min_moving_radius: float,
) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    if measurement.mean < mean_min:
        reasons.append(f"mean<{mean_min:g}")
    if measurement.mean > mean_max:
        reasons.append(f"mean>{mean_max:g}")
    if measurement.mean_saturation > max_mean_saturation:
        reasons.append(f"mean_saturation>{max_mean_saturation:g}")
    if measurement.shadow_fraction > max_shadow_fraction:
        reasons.append(f"shadow_fraction>{max_shadow_fraction:g}")
    if measurement.moving_radius < min_moving_radius:
        reasons.append(f"moving_radius<{min_moving_radius:g}")
    return not reasons, reasons


def _measure_shot(shot: _lpt2d.Shot):
    session = _lpt2d.RenderSession(shot.canvas.width, shot.canvas.height)
    try:
        return render_measure(shot, session)
    finally:
        session.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--out",
        type=Path,
        default=OUT_ROOT / "clean_non_glass_white_dataset",
    )
    parser.add_argument("--per-bucket", type=int, default=3)
    parser.add_argument("--max-attempts-per-bucket", type=int, default=400)
    parser.add_argument("--seed", type=int, default=11)
    parser.add_argument("--width", type=int, default=960)
    parser.add_argument("--height", type=int, default=540)
    parser.add_argument("--rays", type=int, default=400_000)
    parser.add_argument("--mean-min", type=float, default=60.0)
    parser.add_argument("--mean-max", type=float, default=140.0)
    parser.add_argument("--max-mean-saturation", type=float, default=0.66)
    parser.add_argument("--max-shadow-fraction", type=float, default=0.20)
    parser.add_argument("--min-moving-radius", type=float, default=0.010)
    args = parser.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)
    settings = Shot.preset(
        "draft",
        width=args.width,
        height=args.height,
        rays=args.rays,
        depth=10,
    )
    settings.camera = Camera2D(center=[0, 0], width=3.2)

    kept: list[dict] = []
    rejected_counts: dict[str, int] = {}
    buckets = [
        (outcome, grid_name, n_lights)
        for outcome in OUTCOMES
        for grid_name in GRID_SIZES
        for n_lights in (1, 2)
    ]

    for outcome, grid_name, n_lights in buckets:
        entry = _white_entry(outcome, grid_name, n_lights)
        rng = random.Random(f"{args.seed}:{outcome}:{grid_name}:{n_lights}")
        bucket_kept = 0
        attempts = 0
        while bucket_kept < args.per_bucket and attempts < args.max_attempts_per_bucket:
            attempts += 1
            params = _entry_sample(entry, rng)
            animate = build(params)
            ctx = measurement_context(params, animate)
            shot = _authored_shot(settings, animate, ctx)
            shot.trace.rays = args.rays
            measurement = _measure_shot(shot.to_cpp())
            ok, reasons = _passes_clean_filter(
                measurement,
                mean_min=args.mean_min,
                mean_max=args.mean_max,
                max_mean_saturation=args.max_mean_saturation,
                max_shadow_fraction=args.max_shadow_fraction,
                min_moving_radius=args.min_moving_radius,
            )
            if not ok:
                for reason in reasons:
                    rejected_counts[reason] = rejected_counts.get(reason, 0) + 1
                continue

            bucket_kept += 1
            material_dir = args.out / outcome
            material_dir.mkdir(parents=True, exist_ok=True)
            stem = f"white_{grid_name}_{n_lights}light_{bucket_kept:03d}"
            shot_path = material_dir / f"{stem}.shot.json"
            shot.save(shot_path)
            row = {
                "scene": f"{outcome}/{stem}",
                "path": str(shot_path),
                "outcome": outcome,
                "grid": grid_name,
                "n_lights": n_lights,
                "attempt": attempts,
                "metrics": measurement_dict(measurement),
                "params": asdict(params),
            }
            kept.append(row)
            print(
                f"kept {row['scene']:42s} "
                f"mean={measurement.mean:5.1f} sat={measurement.mean_saturation:.3f} "
                f"shadow={measurement.shadow_fraction:.3f} radius={measurement.moving_radius:.4f}"
            )

        if bucket_kept < args.per_bucket:
            print(
                f"warning: bucket {outcome}/{grid_name}/{n_lights}light kept "
                f"{bucket_kept}/{args.per_bucket} after {attempts} attempts"
            )

    manifest = {
        "schema": 1,
        "out": str(args.out),
        "seed": args.seed,
        "per_bucket": args.per_bucket,
        "width": args.width,
        "height": args.height,
        "rays": args.rays,
        "filters": {
            "mean_min": args.mean_min,
            "mean_max": args.mean_max,
            "max_mean_saturation": args.max_mean_saturation,
            "max_shadow_fraction": args.max_shadow_fraction,
            "min_moving_radius": args.min_moving_radius,
            "excluded_materials": ["glass"],
        },
        "kept": kept,
        "rejected_counts": rejected_counts,
    }
    (args.out / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print(f"\nkept {len(kept)} shots in {args.out}")


if __name__ == "__main__":
    main()
