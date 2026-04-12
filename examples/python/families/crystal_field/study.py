"""Measured probe datasets for crystal_field sampler tuning.

This command samples normal free-form crystal_field scenes, renders only the
same low-resolution probe used by ``check.py``, and stores one JSONL row per
measured sample.  It deliberately does not write final PNGs or authored shot
JSONs: the purpose is parameter/filter analysis, not visual catalog output.

Run::

    python -m examples.python.families.crystal_field study measure \
      --out renders/families/crystal_field/studies/measured_1000.jsonl \
      --n 1000 --seed 0

    python -m examples.python.families.crystal_field study analyze \
      --in renders/families/crystal_field/studies/measured_1000.jsonl \
      --out renders/families/crystal_field/studies/measured_1000_analysis
"""

from __future__ import annotations

import argparse
import bisect
import csv
import gzip
import importlib
import json
import math
import os
import random
import subprocess
import sys
import time
from collections import Counter, defaultdict
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .check import (
    PROBE_FPS,
    PROBE_H,
    PROBE_RAYS,
    PROBE_W,
    _measure_and_verdict,
)
from .grid import build_grid, remove_holes
from .params import LightSpectrumConfig, Params
from .sampling import sample
from .scene import build, rendered_light_intensity

SCHEMA_VERSION = 2
RECORD_KIND = "measured_probe"
CHECK_MODULE = importlib.import_module(f"{__package__}.check")

THRESHOLD_NAMES = (
    "MIN_MOVING_RADIUS_RATIO",
    "MAX_MOVING_RADIUS_RATIO",
    "MIN_AMBIENT_RADIUS_RATIO",
    "MAX_AMBIENT_RADIUS_RATIO",
    "MIN_RADIUS_RATIO",
    "MAX_RADIUS_RATIO",
    "MAX_NEAR_BLACK_FRACTION",
    "MIN_MEAN_LUMA",
    "MAX_MEAN_LUMA",
    "GLASS_MAX_MEAN_LUMA",
    "MIN_P05_LUMA",
    "MAX_P05_LUMA",
    "MIN_INTERDECILE_LUMA_RANGE",
    "MIN_LOCAL_CONTRAST",
    "MAX_BRIGHT_NEUTRAL_FRACTION",
    "MAX_MEAN_SATURATION",
)

CONDITIONAL_BIN_GROUPS = (
    "tags.outcome",
    "tags.material_subtype",
    "tags.material_color_mode",
    "tags.n_lights",
    "tags.moving_spectrum",
    "tags.ambient_spectrum",
    "tags.ambient_style",
)

INTERACTION_FEATURES = (
    # Sampled inputs that are most likely to interact with probe outcomes.
    "look_exposure",
    "look_white_point",
    "look_gamma",
    "look_contrast",
    "look_saturation",
    "look_highlights",
    "look_shadows",
    "ambient_intensity",
    "moving_intensity",
    "ambient_rendered_intensity",
    "moving_rendered_intensity",
    "ambient_to_moving_rendered_intensity",
    "ambient_white_mix",
    "ambient_rgb_luminance",
    "moving_rgb_luminance",
    "shape_size",
    "object_count",
    "grid_spacing",
    "light_speed",
)

SPECTRUM_METRIC_FEATURES = (
    "metric_mean_luma",
    "metric_median_luma",
    "metric_p10_luma",
    "metric_p90_luma",
    "metric_interdecile_luma_range",
    "metric_local_contrast",
    "metric_bright_neutral_fraction",
    "metric_near_black_fraction",
    "metric_near_white_fraction",
    "metric_mean_saturation",
    "metric_colorfulness",
    "metric_colored_fraction",
    "metric_moving_radius_mean",
    "metric_ambient_radius_mean",
    "metric_moving_to_ambient_radius_ratio",
)


# ---------------------------------------------------------------------------
# Feature extraction
# ---------------------------------------------------------------------------


def _spectrum_is_colored(spectrum: LightSpectrumConfig) -> bool:
    if spectrum.type == "range":
        return spectrum.wavelength_max - spectrum.wavelength_min < 300.0
    rgb = spectrum.linear_rgb
    effective = [channel + (1.0 - channel) * spectrum.white_mix for channel in rgb]
    return max(effective) - min(effective) > 1e-5 or min(effective) < 1.0 - 1e-5


def _spectrum_label(spectrum: LightSpectrumConfig) -> str:
    if spectrum.type == "range":
        width = spectrum.wavelength_max - spectrum.wavelength_min
        if width >= 300.0:
            return "white_range"
        return f"range_{spectrum.wavelength_min:.0f}_{spectrum.wavelength_max:.0f}"
    if _spectrum_is_colored(spectrum):
        return "rgb_color"
    return "white_color"


def _effective_rgb(spectrum: LightSpectrumConfig) -> list[float]:
    if spectrum.type != "color":
        return [1.0, 1.0, 1.0]
    return [
        channel + (1.0 - channel) * spectrum.white_mix
        for channel in spectrum.linear_rgb
    ]


def _linear_luminance(rgb: list[float]) -> float:
    return 0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2]


def _object_count(p: Params) -> int:
    rng = random.Random(p.build_seed)
    positions = build_grid(p.grid)
    if p.grid.hole_fraction > 0:
        positions = remove_holes(positions, p.grid.hole_fraction, rng)
    return len(positions)


def _material_subtype(p: Params) -> str:
    if p.material.outcome != "brushed_metal":
        return p.material.outcome
    color_names = p.material.color_names
    if not color_names:
        return "brushed_metal/no_color"
    if len(color_names) == 1:
        return "brushed_metal/one_color"
    if None in color_names:
        return "brushed_metal/mixed"
    return "brushed_metal/two_colors"


def _material_color_count(p: Params) -> int:
    return sum(1 for name in p.material.color_names if name is not None)


def _material_color_mode(p: Params) -> str:
    color_names = p.material.color_names
    if not color_names:
        return "none"
    color_count = _material_color_count(p)
    if color_count == 0:
        return "none"
    if color_count == 1 and None not in color_names:
        return "one"
    if None in color_names:
        return "mixed"
    return "two"


def _flat_features(p: Params) -> dict[str, Any]:
    moving_rgb = _effective_rgb(p.light.spectrum)
    ambient_rgb = _effective_rgb(p.light.ambient.spectrum)
    moving_rendered_intensity = rendered_light_intensity(
        p.light.moving_intensity,
        p.light.spectrum,
    )
    ambient_rendered_intensity = rendered_light_intensity(
        p.light.ambient.intensity,
        p.light.ambient.spectrum,
    )
    ambient_to_moving_rendered_intensity = (
        ambient_rendered_intensity / moving_rendered_intensity
        if moving_rendered_intensity > 0
        else 0.0
    )
    rotation = p.shape.rotation

    features: dict[str, Any] = {
        "outcome": p.material.outcome,
        "material_subtype": _material_subtype(p),
        "material_color_mode": _material_color_mode(p),
        "build_seed": p.build_seed,
        "object_count": _object_count(p),
        "grid_rows": p.grid.rows,
        "grid_cols": p.grid.cols,
        "grid_spacing": p.grid.spacing,
        "grid_offset_rows": p.grid.offset_rows,
        "grid_hole_fraction": p.grid.hole_fraction,
        "shape_kind": p.shape.kind,
        "shape_size": p.shape.size,
        "shape_n_sides": p.shape.n_sides,
        "shape_corner_radius": p.shape.corner_radius,
        "shape_has_rotation": rotation is not None,
        "shape_rotation_base": rotation.base_angle if rotation is not None else 0.0,
        "shape_rotation_jitter": rotation.jitter if rotation is not None else 0.0,
        "material_albedo": p.material.albedo,
        "material_fill": p.material.fill,
        "material_ior": p.material.ior,
        "material_cauchy_b": p.material.cauchy_b,
        "material_absorption": p.material.absorption,
        "material_color_count": _material_color_count(p),
        "material_wall_metallic": p.material.wall_metallic,
        "light_n_lights": p.light.n_lights,
        "light_path_style": p.light.path_style,
        "light_n_waypoints": p.light.n_waypoints,
        "light_speed": p.light.speed,
        "moving_intensity": p.light.moving_intensity,
        "moving_rendered_intensity": moving_rendered_intensity,
        "moving_spectrum_type": p.light.spectrum.type,
        "moving_spectrum_label": _spectrum_label(p.light.spectrum),
        "moving_wavelength_min": p.light.spectrum.wavelength_min,
        "moving_wavelength_max": p.light.spectrum.wavelength_max,
        "moving_wavelength_width": (
            p.light.spectrum.wavelength_max - p.light.spectrum.wavelength_min
        ),
        "moving_is_colored": _spectrum_is_colored(p.light.spectrum),
        "moving_rgb_r": moving_rgb[0],
        "moving_rgb_g": moving_rgb[1],
        "moving_rgb_b": moving_rgb[2],
        "moving_rgb_luminance": _linear_luminance(moving_rgb),
        "ambient_style": p.light.ambient.style,
        "ambient_intensity": p.light.ambient.intensity,
        "ambient_rendered_intensity": ambient_rendered_intensity,
        "ambient_to_moving_rendered_intensity": ambient_to_moving_rendered_intensity,
        "ambient_spectrum_type": p.light.ambient.spectrum.type,
        "ambient_spectrum_label": _spectrum_label(p.light.ambient.spectrum),
        "ambient_wavelength_min": p.light.ambient.spectrum.wavelength_min,
        "ambient_wavelength_max": p.light.ambient.spectrum.wavelength_max,
        "ambient_wavelength_width": (
            p.light.ambient.spectrum.wavelength_max
            - p.light.ambient.spectrum.wavelength_min
        ),
        "ambient_is_colored": _spectrum_is_colored(p.light.ambient.spectrum),
        "ambient_rgb_r": ambient_rgb[0],
        "ambient_rgb_g": ambient_rgb[1],
        "ambient_rgb_b": ambient_rgb[2],
        "ambient_rgb_luminance": _linear_luminance(ambient_rgb),
        "ambient_white_mix": p.light.ambient.spectrum.white_mix,
        "look_exposure": p.look.exposure,
        "look_gamma": p.look.gamma,
        "look_contrast": p.look.contrast,
        "look_white_point": p.look.white_point,
        "look_saturation": p.look.saturation,
        "look_temperature": p.look.temperature,
        "look_highlights": p.look.highlights,
        "look_shadows": p.look.shadows,
        "look_vignette": p.look.vignette,
        "look_vignette_radius": p.look.vignette_radius,
        "look_chromatic_aberration": p.look.chromatic_aberration,
    }
    return features


