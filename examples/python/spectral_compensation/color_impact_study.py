"""Measure the impact of spectral band on brightness and circle size.

For each of the 30 white catalog shots, recolors the moving light to orange
and deep orange (with luminance-weighted boost), then measures brightness
and circle radius relative to white.

This produces the key input numbers (R, B) that feed into the correction
recipe from the relationship study.
"""

from __future__ import annotations

import json
import statistics
from pathlib import Path

import _lpt2d


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


# ── Config ─────────────────────────────────────────────────────────────

SHOT_ROOT = Path("renders/lpt2d_crystal_field_catalog_replay_20260411")
PROBE_RAYS = 400_000

BANDS: list[tuple[str, float, float]] = [
    ("orange", 550.0, 700.0),
    ("deep_orange", 570.0, 700.0),
]


def _measure(shot: _lpt2d.Shot, session: _lpt2d.RenderSession) -> dict:
    rr = session.render_shot(shot, analyze=True)
    mov = [c for c in rr.analysis.lights if c.id.startswith("light_")]
    amb = [c for c in rr.analysis.lights if c.id.startswith("amb_")]
    return {
        "mean": float(rr.analysis.luminance.mean),
        "mov_rad": statistics.mean([float(c.radius_ratio) for c in mov]) if mov else 0.0,
        "amb_rad": statistics.mean([float(c.radius_ratio) for c in amb]) if amb else 0.0,
    }


def main() -> None:
    paths = sorted(SHOT_ROOT.rglob("white*.shot.json"))
    print(f"Found {len(paths)} white shot files\n")

    boosts = {name: luminance_boost(wl_min, wl_max) for name, wl_min, wl_max in BANDS}
    for name, wl_min, wl_max in BANDS:
        print(f"  {name:14s}  {wl_min:.0f}–{wl_max:.0f}nm  boost={boosts[name]:.4f}")
    print()

    all_results: list[dict] = []

    for pi, path in enumerate(paths):
        label = f"{path.parent.name}/{path.stem.replace('.shot', '')}"
        material = path.parent.name
        path_str = str(path)

        session = _lpt2d.RenderSession(1920, 1080)

        # White baseline
        white_shot = _lpt2d.load_shot(path_str)
        white_shot.trace.rays = PROBE_RAYS
        white_m = _measure(white_shot, session)

        row: dict = {
            "scene": label,
            "material": material,
            "white_mean": round(white_m["mean"], 1),
            "white_mov_rad": round(white_m["mov_rad"], 4),
        }

        parts = [f"  [{pi+1:2d}] {label:45s}  wh={white_m['mean']:6.1f} rad={white_m['mov_rad']:.4f}"]

        for band_name, wl_min, wl_max in BANDS:
            boost = boosts[band_name]
            shot = _lpt2d.load_shot(path_str)
            shot.trace.rays = PROBE_RAYS
            for lt in shot.scene.lights:
                if lt.id.startswith("light_"):
                    lt.intensity = lt.intensity * boost
                    lt.spectrum = _lpt2d.LightSpectrum.range(wl_min, wl_max)
            m = _measure(shot, session)

            b_ratio = m["mean"] / white_m["mean"] if white_m["mean"] > 0 else 0
            r_ratio = m["mov_rad"] / white_m["mov_rad"] if white_m["mov_rad"] > 0 else 0

            row[f"{band_name}_mean"] = round(m["mean"], 1)
            row[f"{band_name}_brightness_ratio"] = round(b_ratio, 4)
            row[f"{band_name}_mov_rad"] = round(m["mov_rad"], 4)
            row[f"{band_name}_radius_ratio"] = round(r_ratio, 4)

            parts.append(f"  {band_name}: B={b_ratio:.3f} R={r_ratio:.3f}")

        session.close()
        all_results.append(row)
        print("".join(parts))

    # ── Aggregate ──────────────────────────────────────────────────
    print(f"\n\n{'=' * 90}")
    print("AGGREGATE: color impact on brightness (B) and circle radius (R)")
    print(f"{'=' * 90}")

    for band_name, wl_min, wl_max in BANDS:
        b_vals = [r[f"{band_name}_brightness_ratio"] for r in all_results]
        r_vals = [r[f"{band_name}_radius_ratio"] for r in all_results if r[f"{band_name}_radius_ratio"] > 0]

        print(f"\n  {band_name} ({wl_min:.0f}–{wl_max:.0f}nm, boost={boosts[band_name]:.4f}):")
        print(f"    Brightness ratio B:  mean={statistics.mean(b_vals):.4f}  "
              f"median={statistics.median(b_vals):.4f}  "
              f"stdev={statistics.stdev(b_vals):.4f}  "
              f"range=[{min(b_vals):.4f}, {max(b_vals):.4f}]")
        print(f"    Circle radius ratio R: mean={statistics.mean(r_vals):.4f}  "
              f"median={statistics.median(r_vals):.4f}  "
              f"stdev={statistics.stdev(r_vals):.4f}  "
              f"range=[{min(r_vals):.4f}, {max(r_vals):.4f}]")

    # Per-material
    print(f"\n{'-' * 90}")
    print("PER-MATERIAL BREAKDOWN")
    print(f"{'-' * 90}")

    materials = sorted(set(r["material"] for r in all_results))
    for mat in materials:
        mat_rows = [r for r in all_results if r["material"] == mat]
        print(f"\n  {mat} ({len(mat_rows)} scenes):")
        for band_name, _, _ in BANDS:
            b = [r[f"{band_name}_brightness_ratio"] for r in mat_rows]
            r = [r[f"{band_name}_radius_ratio"] for r in mat_rows if r[f"{band_name}_radius_ratio"] > 0]
            b_str = f"B={statistics.mean(b):.3f} ±{statistics.stdev(b):.3f}" if len(b) > 1 else f"B={b[0]:.3f}"
            r_str = f"R={statistics.mean(r):.3f} ±{statistics.stdev(r):.3f}" if len(r) > 1 else f"R={r[0]:.3f}" if r else "R=N/A"
            print(f"    {band_name:14s}  {b_str}  {r_str}")

    # Save
    out = Path("renders/brightness_experiment_shots")
    out.mkdir(parents=True, exist_ok=True)
    (out / "color_impact_study.json").write_text(json.dumps(all_results, indent=2))
    print(f"\nFull data in {out / 'color_impact_study.json'}")


if __name__ == "__main__":
    main()
