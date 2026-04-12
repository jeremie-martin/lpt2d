"""HQ renders from shot files — white vs orange vs deep orange."""

from __future__ import annotations

from pathlib import Path

import _lpt2d
from anim import save_image


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


BANDS: list[tuple[str, float, float]] = [
    ("white", 380.0, 780.0),
    ("orange", 550.0, 700.0),
    ("deep_orange", 570.0, 700.0),
]

SCENES = [
    "glass/white_medium_1light",
    "gray_diffuse/white_medium_1light",
    "black_diffuse/white_medium_1light",
    "brushed_metal/white_medium_1light",
    "colored_diffuse/white_medium_1light",
]

SHOT_ROOT = Path("renders/lpt2d_crystal_field_catalog_replay_20260411")
HQ_RAYS = 2_000_000


def main() -> None:
    out = Path("renders/brightness_experiment_shots")
    out.mkdir(parents=True, exist_ok=True)

    boosts = {name: luminance_boost(wl_min, wl_max) for name, wl_min, wl_max in BANDS}

    for scene_name in SCENES:
        shot_path = SHOT_ROOT / f"{scene_name}.shot.json"
        if not shot_path.exists():
            print(f"  SKIP {scene_name} (not found)")
            continue

        material = scene_name.split("/")[0]
        session = None

        for band_name, wl_min, wl_max in BANDS:
            shot = _lpt2d.load_shot(str(shot_path))
            shot.trace.rays = HQ_RAYS

            boost = boosts[band_name]
            for lt in shot.scene.lights:
                if lt.id.startswith("light_"):
                    lt.intensity = lt.intensity * boost
                    lt.spectrum = _lpt2d.LightSpectrum.range(wl_min, wl_max)

            if session is None:
                session = _lpt2d.RenderSession(shot.canvas.width, shot.canvas.height)

            rr = session.render_shot(shot, analyze=True)

            fname = f"{material}_{band_name}"
            save_image(str(out / f"{fname}.png"), rr.pixels, shot.canvas.width, shot.canvas.height)
            _lpt2d.save_shot(shot, str(out / f"{fname}.shot.json"))

            mean = float(rr.analysis.luminance.mean)
            mov = [c for c in rr.analysis.lights if c.id.startswith("light_")]
            mov_rad = float(mov[0].radius_ratio) if mov else 0.0
            print(f"  {material:18s} {band_name:14s}  mean={mean:6.1f}  mov_rad={mov_rad:.4f}  -> {fname}")

        if session:
            session.close()

    print(f"\nHQ renders in {out}/")


if __name__ == "__main__":
    main()