def _tags(p: Params) -> dict[str, Any]:
    return {
        "outcome": p.material.outcome,
        "material_subtype": _material_subtype(p),
        "material_color_mode": _material_color_mode(p),
        "shape_kind": p.shape.kind,
        "n_lights": p.light.n_lights,
        "path_style": p.light.path_style,
        "moving_spectrum": _spectrum_label(p.light.spectrum),
        "ambient_spectrum": _spectrum_label(p.light.ambient.spectrum),
        "ambient_style": p.light.ambient.style,
    }


def _verdict_reason(ok: bool, summary: str) -> str:
    if ok:
        return "ok"
    text = summary.lower()
    if "no moving lights" in text:
        return "no_moving_lights"
    if "no ambient lights" in text:
        return "no_ambient_lights"
    if "moving_radius_min" in text:
        return "moving_radius_min"
    if "moving_radius_max" in text:
        return "moving_radius_max"
    if "ambient_radius_min" in text:
        return "ambient_radius_min"
    if "ambient_radius_max" in text:
        return "ambient_radius_max"
    if "moving_to_ambient_radius_ratio" in text:
        return "moving_to_ambient_radius_ratio"
    if "near_black" in text:
        return "near_black_fraction"
    if "mean_luma" in text and "too dark" in text:
        return "mean_luma_low"
    if "mean_luma" in text and "too bright" in text:
        return "mean_luma_high"
    if "p05_luma" in text:
        return "p05_luma"
    if "interdecile_luma_range" in text:
        return "interdecile_luma_range"
    if "local_contrast" in text:
        return "local_contrast"
    if "bright_neutral" in text:
        return "bright_neutral_fraction"
    if "saturation" in text:
        return "mean_saturation"
    return "other"


def _measured_record(
    *,
    seed: int,
    trial: int,
    p: Params,
    result,
    elapsed_ms: float,
) -> dict[str, Any]:
    return {
        "schema": SCHEMA_VERSION,
        "record": RECORD_KIND,
        "family": "crystal_field",
        "seed": seed,
        "trial": trial,
        "status": "accepted" if result.verdict.ok else "rejected",
        "tags": _tags(p),
        "features": _flat_features(p),
        "metrics": dict(sorted(result.metrics.items())),
        "verdict": {
            "ok": bool(result.verdict.ok),
            "reason": _verdict_reason(result.verdict.ok, result.verdict.summary),
            "summary": result.verdict.summary,
        },
        "probe": {
            "width": PROBE_W,
            "height": PROBE_H,
            "rays": PROBE_RAYS,
            "fps": PROBE_FPS,
            "analysis_frame": result.analysis_frame,
            "analysis_time": result.analysis_time,
        },
        "measurement_ms": elapsed_ms,
        "params": asdict(p),
    }


def _error_record(
    *,
    seed: int,
    trial: int,
    p: Params | None,
    exc: BaseException,
    elapsed_ms: float,
) -> dict[str, Any]:
    return {
        "schema": SCHEMA_VERSION,
        "record": RECORD_KIND,
        "family": "crystal_field",
        "seed": seed,
        "trial": trial,
        "status": "error",
        "tags": _tags(p) if p is not None else {},
        "features": _flat_features(p) if p is not None else {},
        "metrics": {},
        "verdict": {
            "ok": False,
            "reason": "error",
            "summary": f"{type(exc).__name__}: {exc}",
        },
        "probe": {
            "width": PROBE_W,
            "height": PROBE_H,
            "rays": PROBE_RAYS,
            "fps": PROBE_FPS,
        },
        "measurement_ms": elapsed_ms,
        "params": asdict(p) if p is not None else None,
    }


# ---------------------------------------------------------------------------
# JSONL IO
# ---------------------------------------------------------------------------


def _read_json_line(raw: bytes, *, path: Path, line_no: int) -> dict[str, Any]:
    try:
        obj = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path}:{line_no}: invalid JSONL row") from exc
    if not isinstance(obj, dict):
        raise ValueError(f"{path}:{line_no}: JSONL row is not an object")
    return obj


def _scan_jsonl(path: Path, *, repair: bool = False) -> tuple[int, int]:
    """Return ``(valid_rows, next_trial)`` and optionally truncate partial tail.

    Plain JSONL is used for measured datasets specifically because this kind
    of repair is possible after Ctrl-C, SIGTERM, or a hard kill during write.
    """
    if not path.exists():
        return 0, 0

    if path.suffix == ".gz":
        count = 0
        max_trial = -1
        for obj in _iter_jsonl(path):
            count += 1
            if isinstance(obj.get("trial"), int):
                max_trial = max(max_trial, obj["trial"])
        return count, max_trial + 1

    offset = 0
    count = 0
    max_trial = -1
    with path.open("rb") as fh:
        line_no = 0
        while True:
            raw = fh.readline()
            if not raw:
                break
            line_no += 1
            next_offset = fh.tell()
            if not raw.strip():
                offset = next_offset
                continue
            try:
                obj = _read_json_line(raw, path=path, line_no=line_no)
            except ValueError:
                if repair:
                    with path.open("ab") as repair_fh:
                        repair_fh.truncate(offset)
                    return count, max_trial + 1
                raise
            count += 1
            if isinstance(obj.get("trial"), int):
                max_trial = max(max_trial, obj["trial"])
            offset = next_offset
    return count, max_trial + 1


def _iter_jsonl(path: Path) -> Iterator[dict[str, Any]]:
    if path.suffix == ".gz":
        with gzip.open(path, "rt", encoding="utf-8") as fh:
            for line_no, line in enumerate(fh, start=1):
                if line.strip():
                    obj = json.loads(line)
                    if not isinstance(obj, dict):
                        raise ValueError(f"{path}:{line_no}: JSONL row is not an object")
                    yield obj
        return

    with path.open("rb") as fh:
        for line_no, raw in enumerate(fh, start=1):
            if raw.strip():
                yield _read_json_line(raw, path=path, line_no=line_no)


def _write_jsonl_record(fh, record: Mapping[str, Any], *, fsync: bool) -> None:
    fh.write(json.dumps(record, sort_keys=True, separators=(",", ":")))
    fh.write("\n")
    fh.flush()
    if fsync:
        os.fsync(fh.fileno())


def _metadata_path(out: Path) -> Path:
    if out.suffix == ".jsonl":
        return out.with_suffix(".meta.json")
    return out.with_name(f"{out.name}.meta.json")


def _git_revision() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            check=False,
            cwd=Path(__file__).resolve().parents[4],
            capture_output=True,
            text=True,
        )
    except OSError:
        return "unknown"
    revision = result.stdout.strip()
    return revision if result.returncode == 0 and revision else "unknown"


def _threshold_snapshot() -> dict[str, float]:
    return {name: float(getattr(CHECK_MODULE, name)) for name in THRESHOLD_NAMES}


def _feature_keys_for_seed(seed: int) -> list[str]:
    return sorted(_flat_features(sample(random.Random(f"{seed}:0"))).keys())


