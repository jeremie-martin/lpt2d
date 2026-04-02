#include "spectrum.h"

#include <algorithm>
#include <cmath>

// CIE 1931 color matching functions — piecewise Gaussian approximation
// Reference: Wyman, Sloan, Shirley (2013) "Simple Analytic Approximations to the CIE XYZ Color Matching Functions"

static float gaussian(float x, float mu, float sigma1, float sigma2) {
    float t = (x - mu) / (x < mu ? sigma1 : sigma2);
    return std::exp(-0.5f * t * t);
}

static float cie_x(float nm) {
    return 1.056f * gaussian(nm, 599.8f, 37.9f, 31.0f) + 0.362f * gaussian(nm, 442.0f, 16.0f, 26.7f) -
           0.065f * gaussian(nm, 501.1f, 20.4f, 26.2f);
}

static float cie_y(float nm) {
    return 0.821f * gaussian(nm, 568.8f, 46.9f, 40.5f) + 0.286f * gaussian(nm, 530.9f, 16.3f, 31.1f);
}

static float cie_z(float nm) {
    return 1.217f * gaussian(nm, 437.0f, 11.8f, 36.0f) + 0.681f * gaussian(nm, 459.0f, 26.0f, 13.8f);
}

Vec3 wavelength_to_rgb(float nm) {
    nm = std::clamp(nm, 380.0f, 780.0f);

    float x = cie_x(nm);
    float y = cie_y(nm);
    float z = cie_z(nm);

    // CIE XYZ to linear sRGB (D65 illuminant)
    float r = 3.2406f * x - 1.5372f * y - 0.4986f * z;
    float g = -0.9689f * x + 1.8758f * y + 0.0415f * z;
    float b = 0.0557f * x - 0.2040f * y + 1.0570f * z;

    // Clamp negatives (out-of-gamut wavelengths)
    r = std::max(0.0f, r);
    g = std::max(0.0f, g);
    b = std::max(0.0f, b);

    // Normalize so uniform wavelength sampling (380–780nm) produces white.
    // Without this, the red channel dominates (~0.44 avg vs ~0.27 blue), causing a warm tint.
    // Constants: average of each channel over [380,780] at 1nm resolution.
    constexpr float norm_r = 0.439366f;
    constexpr float norm_g = 0.287747f;
    constexpr float norm_b = 0.272568f;

    return {r / norm_r, g / norm_g, b / norm_b};
}
