"""Shared helpers for the spectral compensation studies.

The studies in this directory compare final-frame appearance, not raw
radiometry. Brightness is the renderer's BT.709 mean luminance on the final
RGB8 image. Circle size is the analyzer's apparent moving-light radius.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

import _lpt2d


SHOT_ROOT = Path("renders/lpt2d_crystal_field_catalog_replay_20260411")
OUT_ROOT = Path("renders/brightness_experiment_shots")
PROBE_RAYS = 400_000


@dataclass(frozen=True)
class Band:
    name: str
    wavelength_min: float
    wavelength_max: float


WHITE_BAND = Band("white", 380.0, 780.0)
STUDY_BANDS: tuple[Band, ...] = (
    Band("orange", 550.0, 700.0),
    Band("deep_orange", 570.0, 700.0),
)


@dataclass
class Measurement:
    mean: float
    median: float
    moving_radius: float
    ambient_radius: float
    moving_confidence: float
    moving_transition_width: float
    moving_peak_contrast: float
    moving_count: int
    ambient_count: int


def band_mean_luminance(wl_min: float, wl_max: float) -> float:
    total = 0.0
    n = 0
    for nm_i in range(int(wl_min), int(wl_max) + 1):
        r, g, b = _lpt2d.wavelength_to_rgb(float(nm_i))
        total += 0.2126 * r + 0.7152 * g + 0.0722 * b
        n += 1
    return total / max(n, 1)


WHITE_MEAN_LUMINANCE = band_mean_luminance(
    WHITE_BAND.wavelength_min,
    WHITE_BAND.wavelength_max,
)


def spectral_boost(band: Band) -> float:
    band_lum = band_mean_luminance(band.wavelength_min, band.wavelength_max)
    if band_lum < 1e-8:
        return 1.0
    return WHITE_MEAN_LUMINANCE / band_lum


def white_shot_paths(root: Path = SHOT_ROOT) -> list[Path]:
    return sorted(root.rglob("white*.shot.json"))


def scene_label(path: Path) -> str:
    return f"{path.parent.name}/{path.stem.replace('.shot', '')}"


def scene_size(path: Path) -> str:
    stem = path.stem
    for size in ("small", "medium", "large"):
        if size in stem:
            return size
    return "unknown"


def scene_light_count(path: Path) -> int:
    stem = path.stem
    if "2light" in stem:
        return 2
    if "1light" in stem:
        return 1
    return 0


def moving_lights(analysis) -> list:
    return [c for c in analysis.lights if c.id.startswith("light_")]


def ambient_lights(analysis) -> list:
    return [c for c in analysis.lights if c.id.startswith("amb_")]


def mean_or_zero(values: Iterable[float]) -> float:
    vals = list(values)
    return statistics.mean(vals) if vals else 0.0


def measure_result(rr: _lpt2d.RenderResult) -> Measurement:
    moving = moving_lights(rr.analysis)
    ambient = ambient_lights(rr.analysis)
    return Measurement(
        mean=float(rr.analysis.luminance.mean),
        median=float(rr.analysis.luminance.median),
        moving_radius=mean_or_zero(float(c.radius_ratio) for c in moving),
        ambient_radius=mean_or_zero(float(c.radius_ratio) for c in ambient),
        moving_confidence=mean_or_zero(float(c.confidence) for c in moving),
        moving_transition_width=mean_or_zero(float(c.transition_width_ratio) for c in moving),
        moving_peak_contrast=mean_or_zero(float(c.peak_contrast) for c in moving),
        moving_count=len(moving),
        ambient_count=len(ambient),
    )


def render_measure(shot: _lpt2d.Shot, session: _lpt2d.RenderSession) -> Measurement:
    return measure_result(session.render_shot(shot, analyze=True))


def postprocess_measure(
    session: _lpt2d.RenderSession,
    base_look: _lpt2d.Look,
    *,
    exposure_delta: float = 0.0,
    gamma_multiplier: float = 1.0,
) -> Measurement:
    pp = base_look.to_post_process()
    pp.exposure = base_look.exposure + exposure_delta
    pp.gamma = max(0.05, base_look.gamma * gamma_multiplier)
    return measure_result(session.postprocess(pp, analyze=True))


def load_probe_shot(path: Path | str, rays: int = PROBE_RAYS) -> _lpt2d.Shot:
    shot = _lpt2d.load_shot(str(path))
    shot.trace.rays = rays
    return shot


def load_band_shot(path: Path | str, band: Band, rays: int = PROBE_RAYS) -> _lpt2d.Shot:
    shot = load_probe_shot(path, rays)
    boost = spectral_boost(band)
    for light in shot.scene.lights:
        if light.id.startswith("light_"):
            light.intensity = light.intensity * boost
            light.spectrum = _lpt2d.LightSpectrum.range(
                band.wavelength_min,
                band.wavelength_max,
            )
    return shot


def ratio(value: float, reference: float) -> float:
    if reference <= 0.0:
        return 0.0
    return value / reference


def log_abs_error(ratio_value: float) -> float:
    return abs(math.log(max(ratio_value, 1e-9)))


def pct_error(ratio_value: float) -> float:
    return abs(ratio_value - 1.0) * 100.0


def percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    vals = sorted(values)
    pos = (len(vals) - 1) * q
    lo = int(math.floor(pos))
    hi = int(math.ceil(pos))
    if lo == hi:
        return vals[lo]
    frac = pos - lo
    return vals[lo] * (1.0 - frac) + vals[hi] * frac


def ratio_summary(values: list[float]) -> dict:
    vals = [v for v in values if v > 0.0 and math.isfinite(v)]
    errors = [pct_error(v) for v in vals]
    if not vals:
        return {
            "n": 0,
            "mean": 0.0,
            "median": 0.0,
            "stdev": 0.0,
            "min": 0.0,
            "max": 0.0,
            "mean_abs_pct_error": 0.0,
            "median_abs_pct_error": 0.0,
            "p90_abs_pct_error": 0.0,
            "max_abs_pct_error": 0.0,
        }
    return {
        "n": len(vals),
        "mean": statistics.mean(vals),
        "median": statistics.median(vals),
        "stdev": statistics.stdev(vals) if len(vals) > 1 else 0.0,
        "min": min(vals),
        "max": max(vals),
        "mean_abs_pct_error": statistics.mean(errors),
        "median_abs_pct_error": statistics.median(errors),
        "p90_abs_pct_error": percentile(errors, 0.90),
        "max_abs_pct_error": max(errors),
    }


def value_summary(values: list[float]) -> dict:
    vals = [v for v in values if math.isfinite(v)]
    if not vals:
        return {"n": 0, "mean": 0.0, "median": 0.0, "stdev": 0.0, "min": 0.0, "max": 0.0}
    return {
        "n": len(vals),
        "mean": statistics.mean(vals),
        "median": statistics.median(vals),
        "stdev": statistics.stdev(vals) if len(vals) > 1 else 0.0,
        "min": min(vals),
        "max": max(vals),
    }


def measurement_dict(measurement: Measurement) -> dict:
    return asdict(measurement)
