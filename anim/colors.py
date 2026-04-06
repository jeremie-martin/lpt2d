"""Color convenience API for spectral materials."""

from __future__ import annotations

import _lpt2d


def resolve_color(color: str | tuple[float, float, float] | None) -> tuple[float, float, float]:
    """Resolve a color specification to sigmoid spectral coefficients (c0, c1, c2).

    Accepts:
      - Named color string: "red", "green", "pink", "magenta", etc.
      - RGB tuple: (1.0, 0.3, 0.5) — converted via Gauss-Newton optimization
      - None: returns (0.0, 0.0, 0.0) meaning spectrally neutral
    """
    if color is None:
        return (0.0, 0.0, 0.0)
    if isinstance(color, str):
        return _lpt2d.named_color(color)
    if isinstance(color, (tuple, list)) and len(color) == 3:
        return _lpt2d.rgb_to_spectral(*color)
    raise TypeError(f"color must be a string, RGB tuple, or None, got {type(color)}")


def fill_rgb(c0: float, c1: float, c2: float) -> tuple[float, float, float]:
    """Compute display RGB for sigmoid spectral coefficients."""
    return _lpt2d.spectral_fill_rgb(c0, c1, c2)
