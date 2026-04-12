"""Characterize the fundamental relationships:
  1. Δexposure → brightness ratio  (and circle size ratio)
  2. Δgamma → brightness ratio     (circle should be invariant)

Sweeps all 30 white shots, computes ratios relative to base, and fits
simple models. The goal: can we predict the effect of an exposure/gamma
change from a single formula, consistently across scenes?
"""

from __future__ import annotations

import json
import math
import statistics
from pathlib import Path

import _lpt2d


SHOT_ROOT = Path("renders/lpt2d_crystal_field_catalog_replay_20260411")
PROBE_RAYS = 400_000
MIN_BASE_MEAN_LUMA = 20.0 / 255.0

# Fine sweeps
EXPOSURE_OFFSETS = [-1.5, -1.25, -1.0, -0.75, -0.5, -0.25, 0.0, 0.25, 0.5, 0.75, 1.0, 1.25, 1.5]
GAMMA_MULTIPLIERS = [0.5, 0.6, 0.7, 0.8, 0.9, 1.0, 1.1, 1.2, 1.3, 1.4, 1.5, 1.6]


def _measure(shot: _lpt2d.Shot, session: _lpt2d.RenderSession) -> dict:
    rr = session.render_shot(shot, analyze=True)
    mov = [c for c in rr.analysis.lights if c.id.startswith("light_")]
    amb = [c for c in rr.analysis.lights if c.id.startswith("amb_")]
    return {
        "mean": float(rr.analysis.image.mean_luma),
        "mov_rad": statistics.mean([float(c.radius_ratio) for c in mov]) if mov else 0.0,
        "amb_rad": statistics.mean([float(c.radius_ratio) for c in amb]) if amb else 0.0,
    }


def _linear_fit(xs: list[float], ys: list[float]) -> tuple[float, float, float]:
    """Returns (slope, intercept, R²)."""
    n = len(xs)
    if n < 2:
        return 0.0, 0.0, 0.0
    mx = sum(xs) / n
    my = sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    syy = sum((y - my) ** 2 for y in ys)
    if sxx < 1e-12 or syy < 1e-12:
        return 0.0, my, 0.0
    slope = sxy / sxx
    intercept = my - slope * mx
    r2 = (sxy ** 2) / (sxx * syy)
    return slope, intercept, r2