def _write_metadata(
    out: Path,
    *,
    seed: int,
    target_rows: int,
    completed_rows: int,
    next_trial: int,
    status: str,
) -> None:
    metadata = {
        "schema": SCHEMA_VERSION,
        "record": "measured_probe_metadata",
        "family": "crystal_field",
        "dataset": str(out),
        "status": status,
        "seed": seed,
        "target_rows": target_rows,
        "completed_rows": completed_rows,
        "next_trial": next_trial,
        "interruption_safe": (
            "Records are newline-delimited JSON. The measure command repairs a "
            "partial final line on resume/analyze."
        ),
        "record_contents": [
            "full Params dataclass as params",
            "flat sampler/render features",
            "probe metrics from core FrameAnalysis",
            "verdict ok/reason/summary",
            "selected analysis frame/time",
            "measurement duration",
            "seed and deterministic per-trial index",
        ],
        "command": sys.argv,
        "git_revision": _git_revision(),
        "probe": {
            "width": PROBE_W,
            "height": PROBE_H,
            "rays": PROBE_RAYS,
            "fps": PROBE_FPS,
        },
        "thresholds": _threshold_snapshot(),
        "feature_keys": _feature_keys_for_seed(seed),
        "updated_unix": time.time(),
    }
    path = _metadata_path(out)
    tmp = path.with_name(f"{path.name}.tmp")
    tmp.write_text(json.dumps(metadata, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


# ---------------------------------------------------------------------------
# Measurement command
# ---------------------------------------------------------------------------


def _measure_one(seed: int, trial: int) -> dict[str, Any]:
    rng = random.Random(f"{seed}:{trial}")
    p = sample(rng)
    start = time.monotonic()
    animate = build(p)
    result = _measure_and_verdict(p, animate)
    elapsed_ms = (time.monotonic() - start) * 1000.0
    return _measured_record(seed=seed, trial=trial, p=p, result=result, elapsed_ms=elapsed_ms)


def run_measure(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Generate measured crystal_field probe JSONL")
    parser.add_argument("--out", required=True, help="Plain .jsonl output path")
    parser.add_argument("-n", "--n", type=int, default=1000, help="Total target rows")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Delete an existing output file before measuring",
    )
    parser.add_argument(
        "--no-resume",
        dest="resume",
        action="store_false",
        help="Fail instead of resuming when the output already exists",
    )
    parser.add_argument("--progress-every", type=int, default=10)
    parser.add_argument("--fsync-every", type=int, default=1)
    parser.add_argument(
        "--stop-on-error",
        action="store_true",
        help="Abort on the first sample/build/render exception",
    )
    parser.set_defaults(resume=True)
    args = parser.parse_args(argv)

    out = Path(args.out)
    if out.suffix == ".gz":
        parser.error("Measured datasets must be plain .jsonl for interruption-safe resume")
    if args.n < 0:
        parser.error("--n must be non-negative")

    out.parent.mkdir(parents=True, exist_ok=True)
    if args.overwrite and out.exists():
        out.unlink()

    if out.exists() and not args.resume:
        raise SystemExit(f"{out} exists; use --overwrite or omit --no-resume")

    existing_rows, next_trial = _scan_jsonl(out, repair=True)
    if next_trial >= args.n:
        print(f"{out}: already has {existing_rows} rows through trial {next_trial - 1}")
        return

    print(
        f"Writing measured probe dataset: {out} "
        f"(seed={args.seed}, rows {next_trial}..{args.n - 1})"
    )
    print(
        f"Probe: {PROBE_W}x{PROBE_H}, rays={PROBE_RAYS}, fps={PROBE_FPS}; "
        "no final renders will be written"
    )
    _write_metadata(
        out,
        seed=args.seed,
        target_rows=args.n,
        completed_rows=existing_rows,
        next_trial=next_trial,
        status="running",
    )

    counts: Counter[str] = Counter()
    started = time.monotonic()
    with out.open("a", encoding="utf-8") as fh:
        try:
            for trial in range(next_trial, args.n):
                p: Params | None = None
                start = time.monotonic()
                try:
                    rng = random.Random(f"{args.seed}:{trial}")
                    p = sample(rng)
                    animate = build(p)
                    result = _measure_and_verdict(p, animate)
                    elapsed_ms = (time.monotonic() - start) * 1000.0
                    record = _measured_record(
                        seed=args.seed,
                        trial=trial,
                        p=p,
                        result=result,
                        elapsed_ms=elapsed_ms,
                    )
                except Exception as exc:
                    elapsed_ms = (time.monotonic() - start) * 1000.0
                    if args.stop_on_error:
                        raise
                    record = _error_record(
                        seed=args.seed,
                        trial=trial,
                        p=p,
                        exc=exc,
                        elapsed_ms=elapsed_ms,
                    )

                status = str(record["status"])
                counts[status] += 1
                fsync_now = args.fsync_every > 0 and (trial + 1) % args.fsync_every == 0
                _write_jsonl_record(fh, record, fsync=fsync_now)

                done = trial + 1
                if args.progress_every > 0 and (
                    done == args.n or (done - next_trial) % args.progress_every == 0
                ):
                    _write_metadata(
                        out,
                        seed=args.seed,
                        target_rows=args.n,
                        completed_rows=done,
                        next_trial=done,
                        status="running",
                    )
                    elapsed = time.monotonic() - started
                    rate = (done - next_trial) / elapsed if elapsed > 0 else 0.0
                    accepted = counts["accepted"]
                    rejected = counts["rejected"]
                    errors = counts["error"]
                    print(
                        f"  {done}/{args.n} rows "
                        f"accepted={accepted} rejected={rejected} errors={errors} "
                        f"rate={rate:.2f}/s",
                        flush=True,
                    )
        except KeyboardInterrupt:
            rows, next_resume_trial = _scan_jsonl(out, repair=True)
            _write_metadata(
                out,
                seed=args.seed,
                target_rows=args.n,
                completed_rows=rows,
                next_trial=next_resume_trial,
                status="interrupted",
            )
            print(f"\nInterrupted. Dataset is usable and resumable: {out}", flush=True)
            raise SystemExit(130) from None

    rows, next_resume_trial = _scan_jsonl(out, repair=True)
    _write_metadata(
        out,
        seed=args.seed,
        target_rows=args.n,
        completed_rows=rows,
        next_trial=next_resume_trial,
        status="complete",
    )
    print(f"Done: {out}")


# ---------------------------------------------------------------------------
# Analysis command
# ---------------------------------------------------------------------------


def _percentile(sorted_values: list[float], q: float) -> float:
    if not sorted_values:
        return float("nan")
    if len(sorted_values) == 1:
        return sorted_values[0]
    pos = (len(sorted_values) - 1) * q
    low = math.floor(pos)
    high = math.ceil(pos)
    if low == high:
        return sorted_values[low]
    weight = pos - low
    return sorted_values[low] * (1.0 - weight) + sorted_values[high] * weight


def _numeric_stats(values: list[float]) -> dict[str, float | int]:
    values = [v for v in values if math.isfinite(v)]
    values.sort()
    if not values:
        return {
            "count": 0,
            "mean": float("nan"),
            "min": float("nan"),
            "p10": float("nan"),
            "p25": float("nan"),
            "median": float("nan"),
            "p75": float("nan"),
            "p90": float("nan"),
            "max": float("nan"),
        }
    return {
        "count": len(values),
        "mean": sum(values) / len(values),
        "min": values[0],
        "p10": _percentile(values, 0.10),
        "p25": _percentile(values, 0.25),
        "median": _percentile(values, 0.50),
        "p75": _percentile(values, 0.75),
        "p90": _percentile(values, 0.90),
        "max": values[-1],
    }


def _as_number(value: Any) -> float | None:
    if type(value) not in (int, float):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _group_value(record: Mapping[str, Any], key: str) -> str:
    current: Any = record
    for part in key.split("."):
        if not isinstance(current, Mapping) or part not in current:
            return "<missing>"
        current = current[part]
    return str(current)


def _pass_rate(counter: Counter[str]) -> float:
    total = counter["accepted"] + counter["rejected"]
    return counter["accepted"] / total if total else 0.0


def _write_csv(path: Path, rows: Iterable[Mapping[str, Any]], fieldnames: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _feature_stat_rows(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    buckets: dict[tuple[str, str], list[float]] = defaultdict(list)
    outcome_buckets: dict[tuple[str, str, str], list[float]] = defaultdict(list)

    for record in records:
        status = str(record.get("status", "unknown"))
        cohort = "accepted" if status == "accepted" else "not_accepted"
        outcome = str(record.get("tags", {}).get("outcome", "<missing>"))
        values = dict(record.get("features", {}))
        values.update({f"metric_{k}": v for k, v in record.get("metrics", {}).items()})

        for name, value in values.items():
            number = _as_number(value)
            if number is None:
                continue
            buckets[(name, "all")].append(number)
            buckets[(name, cohort)].append(number)
            outcome_buckets[(outcome, name, "all")].append(number)
            outcome_buckets[(outcome, name, cohort)].append(number)

    rows: list[dict[str, Any]] = []
    for (feature, cohort), values in sorted(buckets.items()):
        rows.append({"scope": "all", "outcome": "", "feature": feature, "cohort": cohort, **_numeric_stats(values)})
    for (outcome, feature, cohort), values in sorted(outcome_buckets.items()):
        rows.append(
            {
                "scope": "outcome",
                "outcome": outcome,
                "feature": feature,
                "cohort": cohort,
                **_numeric_stats(values),
            }
        )
    return rows


def _spectrum_metric_stat_rows(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    group_keys = ("tags.moving_spectrum", "tags.ambient_spectrum")
    buckets: dict[tuple[str, str, str, str], list[float]] = defaultdict(list)

    for record in records:
        status = str(record.get("status", "unknown"))
        cohort = "accepted" if status == "accepted" else "not_accepted"
        values = _numeric_feature_source(record)
        for group in group_keys:
            value = _group_value(record, group)
            for feature in SPECTRUM_METRIC_FEATURES:
                number = _as_number(values.get(feature))
                if number is None:
                    continue
                buckets[(group, value, feature, "all")].append(number)
                buckets[(group, value, feature, cohort)].append(number)

    rows: list[dict[str, Any]] = []
    for (group, value, feature, cohort), values in sorted(buckets.items()):
        rows.append(
            {
                "group": group,
                "value": value,
                "feature": feature,
                "cohort": cohort,
                **_numeric_stats(values),
            }
        )
    return rows


def _reason_group_rows(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    group_keys = [
        "tags.outcome",
        "tags.material_subtype",
        "tags.n_lights",
        "tags.moving_spectrum",
        "tags.ambient_spectrum",
    ]
    counters: dict[tuple[str, str], Counter[str]] = defaultdict(Counter)
    totals: Counter[tuple[str, str]] = Counter()

    for record in records:
        if record.get("status") == "accepted":
            continue
        verdict = record.get("verdict", {})
        reason = str(verdict.get("reason", "<missing>"))
        for key in group_keys:
            value = _group_value(record, key)
            counters[(key, value)][reason] += 1
            totals[(key, value)] += 1

    rows: list[dict[str, Any]] = []
    for (group, value), counter in sorted(counters.items()):
        total = totals[(group, value)]
        for reason, count in counter.most_common():
            rows.append(
                {
                    "group": group,
                    "value": value,
                    "reason": reason,
                    "count": count,
                    "share": count / total if total else 0.0,
                }
            )
    return rows


def _numeric_values_by_feature(records: list[dict[str, Any]]) -> dict[str, list[tuple[float, str]]]:
    values: dict[str, list[tuple[float, str]]] = defaultdict(list)
    for record in records:
        status = str(record.get("status", "unknown"))
        for feature, value in _numeric_feature_source(record).items():
            number = _as_number(value)
            if number is not None:
                values[feature].append((number, status))
    return values


def _numeric_feature_source(record: Mapping[str, Any]) -> dict[str, Any]:
    features = record.get("features", {})
    source = dict(features) if isinstance(features, Mapping) else {}
    metrics = record.get("metrics", {})
    if isinstance(metrics, Mapping):
        source.update({f"metric_{k}": v for k, v in metrics.items()})
    return source


def _feature_delta_rows(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for feature, values in sorted(_numeric_values_by_feature(records).items()):
        accepted = sorted(v for v, status in values if status == "accepted")
        not_accepted = sorted(v for v, status in values if status != "accepted")
        if not accepted or not not_accepted:
            continue
        accepted_median = _percentile(accepted, 0.50)
        not_accepted_median = _percentile(not_accepted, 0.50)
        rows.append(
            {
                "feature": feature,
                "accepted_count": len(accepted),
                "not_accepted_count": len(not_accepted),
                "accepted_median": accepted_median,
                "not_accepted_median": not_accepted_median,
                "median_delta": accepted_median - not_accepted_median,
                "accepted_p25": _percentile(accepted, 0.25),
                "accepted_p75": _percentile(accepted, 0.75),
                "not_accepted_p25": _percentile(not_accepted, 0.25),
                "not_accepted_p75": _percentile(not_accepted, 0.75),
            }
        )
    rows.sort(key=lambda r: abs(float(r["median_delta"])), reverse=True)
    return rows


def _numeric_bin_rows(records: list[dict[str, Any]], *, bins: int = 10) -> list[dict[str, Any]]:
    return _bin_rows_for_values(_numeric_values_by_feature(records), bins=bins)


def _bucket_ranges_for_counts(bucket_counts: list[int], *, bins: int) -> list[tuple[int, int]]:
    if bins <= 0 or not bucket_counts:
        return []

    bin_count = min(bins, len(bucket_counts))
    suffix_counts = [0] * (len(bucket_counts) + 1)
    for index in range(len(bucket_counts) - 1, -1, -1):
        suffix_counts[index] = suffix_counts[index + 1] + bucket_counts[index]

    ranges: list[tuple[int, int]] = []
    start = 0
    remaining_bins = bin_count
    while start < len(bucket_counts) and remaining_bins > 0:
        if remaining_bins == 1:
            end = len(bucket_counts)
        else:
            max_end = len(bucket_counts) - (remaining_bins - 1)
            target = suffix_counts[start] / remaining_bins
            count = 0
            end = start
            while end < max_end:
                count += bucket_counts[end]
                end += 1
                if count >= target:
                    break
        ranges.append((start, end))
        start = end
        remaining_bins -= 1
    return ranges


def _bin_rows_for_values(values_by_feature: Mapping[str, list[tuple[float, str]]], *, bins: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for feature, values in sorted(values_by_feature.items()):
        if len(values) < bins:
            continue
        sorted_values = sorted(values, key=lambda item: item[0])
        value_buckets: list[tuple[float, Counter[str]]] = []
        for value, status in sorted_values:
            if value_buckets and value_buckets[-1][0] == value:
                value_buckets[-1][1][status] += 1
            else:
                value_buckets.append((value, Counter({status: 1})))
        if len(value_buckets) < 2:
            continue
        bucket_counts = [sum(counter.values()) for _value, counter in value_buckets]
        for bin_idx, (start, end) in enumerate(
            _bucket_ranges_for_counts(bucket_counts, bins=bins)
        ):
            chunk = value_buckets[start:end]
            counter: Counter[str] = Counter()
            for _value, bucket_counter in chunk:
                counter.update(bucket_counter)
            total = sum(counter.values())
            rows.append(
                {
                    "feature": feature,
                    "bin": bin_idx,
                    "low": chunk[0][0],
                    "high": chunk[-1][0],
                    "total": total,
                    "accepted": counter["accepted"],
                    "rejected": counter["rejected"],
                    "errors": counter["error"],
                    "pass_rate": _pass_rate(counter),
                }
            )
    return rows


def _conditional_numeric_bin_rows(
    records: list[dict[str, Any]],
    *,
    bins: int = 10,
    group_keys: Iterable[str] = CONDITIONAL_BIN_GROUPS,
) -> list[dict[str, Any]]:
    """Return quantile pass-rate bins scoped to categorical study groups.

    The measured dataset intentionally stores full rows, but the static HTML
    dashboard should not embed hundreds of thousands of records.  These rows
    are the compact, offline-friendly representation needed to plot a numeric
    parameter on the x-axis under a selected condition such as outcome or
    ambient spectrum.
    """
    rows: list[dict[str, Any]] = []
    for group_key in group_keys:
        values_by_group: dict[tuple[str, str], list[tuple[float, str]]] = defaultdict(list)
        for record in records:
            group_value = _group_value(record, group_key)
            status = str(record.get("status", "unknown"))
            feature_values = dict(record.get("features", {}))
            feature_values.update(
                {f"metric_{k}": v for k, v in record.get("metrics", {}).items()}
            )
            for feature, value in feature_values.items():
                number = _as_number(value)
                if number is not None:
                    values_by_group[(group_value, feature)].append((number, status))

        for (group_value, feature), values in sorted(values_by_group.items()):
            feature_rows = _bin_rows_for_values({feature: values}, bins=bins)
            for row in feature_rows:
                rows.append(
                    {
                        "group": group_key,
                        "value": group_value,
                        **row,
                    }
                )
    return rows


def _axis_bins(values: list[float], *, bins: int) -> list[tuple[float, float]]:
    sorted_values = sorted(v for v in values if math.isfinite(v))
    if len(sorted_values) < bins or sorted_values[0] == sorted_values[-1]:
        return []
    value_buckets: list[tuple[float, int]] = []
    for value in sorted_values:
        if value_buckets and value_buckets[-1][0] == value:
            previous_value, count = value_buckets[-1]
            value_buckets[-1] = (previous_value, count + 1)
        else:
            value_buckets.append((value, 1))
    if len(value_buckets) < 2:
        return []
    return [
        (value_buckets[start][0], value_buckets[end - 1][0])
        for start, end in _bucket_ranges_for_counts(
            [count for _value, count in value_buckets],
            bins=bins,
        )
    ]


def _axis_index(value: float, axis: list[tuple[float, float]]) -> int:
    highs = [high for _low, high in axis]
    index = bisect.bisect_left(highs, value)
    return min(max(index, 0), len(axis) - 1)


def _numeric_interaction_rows(
    records: list[dict[str, Any]],
    *,
    features: Iterable[str] = INTERACTION_FEATURES,
    bins: int = 8,
) -> list[dict[str, Any]]:
    input_features = list(dict.fromkeys(features))
    metric_features = sorted(
        {
            f"metric_{key}"
            for record in records
            if isinstance(record.get("metrics"), Mapping)
            for key, value in record["metrics"].items()
            if _as_number(value) is not None
        }
    )
    selected_features = list(dict.fromkeys([*input_features, *metric_features]))
    values_by_feature: dict[str, list[float]] = defaultdict(list)
    numeric_records: list[tuple[dict[str, float], str]] = []

    for record in records:
        source = _numeric_feature_source(record)
        values: dict[str, float] = {}
        for feature in selected_features:
            number = _as_number(source.get(feature))
            if number is None:
                continue
            values[feature] = number
            values_by_feature[feature].append(number)
        if values:
            numeric_records.append((values, str(record.get("status", "unknown"))))

    axes = {
        feature: axis
        for feature in selected_features
        if (axis := _axis_bins(values_by_feature[feature], bins=bins))
    }
    active_features = [feature for feature in selected_features if feature in axes]
    x_features = [feature for feature in input_features if feature in axes]
    if not x_features or len(active_features) < 2:
        return []

    counters: dict[tuple[str, str, int, int], Counter[str]] = defaultdict(Counter)
    interaction_pairs = [
        (x_feature, y_feature)
        for x_feature in x_features
        for y_feature in active_features
        if y_feature != x_feature
    ]
    for values, status in numeric_records:
        binned = {
            feature: _axis_index(values[feature], axes[feature])
            for feature in active_features
            if feature in values
        }
        for x_feature, y_feature in interaction_pairs:
            if x_feature in binned and y_feature in binned:
                counters[
                    (x_feature, y_feature, binned[x_feature], binned[y_feature])
                ][status] += 1

    rows: list[dict[str, Any]] = []
    for (x_feature, y_feature, x_bin, y_bin), counter in sorted(counters.items()):
        x_low, x_high = axes[x_feature][x_bin]
        y_low, y_high = axes[y_feature][y_bin]
        total = sum(counter.values())
        rows.append(
            {
                "x_feature": x_feature,
                "y_feature": y_feature,
                "x_bin": x_bin,
                "x_low": x_low,
                "x_high": x_high,
                "y_bin": y_bin,
                "y_low": y_low,
                "y_high": y_high,
                "total": total,
                "accepted": counter["accepted"],
                "rejected": counter["rejected"],
                "errors": counter["error"],
                "pass_rate": _pass_rate(counter),
            }
        )
    return rows


def _analyze_records(records: list[dict[str, Any]]) -> dict[str, Any]:
    status_counts: Counter[str] = Counter(str(r.get("status", "unknown")) for r in records)
    failure_reasons: Counter[str] = Counter()
    for record in records:
        if record.get("status") != "accepted":
            verdict = record.get("verdict", {})
            failure_reasons[str(verdict.get("reason", "<missing>"))] += 1

    group_keys = [
        "tags.outcome",
        "tags.material_subtype",
        "tags.material_color_mode",
        "tags.shape_kind",
        "tags.n_lights",
        "tags.path_style",
        "tags.moving_spectrum",
        "tags.ambient_spectrum",
        "tags.ambient_style",
    ]
    groups: dict[str, dict[str, Counter[str]]] = {
        key: defaultdict(Counter) for key in group_keys
    }
    for record in records:
        status = str(record.get("status", "unknown"))
        for key in group_keys:
            groups[key][_group_value(record, key)][status] += 1

    group_rows: list[dict[str, Any]] = []
    for key, values in groups.items():
        for value, counter in values.items():
            total = sum(counter.values())
            group_rows.append(
                {
                    "group": key,
                    "value": value,
                    "total": total,
                    "accepted": counter["accepted"],
                    "rejected": counter["rejected"],
                    "errors": counter["error"],
                    "pass_rate": _pass_rate(counter),
                }
            )
    group_rows.sort(key=lambda r: (r["group"], -int(r["total"]), str(r["value"])))

    return {
        "schema": SCHEMA_VERSION,
        "record_count": len(records),
        "status_counts": dict(status_counts),
        "measured_count": status_counts["accepted"] + status_counts["rejected"],
        "accepted_count": status_counts["accepted"],
        "rejected_count": status_counts["rejected"],
        "error_count": status_counts["error"],
        "pass_rate": _pass_rate(status_counts),
        "failure_reasons": dict(failure_reasons.most_common()),
        "groups": group_rows,
        "feature_stats": _feature_stat_rows(records),
        "spectrum_metric_stats": _spectrum_metric_stat_rows(records),
        "reason_groups": _reason_group_rows(records),
        "feature_deltas": _feature_delta_rows(records),
        "numeric_bins": _numeric_bin_rows(records),
        "conditional_numeric_bins": _conditional_numeric_bin_rows(records),
        "numeric_interactions": _numeric_interaction_rows(records),
    }


def _format_pct(value: float) -> str:
    return f"{100.0 * value:.1f}%"


def _write_html_report(out: Path, summary: Mapping[str, Any]) -> None:
    data_json = json.dumps(summary, separators=(",", ":")).replace("</", "<\\/")

    html_text = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Crystal Field Measured Study</title>
<style>
* {{ box-sizing: border-box; }}
:root {{ color-scheme: dark; --bg:#111111; --panel:#181818; --ink:#eeeeee; --muted:#a7a7a7; --line:#343434; --accent:#74c0fc; --good:#8ce99a; --warn:#ffd43b; --bad:#ff8787; }}
body {{ margin:0; background:var(--bg); color:var(--ink); font-family:ui-sans-serif, system-ui, -apple-system, Segoe UI, sans-serif; }}
main {{ max-width: 1480px; margin: 0 auto; padding: 22px; }}
h1 {{ margin: 0 0 8px; font-size: 34px; }}
h2 {{ margin: 28px 0 10px; font-size: 22px; }}
p {{ line-height: 1.45; }}
a {{ color: var(--accent); }}
select, input {{ background:#101010; color:var(--ink); border:1px solid var(--line); border-radius:6px; padding:7px 9px; }}
.muted {{ color: var(--muted); }}
.note {{ border-left: 3px solid var(--accent); padding: 8px 12px; background:#151515; }}
.cards {{ display:grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap:10px; margin:18px 0; }}
.card {{ border:1px solid var(--line); border-radius:8px; background:var(--panel); padding:12px; }}
.label {{ color:var(--muted); font-size:12px; }}
.value {{ font-size:24px; font-weight:700; margin-top:4px; }}
.grid {{ display:grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap:18px; }}
.section {{ border-top:1px solid var(--line); padding-top:14px; }}
.controls {{ display:flex; gap:10px; flex-wrap:wrap; align-items:center; margin: 8px 0 12px; }}
.chart {{ display:grid; gap:7px; margin: 10px 0 16px; }}
.plotwrap {{ border:1px solid var(--line); border-radius:8px; background:#151515; padding:10px; margin: 10px 0 14px; overflow:auto; }}
.plotwrap svg {{ display:block; width:100%; min-width:720px; height:auto; }}
.empty {{ color:var(--muted); padding:14px; border:1px dashed var(--line); border-radius:8px; }}
.barrow {{ display:grid; grid-template-columns:minmax(160px, 260px) minmax(160px, 1fr) 90px; gap:10px; align-items:center; }}
.barlabel {{ overflow:hidden; text-overflow:ellipsis; white-space:nowrap; color:#dddddd; }}
.bartrack {{ height:15px; border-radius:4px; background:#242424; overflow:hidden; }}
.bar {{ height:100%; border-radius:4px; background:linear-gradient(90deg, var(--accent), var(--good)); min-width:1px; }}
.bar.warn {{ background:linear-gradient(90deg, var(--warn), var(--bad)); }}
.barvalue {{ text-align:right; color:var(--muted); font-variant-numeric:tabular-nums; }}
.tablewrap {{ overflow:auto; border:1px solid var(--line); border-radius:8px; }}
table {{ border-collapse:collapse; min-width:760px; width:100%; }}
th, td {{ border-bottom:1px solid var(--line); padding:7px 8px; text-align:right; font-variant-numeric:tabular-nums; }}
th {{ position:sticky; top:0; background:#202020; color:#d8d8d8; z-index:1; }}
td:first-child, th:first-child, td:nth-child(2), th:nth-child(2) {{ text-align:left; }}
tr:hover td {{ background:#171717; }}
.pill {{ display:inline-block; padding:2px 6px; border-radius:6px; background:#242424; color:#ddd; }}
@media (max-width: 900px) {{ main {{ padding: 14px; }} .grid {{ grid-template-columns: 1fr; }} .barrow {{ grid-template-columns: 1fr; gap:4px; }} .barvalue {{ text-align:left; }} }}
</style></head><body>
<main>
<h1>Crystal Field Measured Study</h1>
<p class="muted">Empirical conditional probabilities from measured probe rows. No final renders are included in this dataset.</p>
<p class="note">A rejection reason is the first failing gate reported by <code>check.py</code>, not every threshold the sample may have failed. This measured-study dataset evaluates one sampled scene with one sampled look per row; it does not record catalog retry loops or 100-look replay attempts.</p>

<div id="cards" class="cards"></div>

<div class="grid">
  <section class="section">
    <h2>Pass Rate By Group</h2>
    <div class="controls">
      <label>Group <select id="groupSelect"></select></label>
      <label>Sort <select id="groupSort"><option value="pass">pass rate</option><option value="total">total</option><option value="name">name</option></select></label>
    </div>
    <div id="groupChart" class="chart"></div>
    <div id="groupTable" class="tablewrap"></div>
  </section>

  <section class="section">
    <h2>Failure Reasons</h2>
    <div class="controls">
      <label>Group <select id="reasonGroupSelect"></select></label>
      <label>Value <select id="reasonValueSelect"></select></label>
    </div>
    <div id="reasonChart" class="chart"></div>
    <div id="reasonTable" class="tablewrap"></div>
  </section>
</div>

<section class="section">
  <h2>Spectrum Impact</h2>
  <p class="muted">Pass rate and probe-metric shifts by moving or ambient light spectrum. This is the direct view for white, orange, deep orange, and complementary RGB ambient.</p>
  <div class="controls">
    <label>Spectrum <select id="spectrumGroupSelect"></select></label>
    <label>Metric <select id="spectrumMetricSelect"></select></label>
  </div>
  <div id="spectrumChart" class="chart"></div>
  <div id="spectrumTable" class="tablewrap"></div>
</section>

<section class="section">
  <h2>Feature Bins</h2>
  <p class="muted">Bins are near equal-count quantiles inside the selected condition. Exact duplicate values stay in one bin. The plot uses the parameter range on the x-axis, gray bars for sample count, and the blue line for <code>P(pass | bin)</code>.</p>
  <div class="controls">
    <label>Feature <select id="binFeatureSelect"></select></label>
    <label>Condition <select id="binGroupSelect"></select></label>
    <label>Value <select id="binValueSelect"></select></label>
  </div>
  <div id="binPlot" class="plotwrap"></div>
  <div id="binChart" class="chart"></div>
  <div id="binTable" class="tablewrap"></div>
</section>

<section class="section">
  <h2>Feature Interactions</h2>
  <p class="muted">Two-parameter heatmaps help separate coupled effects. For example, use exposure on x and ambient intensity on y to see whether exposure still helps within comparable ambient-intensity bands.</p>
  <div class="controls">
    <label>X Feature <select id="interactionXSelect"></select></label>
    <label>Y Feature <select id="interactionYSelect"></select></label>
  </div>
  <div id="interactionPlot" class="plotwrap"></div>
  <div id="interactionTable" class="tablewrap"></div>
</section>

<div class="grid">
  <section class="section">
    <h2>Accepted Vs Rejected Quantiles</h2>
    <div class="controls">
      <label>Scope <select id="statScopeSelect"></select></label>
      <label>Outcome <select id="statOutcomeSelect"></select></label>
      <label>Feature <select id="statFeatureSelect"></select></label>
    </div>
    <div id="statTable" class="tablewrap"></div>
  </section>

  <section class="section">
    <h2>Median Deltas</h2>
    <p class="muted">Accepted median minus not-accepted median. Large absolute values are useful leads, not proof of causality.</p>
    <div class="controls">
      <label>Search <input id="deltaSearch" placeholder="feature name"></label>
    </div>
    <div id="deltaTable" class="tablewrap"></div>
  </section>
</div>
</main>
<script id="summary-data" type="application/json">{data_json}</script>
<script>
const summary = JSON.parse(document.getElementById('summary-data').textContent);
const baseline = Number(summary.pass_rate || 0);
const groups = summary.groups || [];
const reasonGroups = summary.reason_groups || [];
const bins = summary.numeric_bins || [];
const conditionalBins = summary.conditional_numeric_bins || [];
const interactions = summary.numeric_interactions || [];
const stats = summary.feature_stats || [];
const spectrumStats = summary.spectrum_metric_stats || [];
const deltas = summary.feature_deltas || [];

const $ = (id) => document.getElementById(id);
const uniq = (items) => Array.from(new Set(items)).sort();
const esc = (value) => String(value).replace(/[&<>"']/g, (ch) => ({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[ch]));
const fmtInt = (value) => Number(value || 0).toLocaleString();
const fmtNum = (value) => {{
  const n = Number(value);
  if (!Number.isFinite(n)) return 'n/a';
  if (n !== 0 && Math.abs(n) < 0.001) return n.toExponential(2);
  if (Math.abs(n) >= 1000) return n.toLocaleString(undefined, {{maximumFractionDigits: 0}});
  if (Math.abs(n) >= 10) return n.toLocaleString(undefined, {{maximumFractionDigits: 2}});
  return n.toLocaleString(undefined, {{maximumFractionDigits: 4}});
}};
const fmtPct = (value) => `${{(100 * Number(value || 0)).toFixed(3)}}%`;
const binLabel = (row) => {{
  const low = Number(row.low);
  const high = Number(row.high);
  return low === high ? `= ${{fmtNum(low)}}` : `${{fmtNum(low)}} .. ${{fmtNum(high)}}`;
}};
const setOptions = (select, values, selected) => {{
  select.innerHTML = values.map((value) => `<option value="${{esc(value)}}">${{esc(value)}}</option>`).join('');
  if (selected && values.includes(selected)) select.value = selected;
}};
const table = (headers, rows) => {{
  const head = `<tr>${{headers.map((h) => `<th>${{esc(h)}}</th>`).join('')}}</tr>`;
  const body = rows.map((row) => `<tr>${{row.map((cell) => `<td>${{cell}}</td>`).join('')}}</tr>`).join('');
  return `<table>${{head}}${{body}}</table>`;
}};
const chart = (rows, valueKey, labelKey, valueFmt, warn=false) => {{
  const max = Math.max(...rows.map((row) => Number(row[valueKey] || 0)), 0);
  return rows.map((row) => {{
    const value = Number(row[valueKey] || 0);
    const label = typeof labelKey === 'function' ? labelKey(row) : row[labelKey];
    const width = max > 0 ? Math.max(1, 100 * value / max) : 0;
    return `<div class="barrow"><div class="barlabel" title="${{esc(label)}}">${{esc(label)}}</div><div class="bartrack"><div class="bar ${{warn ? 'warn' : ''}}" style="width:${{width}}%"></div></div><div class="barvalue">${{valueFmt(value, row)}}</div></div>`;
  }}).join('');
}};

const overallBins = bins.map((row) => ({{group: 'overall', value: 'all', ...row}}));
const scopedBins = conditionalBins.length ? [...overallBins, ...conditionalBins] : overallBins;

function renderCards() {{
  const meta = summary.dataset_metadata || {{}};
  const cards = [
    ['Rows', fmtInt(summary.record_count)],
    ['Accepted', fmtInt(summary.accepted_count)],
    ['Rejected', fmtInt(summary.rejected_count)],
    ['Errors', fmtInt(summary.error_count)],
    ['Pass Rate', fmtPct(summary.pass_rate)],
    ['Dataset', esc(meta.status || 'analyzed')],
  ];
  $('cards').innerHTML = cards.map(([label, value]) => `<div class="card"><div class="label">${{label}}</div><div class="value">${{value}}</div></div>`).join('');
}}

function renderGroups() {{
  const group = $('groupSelect').value;
  const sort = $('groupSort').value;
  let rows = groups.filter((row) => row.group === group);
  if (sort === 'pass') rows.sort((a, b) => Number(b.pass_rate) - Number(a.pass_rate));
  if (sort === 'total') rows.sort((a, b) => Number(b.total) - Number(a.total));
  if (sort === 'name') rows.sort((a, b) => String(a.value).localeCompare(String(b.value)));
  $('groupChart').innerHTML = chart(rows, 'pass_rate', 'value', (v, row) => `${{fmtPct(v)}} (${{fmtInt(row.accepted)}}/${{fmtInt(row.total)}})`);
  $('groupTable').innerHTML = table(
    ['Value', 'Total', 'Accepted', 'Rejected', 'Errors', 'P(pass)', 'Lift'],
    rows.map((row) => [
      esc(row.value),
      fmtInt(row.total),
      fmtInt(row.accepted),
      fmtInt(row.rejected),
      fmtInt(row.errors),
      fmtPct(row.pass_rate),
      fmtNum(Number(row.pass_rate || 0) / baseline),
    ])
  );
}}

function updateReasonValues() {{
  const group = $('reasonGroupSelect').value;
  const values = uniq(reasonGroups.filter((row) => row.group === group).map((row) => row.value));
  setOptions($('reasonValueSelect'), values, $('reasonValueSelect').value);
  renderReasons();
}}

function renderReasons() {{
  const group = $('reasonGroupSelect').value;
  const value = $('reasonValueSelect').value;
  let rows;
  if (group === 'overall') {{
    rows = Object.entries(summary.failure_reasons || {{}}).map(([reason, count]) => ({{reason, count, share: count / Math.max(1, summary.rejected_count)}}));
  }} else {{
    rows = reasonGroups.filter((row) => row.group === group && row.value === value);
  }}
  rows.sort((a, b) => Number(b.count) - Number(a.count));
  $('reasonChart').innerHTML = chart(rows.slice(0, 12), 'share', 'reason', (v, row) => `${{fmtPct(v)}} (${{fmtInt(row.count)}})`, true);
  $('reasonTable').innerHTML = table(
    ['Reason', 'Count', 'Share Of Rejections'],
    rows.map((row) => [esc(row.reason), fmtInt(row.count), fmtPct(row.share)])
  );
}}

function spectrumStat(group, value, feature, cohort) {{
  return spectrumStats.find((row) => row.group === group && row.value === value && row.feature === feature && row.cohort === cohort);
}}

function renderSpectrumImpact() {{
  const group = $('spectrumGroupSelect').value;
  const feature = $('spectrumMetricSelect').value;
  const passRows = groups
    .filter((row) => row.group === group)
    .sort((a, b) => Number(b.pass_rate) - Number(a.pass_rate));
  $('spectrumChart').innerHTML = chart(
    passRows,
    'pass_rate',
    'value',
    (v, row) => `${{fmtPct(v)}} (${{fmtInt(row.accepted)}}/${{fmtInt(row.total)}})`
  );
  $('spectrumTable').innerHTML = table(
    ['Spectrum', 'Total', 'Accepted', 'P(pass)', 'Lift', 'Metric Median', 'Metric P10-P90', 'Accepted Median', 'Rejected Median'],
    passRows.map((row) => {{
      const all = spectrumStat(group, row.value, feature, 'all') || {{}};
      const accepted = spectrumStat(group, row.value, feature, 'accepted') || {{}};
      const notAccepted = spectrumStat(group, row.value, feature, 'not_accepted') || {{}};
      return [
        esc(row.value),
        fmtInt(row.total),
        fmtInt(row.accepted),
        fmtPct(row.pass_rate),
        fmtNum(Number(row.pass_rate || 0) / baseline),
        fmtNum(all.median),
        `${{fmtNum(all.p10)}} - ${{fmtNum(all.p90)}}`,
        fmtNum(accepted.median),
        fmtNum(notAccepted.median),
      ];
    }})
  );
}}

function plotBins(rows) {{
  if (!rows.length) return '<div class="empty">No bins for this selection.</div>';
  const width = 980;
  const height = 280;
  const left = 60;
  const right = 22;
  const top = 18;
  const bottom = 52;
  const plotW = width - left - right;
  const plotH = height - top - bottom;
  const passValues = rows.map((row) => Number(row.pass_rate || 0));
  const totals = rows.map((row) => Number(row.total || 0));
  const yMax = Math.max(baseline, ...passValues, 0.000001) * 1.15;
  const totalMax = Math.max(...totals, 1);
  const x = (index) => rows.length === 1 ? left + plotW / 2 : left + (plotW * index) / (rows.length - 1);
  const y = (value) => top + plotH - plotH * Number(value || 0) / yMax;
  const barW = Math.max(8, plotW / Math.max(rows.length, 1) * 0.58);
  const bars = rows.map((row, index) => {{
    const barH = plotH * Number(row.total || 0) / totalMax;
    const bx = x(index) - barW / 2;
    const by = top + plotH - barH;
    return `<rect x="${{bx.toFixed(2)}}" y="${{by.toFixed(2)}}" width="${{barW.toFixed(2)}}" height="${{barH.toFixed(2)}}" fill="#2b2b2b"></rect>`;
  }}).join('');
  const points = rows.map((row, index) => `${{x(index).toFixed(2)}},${{y(row.pass_rate).toFixed(2)}}`).join(' ');
  const dots = rows.map((row, index) => `<circle cx="${{x(index).toFixed(2)}}" cy="${{y(row.pass_rate).toFixed(2)}}" r="3.5" fill="#74c0fc"><title>${{esc(binLabel(row))}}: ${{fmtPct(row.pass_rate)}} / ${{fmtInt(row.accepted)}} accepted of ${{fmtInt(row.total)}}</title></circle>`).join('');
  const step = Math.max(1, Math.ceil(rows.length / 6));
  const labels = rows.map((row, index) => {{
    if (index % step !== 0 && index !== rows.length - 1) return '';
    const mid = (Number(row.low) + Number(row.high)) / 2;
    return `<text x="${{x(index).toFixed(2)}}" y="${{height - 20}}" text-anchor="middle" fill="#a7a7a7" font-size="11">${{esc(fmtNum(mid))}}</text>`;
  }}).join('');
  const baselineY = y(baseline);
  return `<svg viewBox="0 0 ${{width}} ${{height}}" role="img" aria-label="Pass rate by numeric bin">
    <line x1="${{left}}" y1="${{top + plotH}}" x2="${{width - right}}" y2="${{top + plotH}}" stroke="#444"></line>
    <line x1="${{left}}" y1="${{top}}" x2="${{left}}" y2="${{top + plotH}}" stroke="#444"></line>
    ${{bars}}
    <line x1="${{left}}" y1="${{baselineY.toFixed(2)}}" x2="${{width - right}}" y2="${{baselineY.toFixed(2)}}" stroke="#ffd43b" stroke-dasharray="5 5"></line>
    <polyline points="${{points}}" fill="none" stroke="#74c0fc" stroke-width="3" stroke-linejoin="round" stroke-linecap="round"></polyline>
    ${{dots}}
    <text x="${{left + 4}}" y="${{top + 12}}" fill="#a7a7a7" font-size="12">P(pass)</text>
    <text x="${{left + 4}}" y="${{baselineY - 6}}" fill="#ffd43b" font-size="11">overall ${{fmtPct(baseline)}}</text>
    <text x="${{width - right}}" y="${{height - 5}}" text-anchor="end" fill="#a7a7a7" font-size="12">parameter value</text>
    ${{labels}}
  </svg>`;
}}

function updateBinValues() {{
  const group = $('binGroupSelect').value;
  if (group === 'overall') {{
    $('binValueSelect').innerHTML = '<option value="all">all</option>';
    $('binValueSelect').disabled = true;
    renderBins();
    return;
  }}
  $('binValueSelect').disabled = false;
  const values = uniq(scopedBins.filter((row) => row.group === group).map((row) => row.value));
  setOptions($('binValueSelect'), values, $('binValueSelect').value);
  renderBins();
}}

function selectedBinRows() {{
  const feature = $('binFeatureSelect').value;
  const group = $('binGroupSelect').value || 'overall';
  const value = group === 'overall' ? 'all' : $('binValueSelect').value;
  return scopedBins
    .filter((row) => row.feature === feature && row.group === group && row.value === value)
    .sort((a, b) => Number(a.bin) - Number(b.bin));
}}

function renderBins() {{
  const rows = selectedBinRows();
  $('binPlot').innerHTML = plotBins(rows);
  $('binChart').innerHTML = chart(rows, 'pass_rate', binLabel, (v, row) => `${{fmtPct(v)}} / lift ${{fmtNum(v / baseline)}}`);
  $('binTable').innerHTML = table(
    ['Bin', 'Range', 'Total', 'Accepted', 'Rejected', 'Errors', 'P(pass)', 'Lift'],
    rows.map((row) => [
      fmtInt(row.bin),
      esc(binLabel(row)),
      fmtInt(row.total),
      fmtInt(row.accepted),
      fmtInt(row.rejected),
      fmtInt(row.errors),
      fmtPct(row.pass_rate),
      fmtNum(Number(row.pass_rate || 0) / baseline),
    ])
  );
}}

function heatColor(passRate) {{
  const lift = baseline > 0 ? Number(passRate || 0) / baseline : 0;
  if (lift >= 1) {{
    const t = Math.min(1, (lift - 1) / 2);
    return `rgb(${{Math.round(38 + 28 * t)}}, ${{Math.round(92 + 132 * t)}}, ${{Math.round(86 + 74 * t)}})`;
  }}
  const t = Math.max(0, Math.min(1, lift));
  return `rgb(${{Math.round(126 + 38 * (1 - t))}}, ${{Math.round(86 + 42 * t)}}, ${{Math.round(82 + 36 * t)}})`;
}}

function interactionRowsForSelection() {{
  const xFeature = $('interactionXSelect').value;
  const yFeature = $('interactionYSelect').value;
  return interactions.filter((row) => row.x_feature === xFeature && row.y_feature === yFeature);
}}

function plotInteractions(rows) {{
  if (!rows.length) return '<div class="empty">No interaction bins for this feature pair.</div>';
  const xBins = uniq(rows.map((row) => String(row.x_bin))).map(Number).sort((a, b) => a - b);
  const yBins = uniq(rows.map((row) => String(row.y_bin))).map(Number).sort((a, b) => a - b);
  const byCell = new Map(rows.map((row) => [`${{row.x_bin}},${{row.y_bin}}`, row]));
  const width = 980;
  const height = 420;
  const left = 118;
  const right = 22;
  const top = 24;
  const bottom = 86;
  const plotW = width - left - right;
  const plotH = height - top - bottom;
  const cellW = plotW / Math.max(1, xBins.length);
  const cellH = plotH / Math.max(1, yBins.length);
  const cells = [];
  for (const [yi, yBin] of yBins.entries()) {{
    for (const [xi, xBin] of xBins.entries()) {{
      const row = byCell.get(`${{xBin}},${{yBin}}`);
      const x = left + xi * cellW;
      const y = top + (yBins.length - 1 - yi) * cellH;
      const passRate = row ? Number(row.pass_rate || 0) : 0;
      const fill = row ? heatColor(passRate) : '#222';
      const text = row && cellW > 62 && cellH > 34 ? fmtPct(passRate) : '';
      cells.push(`<g><rect x="${{x.toFixed(2)}}" y="${{y.toFixed(2)}}" width="${{cellW.toFixed(2)}}" height="${{cellH.toFixed(2)}}" fill="${{fill}}" stroke="#181818"></rect><title>${{row ? `${{binLabel({{low: row.x_low, high: row.x_high}})}} x ${{binLabel({{low: row.y_low, high: row.y_high}})}}: ${{fmtPct(row.pass_rate)}} / ${{fmtInt(row.accepted)}} accepted of ${{fmtInt(row.total)}}` : 'empty'}}</title>${{text ? `<text x="${{(x + cellW / 2).toFixed(2)}}" y="${{(y + cellH / 2 + 4).toFixed(2)}}" text-anchor="middle" fill="#eeeeee" font-size="11">${{text}}</text>` : ''}}</g>`);
    }}
  }}
  const xLabels = xBins.map((xBin, index) => {{
    const row = rows.find((candidate) => Number(candidate.x_bin) === xBin);
    const x = left + index * cellW + cellW / 2;
    const label = row ? fmtNum((Number(row.x_low) + Number(row.x_high)) / 2) : String(xBin);
    return `<text x="${{x.toFixed(2)}}" y="${{height - 40}}" text-anchor="middle" fill="#a7a7a7" font-size="11">${{esc(label)}}</text>`;
  }}).join('');
  const yLabels = yBins.map((yBin, index) => {{
    const row = rows.find((candidate) => Number(candidate.y_bin) === yBin);
    const y = top + (yBins.length - 1 - index) * cellH + cellH / 2 + 4;
    const label = row ? fmtNum((Number(row.y_low) + Number(row.y_high)) / 2) : String(yBin);
    return `<text x="${{left - 10}}" y="${{y.toFixed(2)}}" text-anchor="end" fill="#a7a7a7" font-size="11">${{esc(label)}}</text>`;
  }}).join('');
  return `<svg viewBox="0 0 ${{width}} ${{height}}" role="img" aria-label="Two-feature pass-rate heatmap">
    ${{cells.join('')}}
    ${{xLabels}}
    ${{yLabels}}
    <text x="${{left + plotW / 2}}" y="${{height - 8}}" text-anchor="middle" fill="#a7a7a7" font-size="12">${{esc($('interactionXSelect').value)}}</text>
    <text transform="translate(16 ${{top + plotH / 2}}) rotate(-90)" text-anchor="middle" fill="#a7a7a7" font-size="12">${{esc($('interactionYSelect').value)}}</text>
    <text x="${{width - right}}" y="${{top + 12}}" text-anchor="end" fill="#ffd43b" font-size="11">overall ${{fmtPct(baseline)}}</text>
  </svg>`;
}}

function updateInteractionYOptions() {{
  const xFeature = $('interactionXSelect').value;
  const values = uniq(interactions.filter((row) => row.x_feature === xFeature).map((row) => row.y_feature));
  const preferredByX = {{
    look_exposure: 'ambient_intensity',
    look_white_point: 'ambient_intensity',
    ambient_intensity: 'metric_ambient_radius_mean',
    moving_intensity: 'metric_moving_radius_mean',
  }};
  const preferredCandidate = preferredByX[xFeature];
  const preferred = preferredCandidate && values.includes(preferredCandidate) ? preferredCandidate : values[0];
  setOptions($('interactionYSelect'), values, $('interactionYSelect').value || preferred);
  if (!$('interactionYSelect').value && preferred) $('interactionYSelect').value = preferred;
  renderInteractions();
}}

function renderInteractions() {{
  const rows = interactionRowsForSelection();
  $('interactionPlot').innerHTML = plotInteractions(rows);
  const tableRows = [...rows]
    .sort((a, b) => Number(b.pass_rate) - Number(a.pass_rate) || Number(b.total) - Number(a.total))
    .slice(0, 40);
  $('interactionTable').innerHTML = table(
    ['X Range', 'Y Range', 'Total', 'Accepted', 'P(pass)', 'Lift'],
    tableRows.map((row) => [
      esc(binLabel({{low: row.x_low, high: row.x_high}})),
      esc(binLabel({{low: row.y_low, high: row.y_high}})),
      fmtInt(row.total),
      fmtInt(row.accepted),
      fmtPct(row.pass_rate),
      fmtNum(Number(row.pass_rate || 0) / baseline),
    ])
  );
}}

function statRowsForSelection() {{
  const scope = $('statScopeSelect').value;
  const outcome = $('statOutcomeSelect').value;
  const feature = $('statFeatureSelect').value;
  return stats.filter((row) => row.scope === scope && row.feature === feature && (scope !== 'outcome' || row.outcome === outcome));
}}

function updateStatOutcomes() {{
  const scope = $('statScopeSelect').value;
  const outcomes = uniq(stats.filter((row) => row.scope === 'outcome').map((row) => row.outcome));
  $('statOutcomeSelect').disabled = scope !== 'outcome';
  setOptions($('statOutcomeSelect'), outcomes, $('statOutcomeSelect').value);
  renderStats();
}}

function renderStats() {{
  const rows = statRowsForSelection().sort((a, b) => String(a.cohort).localeCompare(String(b.cohort)));
  $('statTable').innerHTML = table(
    ['Cohort', 'Count', 'Mean', 'Min', 'P10', 'P25', 'Median', 'P75', 'P90', 'Max'],
    rows.map((row) => [
      esc(row.cohort),
      fmtInt(row.count),
      fmtNum(row.mean),
      fmtNum(row.min),
      fmtNum(row.p10),
      fmtNum(row.p25),
      fmtNum(row.median),
      fmtNum(row.p75),
      fmtNum(row.p90),
      fmtNum(row.max),
    ])
  );
}}

function renderDeltas() {{
  const query = $('deltaSearch').value.toLowerCase();
  const rows = deltas
    .filter((row) => String(row.feature).toLowerCase().includes(query))
    .slice(0, 80);
  $('deltaTable').innerHTML = table(
    ['Feature', 'Accepted N', 'Rejected N', 'Accepted Median', 'Rejected Median', 'Delta', 'Accepted P25-P75', 'Rejected P25-P75'],
    rows.map((row) => [
      esc(row.feature),
      fmtInt(row.accepted_count),
      fmtInt(row.not_accepted_count),
      fmtNum(row.accepted_median),
      fmtNum(row.not_accepted_median),
      fmtNum(row.median_delta),
      `${{fmtNum(row.accepted_p25)}} - ${{fmtNum(row.accepted_p75)}}`,
      `${{fmtNum(row.not_accepted_p25)}} - ${{fmtNum(row.not_accepted_p75)}}`,
    ])
  );
}}

function init() {{
  renderCards();
  const groupNames = uniq(groups.map((row) => row.group));
  setOptions($('groupSelect'), groupNames, groupNames.includes('tags.outcome') ? 'tags.outcome' : groupNames[0]);
  $('groupSelect').addEventListener('change', renderGroups);
  $('groupSort').addEventListener('change', renderGroups);

  const reasonGroupNames = ['overall', ...uniq(reasonGroups.map((row) => row.group))];
  setOptions($('reasonGroupSelect'), reasonGroupNames, 'overall');
  $('reasonGroupSelect').addEventListener('change', () => {{
    if ($('reasonGroupSelect').value === 'overall') {{
      $('reasonValueSelect').innerHTML = '<option value="all">all</option>';
      $('reasonValueSelect').disabled = true;
      renderReasons();
    }} else {{
      $('reasonValueSelect').disabled = false;
      updateReasonValues();
    }}
  }});
  $('reasonValueSelect').addEventListener('change', renderReasons);
  $('reasonValueSelect').innerHTML = '<option value="all">all</option>';
  $('reasonValueSelect').disabled = true;

  const spectrumGroups = uniq(spectrumStats.map((row) => row.group));
  setOptions(
    $('spectrumGroupSelect'),
    spectrumGroups,
    spectrumGroups.includes('tags.moving_spectrum') ? 'tags.moving_spectrum' : spectrumGroups[0]
  );
  const spectrumMetrics = uniq(spectrumStats.map((row) => row.feature));
  setOptions(
    $('spectrumMetricSelect'),
    spectrumMetrics,
    spectrumMetrics.includes('metric_mean_luma') ? 'metric_mean_luma' : spectrumMetrics[0]
  );
  $('spectrumGroupSelect').addEventListener('change', renderSpectrumImpact);
  $('spectrumMetricSelect').addEventListener('change', renderSpectrumImpact);

  const binFeatures = uniq(scopedBins.map((row) => row.feature));
  setOptions($('binFeatureSelect'), binFeatures, binFeatures.includes('look_exposure') ? 'look_exposure' : binFeatures[0]);
  $('binFeatureSelect').addEventListener('change', renderBins);
  const binGroups = ['overall', ...uniq(conditionalBins.map((row) => row.group))];
  setOptions($('binGroupSelect'), binGroups, 'overall');
  $('binGroupSelect').addEventListener('change', updateBinValues);
  $('binValueSelect').innerHTML = '<option value="all">all</option>';
  $('binValueSelect').disabled = true;
  $('binValueSelect').addEventListener('change', renderBins);

  const interactionXFeatures = uniq(interactions.map((row) => row.x_feature));
  setOptions(
    $('interactionXSelect'),
    interactionXFeatures,
    interactionXFeatures.includes('look_exposure') ? 'look_exposure' : interactionXFeatures[0]
  );
  $('interactionXSelect').addEventListener('change', updateInteractionYOptions);
  $('interactionYSelect').addEventListener('change', renderInteractions);

  const scopes = uniq(stats.map((row) => row.scope));
  setOptions($('statScopeSelect'), scopes, scopes.includes('all') ? 'all' : scopes[0]);
  const statFeatures = uniq(stats.map((row) => row.feature));
  setOptions($('statFeatureSelect'), statFeatures, statFeatures.includes('look_exposure') ? 'look_exposure' : statFeatures[0]);
  $('statScopeSelect').addEventListener('change', updateStatOutcomes);
  $('statOutcomeSelect').addEventListener('change', renderStats);
  $('statFeatureSelect').addEventListener('change', renderStats);

  $('deltaSearch').addEventListener('input', renderDeltas);
  renderGroups();
  renderReasons();
  renderSpectrumImpact();
  renderBins();
  updateInteractionYOptions();
  updateStatOutcomes();
  renderDeltas();
}}

init();
</script>
</body></html>
"""
    (out / "index.html").write_text(html_text, encoding="utf-8")


def run_analyze(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Analyze a measured crystal_field JSONL dataset")
    parser.add_argument("--in", dest="in_path", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)

    in_path = Path(args.in_path)
    out = Path(args.out)
    if in_path.suffix != ".gz":
        _scan_jsonl(in_path, repair=True)
    records = list(_iter_jsonl(in_path))
    summary = _analyze_records(records)
    meta_path = _metadata_path(in_path)
    if meta_path.exists():
        summary["dataset_metadata"] = json.loads(meta_path.read_text(encoding="utf-8"))

    out.mkdir(parents=True, exist_ok=True)
    (out / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    _write_csv(
        out / "groups.csv",
        summary["groups"],
        ["group", "value", "total", "accepted", "rejected", "errors", "pass_rate"],
    )
    _write_csv(
        out / "failure_reasons.csv",
        [
            {"reason": reason, "count": count}
            for reason, count in summary["failure_reasons"].items()
        ],
        ["reason", "count"],
    )
    _write_csv(
        out / "feature_stats.csv",
        summary["feature_stats"],
        [
            "scope",
            "outcome",
            "feature",
            "cohort",
            "count",
            "mean",
            "min",
            "p10",
            "p25",
            "median",
            "p75",
            "p90",
            "max",
        ],
    )
    _write_csv(
        out / "spectrum_metric_stats.csv",
        summary["spectrum_metric_stats"],
        [
            "group",
            "value",
            "feature",
            "cohort",
            "count",
            "mean",
            "min",
            "p10",
            "p25",
            "median",
            "p75",
            "p90",
            "max",
        ],
    )
    _write_csv(
        out / "reason_groups.csv",
        summary["reason_groups"],
        ["group", "value", "reason", "count", "share"],
    )
    _write_csv(
        out / "feature_deltas.csv",
        summary["feature_deltas"],
        [
            "feature",
            "accepted_count",
            "not_accepted_count",
            "accepted_median",
            "not_accepted_median",
            "median_delta",
            "accepted_p25",
            "accepted_p75",
            "not_accepted_p25",
            "not_accepted_p75",
        ],
    )
    _write_csv(
        out / "numeric_bins.csv",
        summary["numeric_bins"],
        ["feature", "bin", "low", "high", "total", "accepted", "rejected", "errors", "pass_rate"],
    )
    _write_csv(
        out / "conditional_numeric_bins.csv",
        summary["conditional_numeric_bins"],
        [
            "group",
            "value",
            "feature",
            "bin",
            "low",
            "high",
            "total",
            "accepted",
            "rejected",
            "errors",
            "pass_rate",
        ],
    )
    _write_csv(
        out / "numeric_interactions.csv",
        summary["numeric_interactions"],
        [
            "x_feature",
            "y_feature",
            "x_bin",
            "x_low",
            "x_high",
            "y_bin",
            "y_low",
            "y_high",
            "total",
            "accepted",
            "rejected",
            "errors",
            "pass_rate",
        ],
    )
    _write_html_report(out, summary)
    print(f"Analysis written to {out}")


def run_study(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Crystal field measured-study tools")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("measure", help="sample scenes and write measured probe JSONL")
    sub.add_parser("analyze", help="analyze measured probe JSONL")

    ns, rest = parser.parse_known_args(argv)
    if ns.cmd == "measure":
        run_measure(rest)
    elif ns.cmd == "analyze":
        run_analyze(rest)
    else:  # pragma: no cover - argparse enforces choices.
        parser.error(f"unknown command: {ns.cmd}")


if __name__ == "__main__":
    run_study()
