"""Find exposure+gamma corrections that match both circle size and brightness.

Strategy:
  1. Render white baseline → get target brightness and circle size
  2. Render orange at base settings → get actual brightness and circle size
  3. Sweep exposure to find the value that matches the white circle size
  4. At that exposure, sweep gamma to find the value that matches white brightness
  5. Render the final corrected orange and compare
"""

from __future__ import annotations

import json
import statistics
from pathlib import Path

import _lpt2d
from anim import save_image


# ── Luminance-weighted boost ───────────────────────────────────────────

def _band_mean_luminance(wl_min: float, wl_max: float) -> float:
    total = 0.0
    n = 0
    for nm_i in range(int(wl_min), int(wl_max) + 1):
        r, g, b = _lpt2d.wavelength_to_rgb(float(nm_i))
        total += 0.2126 * r + 0.7152 * g + 0.0722 * b
        n += 1
    return total / max(n, 1)


_WHITE_LUM = _band_mean_luminance(380.0, 780.0)


def luminance_boost(wl_min: float, wl_max: float) -> float:
    band_lum = _band_mean_luminance(wl_min, wl_max)
    if band_lum < 1e-8:
        return 1.0
    return _WHITE_LUM / band_lum


# ── Measurement ────────────────────────────────────────────────────────

PROBE_RAYS = 400_000


def _measure(shot: _lpt2d.Shot, session: _lpt2d.RenderSession) -> dict:
    rr = session.render_shot(shot, analyze=True)
    mov = [c for c in rr.analysis.lights if c.id.startswith("light_")]
    amb = [c for c in rr.analysis.lights if c.id.startswith("amb_")]
    return {
        "mean": float(rr.analysis.luminance.mean),
        "median": float(rr.analysis.luminance.median),
        "mov_rad": statistics.mean([float(c.radius_ratio) for c in mov]) if mov else 0.0,
        "amb_rad": statistics.mean([float(c.radius_ratio) for c in amb]) if amb else 0.0,
    }


def _make_orange_shot(path: str, wl_min: float, wl_max: float, boost: float) -> _lpt2d.Shot:
    shot = _lpt2d.load_shot(path)
    shot.trace.rays = PROBE_RAYS
    for lt in shot.scene.lights:
        if lt.id.startswith("light_"):
            lt.intensity = lt.intensity * boost
            lt.spectrum = _lpt2d.LightSpectrum.range(wl_min, wl_max)
    return shot


# ── Search ─────────────────────────────────────────────────────────────

def _bisect_exposure_for_radius(
    path: str, wl_min: float, wl_max: float, boost: float,
    target_radius: float, session: _lpt2d.RenderSession,
    base_exposure: float,
) -> tuple[float, dict]:
    """Binary search for exposure offset that matches target circle radius."""
    lo, hi = -3.0, 3.0

    # Exposure increases radius, so we search for the right offset
    best_offset = 0.0
    best_m = None
    best_err = float("inf")

    for _ in range(20):  # fine binary search
        mid = (lo + hi) / 2.0
        shot = _make_orange_shot(path, wl_min, wl_max, boost)
        shot.look.exposure = base_exposure + mid
        m = _measure(shot, session)

        err = abs(m["mov_rad"] - target_radius)
        if err < best_err:
            best_err = err
            best_offset = mid
            best_m = m

        if m["mov_rad"] < target_radius:
            lo = mid  # need more exposure to grow circle
        else:
            hi = mid

    return best_offset, best_m


def _bisect_gamma_for_brightness(
    path: str, wl_min: float, wl_max: float, boost: float,
    exposure: float, target_mean: float, session: _lpt2d.RenderSession,
) -> tuple[float, dict]:
    """Binary search for gamma that matches target brightness at given exposure."""
    lo, hi = 0.4, 4.0

    best_gamma = 1.0
    best_m = None
    best_err = float("inf")

    for _ in range(20):
        mid = (lo + hi) / 2.0
        shot = _make_orange_shot(path, wl_min, wl_max, boost)
        shot.look.exposure = exposure
        shot.look.gamma = mid
        m = _measure(shot, session)

        err = abs(m["mean"] - target_mean)
        if err < best_err:
            best_err = err
            best_gamma = mid
            best_m = m

        if m["mean"] < target_mean:
            lo = mid  # need more gamma to brighten
        else:
            hi = mid

    return best_gamma, best_m


