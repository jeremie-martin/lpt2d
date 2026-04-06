#include "color.h"
#include "spectrum.h"

#include <algorithm>
#include <cmath>

// ─── Sigmoid spectral model ────────────────────────────────────────────

static float sigmoid(float x) {
    return 0.5f + x / (2.0f * std::sqrt(1.0f + x * x));
}

static float sigmoid_deriv(float x) {
    float s = 1.0f + x * x;
    return 1.0f / (2.0f * s * std::sqrt(s));
}

// Evaluate spectral reflectance at normalized wavelength t ∈ [0,1]
static float spectral_eval(float t, float c0, float c1, float c2) {
    return sigmoid(c0 + c1 * t + c2 * t * t);
}

// Number of integration samples (5nm spacing over [380,780])
static constexpr int SPEC_N = 81;

struct SpecLUT {
    float t[SPEC_N];     // normalized wavelength: (nm - 380) / 400
    float r[SPEC_N], g[SPEC_N], b[SPEC_N]; // white-balanced sRGB from wavelength_to_rgb
};

static const SpecLUT& get_spec_lut() {
    static const SpecLUT lut = [] {
        SpecLUT l{};
        for (int i = 0; i < SPEC_N; ++i) {
            float nm = 380.0f + i * 5.0f;
            l.t[i] = (nm - 380.0f) / 400.0f;
            Vec3 rgb = wavelength_to_rgb(nm);
            l.r[i] = rgb.r;
            l.g[i] = rgb.g;
            l.b[i] = rgb.b;
        }
        return l;
    }();
    return lut;
}

// ─── Forward: spectral coefficients → perceived RGB ────────────────────

Vec3 spectral_to_rgb(float c0, float c1, float c2) {
    const auto& lut = get_spec_lut();
    float sr = 0, sg = 0, sb = 0;
    for (int i = 0; i < SPEC_N; ++i) {
        float R = spectral_eval(lut.t[i], c0, c1, c2);
        sr += R * lut.r[i];
        sg += R * lut.g[i];
        sb += R * lut.b[i];
    }
    float scale = 1.0f / SPEC_N;
    return {sr * scale, sg * scale, sb * scale};
}

// ─── Inverse: RGB → spectral coefficients (Gauss-Newton) ──────────────

// Solve 3×3 system Ax = b via Cramer's rule
static bool solve3(const float A[3][3], const float b[3], float x[3]) {
    float det = A[0][0] * (A[1][1] * A[2][2] - A[1][2] * A[2][1])
              - A[0][1] * (A[1][0] * A[2][2] - A[1][2] * A[2][0])
              + A[0][2] * (A[1][0] * A[2][1] - A[1][1] * A[2][0]);
    if (std::abs(det) < 1e-12f) return false;
    float inv = 1.0f / det;
    x[0] = inv * (b[0] * (A[1][1]*A[2][2] - A[1][2]*A[2][1])
                - A[0][1] * (b[1]*A[2][2] - A[1][2]*b[2])
                + A[0][2] * (b[1]*A[2][1] - A[1][1]*b[2]));
    x[1] = inv * (A[0][0] * (b[1]*A[2][2] - A[1][2]*b[2])
                - b[0] * (A[1][0]*A[2][2] - A[1][2]*A[2][0])
                + A[0][2] * (A[1][0]*b[2] - b[1]*A[2][0]));
    x[2] = inv * (A[0][0] * (A[1][1]*b[2] - b[1]*A[2][1])
                - A[0][1] * (A[1][0]*b[2] - b[1]*A[2][0])
                + b[0] * (A[1][0]*A[2][1] - A[1][1]*A[2][0]));
    return true;
}

SpectralCoeffs rgb_to_spectral(float r, float g, float b) {
    const auto& lut = get_spec_lut();
    float target[3] = {r, g, b};
    float c0 = 0.0f, c1 = 0.0f, c2 = 0.0f;

    for (int iter = 0; iter < 40; ++iter) {
        // Forward pass + Jacobian accumulation
        float cur[3] = {0, 0, 0};
        float J[3][3] = {};
        for (int i = 0; i < SPEC_N; ++i) {
            float t = lut.t[i];
            float poly = c0 + c1 * t + c2 * t * t;
            float s = sigmoid(poly);
            float ds = sigmoid_deriv(poly);

            float rgb[3] = {lut.r[i], lut.g[i], lut.b[i]};
            float dpoly[3] = {1.0f, t, t * t}; // d(poly)/d(c0,c1,c2)

            for (int ch = 0; ch < 3; ++ch) {
                cur[ch] += s * rgb[ch];
                for (int k = 0; k < 3; ++k)
                    J[ch][k] += ds * dpoly[k] * rgb[ch];
            }
        }

        float scale = 1.0f / SPEC_N;
        for (int ch = 0; ch < 3; ++ch) {
            cur[ch] *= scale;
            for (int k = 0; k < 3; ++k)
                J[ch][k] *= scale;
        }

        // Residual and convergence check
        float res[3] = {cur[0] - target[0], cur[1] - target[1], cur[2] - target[2]};
        float err = res[0]*res[0] + res[1]*res[1] + res[2]*res[2];
        if (err < 1e-10f) break;

        // Gauss-Newton: solve J·Δ = -res
        float neg_res[3] = {-res[0], -res[1], -res[2]};
        float delta[3];
        if (!solve3(J, neg_res, delta)) break;

        // Damped update (clamp step size for stability)
        float step = 1.0f;
        float mag = std::sqrt(delta[0]*delta[0] + delta[1]*delta[1] + delta[2]*delta[2]);
        if (mag > 5.0f) step = 5.0f / mag;

        c0 += step * delta[0];
        c1 += step * delta[1];
        c2 += step * delta[2];
    }

    return {c0, c1, c2};
}

// ─── Named colors ──────────────────────────────────────────────────────

static const NamedColorEntry kNamedColors[] = {
    // Spectral colors
    {"red",     1.0f, 0.0f, 0.0f},
    {"orange",  1.0f, 0.5f, 0.0f},
    {"amber",   1.0f, 0.75f, 0.0f},
    {"yellow",  1.0f, 1.0f, 0.0f},
    {"green",   0.0f, 1.0f, 0.0f},
    {"cyan",    0.0f, 1.0f, 1.0f},
    {"blue",    0.0f, 0.0f, 1.0f},
    {"violet",  0.5f, 0.0f, 1.0f},
    // Non-spectral colors (now possible!)
    {"pink",    1.0f, 0.4f, 0.6f},
    {"magenta", 1.0f, 0.0f, 1.0f},
    {"purple",  0.6f, 0.0f, 1.0f},
    {"warm",    1.0f, 0.85f, 0.7f},
    {"cool",    0.7f, 0.85f, 1.0f},
    {"gold",    1.0f, 0.84f, 0.0f},
    {nullptr,   0.0f, 0.0f, 0.0f},
};

std::optional<SpectralCoeffs> named_color(std::string_view name) {
    for (const auto* entry = kNamedColors; entry->name; ++entry) {
        if (name == entry->name)
            return rgb_to_spectral(entry->r, entry->g, entry->b);
    }
    return std::nullopt;
}

const NamedColorEntry* named_colors() { return kNamedColors; }

int named_color_count() {
    int n = 0;
    for (const auto* e = kNamedColors; e->name; ++e) ++n;
    return n;
}
