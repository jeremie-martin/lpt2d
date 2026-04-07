"""Save and load reference baselines for fidelity comparison."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from PIL import Image


def _result_metadata(result) -> dict:
    m = result.metrics
    return {
        "width": result.width,
        "height": result.height,
        "total_rays": result.total_rays,
        "max_hdr": result.max_hdr,
        "time_ms": result.time_ms,
        "metrics": {
            "mean_lum": m.mean_lum,
            "pct_black": m.pct_black,
            "pct_clipped": m.pct_clipped,
            "p50": m.p50,
            "p95": m.p95,
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
    results_by_frame: dict[int, object],
    *,
    metadata: dict | None = None,
    timing_by_frame: dict[int, dict] | None = None,
) -> None:
    """Save multiple frame baselines for one scene directory."""
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True)

    frames_meta: dict[str, dict] = {}
    for frame_index, result in sorted(results_by_frame.items()):
        image_name = f"frame_{frame_index:04d}.png"
        pixels = np.frombuffer(result.pixels, dtype=np.uint8).reshape(result.height, result.width, 3)
        Image.fromarray(pixels, "RGB").save(path / image_name)

        frame_meta = _result_metadata(result)
        frame_meta["image"] = image_name
        if timing_by_frame and frame_index in timing_by_frame:
            frame_meta.update(timing_by_frame[frame_index])
        frames_meta[str(frame_index)] = frame_meta

    doc = {"frames": frames_meta}
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
    """Load a scene baseline with one or more reference frames.

    Returns ``{"frames": {frame_index: baseline_dict}, "metadata": metadata}``.
    Legacy single-frame baselines are exposed as frame ``0``.
    """
    path = Path(path)
    meta = json.loads((path / "metadata.json").read_text())

    if "frames" not in meta:
        baseline = load_baseline(path)
        return {"frames": {0: baseline}, "metadata": baseline.get("metadata")}

    metadata = meta.get("metadata")
    frames: dict[int, dict] = {}
    for key, frame_meta in meta["frames"].items():
        frame_index = int(key)
        image_name = frame_meta.get("image", f"frame_{frame_index:04d}.png")
        frames[frame_index] = _baseline_record(path / image_name, frame_meta, metadata)

    return {"frames": frames, "metadata": metadata}