def main() -> None:
    paths = sorted(SHOT_ROOT.rglob("white*.shot.json"))
    print(f"Found {len(paths)} white shot files\n")

    # Collect all ratio observations
    # For exposure: (Δexp, brightness_ratio, radius_ratio) per scene
    # For gamma: (γ_multiplier, brightness_ratio) per scene
    all_exp_brightness: dict[float, list[float]] = {o: [] for o in EXPOSURE_OFFSETS}
    all_exp_radius: dict[float, list[float]] = {o: [] for o in EXPOSURE_OFFSETS}
    all_gamma_brightness: dict[float, list[float]] = {m: [] for m in GAMMA_MULTIPLIERS}
    all_gamma_radius: dict[float, list[float]] = {m: [] for m in GAMMA_MULTIPLIERS}

    scene_data: list[dict] = []

    for pi, path in enumerate(paths):
        label = f"{path.parent.name}/{path.stem.replace('.shot', '')}"
        shot_str = str(path)

        base_shot = _lpt2d.load_shot(shot_str)
        base_exposure = base_shot.look.exposure
        base_gamma = base_shot.look.gamma

        session = _lpt2d.RenderSession(base_shot.canvas.width, base_shot.canvas.height)

        # Baseline
        base_shot.trace.rays = PROBE_RAYS
        base_m = _measure(base_shot, session)

        if base_m["mean"] < MIN_BASE_MEAN_LUMA or base_m["mov_rad"] < 0.001:
            session.close()
            print(f"  [{pi+1:2d}/{len(paths)}] {label:45s}  SKIP (mean_luma={base_m['mean']:.3f} rad={base_m['mov_rad']:.4f})")
            continue

        # Exposure sweep
        exp_rows = []
        for offset in EXPOSURE_OFFSETS:
            shot = _lpt2d.load_shot(shot_str)
            shot.trace.rays = PROBE_RAYS
            shot.look.exposure = base_exposure + offset
            m = _measure(shot, session)
            bright_ratio = m["mean"] / base_m["mean"]
            rad_ratio = m["mov_rad"] / base_m["mov_rad"] if base_m["mov_rad"] > 0 else 0
            exp_rows.append({"offset": offset, "bright_ratio": bright_ratio, "rad_ratio": rad_ratio})
            all_exp_brightness[offset].append(bright_ratio)
            if rad_ratio > 0:
                all_exp_radius[offset].append(rad_ratio)

        # Gamma sweep
        gamma_rows = []
        for mult in GAMMA_MULTIPLIERS:
            shot = _lpt2d.load_shot(shot_str)
            shot.trace.rays = PROBE_RAYS
            shot.look.gamma = base_gamma * mult
            m = _measure(shot, session)
            bright_ratio = m["mean"] / base_m["mean"]
            rad_ratio = m["mov_rad"] / base_m["mov_rad"] if base_m["mov_rad"] > 0 else 0
            gamma_rows.append({"mult": mult, "bright_ratio": bright_ratio, "rad_ratio": rad_ratio})
            all_gamma_brightness[mult].append(bright_ratio)
            if rad_ratio > 0:
                all_gamma_radius[mult].append(rad_ratio)

        session.close()
        scene_data.append({
            "label": label, "base_exposure": base_exposure, "base_gamma": base_gamma,
            "base_mean": base_m["mean"], "base_mov_rad": base_m["mov_rad"],
            "exposure_sweep": exp_rows, "gamma_sweep": gamma_rows,
        })
        print(f"  [{pi+1:2d}/{len(paths)}] {label:45s}  mean_luma={base_m['mean']:.3f}  rad={base_m['mov_rad']:.4f}")

    # ── Analysis ───────────────────────────────────────────────────
    print(f"\n\n{'=' * 100}")
    print("RELATIONSHIP 1: Δexposure → brightness ratio")
    print(f"{'=' * 100}")
    print(f"\n  {'Δexp':>6s}  {'Mean ratio':>10s}  {'Stdev':>7s}  {'Min':>7s}  {'Max':>7s}  {'CV%':>5s}  {'N':>3s}")
    print(f"  {'-' * 55}")

    exp_offsets_clean = []
    exp_bright_means = []
    for offset in EXPOSURE_OFFSETS:
        vals = all_exp_brightness[offset]
        if len(vals) < 2:
            continue
        m = statistics.mean(vals)
        s = statistics.stdev(vals)
        cv = s / m * 100 if m > 0 else 0
        exp_offsets_clean.append(offset)
        exp_bright_means.append(m)
        print(f"  {offset:+6.2f}  {m:10.4f}  {s:7.4f}  {min(vals):7.4f}  {max(vals):7.4f}  {cv:5.1f}  {len(vals):3d}")

    # Fit: log(brightness_ratio) = a * Δexposure  →  brightness_ratio = exp(a * Δexp)
    log_bright = [math.log(b) for b in exp_bright_means]
    a_bright, b_bright, r2_bright = _linear_fit(exp_offsets_clean, log_bright)
    print(f"\n  Model: brightness_ratio = exp({a_bright:.4f} * Δexposure)")
    print(f"  Equivalently: brightness_ratio ≈ {math.exp(a_bright):.4f} ^ Δexposure")
    print(f"  R² = {r2_bright:.6f}")

    # Prediction errors
    pred_errors_bright = []
    for offset, actual in zip(exp_offsets_clean, exp_bright_means):
        predicted = math.exp(a_bright * offset + b_bright)
        err = abs(predicted - actual) / actual * 100
        pred_errors_bright.append(err)
    print(f"  Mean prediction error: {statistics.mean(pred_errors_bright):.2f}%")

    print(f"\n\n{'=' * 100}")
    print("RELATIONSHIP 2: Δexposure → circle radius ratio")
    print(f"{'=' * 100}")
    print(f"\n  {'Δexp':>6s}  {'Mean ratio':>10s}  {'Stdev':>7s}  {'Min':>7s}  {'Max':>7s}  {'CV%':>5s}  {'N':>3s}")
    print(f"  {'-' * 55}")

    exp_rad_means = []
    exp_offsets_rad = []
    for offset in EXPOSURE_OFFSETS:
        vals = all_exp_radius[offset]
        if len(vals) < 2:
            continue
        m = statistics.mean(vals)
        s = statistics.stdev(vals)
        cv = s / m * 100 if m > 0 else 0
        exp_offsets_rad.append(offset)
        exp_rad_means.append(m)
        print(f"  {offset:+6.2f}  {m:10.4f}  {s:7.4f}  {min(vals):7.4f}  {max(vals):7.4f}  {cv:5.1f}  {len(vals):3d}")

    log_rad = [math.log(max(r, 1e-6)) for r in exp_rad_means]
    a_rad, b_rad, r2_rad = _linear_fit(exp_offsets_rad, log_rad)
    print(f"\n  Model: radius_ratio = exp({a_rad:.4f} * Δexposure)")
    print(f"  Equivalently: radius_ratio ≈ {math.exp(a_rad):.4f} ^ Δexposure")
    print(f"  R² = {r2_rad:.6f}")

    pred_errors_rad = []
    for offset, actual in zip(exp_offsets_rad, exp_rad_means):
        predicted = math.exp(a_rad * offset + b_rad)
        err = abs(predicted - actual) / actual * 100
        pred_errors_rad.append(err)
    print(f"  Mean prediction error: {statistics.mean(pred_errors_rad):.2f}%")

    print(f"\n\n{'=' * 100}")
    print("RELATIONSHIP 3: γ multiplier → brightness ratio")
    print(f"{'=' * 100}")
    print(f"\n  {'γ mult':>6s}  {'Mean ratio':>10s}  {'Stdev':>7s}  {'Min':>7s}  {'Max':>7s}  {'CV%':>5s}  {'N':>3s}")
    print(f"  {'-' * 55}")

    gamma_mults_clean = []
    gamma_bright_means = []
    for mult in GAMMA_MULTIPLIERS:
        vals = all_gamma_brightness[mult]
        if len(vals) < 2:
            continue
        m = statistics.mean(vals)
        s = statistics.stdev(vals)
        cv = s / m * 100 if m > 0 else 0
        gamma_mults_clean.append(mult)
        gamma_bright_means.append(m)
        print(f"  {mult:6.2f}  {m:10.4f}  {s:7.4f}  {min(vals):7.4f}  {max(vals):7.4f}  {cv:5.1f}  {len(vals):3d}")

    # Gamma: brightness scales roughly as γ^k for some k, or log(bright) = k * log(mult)
    log_gamma = [math.log(m) for m in gamma_mults_clean]
    log_gamma_bright = [math.log(b) for b in gamma_bright_means]
    k_gamma, c_gamma, r2_gamma = _linear_fit(log_gamma, log_gamma_bright)
    print(f"\n  Model: brightness_ratio = γ_multiplier ^ {k_gamma:.4f}")
    print(f"  R² = {r2_gamma:.6f}")

    pred_errors_gamma = []
    for mult, actual in zip(gamma_mults_clean, gamma_bright_means):
        predicted = math.exp(k_gamma * math.log(mult) + c_gamma)
        err = abs(predicted - actual) / actual * 100
        pred_errors_gamma.append(err)
    print(f"  Mean prediction error: {statistics.mean(pred_errors_gamma):.2f}%")

    # Confirm gamma doesn't affect circle
    print(f"\n\n{'=' * 100}")
    print("CONFIRMATION: γ multiplier → circle radius ratio (should be ~1.0)")
    print(f"{'=' * 100}")
    print(f"\n  {'γ mult':>6s}  {'Mean ratio':>10s}  {'Stdev':>7s}  {'N':>3s}")
    print(f"  {'-' * 30}")
    for mult in GAMMA_MULTIPLIERS:
        vals = all_gamma_radius[mult]
        if len(vals) < 2:
            continue
        m = statistics.mean(vals)
        s = statistics.stdev(vals)
        print(f"  {mult:6.2f}  {m:10.4f}  {s:7.4f}  {len(vals):3d}")

    # ── Prediction recipe ──────────────────────────────────────────
    print(f"\n\n{'=' * 100}")
    print("PREDICTION RECIPE")
    print(f"{'=' * 100}")
    print(f"""
  Given:
    - Circle radius ratio R (orange_rad / white_rad), e.g. 0.75
    - Brightness ratio B after boost (orange_mean / white_mean), e.g. 1.00

  Step 1: Find Δexposure to correct circle size
    We need radius_ratio = 1/R after exposure correction.
    radius_ratio = {math.exp(a_rad):.4f} ^ Δexp
    Δexp = log(1/R) / log({math.exp(a_rad):.4f}) = log(1/R) / {a_rad:.4f}

  Step 2: Predict brightness change from that exposure shift
    brightness will change by: {math.exp(a_bright):.4f} ^ Δexp

  Step 3: Find γ multiplier to correct brightness back
    Total brightness after exp: B * {math.exp(a_bright):.4f} ^ Δexp
    We want final brightness = 1.0 (match white)
    γ_mult ^ {k_gamma:.4f} = 1.0 / (B * {math.exp(a_bright):.4f} ^ Δexp)
    γ_mult = (1.0 / (B * {math.exp(a_bright):.4f} ^ Δexp)) ^ (1/{k_gamma:.4f})
""")

    # Worked examples
    print("  WORKED EXAMPLES:")
    print(f"  {'Band':14s}  {'R':>5s}  {'B':>5s}  {'Δexp':>6s}  {'γ_mult':>7s}  {'Pred bright':>11s}  {'Pred rad':>9s}")
    print(f"  {'-' * 65}")
    for band, R_typical in [("orange 550-700", 0.75), ("deep_orange", 0.50)]:
        B = 1.0  # assume luminance boost already matched
        delta_exp = math.log(1.0 / R_typical) / a_rad
        bright_after_exp = B * math.exp(a_bright * delta_exp)
        gamma_mult = (1.0 / bright_after_exp) ** (1.0 / k_gamma)
        # Predict final
        pred_bright = bright_after_exp * (gamma_mult ** k_gamma)
        pred_rad = R_typical * math.exp(a_rad * delta_exp)
        print(f"  {band:14s}  {R_typical:5.2f}  {B:5.2f}  {delta_exp:+6.2f}  {gamma_mult:7.3f}  "
              f"{pred_bright:11.4f}  {pred_rad:9.4f}")

    # ── Per-scene consistency check ────────────────────────────────
    print(f"\n\n{'=' * 100}")
    print("PER-SCENE CONSISTENCY: how well does the model predict each scene?")
    print(f"{'=' * 100}")

    per_scene_bright_slopes = []
    per_scene_rad_slopes = []
    per_scene_gamma_exps = []

    for sd in scene_data:
        # Fit per-scene exposure→brightness slope
        offsets = [r["offset"] for r in sd["exposure_sweep"]]
        log_b = [math.log(max(r["bright_ratio"], 1e-6)) for r in sd["exposure_sweep"]]
        slope_b, _, _ = _linear_fit(offsets, log_b)
        per_scene_bright_slopes.append(math.exp(slope_b))

        # Fit per-scene exposure→radius slope
        valid_rad = [(r["offset"], r["rad_ratio"]) for r in sd["exposure_sweep"] if r["rad_ratio"] > 0.01]
        if len(valid_rad) >= 3:
            offs_r = [v[0] for v in valid_rad]
            log_r = [math.log(v[1]) for v in valid_rad]
            slope_r, _, _ = _linear_fit(offs_r, log_r)
            per_scene_rad_slopes.append(math.exp(slope_r))

        # Fit per-scene gamma→brightness exponent
        mults = [r["mult"] for r in sd["gamma_sweep"]]
        log_m = [math.log(m) for m in mults]
        log_gb = [math.log(max(r["bright_ratio"], 1e-6)) for r in sd["gamma_sweep"]]
        k, _, _ = _linear_fit(log_m, log_gb)
        per_scene_gamma_exps.append(k)

    print(f"\n  Exposure → brightness base (per scene):")
    print(f"    mean={statistics.mean(per_scene_bright_slopes):.4f}  stdev={statistics.stdev(per_scene_bright_slopes):.4f}  "
          f"CV={statistics.stdev(per_scene_bright_slopes)/statistics.mean(per_scene_bright_slopes)*100:.1f}%  "
          f"range=[{min(per_scene_bright_slopes):.4f}, {max(per_scene_bright_slopes):.4f}]")

    if per_scene_rad_slopes:
        print(f"\n  Exposure → radius base (per scene):")
        print(f"    mean={statistics.mean(per_scene_rad_slopes):.4f}  stdev={statistics.stdev(per_scene_rad_slopes):.4f}  "
              f"CV={statistics.stdev(per_scene_rad_slopes)/statistics.mean(per_scene_rad_slopes)*100:.1f}%  "
              f"range=[{min(per_scene_rad_slopes):.4f}, {max(per_scene_rad_slopes):.4f}]")

    print(f"\n  Gamma → brightness exponent (per scene):")
    print(f"    mean={statistics.mean(per_scene_gamma_exps):.4f}  stdev={statistics.stdev(per_scene_gamma_exps):.4f}  "
          f"CV={statistics.stdev(per_scene_gamma_exps)/statistics.mean(per_scene_gamma_exps)*100:.1f}%  "
          f"range=[{min(per_scene_gamma_exps):.4f}, {max(per_scene_gamma_exps):.4f}]")

    # Save everything
    out = Path("renders/brightness_experiment_shots")
    out.mkdir(parents=True, exist_ok=True)
    (out / "relationship_study.json").write_text(json.dumps({
        "exposure_brightness_base": math.exp(a_bright),
        "exposure_radius_base": math.exp(a_rad),
        "gamma_brightness_exponent": k_gamma,
        "r2_exposure_brightness": r2_bright,
        "r2_exposure_radius": r2_rad,
        "r2_gamma_brightness": r2_gamma,
        "per_scene_bright_slopes": per_scene_bright_slopes,
        "per_scene_rad_slopes": per_scene_rad_slopes,
        "per_scene_gamma_exps": per_scene_gamma_exps,
        "scene_data": scene_data,
    }, indent=2))
    print(f"\nFull data in {out / 'relationship_study.json'}")


if __name__ == "__main__":
    main()
