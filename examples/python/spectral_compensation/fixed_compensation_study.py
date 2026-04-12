"""Directly tune and validate fixed warm-band compensation constants.

Question answered here:

    If the only thing known about the scene is the moving-light spectral band,
    what fixed exposure offset and gamma multiplier best preserve both
    final-frame brightness and apparent moving-light circle size?

The script keeps the model deliberately small:

1. Measure each white catalog shot.
2. Re-render the same shot with the moving light recolored to a warm band and
   luminance-boosted.
3. For each scene, find the exposure offset that best restores the white
   moving-light radius.
4. Use the median per-scene offset as the center of a small direct grid search.
5. At that median offset, find each scene's brightness-matching gamma
   multiplier; use the median as the gamma grid center.
6. Choose the fixed per-band pair with a joint brightness+radius objective.
7. Report both the best fixed pair and the residual errors across every scene.

All exposure/gamma trials use RenderSession.postprocess() after the band render,
so the expensive traced light transport is held fixed while post-processing is
swept.
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
from pathlib import Path

import _lpt2d

from spectral_common import (
    OUT_ROOT,
    PROBE_RAYS,
    SHOT_ROOT,
    STUDY_BANDS,
    Band,
    Measurement,
    load_band_shot,
    load_probe_shot,
    measurement_dict,
    postprocess_measure,
    ratio,
    ratio_summary,
    render_measure,
    scene_label,
    scene_light_count,
    scene_size,
    spectral_boost,
    percentile,
    value_summary,
    white_shot_paths,
)


EXPOSURE_SEARCH_MIN = -0.20
EXPOSURE_SEARCH_MAX = 1.80
EXPOSURE_COARSE_STEP = 0.05
EXPOSURE_REFINE_RADIUS = 0.05
EXPOSURE_REFINE_STEP = 0.01

GAMMA_SEARCH_MIN = 0.25
GAMMA_SEARCH_MAX = 1.30
GAMMA_SEARCH_ITERS = 18

FIXED_EXPOSURE_GRID_RADIUS = 0.25
FIXED_EXPOSURE_GRID_STEP = 0.05
FIXED_GAMMA_GRID_RADIUS = 0.25
FIXED_GAMMA_GRID_STEP = 0.05


def _frange(start: float, stop: float, step: float) -> list[float]:
    vals: list[float] = []
    i = 0
    while True:
        value = start + step * i
        if value > stop + 1e-9:
            break
        vals.append(round(value, 6))
        i += 1
    return vals


def _target_score(brightness_ratio: float, radius_ratio: float) -> float:
    """Symmetric multiplicative error in brightness and radius."""
    if brightness_ratio <= 0.0 or radius_ratio <= 0.0:
        return float("inf")
    return abs(math.log(brightness_ratio)) + abs(math.log(radius_ratio))


def _fixed_objective(joint_scores: list[float]) -> float:
    """Robust scalar score for fixed correction selection.

    The 90th percentile keeps the chosen constants useful for most scenes,
    while the small mean term breaks ties without letting one detector outlier
    dominate everything.
    """
    if not joint_scores:
        return float("inf")
    return percentile(joint_scores, 0.90) + 0.25 * statistics.mean(joint_scores)


def _radius_score(radius_ratio: float) -> float:
    if radius_ratio <= 0.0:
        return float("inf")
    return abs(math.log(radius_ratio))


def _find_exposure_for_radius(
    session: _lpt2d.RenderSession,
    base_look: _lpt2d.Look,
    white: Measurement,
) -> tuple[float, Measurement]:
    """Find the exposure offset that best matches white moving-light radius."""
    candidates = _frange(EXPOSURE_SEARCH_MIN, EXPOSURE_SEARCH_MAX, EXPOSURE_COARSE_STEP)
    best_delta = 0.0
    best_measure = None
    best_score = float("inf")

    for delta in candidates:
        measurement = postprocess_measure(session, base_look, exposure_delta=delta)
        radius_ratio = ratio(measurement.moving_radius, white.moving_radius)
        score = _radius_score(radius_ratio)
        if score < best_score:
            best_delta = delta
            best_measure = measurement
            best_score = score

    refine_start = max(EXPOSURE_SEARCH_MIN, best_delta - EXPOSURE_REFINE_RADIUS)
    refine_stop = min(EXPOSURE_SEARCH_MAX, best_delta + EXPOSURE_REFINE_RADIUS)
    for delta in _frange(refine_start, refine_stop, EXPOSURE_REFINE_STEP):
        measurement = postprocess_measure(session, base_look, exposure_delta=delta)
        radius_ratio = ratio(measurement.moving_radius, white.moving_radius)
        score = _radius_score(radius_ratio)
        if score < best_score:
            best_delta = delta
            best_measure = measurement
            best_score = score

    if best_measure is None:
        best_measure = postprocess_measure(session, base_look)
    return best_delta, best_measure


def _find_gamma_for_brightness(
    session: _lpt2d.RenderSession,
    base_look: _lpt2d.Look,
    *,
    exposure_delta: float,
    target_mean: float,
) -> tuple[float, Measurement]:
    """Find the gamma multiplier that best matches white mean luminance."""
    lo = GAMMA_SEARCH_MIN
    hi = GAMMA_SEARCH_MAX
    best_gamma = 1.0
    best_measure = None
    best_score = float("inf")

    for _ in range(GAMMA_SEARCH_ITERS):
        mid = (lo + hi) * 0.5
        measurement = postprocess_measure(
            session,
            base_look,
            exposure_delta=exposure_delta,
            gamma_multiplier=mid,
        )
        brightness_ratio = ratio(measurement.mean, target_mean)
        score = abs(math.log(max(brightness_ratio, 1e-9)))
        if score < best_score:
            best_gamma = mid
            best_measure = measurement
            best_score = score

        if measurement.mean < target_mean:
            lo = mid
        else:
            hi = mid

    if best_measure is None:
        best_measure = postprocess_measure(
            session,
            base_look,
            exposure_delta=exposure_delta,
            gamma_multiplier=best_gamma,
        )
    return best_gamma, best_measure


def _first_pass_scene_optima(path: Path, band: Band, rays: int) -> dict:
    white_shot = load_probe_shot(path, rays)
    band_shot = load_band_shot(path, band, rays)
    base_look = band_shot.look
    session = _lpt2d.RenderSession(band_shot.canvas.width, band_shot.canvas.height)
    try:
        white = render_measure(white_shot, session)
        band_base = render_measure(band_shot, session)
        exposure_delta, exposure_measure = _find_exposure_for_radius(
            session,
            base_look,
            white,
        )
        gamma_multiplier, scene_optimal = _find_gamma_for_brightness(
            session,
            base_look,
            exposure_delta=exposure_delta,
            target_mean=white.mean,
        )
    finally:
        session.close()

    return {
        "scene": scene_label(path),
        "material": path.parent.name,
        "size": scene_size(path),
        "n_lights": scene_light_count(path),
        "base_exposure": float(base_look.exposure),
        "base_gamma": float(base_look.gamma),
        "white": measurement_dict(white),
        "band_base": measurement_dict(band_base),
        "base_brightness_ratio": ratio(band_base.mean, white.mean),
        "base_radius_ratio": ratio(band_base.moving_radius, white.moving_radius),
        "scene_optimal_exposure_delta": exposure_delta,
        "scene_optimal_gamma_multiplier": gamma_multiplier,
        "scene_optimal_brightness_ratio": ratio(scene_optimal.mean, white.mean),
        "scene_optimal_radius_ratio": ratio(scene_optimal.moving_radius, white.moving_radius),
        "exposure_only_brightness_ratio": ratio(exposure_measure.mean, white.mean),
        "exposure_only_radius_ratio": ratio(exposure_measure.moving_radius, white.moving_radius),
    }


def _gamma_needed_at_fixed_exposure(
    path: Path,
    band: Band,
    rays: int,
    fixed_exposure_delta: float,
    target_mean: float,
) -> tuple[float, Measurement]:
    band_shot = load_band_shot(path, band, rays)
    base_look = band_shot.look
    session = _lpt2d.RenderSession(band_shot.canvas.width, band_shot.canvas.height)
    try:
        render_measure(band_shot, session)
        return _find_gamma_for_brightness(
            session,
            base_look,
            exposure_delta=fixed_exposure_delta,
            target_mean=target_mean,
        )
    finally:
        session.close()


def _candidate_values(
    center: float,
    *,
    lower: float,
    upper: float,
    radius: float,
    step: float,
    extras: list[float] | None = None,
) -> list[float]:
    start = max(lower, center - radius)
    stop = min(upper, center + radius)
    values = _frange(start, stop, step)
    if extras:
        values.extend(v for v in extras if lower <= v <= upper)
    return sorted(set(round(v, 6) for v in values))


def _evaluate_fixed_grid(
    paths: list[Path],
    rows: list[dict],
    band: Band,
    rays: int,
    exposure_candidates: list[float],
    gamma_candidates: list[float],
) -> tuple[dict, list[dict]]:
    records: dict[tuple[float, float], dict] = {}
    for exposure_delta in exposure_candidates:
        for gamma_multiplier in gamma_candidates:
            records[(exposure_delta, gamma_multiplier)] = {
                "exposure_delta": exposure_delta,
                "gamma_multiplier": gamma_multiplier,
                "brightness_ratios": [],
                "radius_ratios": [],
                "joint_scores": [],
            }

    for idx, (path, row) in enumerate(zip(paths, rows), start=1):
        band_shot = load_band_shot(path, band, rays)
        session = _lpt2d.RenderSession(band_shot.canvas.width, band_shot.canvas.height)
        try:
            render_measure(band_shot, session)
            for exposure_delta in exposure_candidates:
                for gamma_multiplier in gamma_candidates:
                    measurement = postprocess_measure(
                        session,
                        band_shot.look,
                        exposure_delta=exposure_delta,
                        gamma_multiplier=gamma_multiplier,
                    )
                    brightness_ratio = ratio(measurement.mean, row["white"]["mean"])
                    radius_ratio = ratio(
                        measurement.moving_radius,
                        row["white"]["moving_radius"],
                    )
                    rec = records[(exposure_delta, gamma_multiplier)]
                    rec["brightness_ratios"].append(brightness_ratio)
                    rec["radius_ratios"].append(radius_ratio)
                    rec["joint_scores"].append(_target_score(brightness_ratio, radius_ratio))
        finally:
            session.close()
        print(f"      fixed grid [{idx:2d}/{len(paths)}] {row['scene']}")

    ranked: list[dict] = []
    for rec in records.values():
        brightness_summary = ratio_summary(rec["brightness_ratios"])
        radius_summary = ratio_summary(rec["radius_ratios"])
        ranked.append(
            {
                "exposure_delta": rec["exposure_delta"],
                "gamma_multiplier": rec["gamma_multiplier"],
                "objective": _fixed_objective(rec["joint_scores"]),
                "joint_score": value_summary(rec["joint_scores"]),
                "brightness": brightness_summary,
                "radius": radius_summary,
                "brightness_ratios": rec["brightness_ratios"],
                "radius_ratios": rec["radius_ratios"],
                "joint_scores": rec["joint_scores"],
            }
        )

    ranked.sort(key=lambda r: (r["objective"], r["joint_score"]["mean"]))
    return ranked[0], ranked[:10]


def _summarize_rows(rows: list[dict]) -> dict:
    return {
        "base_brightness": ratio_summary([r["base_brightness_ratio"] for r in rows]),
        "base_radius": ratio_summary([r["base_radius_ratio"] for r in rows]),
        "scene_optimal_exposure_delta": value_summary(
            [r["scene_optimal_exposure_delta"] for r in rows]
        ),
        "scene_optimal_gamma_multiplier": value_summary(
            [r["scene_optimal_gamma_multiplier"] for r in rows]
        ),
        "scene_optimal_brightness": ratio_summary(
            [r["scene_optimal_brightness_ratio"] for r in rows]
        ),
        "scene_optimal_radius": ratio_summary([r["scene_optimal_radius_ratio"] for r in rows]),
        "fixed_gamma_needed": value_summary([r["fixed_gamma_needed"] for r in rows]),
        "fixed_brightness": ratio_summary([r["fixed_brightness_ratio"] for r in rows]),
        "fixed_radius": ratio_summary([r["fixed_radius_ratio"] for r in rows]),
        "fixed_joint_score": value_summary([r["fixed_joint_score"] for r in rows]),
    }


def _worst_rows(rows: list[dict], key: str, n: int = 6) -> list[dict]:
    ranked = sorted(rows, key=lambda r: abs(r[key] - 1.0), reverse=True)
    keep_keys = [
        "scene",
        "base_brightness_ratio",
        "base_radius_ratio",
        "fixed_brightness_ratio",
        "fixed_radius_ratio",
        "scene_optimal_exposure_delta",
        "fixed_gamma_needed",
        "fixed_joint_score",
    ]
    return [{k: row[k] for k in keep_keys} for row in ranked[:n]]


def run_study(paths: list[Path], rays: int) -> dict:
    result = {
        "rays": rays,
        "shot_root": str(SHOT_ROOT),
        "n_scenes": len(paths),
        "method": {
            "brightness_metric": "final RGB8 BT.709 mean luminance",
            "radius_metric": "mean FrameAnalysis radius_ratio over moving lights",
            "fixed_exposure_rule": "median of per-scene radius-matching exposure offsets",
        "fixed_gamma_center": (
            "median of per-scene brightness-matching gamma multipliers at the median exposure"
        ),
        "fixed_pair_rule": (
            "small direct grid around the median exposure/gamma centers, selected by "
            "p90(abs(log brightness ratio)+abs(log radius ratio)) plus 0.25 mean"
        ),
        },
        "bands": {},
    }

    for band in STUDY_BANDS:
        print(f"\n=== {band.name} {band.wavelength_min:.0f}-{band.wavelength_max:.0f}nm ===")
        rows: list[dict] = []
        for idx, path in enumerate(paths, start=1):
            row = _first_pass_scene_optima(path, band, rays)
            rows.append(row)
            print(
                f"  [{idx:2d}/{len(paths)}] {row['scene']:45s} "
                f"base B={row['base_brightness_ratio']:.3f} R={row['base_radius_ratio']:.3f} "
                f"scene-opt dE={row['scene_optimal_exposure_delta']:+.2f} "
                f"g={row['scene_optimal_gamma_multiplier']:.3f}"
            )

        fixed_exposure_delta = statistics.median(
            row["scene_optimal_exposure_delta"] for row in rows
        )

        for idx, (path, row) in enumerate(zip(paths, rows), start=1):
            gamma_needed, gamma_measure = _gamma_needed_at_fixed_exposure(
                path,
                band,
                rays,
                fixed_exposure_delta,
                row["white"]["mean"],
            )
            row["fixed_exposure_delta"] = fixed_exposure_delta
            row["fixed_gamma_needed"] = gamma_needed
            row["fixed_exposure_gamma_needed_brightness_ratio"] = ratio(
                gamma_measure.mean,
                row["white"]["mean"],
            )
            row["fixed_exposure_gamma_needed_radius_ratio"] = ratio(
                gamma_measure.moving_radius,
                row["white"]["moving_radius"],
            )
            print(
                f"      fixed dE pass [{idx:2d}/{len(paths)}] {row['scene']:45s} "
                f"gamma-needed={gamma_needed:.3f}"
            )

        gamma_center = statistics.median(row["fixed_gamma_needed"] for row in rows)
        exposure_candidates = _candidate_values(
            fixed_exposure_delta,
            lower=EXPOSURE_SEARCH_MIN,
            upper=EXPOSURE_SEARCH_MAX,
            radius=FIXED_EXPOSURE_GRID_RADIUS,
            step=FIXED_EXPOSURE_GRID_STEP,
            extras=[fixed_exposure_delta],
        )
        gamma_candidates = _candidate_values(
            gamma_center,
            lower=GAMMA_SEARCH_MIN,
            upper=GAMMA_SEARCH_MAX,
            radius=FIXED_GAMMA_GRID_RADIUS,
            step=FIXED_GAMMA_GRID_STEP,
            extras=[gamma_center],
        )
        best_fixed, top_fixed = _evaluate_fixed_grid(
            paths,
            rows,
            band,
            rays,
            exposure_candidates,
            gamma_candidates,
        )
        fixed_exposure_delta = best_fixed["exposure_delta"]
        fixed_gamma_multiplier = best_fixed["gamma_multiplier"]

        for idx, row in enumerate(rows):
            row["fixed_exposure_delta"] = fixed_exposure_delta
            row["fixed_gamma_multiplier"] = fixed_gamma_multiplier
            row["fixed_brightness_ratio"] = best_fixed["brightness_ratios"][idx]
            row["fixed_radius_ratio"] = best_fixed["radius_ratios"][idx]
            row["fixed_joint_score"] = best_fixed["joint_scores"][idx]

        result["bands"][band.name] = {
            "band": {
                "name": band.name,
                "wavelength_min": band.wavelength_min,
                "wavelength_max": band.wavelength_max,
                "spectral_boost": spectral_boost(band),
            },
            "fixed_correction": {
                "exposure_delta": fixed_exposure_delta,
                "gamma_multiplier": fixed_gamma_multiplier,
                "objective": best_fixed["objective"],
            },
            "fixed_grid": {
                "exposure_candidates": exposure_candidates,
                "gamma_candidates": gamma_candidates,
                "center_exposure_delta": statistics.median(
                    row["scene_optimal_exposure_delta"] for row in rows
                ),
                "center_gamma_multiplier": gamma_center,
                "top_candidates": [
                    {
                        k: candidate[k]
                        for k in (
                            "exposure_delta",
                            "gamma_multiplier",
                            "objective",
                            "joint_score",
                            "brightness",
                            "radius",
                        )
                    }
                    for candidate in top_fixed
                ],
            },
            "summary": _summarize_rows(rows),
            "worst_fixed_brightness": _worst_rows(rows, "fixed_brightness_ratio"),
            "worst_fixed_radius": _worst_rows(rows, "fixed_radius_ratio"),
            "rows": rows,
        }

        summary = result["bands"][band.name]["summary"]
        print(
            f"\n  fixed correction: dE={fixed_exposure_delta:+.3f}, "
            f"gamma*={fixed_gamma_multiplier:.3f}"
        )
        print(
            "  fixed brightness abs error: "
            f"mean={summary['fixed_brightness']['mean_abs_pct_error']:.1f}% "
            f"p90={summary['fixed_brightness']['p90_abs_pct_error']:.1f}% "
            f"max={summary['fixed_brightness']['max_abs_pct_error']:.1f}%"
        )
        print(
            "  fixed radius abs error:     "
            f"mean={summary['fixed_radius']['mean_abs_pct_error']:.1f}% "
            f"p90={summary['fixed_radius']['p90_abs_pct_error']:.1f}% "
            f"max={summary['fixed_radius']['max_abs_pct_error']:.1f}%"
        )

    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rays", type=int, default=PROBE_RAYS)
    parser.add_argument("--limit", type=int, default=0, help="Optional scene limit for quick checks")
    parser.add_argument("--out", type=Path, default=OUT_ROOT / "fixed_compensation_study.json")
    args = parser.parse_args()

    paths = white_shot_paths(SHOT_ROOT)
    if args.limit > 0:
        paths = paths[: args.limit]
    if not paths:
        raise SystemExit(f"No white shot files found under {SHOT_ROOT}")

    data = run_study(paths, args.rays)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(data, indent=2))
    print(f"\nFull data in {args.out}")


if __name__ == "__main__":
    main()
