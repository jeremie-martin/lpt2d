#include "image_analysis.h"

#include "scene.h"  // for Bounds, Vec2

#include <algorithm>
#include <array>
#include <cmath>
#include <cstddef>

// ───────────────────────────────────────────────────────────────────────────
// finalize_luminance
// ───────────────────────────────────────────────────────────────────────────
//
// Takes a populated 256-bin histogram over the BT.709 integer luminance of
// a w*h image (plus the number of pixels whose channels saturated at 255)
// and derives every scalar field of LuminanceStats. Called by the GPU
// compute-shader path in gpu_image_analysis.cpp after the analysis SSBO
// has been mapped back to the CPU, and by the native test fixtures.

LuminanceStats finalize_luminance(const std::array<int, 256>& histogram,
                                  int clipped, int width, int height) {
    LuminanceStats s;
    s.histogram = histogram;
    s.width = width;
    s.height = height;

    const std::size_t n = static_cast<std::size_t>(width) * static_cast<std::size_t>(height);
    if (n == 0) {
        return s;
    }

    // Derive Σ bin and Σ bin² from the histogram itself. 256 ops total —
    // the GPU path has no pixel-loop sum to pass in, and this keeps the
    // mean/std math in one place regardless of caller.
    double sum = 0.0;
    double squared_sum = 0.0;
    for (int i = 0; i < 256; ++i) {
        const double count = static_cast<double>(histogram[i]);
        sum += count * static_cast<double>(i);
        squared_sum += count * static_cast<double>(i) * static_cast<double>(i);
    }

    s.mean_lum = static_cast<float>(sum / static_cast<double>(n));
    s.pct_black = static_cast<float>(histogram[0]) / static_cast<float>(n);
    s.pct_clipped = static_cast<float>(clipped) / static_cast<float>(n);

    // Variance via E[X²] - E[X]²
    const double mean = sum / static_cast<double>(n);
    const double var = (squared_sum / static_cast<double>(n)) - mean * mean;
    s.std_dev = var > 0.0 ? static_cast<float>(std::sqrt(var)) : 0.0f;

    // Min / max: first and last populated histogram bins.
    s.lum_min = 0;
    s.lum_max = 0;
    for (int i = 0; i < 256; ++i) {
        if (histogram[i] > 0) {
            s.lum_min = i;
            break;
        }
    }
    for (int i = 255; i >= 0; --i) {
        if (histogram[i] > 0) {
            s.lum_max = i;
            break;
        }
    }

    // Percentiles via cumulative histogram. Match the renderer.cpp convention
    // of "first bin where cumulative count >= target_k".
    const auto target = [n](float pct) -> std::size_t {
        return static_cast<std::size_t>(pct * static_cast<float>(n));
    };
    const std::size_t t05 = target(0.05f);
    const std::size_t t50 = target(0.50f);
    const std::size_t t95 = target(0.95f);
    const std::size_t t99 = target(0.99f);

    float p05 = 255.0f, p50 = 255.0f, p95 = 255.0f, p99 = 255.0f;
    bool have05 = false, have50 = false, have95 = false, have99 = false;
    std::size_t cumul = 0;
    for (int i = 0; i < 256; ++i) {
        cumul += static_cast<std::size_t>(histogram[i]);
        if (!have05 && cumul >= t05) { p05 = static_cast<float>(i); have05 = true; }
        if (!have50 && cumul >= t50) { p50 = static_cast<float>(i); have50 = true; }
        if (!have95 && cumul >= t95) { p95 = static_cast<float>(i); have95 = true; }
        if (!have99 && cumul >= t99) { p99 = static_cast<float>(i); have99 = true; break; }
    }
    s.p05 = p05;
    s.p50 = p50;
    s.p95 = p95;
    s.p99 = p99;

    return s;
}

// ───────────────────────────────────────────────────────────────────────────
// viewport_xform
// ───────────────────────────────────────────────────────────────────────────

ViewportXform viewport_xform(const Bounds& bounds, int width, int height) {
    const Vec2 size = bounds.max - bounds.min;
    if (size.x <= 0.0f || size.y <= 0.0f || width <= 0 || height <= 0) {
        return {1.0f, 0.0f, 0.0f};
    }
    const float sx = static_cast<float>(width) / size.x;
    const float sy = static_cast<float>(height) / size.y;
    const float s = std::min(sx, sy);
    const float ox = (static_cast<float>(width) - size.x * s) * 0.5f;
    const float oy = (static_cast<float>(height) - size.y * s) * 0.5f;
    return {s, ox, oy};
}
