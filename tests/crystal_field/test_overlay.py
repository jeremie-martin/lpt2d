"""Overlay smoke test — confirm draw_metrics_overlay writes visible pixels.

This is a shape/pixel-presence regression test, not a visual one.  We
create a solid-colour PNG, call the overlay, and assert that the
bottom-left corner (where the overlay lands) now contains pixels that
differ from the background.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image

from examples.python.families.crystal_field.overlay import draw_metrics_overlay


def _make_background(path: Path, size: tuple[int, int] = (640, 360)) -> None:
    """Solid grey PNG at the given path."""
    img = Image.new("RGB", size, color=(64, 64, 64))
    img.save(path)


def _sample_metrics() -> dict[str, float]:
    return {
        "mean": 0.42,
        "spread": 0.58,
        "p99": 0.97,
        "clip%": 0.02,
        "sat": 0.31,
        "color": 3.5,
        "moving_r": 18.0,
        "ambient_r": 12.0,
        "ratio": 1.5,
        "sharp": 0.021,
        "exp": -4.2,
        "gam": 1.7,
        "wp": 0.6,
    }


def test_overlay_writes_pixels_in_bottom_left(tmp_path):
    path = tmp_path / "scene.png"
    _make_background(path)

    draw_metrics_overlay(path, _sample_metrics())

    # Reload the modified image and examine the bottom-left region.
    img = np.array(Image.open(path).convert("RGB"))
    h = img.shape[0]

    # The overlay is anchored with margin=16 from bottom-left.
    # Check a box starting ~20px in from the left, ~20-200px up from the bottom.
    bl = img[h - 200 : h - 20, 20:400]
    # At least some pixels in this region should differ from the 64/64/64 background.
    diff_mask = np.any(bl != 64, axis=-1)
    changed_pixels = diff_mask.sum()
    assert changed_pixels > 500, (
        f"Overlay did not change enough pixels ({changed_pixels}) in "
        f"the bottom-left region; expected overlay text + background box."
    )


def test_overlay_preserves_image_size(tmp_path):
    path = tmp_path / "scene.png"
    _make_background(path, size=(800, 450))
    draw_metrics_overlay(path, _sample_metrics())
    img = Image.open(path)
    assert img.size == (800, 450)


def test_overlay_empty_metrics_is_noop(tmp_path):
    path = tmp_path / "scene.png"
    _make_background(path)
    before = np.array(Image.open(path).convert("RGB"))
    draw_metrics_overlay(path, {})
    after = np.array(Image.open(path).convert("RGB"))
    # Empty metrics dict → the function returns early without touching the file.
    assert np.array_equal(before, after)
