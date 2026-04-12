"""Directly tune and validate fixed warm-band compensation constants.

Question answered here:

    If the only thing known about the scene is the moving-light spectral band,
    what fixed exposure offset and gamma multiplier best preserve both
    final-frame brightness and apparent moving-light circle size?

The script keeps the model deliberately small:

1. Measure each white catalog shot, optionally at several moving-light
   intensity multipliers.
2. Re-render the same shot with the moving light recolored to a warm band and
   luminance-boosted.
3. For each scene, find the exposure offset that best restores the white
   moving-light radius.
4. Use the median per-scene offset as the center of a small direct grid search.
5. At that median offset, find each scene's brightness-matching gamma
   multiplier; use the median as the gamma grid center.
6. Choose the fixed per-band pair with a joint brightness+radius objective.
7. Report both the best fixed pair and the residual errors across every clean
   scene/intensity operating point.

All exposure/gamma trials use RenderSession.postprocess() after the band render,
so the expensive traced light transport is held fixed while post-processing is
swept.
"""

from __future__ import annotations

import argparse
import glob
import hashlib
import json
import math
import statistics
from dataclasses import dataclass
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


@dataclass(frozen=True)
class SceneCase:
    path: Path
    intensity_multiplier: float
    source_hash: str


def _source_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _case_label(case: SceneCase) -> str:
    root = case.path.parent.parent.name
    label = f"{root}/{scene_label(case.path)}"
    if abs(case.intensity_multiplier - 1.0) > 1e-9:
        label = f"{label}@I{case.intensity_multiplier:g}"
    return label


def _parse_multipliers(text: str) -> list[float]:
    parts = text.replace(",", " ").split()
    values = [float(part) for part in parts]
    if not values:
        raise SystemExit("At least one moving-light intensity multiplier is required")
    if any(value <= 0.0 for value in values):
        raise SystemExit("Moving-light intensity multipliers must be positive")
    return sorted(set(round(value, 6) for value in values))


def _shot_roots(explicit_roots: list[Path] | None, root_globs: list[str]) -> list[Path]:
    roots = list(explicit_roots or [])
    for pattern in root_globs:
        roots.extend(Path(path) for path in sorted(glob.glob(pattern)) if Path(path).is_dir())
    if not roots:
        roots.append(SHOT_ROOT)
    deduped: list[Path] = []
    seen: set[Path] = set()
    for root in roots:
        key = root.resolve()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(root)
    return deduped


def _build_scene_cases(
    paths: list[Path],
    intensity_multipliers: list[float],
    *,
    deduplicate_shots: bool,
) -> tuple[list[SceneCase], int]:
    seen: set[str] = set()
    cases: list[SceneCase] = []
    for path in paths:
        shot_hash = _source_hash(path)
        if deduplicate_shots and shot_hash in seen:
            continue
        seen.add(shot_hash)
        for multiplier in intensity_multipliers:
            cases.append(
                SceneCase(
                    path=path,
                    intensity_multiplier=multiplier,
                    source_hash=shot_hash,
                )
            )
    return cases, len(seen)


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


def _first_pass_scene_optima(case: SceneCase, band: Band, rays: int) -> dict:
    white_shot = load_probe_shot(
        case.path,
        rays,
        moving_intensity_multiplier=case.intensity_multiplier,
    )
    band_shot = load_band_shot(
        case.path,
        band,
        rays,
        moving_intensity_multiplier=case.intensity_multiplier,
    )
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
        "scene": _case_label(case),
        "source_scene": scene_label(case.path),
        "source_path": str(case.path),
        "source_hash": case.source_hash,
        "catalog": case.path.parent.parent.name,
        "material": case.path.parent.name,
        "size": scene_size(case.path),
        "n_lights": scene_light_count(case.path),
        "moving_intensity_multiplier": case.intensity_multiplier,
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
    case: SceneCase,
    band: Band,
    rays: int,
    fixed_exposure_delta: float,
    target_mean: float,
) -> tuple[float, Measurement]:
    band_shot = load_band_shot(
        case.path,
        band,
        rays,
        moving_intensity_multiplier=case.intensity_multiplier,
    )
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
    if stop < start:
        stop = start
    values = _frange(start, stop, step)
    if extras:
        values.extend(v for v in extras if lower <= v <= upper)
    return sorted(set(round(v, 6) for v in values))


