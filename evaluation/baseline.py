"""Save and load reference baselines for fidelity comparison."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from PIL import Image


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

    m = result.metrics
    meta = {
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
    if metadata:
        meta["metadata"] = metadata

    (path / "metadata.json").write_text(json.dumps(meta, indent=2) + "\n")


def load_baseline(path: Path) -> dict:
    """Load a baseline from a directory created by ``save_baseline``.

    Returns a dict with keys: ``pixels`` (ndarray H,W,3 uint8), ``width``,
    ``height``, ``metrics`` (dict), ``time_ms``, ``metadata``.
    """
    path = Path(path)
    img = Image.open(path / "image.png").convert("RGB")
    pixels = np.asarray(img, dtype=np.uint8)

    meta = json.loads((path / "metadata.json").read_text())

    return {
        "pixels": pixels,
        "width": meta["width"],
        "height": meta["height"],
        "total_rays": meta.get("total_rays"),
        "max_hdr": meta.get("max_hdr"),
        "time_ms": meta.get("time_ms"),
        "metrics": meta.get("metrics"),
        "metadata": meta.get("metadata"),
    }
