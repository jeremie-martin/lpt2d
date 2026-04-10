"""Save and load reference baselines for fidelity comparison."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

BASELINE_SET_SCHEMA_VERSION = 4


def _result_metadata(result) -> dict:
    m = result.metrics
    return {
        "width": result.width,
        "height": result.height,
        "total_rays": result.total_rays,
        "max_hdr": result.max_hdr,
        "time_ms": result.time_ms,
        "metrics": {
            "mean": m.mean,
            "median": m.median,
            "highlight_ceiling": m.highlight_ceiling,
            "near_black_fraction": m.near_black_fraction,
            "clipped_channel_fraction": m.clipped_channel_fraction,
            "histogram": list(m.histogram),
        },
    }


def _baseline_record(image_path: Path, meta: dict, metadata: dict | None = None) -> dict:
    img = Image.open(image_path).convert("RGB")
    pixels = np.asarray(img, dtype=np.uint8)
    record = {
        "pixels": pixels,
        "width": meta["width"],
        "height": meta["height"],
        "total_rays": meta.get("total_rays"),
        "max_hdr": meta.get("max_hdr"),
        "time_ms": meta.get("time_ms"),
        "metrics": meta.get("metrics"),
        "metadata": metadata,
    }
    if "render_timing" in meta:
        record["render_timing"] = meta["render_timing"]
    if "wall_timing" in meta:
        record["wall_timing"] = meta["wall_timing"]
    return record


def save_baseline(
    path: Path,
    result,
    *,
    metadata: dict | None = None,
) -> None:
    """Save a RenderResult as a baseline directory.

    Creates ``path/image.png`` and ``path/metadata.json``.
    """
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True)

    pixels = np.frombuffer(result.pixels, dtype=np.uint8).reshape(result.height, result.width, 3)
    Image.fromarray(pixels, "RGB").save(path / "image.png")

    meta = _result_metadata(result)
    if metadata:
        meta["metadata"] = metadata

    (path / "metadata.json").write_text(json.dumps(meta, indent=2) + "\n")


def save_baseline_set(
    path: Path,
    results_by_case: dict[int, Any],
    *,
    metadata: dict | None = None,
    timing_by_case: dict[int, dict] | None = None,
    scene_json_by_case: dict[int, str] | None = None,
    warmup_scene_json: str | None = None,
) -> None:
    """Save multiple benchmark-case baselines for one scene directory."""
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True)

    cases_meta: dict[str, dict] = {}
    for case_index, result in sorted(results_by_case.items()):
        image_name = f"case_{case_index:04d}.png"
        pixels = np.frombuffer(result.pixels, dtype=np.uint8).reshape(
            result.height, result.width, 3
        )
        Image.fromarray(pixels, "RGB").save(path / image_name)

        case_meta = _result_metadata(result)
        case_meta["image"] = image_name
        if timing_by_case and case_index in timing_by_case:
            case_meta.update(timing_by_case[case_index])
        if scene_json_by_case and case_index in scene_json_by_case:
            scene_json_name = f"case_{case_index:04d}.json"
            (path / scene_json_name).write_text(scene_json_by_case[case_index])
            case_meta["scene_json"] = scene_json_name
        cases_meta[str(case_index)] = case_meta

    doc = {
        "schema_version": BASELINE_SET_SCHEMA_VERSION,
        "cases": cases_meta,
    }
    if warmup_scene_json is not None:
        warmup_name = "warmup.json"
        (path / warmup_name).write_text(warmup_scene_json)
        doc["warmup_scene_json"] = warmup_name
    if metadata is not None:
        doc["metadata"] = metadata

    (path / "metadata.json").write_text(json.dumps(doc, indent=2) + "\n")


def load_baseline(path: Path) -> dict:
    """Load a baseline from a directory created by ``save_baseline``.

    Returns a dict with keys: ``pixels`` (ndarray H,W,3 uint8), ``width``,
    ``height``, ``metrics`` (dict), ``time_ms``, ``metadata``.
    """
    path = Path(path)
    meta = json.loads((path / "metadata.json").read_text())
    return _baseline_record(path / "image.png", meta, meta.get("metadata"))


def load_baseline_set(path: Path) -> dict:
    """Load a scene baseline with one or more benchmark cases.

    Returns ``{"cases": {case_index: baseline_dict}, "metadata": metadata}``.
    """
    path = Path(path)
    meta = json.loads((path / "metadata.json").read_text())
    if meta.get("schema_version") != BASELINE_SET_SCHEMA_VERSION:
        raise ValueError(
            f"baseline schema_version must be {BASELINE_SET_SCHEMA_VERSION},"
            f" got {meta.get('schema_version')!r}"
        )
    if "cases" not in meta or not meta["cases"]:
        raise ValueError("baseline metadata must contain a non-empty `cases` mapping")

    metadata = meta.get("metadata")
    cases: dict[int, dict] = {}
    for key, case_meta in meta["cases"].items():
        case_index = int(key)
        image_name = case_meta.get("image")
        if not image_name:
            raise ValueError(f"case {case_index} missing `image` field")
        record = _baseline_record(path / image_name, case_meta, metadata)

        scene_json_name = case_meta.get("scene_json")
        if not scene_json_name:
            raise ValueError(f"case {case_index} missing `scene_json` field")
        record["scene_json"] = (path / scene_json_name).read_text()
        record["scene_json_path"] = scene_json_name
        cases[case_index] = record

    warmup_scene_json_name = meta.get("warmup_scene_json")
    if not warmup_scene_json_name:
        raise ValueError("baseline metadata must contain `warmup_scene_json`")

    return {
        "schema_version": meta["schema_version"],
        "cases": cases,
        "metadata": metadata,
        "warmup_scene_json": (path / warmup_scene_json_name).read_text(),
        "warmup_scene_json_path": warmup_scene_json_name,
    }
