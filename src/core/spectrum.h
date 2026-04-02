#pragma once

#include "scene.h"

// Convert wavelength (nm) in visible range [380, 780] to linear sRGB.
// Uses CIE 1931 color matching functions (piecewise Gaussian fit).
Vec3 wavelength_to_rgb(float nm);
