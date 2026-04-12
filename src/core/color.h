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

struct RangeToColorSpectrum {
    LightSpectrum spectrum;
    float intensity_scale;
    Vec3 averaged_rgb;
    Vec3 fitted_rgb;
};

// Convert linear sRGB to sigmoid spectral coefficients via Gauss-Newton optimization.
// Uses the existing wavelength_to_rgb LUT for spectral integration.
SpectralCoeffs rgb_to_spectral(float r, float g, float b);

// Compute perceived linear sRGB from spectral coefficients (for fill color, GUI, etc.)
Vec3 spectral_to_rgb(float c0, float c1, float c2);

// Build a light emission spectrum from authored RGB plus a perceptual white mix.
// The resulting spectrum still emits sampled wavelengths; RGB is only the
// authoring target used to fit the sigmoid spectral coefficients.
LightSpectrum light_spectrum_color(float r, float g, float b, float white_mix = 0.0f);

// Build a color spectrum directly from coefficients. Used for runtime shape
// emission derived from material spectral coefficients.
LightSpectrum light_spectrum_from_coeffs(float c0, float c1, float c2);

// Convert a legacy uniform wavelength range to a fitted color spectrum plus a
// scalar that should be multiplied into light intensity to preserve the old
// range's linear RGB energy as closely as the three-coefficient model allows.
RangeToColorSpectrum range_to_color_spectrum(float wl_min, float wl_max, float headroom = 1.0f);

// Resolve a named color to spectral coefficients. Returns nullopt for unknown names.
std::optional<SpectralCoeffs> named_color(std::string_view name);

// List all known named colors (null-terminated array).
const NamedColorEntry* named_colors();
int named_color_count();
