#include "spectrum.h"
#include "color.h"

#include <algorithm>
#include <array>
#include <cmath>

// CIE 1931 color matching functions — piecewise Gaussian approximation
// Reference: Wyman, Sloan, Shirley (2013)

static float gaussian(float x, float mu, float sigma1, float sigma2) {
    float t = (x - mu) / (x < mu ? sigma1 : sigma2);
    return std::exp(-0.5f * t * t);
}

static Vec3 compute_rgb(float nm) {
    float cx = 1.056f * gaussian(nm, 599.8f, 37.9f, 31.0f) + 0.362f * gaussian(nm, 442.0f, 16.0f, 26.7f) -
               0.065f * gaussian(nm, 501.1f, 20.4f, 26.2f);
    float cy = 0.821f * gaussian(nm, 568.8f, 46.9f, 40.5f) + 0.286f * gaussian(nm, 530.9f, 16.3f, 31.1f);
    float cz = 1.217f * gaussian(nm, 437.0f, 11.8f, 36.0f) + 0.681f * gaussian(nm, 459.0f, 26.0f, 13.8f);

    float r = std::max(0.0f, 3.2406f * cx - 1.5372f * cy - 0.4986f * cz);
    float g = std::max(0.0f, -0.9689f * cx + 1.8758f * cy + 0.0415f * cz);
    float b = std::max(0.0f, 0.0557f * cx - 0.2040f * cy + 1.0570f * cz);

    // White-balance: uniform sampling [380,780] → neutral white
    constexpr float norm_r = 0.439366f, norm_g = 0.287747f, norm_b = 0.272568f;
    return {r / norm_r, g / norm_g, b / norm_b};
}

// Precomputed LUT: 401 entries at 1nm spacing [380..780]
static const auto& get_lut() {
    static const auto lut = [] {
        std::array<Vec3, 401> table;
        for (int i = 0; i <= 400; ++i)
            table[i] = compute_rgb(380.0f + i);
        return table;
    }();
    return lut;
}

Vec3 wavelength_to_rgb(float nm) {
    nm = std::clamp(nm, 380.0f, 780.0f);
    float idx = nm - 380.0f;
    int i = std::min((int)idx, 399);
    float frac = idx - i;
    const auto& lut = get_lut();
    const Vec3& a = lut[i];
    const Vec3& b = lut[i + 1];
    return {a.r + (b.r - a.r) * frac, a.g + (b.g - a.g) * frac, a.b + (b.b - a.b) * frac};
}

Vec3 spectral_fill_rgb(float c0, float c1, float c2) {
    Vec3 raw = spectral_to_rgb(c0, c1, c2);
    float m = std::max({raw.r, raw.g, raw.b, 1e-6f});
    return {raw.r / m, raw.g / m, raw.b / m};
}