def _evaluate_fixed_grid(
    cases: list[SceneCase],
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

    for idx, (case, row) in enumerate(zip(cases, rows), start=1):
        band_shot = load_band_shot(
            case.path,
            band,
            rays,
            moving_intensity_multiplier=case.intensity_multiplier,
        )
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
        print(f"      fixed grid [{idx:2d}/{len(cases)}] {row['scene']}")

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


def _passes_clean_filter(
    measurement: Measurement,
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


def run_study(
    cases: list[SceneCase],
    rays: int,
    *,
    shot_roots: list[Path],
    n_input_shot_files: int,
    n_source_scenes: int,
    deduplicate_shots: bool,
    moving_intensity_multipliers: list[float],
    exclude_materials: set[str],
    mean_min: float,
    mean_max: float,
    max_mean_saturation: float,
    max_shadow_fraction: float,
    min_moving_radius: float,
    fixed_gamma_min: float,
) -> dict:
    eligible_cases: list[SceneCase] = []
    rejected: list[dict] = []
    for case in cases:
        material = case.path.parent.name
        if material in exclude_materials:
            rejected.append(
                {
                    "scene": _case_label(case),
                    "source_scene": scene_label(case.path),
                    "source_path": str(case.path),
                    "source_hash": case.source_hash,
                    "catalog": case.path.parent.parent.name,
                    "material": material,
                    "moving_intensity_multiplier": case.intensity_multiplier,
                    "reasons": ["excluded_material"],
                }
            )
            continue

        shot = load_probe_shot(
            case.path,
            rays,
            moving_intensity_multiplier=case.intensity_multiplier,
        )
        session = _lpt2d.RenderSession(shot.canvas.width, shot.canvas.height)
        try:
            white = render_measure(shot, session)
        finally:
            session.close()
        ok, reasons = _passes_clean_filter(
            white,
            mean_min=mean_min,
            mean_max=mean_max,
            max_mean_saturation=max_mean_saturation,
            max_shadow_fraction=max_shadow_fraction,
            min_moving_radius=min_moving_radius,
        )
        if ok:
            eligible_cases.append(case)
        else:
            rejected.append(
                {
                    "scene": _case_label(case),
                    "source_scene": scene_label(case.path),
                    "source_path": str(case.path),
                    "source_hash": case.source_hash,
                    "catalog": case.path.parent.parent.name,
                    "material": material,
                    "moving_intensity_multiplier": case.intensity_multiplier,
                    "white": measurement_dict(white),
                    "reasons": reasons,
                }
            )

    if not eligible_cases:
        raise SystemExit("No eligible scenes after clean-scene filtering")

    result = {
        "rays": rays,
        "shot_roots": [str(root) for root in shot_roots],
        "n_input_shot_files": n_input_shot_files,
        "n_source_scenes": n_source_scenes,
        "n_input_cases": len(cases),
        "n_clean_source_scenes": len({case.source_hash for case in eligible_cases}),
        "n_scene_cases": len(eligible_cases),
        "n_scenes": len(eligible_cases),
        "clean_filter": {
            "exclude_materials": sorted(exclude_materials),
            "mean_min": mean_min,
            "mean_max": mean_max,
            "max_mean_saturation": max_mean_saturation,
            "max_shadow_fraction": max_shadow_fraction,
            "min_moving_radius": min_moving_radius,
            "fixed_gamma_min": fixed_gamma_min,
            "deduplicate_shots": deduplicate_shots,
            "moving_intensity_multipliers": moving_intensity_multipliers,
            "rejected": rejected,
        },
        "method": {
            "brightness_metric": "final RGB8 BT.709 mean luminance",
            "radius_metric": "mean FrameAnalysis radius_ratio over moving lights",
            "fixed_exposure_rule": "median of per-scene radius-matching exposure offsets",
            "fixed_gamma_center": (
                "median of per-scene brightness-matching gamma multipliers at the "
                "median exposure"
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
        for idx, case in enumerate(eligible_cases, start=1):
            row = _first_pass_scene_optima(case, band, rays)
            rows.append(row)
            print(
                f"  [{idx:2d}/{len(eligible_cases)}] {row['scene']:45s} "
                f"base B={row['base_brightness_ratio']:.3f} R={row['base_radius_ratio']:.3f} "
                f"scene-opt dE={row['scene_optimal_exposure_delta']:+.2f} "
                f"g={row['scene_optimal_gamma_multiplier']:.3f}"
            )

        fixed_exposure_delta = statistics.median(
            row["scene_optimal_exposure_delta"] for row in rows
        )

        for idx, (case, row) in enumerate(zip(eligible_cases, rows), start=1):
            gamma_needed, gamma_measure = _gamma_needed_at_fixed_exposure(
                case,
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
                f"      fixed dE pass [{idx:2d}/{len(eligible_cases)}] {row['scene']:45s} "
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
            lower=fixed_gamma_min,
            upper=GAMMA_SEARCH_MAX,
            radius=FIXED_GAMMA_GRID_RADIUS,
            step=FIXED_GAMMA_GRID_STEP,
            extras=[gamma_center],
        )
        best_fixed, top_fixed = _evaluate_fixed_grid(
            eligible_cases,
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
    parser.add_argument(
        "--shot-root",
        dest="shot_roots",
        type=Path,
        action="append",
        help="Directory containing white*.shot.json files. May be passed more than once.",
    )
    parser.add_argument(
        "--shot-root-glob",
        dest="shot_root_globs",
        action="append",
        default=[],
        help="Glob for shot-root directories, for example 'renders/lpt2d_crystal_field_catalog_*'.",
    )
    parser.add_argument(
        "--no-deduplicate-shots",
        action="store_true",
        help="Keep exact duplicate shot JSON files instead of hashing and dropping repeats.",
    )
    parser.add_argument(
        "--moving-intensity-multipliers",
        default="1.0",
        help=(
            "Comma- or space-separated moving-light intensity multipliers. "
            "Each multiplier is filtered as its own white-baseline operating point."
        ),
    )
    parser.add_argument(
        "--include-glass",
        action="store_true",
        help="Include glass scenes. Default excludes them for compensation calibration.",
    )
    parser.add_argument("--mean-min", type=float, default=60.0)
    parser.add_argument("--mean-max", type=float, default=140.0)
    parser.add_argument("--max-mean-saturation", type=float, default=0.66)
    parser.add_argument("--max-shadow-fraction", type=float, default=0.20)
    parser.add_argument("--min-moving-radius", type=float, default=0.010)
    parser.add_argument(
        "--fixed-gamma-min",
        type=float,
        default=0.70,
        help=(
            "Do not select fixed gamma multipliers below this value. "
            "Very low gamma multipliers tend to look visually destructive."
        ),
    )
    args = parser.parse_args()
    if args.fixed_gamma_min > GAMMA_SEARCH_MAX:
        raise SystemExit(f"--fixed-gamma-min must be <= {GAMMA_SEARCH_MAX}")

    shot_roots = _shot_roots(args.shot_roots, args.shot_root_globs)
    intensity_multipliers = _parse_multipliers(args.moving_intensity_multipliers)
    paths: list[Path] = []
    for root in shot_roots:
        paths.extend(white_shot_paths(root))
    if args.limit > 0:
        paths = paths[: args.limit]
    if not paths:
        roots = ", ".join(str(root) for root in shot_roots)
        raise SystemExit(f"No white shot files found under {roots}")

    cases, n_source_scenes = _build_scene_cases(
        paths,
        intensity_multipliers,
        deduplicate_shots=not args.no_deduplicate_shots,
    )

    exclude_materials = set() if args.include_glass else {"glass"}
    data = run_study(
        cases,
        args.rays,
        shot_roots=shot_roots,
        n_input_shot_files=len(paths),
        n_source_scenes=n_source_scenes,
        deduplicate_shots=not args.no_deduplicate_shots,
        moving_intensity_multipliers=intensity_multipliers,
        exclude_materials=exclude_materials,
        mean_min=args.mean_min,
        mean_max=args.mean_max,
        max_mean_saturation=args.max_mean_saturation,
        max_shadow_fraction=args.max_shadow_fraction,
        min_moving_radius=args.min_moving_radius,
        fixed_gamma_min=args.fixed_gamma_min,
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(data, indent=2))
    print(f"\nFull data in {args.out}")


if __name__ == "__main__":
    main()
