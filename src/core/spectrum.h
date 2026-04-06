#pragma once

#include "scene.h"

// Convert wavelength (nm) in visible range [380, 780] to linear sRGB.
// Uses CIE 1931 color matching functions (piecewise Gaussian fit).
Vec3 wavelength_to_rgb(float nm);

// Compute fill RGB from sigmoid spectral coefficients. Returns neutral white
// {1,1,1} when all coefficients are zero. Result is normalized so max channel = 1.
Vec3 spectral_fill_rgb(float c0, float c1, float c2);
