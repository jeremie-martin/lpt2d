"""Measure the apparent size and sharpness of point-light circles.

Each point light produces a bright blob on screen whose radius and edge
sharpness depend on exposure, tonemapping, object proximity, and how many
other lights contribute.  This module extracts per-light metrics from a
rendered image so that scene generators can enforce quality bounds.

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
        print(f"{c.label}: radius={c.radius_px:.1f}px  sharpness={c.sharpness:.2f}")
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class LightCircle:
    """Measured properties of one point light's apparent circle."""

    label: str
    world_pos: tuple[float, float]
    pixel_pos: tuple[float, float]

    # Peak luminance at the light centre (0-1 scale).
    peak: float

    # Background luminance floor (median of the outer half of the profile).
    background: float

    # Radius (in pixels) at which the above-background luminance drops
    # to 50% of the above-background peak.  Larger = bigger apparent blob.
    radius_px: float

    # Sharpness of the circle edge.  Defined as 1 / (radius_20 - radius_80),
    # where fractions are relative to above-background amplitude.
    # Higher = sharper edge transition.
    sharpness: float

    # Radial profile: average luminance at each integer pixel radius.
    # profile[r] is the mean luminance at distance r from the centre.
    profile: np.ndarray


def _luminance(rgb: np.ndarray) -> np.ndarray:
    """BT.709 luminance from uint8 RGB, returned as float32 in [0, 1]."""
    return (
        0.2126 * rgb[..., 0].astype(np.float32)
        + 0.7152 * rgb[..., 1].astype(np.float32)
        + 0.0722 * rgb[..., 2].astype(np.float32)
    ) / 255.0


def _radial_profile(
    lum: np.ndarray,
    cx: float,
    cy: float,
    max_radius: int,
) -> np.ndarray:
    """Average luminance in concentric rings around (cx, cy).

    Returns an array of length *max_radius* + 1 where entry *r* is the
    mean luminance of all pixels whose distance from the centre rounds
    to *r*.
    """
    h, w = lum.shape
    ys = np.arange(h, dtype=np.float32) - cy
    xs = np.arange(w, dtype=np.float32) - cx
    xg, yg = np.meshgrid(xs, ys)
    dist = np.sqrt(xg * xg + yg * yg)

    profile = np.zeros(max_radius + 1, dtype=np.float64)
    counts = np.zeros(max_radius + 1, dtype=np.int64)

    # Quantize distance to integer bins.
    ri = np.clip(np.round(dist).astype(np.int64), 0, max_radius)
    for r in range(max_radius + 1):
        mask = ri == r
        if mask.any():
            profile[r] = lum[mask].mean()
            counts[r] = mask.sum()

    return profile.astype(np.float32)


def _find_radius_at_fraction(
    profile: np.ndarray, peak: float, background: float, fraction: float,
) -> float:
    """Radius where the above-background luminance drops to *fraction* of (peak - background).

    Uses linear interpolation between the two bracketing integer radii.
    Returns the last radius if the profile never drops that low.
    """
    amplitude = peak - background
    threshold = background + amplitude * fraction
    for r in range(1, len(profile)):
        if profile[r] <= threshold:
            prev = float(profile[r - 1])
            curr = float(profile[r])
            if abs(prev - curr) < 1e-9:
                return float(r)
            frac = (prev - threshold) / (prev - curr)
            return (r - 1) + frac
    return float(len(profile) - 1)


def measure_light_circles(
    pixels: bytes,
    width: int,
    height: int,
    light_positions: list[tuple[float, float]],
    camera_center: tuple[float, float] = (0.0, 0.0),
    camera_width: float = 3.2,
    max_radius_px: int = 200,
    labels: list[str] | None = None,
) -> list[LightCircle]:
    """Measure the apparent circle of each point light.

    Parameters
    ----------
    pixels : bytes
        Raw RGB8 pixel data (width * height * 3 bytes), as returned by
        ``RenderResult.pixels``.
    width, height : int
        Canvas dimensions.
    light_positions : list of (x, y)
        World-space positions of the lights to measure.
    camera_center : (float, float)
        Camera centre in world space.
    camera_width : float
        Camera horizontal extent in world units.
    max_radius_px : int
        Maximum analysis radius in pixels.
    labels : list of str or None
        Optional per-light labels.  Defaults to ``"light_0"``, ``"light_1"``, etc.

    Returns
    -------
    list of LightCircle
        One entry per light, in the same order as *light_positions*.
    """
    arr = np.frombuffer(pixels, dtype=np.uint8).reshape(height, width, 3)
    lum = _luminance(arr)

    cam_height = camera_width * height / width
    cx_world, cy_world = camera_center
    x_min = cx_world - camera_width / 2
    y_max = cy_world + cam_height / 2

    results: list[LightCircle] = []

    for i, (wx, wy) in enumerate(light_positions):
        # World -> pixel.
        px = (wx - x_min) / camera_width * width
        py = (y_max - wy) / cam_height * height
        label = labels[i] if labels else f"light_{i}"

        # Clamp to canvas — lights may be partially off-screen.
        px_c = max(0.0, min(float(width - 1), px))
        py_c = max(0.0, min(float(height - 1), py))

        profile = _radial_profile(lum, px_c, py_c, max_radius_px)

        # Peak: average of the innermost few pixels (radius 0–2) to
        # smooth out single-pixel noise.
        peak = float(profile[:3].max())

        # Background: median of the outer quarter of the profile, where
        # we expect only reflected / ambient light with no direct contribution.
        outer_start = max(1, int(max_radius_px * 0.75))
        bg = float(np.median(profile[outer_start:]))

        amplitude = peak - bg
        if amplitude < 0.01:
            # Light is essentially invisible above background.
            results.append(
                LightCircle(label, (wx, wy), (px, py), peak, bg, 0.0, 0.0, profile)
            )
            continue

        r50 = _find_radius_at_fraction(profile, peak, bg, 0.50)
        r80 = _find_radius_at_fraction(profile, peak, bg, 0.80)
        r20 = _find_radius_at_fraction(profile, peak, bg, 0.20)

        edge_width = r20 - r80
        sharpness = 1.0 / edge_width if edge_width > 0.5 else 2.0  # cap at 2.0

        results.append(
            LightCircle(label, (wx, wy), (px, py), peak, bg, r50, sharpness, profile)
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
            f"{c.label:>12s}  peak={c.peak:.3f}  bg={c.background:.3f}  "
            f"r={c.radius_px:5.1f}px ({r_world:.3f}u)  "
            f"sharp={c.sharpness:.2f}"
        )
    return "\n".join(lines)
