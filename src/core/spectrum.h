#pragma once

#include "scene.h"

// Convert wavelength (nm) in visible range [380, 780] to linear sRGB.
// Uses CIE 1931 color matching functions (piecewise Gaussian fit).
Vec3 wavelength_to_rgb(float nm);

// Compute fill RGB from spectral parameters by integrating a Gaussian passband
// against the CIE matching functions. Returns neutral white {1,1,1} when
// wavelength <= 0 (spectrally neutral). Result is normalized so max channel = 1.
Vec3 spectral_fill_rgb(float wavelength, float bandwidth);
