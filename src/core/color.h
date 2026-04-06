#pragma once

#include "scene.h"
#include <optional>
#include <string_view>

// Three-coefficient sigmoid spectral model (Jakob & Hanika 2019).
// Reflectance R(λ) = sigmoid(c0 + c1·t + c2·t²) where t = (λ-380)/400.
// All zeros = spectrally neutral (shader returns 1.0 for all wavelengths).

struct SpectralCoeffs {
    float c0, c1, c2;
};

struct NamedColorEntry {
    const char* name;
    float r, g, b; // linear sRGB
};

// Convert linear sRGB to sigmoid spectral coefficients via Gauss-Newton optimization.
// Uses the existing wavelength_to_rgb LUT for spectral integration.
SpectralCoeffs rgb_to_spectral(float r, float g, float b);

// Compute perceived linear sRGB from spectral coefficients (for fill color, GUI, etc.)
Vec3 spectral_to_rgb(float c0, float c1, float c2);

// Resolve a named color to spectral coefficients. Returns nullopt for unknown names.
std::optional<SpectralCoeffs> named_color(std::string_view name);

// List all known named colors (null-terminated array).
const NamedColorEntry* named_colors();
int named_color_count();
