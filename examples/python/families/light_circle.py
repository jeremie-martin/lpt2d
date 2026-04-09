"""Measure the apparent size and sharpness of point-light circles.

Each point light produces a bright blob on screen.  This module measures
the radius and edge sharpness of each blob using a threshold method with
Voronoi masking — each pixel is attributed to its nearest light source,
preventing overlapping light fields from contaminating each other.

Typical usage::

    from examples.python.families.light_circle import measure_light_circles, LightCircle

    circles = measure_light_circles(
        pixels=render_result.pixels,
        width=1280, height=720,
        light_positions=[(0.0, 0.0), (-1.4, 0.75)],
        camera_center=(0.0, 0.0),
        camera_width=3.2,
    )
    for c in circles:
        print(f"{c.label}: radius={c.radius_px:.1f}px  sharpness={c.sharpness:.3f}")
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

# Luminance threshold for "bright blob" detection.  Pixels above this
# are considered part of a light's visible circle.
BRIGHT_THRESHOLD = 0.92


@dataclass(frozen=True)
class LightCircle:
    """Measured properties of one point light's apparent circle."""

    label: str
    world_pos: tuple[float, float]
    pixel_pos: tuple[float, float]

    # Radius (in pixels) of the bright blob: the 90th percentile distance
    # of pixels above BRIGHT_THRESHOLD that are closest to this light.
    radius_px: float

    # Edge sharpness: luminance drop per pixel across the circle edge.
    # Higher = crisper edge.  Measured over the [0.5r, 1.5r] band of the
    # Voronoi-masked radial profile.
    sharpness: float

    # Mean image luminance (same for all lights in the same image).
    mean_luminance: float

    # Voronoi-masked radial profile (luminance vs distance, only counting
    # pixels attributed to this light).
    profile: np.ndarray


def _luminance(rgb: np.ndarray) -> np.ndarray:
    """BT.709 luminance from uint8 RGB, returned as float32 in [0, 1]."""
    return (
        0.2126 * rgb[..., 0].astype(np.float32)
        + 0.7152 * rgb[..., 1].astype(np.float32)
        + 0.0722 * rgb[..., 2].astype(np.float32)
    ) / 255.0


def _world_to_pixel(
    wx: float, wy: float,
    width: int, height: int,
    camera_center: tuple[float, float],
    camera_width: float,
) -> tuple[float, float]:
    cam_height = camera_width * height / width
    px = (wx - (camera_center[0] - camera_width / 2)) / camera_width * width
    py = ((camera_center[1] + cam_height / 2) - wy) / cam_height * height
    return px, py


def measure_light_circles(
    pixels: bytes,
    width: int,
    height: int,
    light_positions: list[tuple[float, float]],
    camera_center: tuple[float, float] = (0.0, 0.0),
    camera_width: float = 3.2,
    max_radius_px: int = 200,
    labels: list[str] | None = None,
    threshold: float = BRIGHT_THRESHOLD,
) -> list[LightCircle]:
    """Measure the apparent circle of each point light.

    Uses Voronoi masking: each pixel is attributed to its nearest light,
    so overlapping light fields don't contaminate each other's measurements.
    The bright blob radius is the 90th percentile distance of pixels above
    *threshold* within each light's Voronoi cell.

    Parameters
    ----------
    pixels : bytes
        Raw RGB8 pixel data (width * height * 3 bytes).
    width, height : int
        Canvas dimensions.
    light_positions : list of (x, y)
        World-space positions of all lights in the scene.
    camera_center, camera_width : float
        Camera parameters for world-to-pixel mapping.
    max_radius_px : int
        Ignore bright pixels beyond this distance from a light.
    labels : list of str or None
        Per-light names.  Defaults to ``"light_0"``, etc.
    threshold : float
        Luminance threshold for bright-blob detection (default 0.92).
    """
    arr = np.frombuffer(pixels, dtype=np.uint8).reshape(height, width, 3)
    lum = _luminance(arr)
    mean_lum = float(lum.mean())

    # Pre-compute pixel positions for all lights.
    pixel_positions = [
        _world_to_pixel(wx, wy, width, height, camera_center, camera_width)
        for wx, wy in light_positions
    ]

    # Pre-compute distance grids from each light.
    ys = np.arange(height, dtype=np.float32)
    xs = np.arange(width, dtype=np.float32)
    xg, yg = np.meshgrid(xs, ys)

    dist_grids = []
    for px, py in pixel_positions:
        dist_grids.append(np.sqrt((xg - px) ** 2 + (yg - py) ** 2))

    # Voronoi assignment: each pixel belongs to its nearest light.
    if len(dist_grids) > 1:
        stacked = np.stack(dist_grids, axis=0)
        nearest = np.argmin(stacked, axis=0)
    else:
        nearest = np.zeros((height, width), dtype=np.intp)

    bright = lum >= threshold

    results: list[LightCircle] = []

    for i, (wx, wy) in enumerate(light_positions):
        px, py = pixel_positions[i]
        label = labels[i] if labels else f"light_{i}"
        dist = dist_grids[i]
        mask = nearest == i  # Voronoi cell for this light

        # --- Radius: 90th percentile of bright-pixel distances in this cell ---
        bright_in_cell = bright & mask & (dist < max_radius_px)
        cell_dists = dist[bright_in_cell]
        radius = float(np.percentile(cell_dists, 90)) if len(cell_dists) > 5 else 0.0

        # --- Radial profile (Voronoi-masked) ---
        ri = np.clip(np.round(dist).astype(np.int64), 0, max_radius_px)
        # Exclude pixels outside this light's Voronoi cell.
        ri_flat = ri.ravel().copy()
        mask_flat = mask.ravel()
        ri_flat[~mask_flat] = max_radius_px + 1  # sentinel: excluded from bincount
        valid = ri_flat <= max_radius_px
        lum_flat = lum.ravel().astype(np.float64)

        with np.errstate(invalid="ignore", divide="ignore"):
            sums = np.bincount(ri_flat[valid], weights=lum_flat[valid], minlength=max_radius_px + 1)
            counts = np.bincount(ri_flat[valid], minlength=max_radius_px + 1)
            profile = np.where(counts > 0, sums / counts, 0.0).astype(np.float32)

        # --- Sharpness: luminance drop per pixel across the edge band ---
        r_lo = max(1, int(radius * 0.5))
        r_hi = min(max_radius_px - 1, int(radius * 1.5) + 1)
        if r_hi > r_lo and radius > 2:
            edge = profile[r_lo : r_hi + 1]
            if len(edge) >= 2:
                sharpness = float(edge[0] - edge[-1]) / (r_hi - r_lo)
            else:
                sharpness = 0.0
        else:
            sharpness = 0.0

        results.append(
            LightCircle(label, (wx, wy), (px, py), radius, sharpness, mean_lum, profile)
        )

    return results


def pixels_to_world(radius_px: float, camera_width: float, canvas_width: int) -> float:
    """Convert a pixel radius to world units."""
    return radius_px * camera_width / canvas_width


def summarize(circles: list[LightCircle], camera_width: float = 3.2, canvas_width: int = 1280) -> str:
    """One-line-per-light summary string."""
    lines = []
    for c in circles:
        r_world = pixels_to_world(c.radius_px, camera_width, canvas_width)
        lines.append(
            f"{c.label:>12s}  r={c.radius_px:5.1f}px ({r_world:.3f}u)  "
            f"sharp={c.sharpness:.4f}  mean={c.mean_luminance:.3f}"
        )
    return "\n".join(lines)