# ── Main ───────────────────────────────────────────────────────────────

SHOT_ROOT = Path("renders/lpt2d_crystal_field_catalog_replay_20260411")

SCENES = [
    "glass/white_medium_1light",
    "gray_diffuse/white_medium_1light",
    "black_diffuse/white_medium_1light",
    "brushed_metal/white_medium_1light",
    "colored_diffuse/white_medium_1light",
    "glass/white_small_1light",
    "gray_diffuse/white_small_1light",
    "black_diffuse/white_small_1light",
    "brushed_metal/white_small_1light",
    "colored_diffuse/white_small_1light",
]

BANDS = [
    ("orange", 550.0, 700.0),
    ("deep_orange", 570.0, 700.0),
]

HQ_RAYS = 2_000_000


def main() -> None:
    out = Path("renders/brightness_experiment_shots")
    out.mkdir(parents=True, exist_ok=True)

    boosts = {name: luminance_boost(wl_min, wl_max) for name, wl_min, wl_max in BANDS}
    results: list[dict] = []

    for scene_name in SCENES:
        shot_path = SHOT_ROOT / f"{scene_name}.shot.json"
        if not shot_path.exists():
            print(f"  SKIP {scene_name}")
            continue

        material = scene_name.split("/")[0]
        size = "medium" if "medium" in scene_name else "small"
        label = f"{material}/{size}"
        path_str = str(shot_path)

        session = _lpt2d.RenderSession(1920, 1080)

        # Step 1: White baseline
        white_shot = _lpt2d.load_shot(path_str)
        white_shot.trace.rays = PROBE_RAYS
        white_m = _measure(white_shot, session)
        base_exposure = white_shot.look.exposure
        base_gamma = white_shot.look.gamma

        print(f"\n{'=' * 95}")
        print(f"{label}  (exposure={base_exposure:.2f}, gamma={base_gamma:.2f})")
        print(f"  WHITE baseline: mean={white_m['mean']:.1f}  mov_rad={white_m['mov_rad']:.4f}")

        for band_name, wl_min, wl_max in BANDS:
            boost = boosts[band_name]

            # Step 2: Orange at base settings (with luminance boost only)
            orange_base = _make_orange_shot(path_str, wl_min, wl_max, boost)
            orange_base_m = _measure(orange_base, session)
            print(f"\n  {band_name} (boost={boost:.4f}):")
            print(f"    Base settings:     mean={orange_base_m['mean']:6.1f} ({orange_base_m['mean']/white_m['mean']*100:.1f}%)  "
                  f"mov_rad={orange_base_m['mov_rad']:.4f} ({orange_base_m['mov_rad']/white_m['mov_rad']*100:.1f}%)" if white_m["mov_rad"] > 0 else "")

            if white_m["mov_rad"] < 0.002:
                print(f"    White circle too small to target, skipping")
                continue

            # Step 3: Find exposure that matches white circle
            exp_offset, exp_m = _bisect_exposure_for_radius(
                path_str, wl_min, wl_max, boost,
                white_m["mov_rad"], session, base_exposure,
            )
            corrected_exposure = base_exposure + exp_offset
            print(f"    After exp adjust:  mean={exp_m['mean']:6.1f} ({exp_m['mean']/white_m['mean']*100:.1f}%)  "
                  f"mov_rad={exp_m['mov_rad']:.4f} ({exp_m['mov_rad']/white_m['mov_rad']*100:.1f}%)  "
                  f"exposure={corrected_exposure:.2f} (Δ={exp_offset:+.2f})")

            # Step 4: Find gamma that matches white brightness
            corrected_gamma, final_m = _bisect_gamma_for_brightness(
                path_str, wl_min, wl_max, boost,
                corrected_exposure, white_m["mean"], session,
            )
            print(f"    After γ correct:   mean={final_m['mean']:6.1f} ({final_m['mean']/white_m['mean']*100:.1f}%)  "
                  f"mov_rad={final_m['mov_rad']:.4f} ({final_m['mov_rad']/white_m['mov_rad']*100:.1f}%)  "
                  f"gamma={corrected_gamma:.3f} (was {base_gamma:.2f})")

            row = {
                "scene": label,
                "band": band_name,
                "base_exposure": base_exposure,
                "base_gamma": base_gamma,
                "white_mean": white_m["mean"],
                "white_mov_rad": white_m["mov_rad"],
                "orange_base_mean": orange_base_m["mean"],
                "orange_base_rad": orange_base_m["mov_rad"],
                "corrected_exposure": corrected_exposure,
                "exposure_delta": exp_offset,
                "corrected_gamma": corrected_gamma,
                "gamma_delta": corrected_gamma - base_gamma,
                "final_mean": final_m["mean"],
                "final_rad": final_m["mov_rad"],
                "brightness_error": abs(final_m["mean"] / white_m["mean"] - 1.0) * 100,
                "radius_error": abs(final_m["mov_rad"] / white_m["mov_rad"] - 1.0) * 100 if white_m["mov_rad"] > 0 else 0,
            }
            results.append(row)

            # Step 5: HQ render of white, base orange, corrected orange
            for variant, rays_override, exp_ov, gamma_ov, wlmin, wlmax, bst in [
                ("white", HQ_RAYS, base_exposure, base_gamma, 380.0, 780.0, 1.0),
                (f"{band_name}_base", HQ_RAYS, base_exposure, base_gamma, wl_min, wl_max, boost),
                (f"{band_name}_corrected", HQ_RAYS, corrected_exposure, corrected_gamma, wl_min, wl_max, boost),
            ]:
                hq_shot = _lpt2d.load_shot(path_str)
                hq_shot.trace.rays = rays_override
                hq_shot.look.exposure = exp_ov
                hq_shot.look.gamma = gamma_ov
                for lt in hq_shot.scene.lights:
                    if lt.id.startswith("light_"):
                        lt.intensity = lt.intensity * bst
                        lt.spectrum = _lpt2d.LightSpectrum.range(wlmin, wlmax)
                hq_rr = session.render_shot(hq_shot)
                fname = f"{material}_{size}_{variant}"
                save_image(str(out / f"{fname}.png"), hq_rr.pixels, 1920, 1080)
                _lpt2d.save_shot(hq_shot, str(out / f"{fname}.shot.json"))

        session.close()

    # Summary
    print(f"\n\n{'=' * 95}")
    print("SUMMARY: exposure+gamma correction to match white circle+brightness")
    print(f"{'=' * 95}")
    print(f"{'Scene':20s}  {'Band':14s}  {'Δexp':>6s}  {'Δγ':>7s}  "
          f"{'Bright err':>10s}  {'Radius err':>10s}")
    print("-" * 80)
    for r in results:
        print(f"{r['scene']:20s}  {r['band']:14s}  {r['exposure_delta']:+6.2f}  {r['gamma_delta']:+7.3f}  "
              f"{r['brightness_error']:9.1f}%  {r['radius_error']:9.1f}%")

    # Aggregate
    if results:
        print(f"\n  Mean brightness error: {statistics.mean(r['brightness_error'] for r in results):.1f}%")
        print(f"  Mean radius error:     {statistics.mean(r['radius_error'] for r in results):.1f}%")
        print(f"  Exposure Δ range:      {min(r['exposure_delta'] for r in results):+.2f} to {max(r['exposure_delta'] for r in results):+.2f}")
        print(f"  Gamma Δ range:         {min(r['gamma_delta'] for r in results):+.3f} to {max(r['gamma_delta'] for r in results):+.3f}")

    (out / "circle_brightness_matching.json").write_text(json.dumps(results, indent=2))
    print(f"\nResults + HQ renders in {out}/")


if __name__ == "__main__":
    main()
