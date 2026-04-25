"""Spectrum-aware light intensity helpers.

Ray tracing gives each ray equal energy, and wavelengths outside the CIE
luminance curve contribute little perceived brightness per photon. So a
projector that emits only 580-650 nm (our "warm" preset) looks much dimmer
than a full-spectrum white projector at the same authored intensity — not
because fewer rays hit the sensor, but because each ray is weighted by the
luminosity function during final RGB resolution.

``spectral_luminance_boost`` computes the multiplier that brings a narrow
spectral band up to the same perceived luminance as full-spectrum white.
``intensity_for_spectrum`` is the one-shot convenience for families that
author intensity as "white-equivalent intent".

Originally proven out in ``crystal_field`` (see ``crystal_field/scene.py``);
hoisted here so every family can share the calibration.
"""

from __future__ import annotations

from functools import lru_cache

import _lpt2d

from .types import LightSpectrum

_WHITE_MIN = 380.0
_WHITE_MAX = 780.0


@lru_cache(maxsize=None)
def _mean_band_luminance(wl_min: float, wl_max: float) -> float:
    """Mean perceived luminance per photon for a uniform spectral band [nm]."""
    total = 0.0
    count = 0
    for nm in range(int(wl_min), int(wl_max) + 1):
        r, g, b = _lpt2d.wavelength_to_rgb(float(nm))
        total += 0.2126 * r + 0.7152 * g + 0.0722 * b
        count += 1
    return total / max(count, 1)


_WHITE_MEAN = _mean_band_luminance(_WHITE_MIN, _WHITE_MAX)


def spectral_luminance_boost(wl_min: float, wl_max: float) -> float:
    """Intensity multiplier so a uniform [wl_min, wl_max] band matches white."""
    band = _mean_band_luminance(wl_min, wl_max)
    if band < 1e-8:
        return 1.0
    return _WHITE_MEAN / band


def _color_luminance(r: float, g: float, b: float, white_mix: float) -> float:
    r2 = r + (1.0 - r) * white_mix
    g2 = g + (1.0 - g) * white_mix
    b2 = b + (1.0 - b) * white_mix
    return 0.2126 * r2 + 0.7152 * g2 + 0.0722 * b2


def intensity_for_spectrum(
    white_intensity: float,
    spectrum: LightSpectrum,
    *,
    white_mix: float = 0.0,
) -> float:
    """Convert white-equivalent intent to render-time ``intensity``.

    ``spectrum.type`` is either "range" (uniform band) or "color" (RGB point
    in sigmoid space). Range spectra use :func:`spectral_luminance_boost`;
    color spectra scale by the inverse perceived luminance of their linear RGB.

    Parameters
    ----------
    white_intensity : float
        Intensity the caller would use for full-spectrum white.
    spectrum : LightSpectrum
        The light's spectrum; ``.type`` is inspected.
    white_mix : float
        Only used for ``color`` spectra — matches ``LightSpectrum.color``'s
        ``white_mix`` argument, since the emitted luminance includes it.
    """
    if spectrum.type == "range":
        return white_intensity * spectral_luminance_boost(
            spectrum.wavelength_min, spectrum.wavelength_max
        )
    # color spectrum: scale inversely by perceived luminance of the resolved RGB
    lum = _color_luminance(
        spectrum.linear_r, spectrum.linear_g, spectrum.linear_b, white_mix
    )
    return white_intensity / max(lum, 1e-4)
