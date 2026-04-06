"""Color convenience API for spectral materials."""

from __future__ import annotations

import _lpt2d


def resolve_color(color: str | None) -> tuple[float, float]:
    """Resolve a color specification to (color_wavelength, color_bandwidth).

    Accepts:
      - Named color string: "red", "green", "blue", etc.
      - None: returns (0.0, 50.0) meaning achromatic/spectrally neutral
    """
    if color is None:
        return (0.0, 50.0)
    return _lpt2d.named_color(color)


def fill_rgb(wavelength: float, bandwidth: float) -> tuple[float, float, float]:
    """Compute display RGB for a spectral material's fill color."""
    return _lpt2d.spectral_fill_rgb(wavelength, bandwidth)
