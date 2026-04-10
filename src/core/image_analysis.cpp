#include "image_analysis.h"

#include "scene.h"  // for Bounds, Vec2

#include <algorithm>
#include <array>
#include <cmath>
#include <cstddef>
#include <limits>
#include <vector>

namespace {

// BT.709 integer-approximation weights that match the GLSL post-process
// shader and the historical renderer.cpp histogram loop:
//   lum = (218*R + 732*G + 74*B) >> 10
// Keeping the same weights is important so pixel-by-pixel the GUI stats
// panel and the Python metrics dict report identical numbers.
constexpr std::uint32_t BT709_R = 218;
constexpr std::uint32_t BT709_G = 732;
constexpr std::uint32_t BT709_B = 74;

// Float BT.709 weights used on 0..1 linear data (light-circle path).
constexpr float BT709_RF = 0.2126f;
constexpr float BT709_GF = 0.7152f;
constexpr float BT709_BF = 0.0722f;

// Convert a 256-bin histogram over n_pixels into a LuminanceStats bundle.
// This is pulled out of the RGB8/RGBA8/HDR paths because all three produce
// the same histogram shape; only the per-pixel loop differs.
//
// `clipped` is the count of pixels with any channel == 255 (LDR) or any
// channel >= 1.0 (HDR, computed by the caller).
// `squared_sum` is Σ(i² · hist[i]) — passed in so callers can compute it in
// the same sweep as the histogram increment.
LuminanceStats finalize_luminance(const std::array<int, 256>& histogram,
                                  std::size_t clipped, double sum,
                                  double squared_sum, int width, int height) {
    LuminanceStats s;
    s.histogram = histogram;
    s.width = width;
    s.height = height;

    const std::size_t n = static_cast<std::size_t>(width) * static_cast<std::size_t>(height);
    if (n == 0) {
        return s;
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

// Per-pixel luminance on a 0..1 float scale (matches Python light_circle.py).
inline float lum01_u8(std::uint8_t r, std::uint8_t g, std::uint8_t b) {
    return (BT709_RF * static_cast<float>(r)
            + BT709_GF * static_cast<float>(g)
            + BT709_BF * static_cast<float>(b)) / 255.0f;
}

inline float lum01_f(float r, float g, float b) {
    return BT709_RF * r + BT709_GF * g + BT709_BF * b;
}

// Shared Voronoi-per-pixel light-circle reduction.
//
// The template parameter `GetLum` is a callable `(int x, int y) -> float`
// that returns per-pixel luminance in 0..1 (or higher for HDR). Keeps the
// LDR and HDR paths one function.
template <typename GetLum>
std::vector<LightCircle>
measure_light_circles_impl(int width, int height,
                           const Bounds& world_bounds,
                           std::span<const LightRef> lights,
                           const LightCircleParams& p,
                           GetLum get_lum) {
    const int L = static_cast<int>(lights.size());
    std::vector<LightCircle> out;
    out.reserve(L);

    // Per-light centres in pixel space.
    const auto vp = viewport_xform(world_bounds, width, height);
    struct Center { float x, y; };
    std::vector<Center> centers;
    centers.reserve(L);
    for (const auto& lr : lights) {
        const float px = (lr.world_x - world_bounds.min.x) * vp.scale + vp.offset_x;
        const float py = (world_bounds.max.y - lr.world_y) * vp.scale + vp.offset_y;
        centers.push_back({px, py});
    }

    if (L == 0 || width <= 0 || height <= 0) {
        return out;
    }

    const int max_r = std::max(0, p.max_radius_px);
    const int bins = max_r + 1;

    // Per-light accumulators.
    std::vector<std::vector<float>> bright_dists(L);
    std::vector<std::vector<double>> profile_sum(L, std::vector<double>(bins, 0.0));
    std::vector<std::vector<std::uint32_t>>
        profile_cnt(L, std::vector<std::uint32_t>(bins, 0u));

    double total_lum = 0.0;
    const std::size_t n_pixels = static_cast<std::size_t>(width) * static_cast<std::size_t>(height);

    // Single pass: per pixel, find nearest light (O(L)), accumulate profile
    // bin and bright-distance list.
    for (int y = 0; y < height; ++y) {
        for (int x = 0; x < width; ++x) {
            const float lum = get_lum(x, y);
            total_lum += static_cast<double>(lum);

            // Nearest light via squared-distance scan.
            int best = 0;
            float best_d2 = std::numeric_limits<float>::infinity();
            for (int i = 0; i < L; ++i) {
                const float dx = static_cast<float>(x) - centers[i].x;
                const float dy = static_cast<float>(y) - centers[i].y;
                const float d2 = dx * dx + dy * dy;
                if (d2 < best_d2) {
                    best_d2 = d2;
                    best = i;
                }
            }
            const float d = std::sqrt(best_d2);
            const int di = std::min(static_cast<int>(std::lround(d)), max_r);
            profile_sum[best][di] += static_cast<double>(lum);
            profile_cnt[best][di] += 1u;

            if (lum >= p.bright_threshold && d < static_cast<float>(max_r)) {
                bright_dists[best].push_back(d);
            }
        }
    }

    const float mean_lum = n_pixels > 0
        ? static_cast<float>(total_lum / static_cast<double>(n_pixels))
        : 0.0f;

    for (int i = 0; i < L; ++i) {
        LightCircle c;
        c.id = lights[i].id;
        c.world_x = lights[i].world_x;
        c.world_y = lights[i].world_y;
        c.pixel_x = centers[i].x;
        c.pixel_y = centers[i].y;
        c.mean_luminance = mean_lum;

        // Radial profile: per-bin mean luminance in the Voronoi cell.
        c.profile.assign(bins, 0.0f);
        for (int r = 0; r < bins; ++r) {
            if (profile_cnt[i][r] > 0) {
                c.profile[r] = static_cast<float>(
                    profile_sum[i][r] / static_cast<double>(profile_cnt[i][r]));
            }
        }

        c.n_bright_pixels = static_cast<int>(bright_dists[i].size());

        // Primary radius: percentile of bright-pixel distances.
        if (c.n_bright_pixels >= p.min_bright_pixels) {
            auto& bd = bright_dists[i];
            const float pct_frac = std::clamp(p.radius_percentile / 100.0f, 0.0f, 1.0f);
            std::size_t k = static_cast<std::size_t>(
                std::floor(static_cast<float>(bd.size()) * pct_frac));
            if (k >= bd.size()) k = bd.size() - 1;
            std::nth_element(bd.begin(), bd.begin() + static_cast<std::ptrdiff_t>(k), bd.end());
            c.radius_px = bd[k];
        } else {
            c.radius_px = 0.0f;
        }

        // Secondary radius: smallest r where profile drops to
        // `half_max_fraction * peak`. Peak is the profile's max value, so
        // this is a classic FWHM when half_max_fraction == 0.5.
        float peak = 0.0f;
        for (int r = 0; r < bins; ++r) {
            peak = std::max(peak, c.profile[r]);
        }
        const float half_target = peak * p.half_max_fraction;
        float hm_radius = 0.0f;
        if (peak > 0.0f) {
            for (int r = 0; r < bins; ++r) {
                if (c.profile[r] < half_target) {
                    hm_radius = static_cast<float>(r);
                    break;
                }
            }
        }
        c.radius_half_max_px = hm_radius;

        // Sharpness: luminance drop per pixel across [0.5r, 1.5r].
        c.sharpness = 0.0f;
        if (c.radius_px > 2.0f) {
            const int r_lo = std::max(1, static_cast<int>(c.radius_px * 0.5f));
            const int r_hi = std::min(max_r - 1, static_cast<int>(c.radius_px * 1.5f) + 1);
            if (r_hi > r_lo) {
                c.sharpness = (c.profile[r_lo] - c.profile[r_hi])
                            / static_cast<float>(r_hi - r_lo);
            }
        }

        out.push_back(std::move(c));
    }

    return out;
}

}  // namespace

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

// ───────────────────────────────────────────────────────────────────────────
// compute_luminance_stats (RGB8 / RGBA8 / HDR)
// ───────────────────────────────────────────────────────────────────────────

LuminanceStats compute_luminance_stats(const uint8_t* rgb, int width, int height) {
    std::array<int, 256> histogram{};
    std::size_t clipped = 0;
    double sum = 0.0;
    double squared_sum = 0.0;

    if (rgb == nullptr || width <= 0 || height <= 0) {
        return finalize_luminance(histogram, clipped, sum, squared_sum, width, height);
    }

    const std::size_t n_pixels = static_cast<std::size_t>(width) * static_cast<std::size_t>(height);
    for (std::size_t i = 0; i < n_pixels; ++i) {
        const std::uint8_t r = rgb[3 * i + 0];
        const std::uint8_t g = rgb[3 * i + 1];
        const std::uint8_t b = rgb[3 * i + 2];
        std::uint32_t lum = (BT709_R * r + BT709_G * g + BT709_B * b) >> 10;
        if (lum > 255) lum = 255;
        histogram[lum] += 1;
        sum += static_cast<double>(lum);
        squared_sum += static_cast<double>(lum) * static_cast<double>(lum);
        if (r == 255 || g == 255 || b == 255) ++clipped;
    }

    return finalize_luminance(histogram, clipped, sum, squared_sum, width, height);
}

LuminanceStats compute_luminance_stats_rgba(const uint8_t* rgba, int width, int height) {
    std::array<int, 256> histogram{};
    std::size_t clipped = 0;
    double sum = 0.0;
    double squared_sum = 0.0;

    if (rgba == nullptr || width <= 0 || height <= 0) {
        return finalize_luminance(histogram, clipped, sum, squared_sum, width, height);
    }

    const std::size_t n_pixels = static_cast<std::size_t>(width) * static_cast<std::size_t>(height);
    for (std::size_t i = 0; i < n_pixels; ++i) {
        const std::uint8_t r = rgba[4 * i + 0];
        const std::uint8_t g = rgba[4 * i + 1];
        const std::uint8_t b = rgba[4 * i + 2];
        std::uint32_t lum = (BT709_R * r + BT709_G * g + BT709_B * b) >> 10;
        if (lum > 255) lum = 255;
        histogram[lum] += 1;
        sum += static_cast<double>(lum);
        squared_sum += static_cast<double>(lum) * static_cast<double>(lum);
        if (r == 255 || g == 255 || b == 255) ++clipped;
    }

    return finalize_luminance(histogram, clipped, sum, squared_sum, width, height);
}

LuminanceStats compute_luminance_stats_hdr(const float* rgb, int width, int height) {
    std::array<int, 256> histogram{};
    std::size_t clipped = 0;
    double sum = 0.0;
    double squared_sum = 0.0;

    if (rgb == nullptr || width <= 0 || height <= 0) {
        return finalize_luminance(histogram, clipped, sum, squared_sum, width, height);
    }

    const std::size_t n_pixels = static_cast<std::size_t>(width) * static_cast<std::size_t>(height);

    // Two-pass: first find the maximum raw luminance so we can normalise
    // the histogram into a 0..255 range that is comparable with the LDR
    // path regardless of the absolute accumulation scale. NaN/Inf inputs
    // (from a misbehaving shader or corrupt buffer) are filtered out so
    // the metrics stay finite instead of propagating garbage to callers.
    float raw_max = 0.0f;
    for (std::size_t i = 0; i < n_pixels; ++i) {
        const float r = rgb[3 * i + 0];
        const float g = rgb[3 * i + 1];
        const float b = rgb[3 * i + 2];
        const float l = lum01_f(r, g, b);
        if (std::isfinite(l) && l > raw_max) raw_max = l;
    }
    const float inv_max = (raw_max > 1e-6f) ? (1.0f / raw_max) : 1.0f;

    for (std::size_t i = 0; i < n_pixels; ++i) {
        const float r = rgb[3 * i + 0];
        const float g = rgb[3 * i + 1];
        const float b = rgb[3 * i + 2];
        float lum_raw = lum01_f(r, g, b);
        if (!std::isfinite(lum_raw)) lum_raw = 0.0f;
        const float norm = std::clamp(lum_raw * inv_max, 0.0f, 1.0f);
        int bin = static_cast<int>(std::lround(norm * 255.0f));
        if (bin < 0) bin = 0;
        if (bin > 255) bin = 255;
        histogram[bin] += 1;
        sum += static_cast<double>(bin);
        squared_sum += static_cast<double>(bin) * static_cast<double>(bin);
        // Count pixels that would clip in a naive 0..1 LDR viewer, measured
        // on the RAW linear values so callers can distinguish "physically
        // bright" frames from "over-exposed tonemap" frames. Use
        // std::isgreaterequal to avoid a NaN >= 1.0 surprise.
        if (std::isgreaterequal(r, 1.0f) || std::isgreaterequal(g, 1.0f) ||
            std::isgreaterequal(b, 1.0f)) ++clipped;
    }

    return finalize_luminance(histogram, clipped, sum, squared_sum, width, height);
}

// ───────────────────────────────────────────────────────────────────────────
// compute_color_stats
// ───────────────────────────────────────────────────────────────────────────

ColorStats compute_color_stats(const uint8_t* rgb, int width, int height,
                               float saturation_threshold) {
    ColorStats s;
    if (rgb == nullptr || width <= 0 || height <= 0) {
        return s;
    }

    const std::size_t n_pixels = static_cast<std::size_t>(width) * static_cast<std::size_t>(height);
    double sat_sum = 0.0;
    int n_chromatic = 0;

    for (std::size_t i = 0; i < n_pixels; ++i) {
        const int r = rgb[3 * i + 0];
        const int g = rgb[3 * i + 1];
        const int b = rgb[3 * i + 2];
        const int cmax = std::max({r, g, b});
        const int cmin = std::min({r, g, b});
        const int delta = cmax - cmin;
        if (cmax == 0 || delta == 0) continue;
        const float sat = static_cast<float>(delta) / static_cast<float>(cmax);
        if (sat <= saturation_threshold) continue;

        sat_sum += static_cast<double>(sat);
        ++n_chromatic;

        // HSV hue in 0..6, then normalise to 0..1 and bin to 36 buckets.
        float h_raw;
        if (r == cmax) {
            h_raw = static_cast<float>(g - b) / static_cast<float>(delta);
        } else if (g == cmax) {
            h_raw = 2.0f + static_cast<float>(b - r) / static_cast<float>(delta);
        } else {
            h_raw = 4.0f + static_cast<float>(r - g) / static_cast<float>(delta);
        }
        float h = h_raw / 6.0f;
        h = h - std::floor(h);  // (x mod 1) — handles negative h_raw
        int bin = static_cast<int>(std::floor(h * 36.0f));
        if (bin < 0) bin = 0;
        if (bin > 35) bin = 35;
        s.hue_histogram[bin] += 1;
    }

    s.n_chromatic = n_chromatic;
    s.chromatic_fraction = n_pixels > 0
        ? static_cast<float>(n_chromatic) / static_cast<float>(n_pixels)
        : 0.0f;
    s.mean_saturation = n_chromatic > 0
        ? static_cast<float>(sat_sum / static_cast<double>(n_chromatic))
        : 0.0f;

    // Shannon entropy of the 36-bin hue histogram (bits).
    if (n_chromatic > 0) {
        const double inv = 1.0 / static_cast<double>(n_chromatic);
        double entropy = 0.0;
        for (int k = 0; k < 36; ++k) {
            if (s.hue_histogram[k] > 0) {
                const double p = static_cast<double>(s.hue_histogram[k]) * inv;
                entropy -= p * std::log2(p);
            }
        }
        s.hue_entropy = static_cast<float>(entropy);
    }

    s.color_richness = s.hue_entropy * s.mean_saturation * s.chromatic_fraction;
    return s;
}

// ───────────────────────────────────────────────────────────────────────────
// measure_light_circles (LDR / HDR)
// ───────────────────────────────────────────────────────────────────────────

std::vector<LightCircle>
measure_light_circles(const uint8_t* rgb, int width, int height,
                      const Bounds& world_bounds,
                      std::span<const LightRef> lights,
                      const LightCircleParams& params) {
    if (rgb == nullptr || width <= 0 || height <= 0) {
        return {};
    }
    auto get_lum = [rgb, width](int x, int y) -> float {
        const std::size_t i = (static_cast<std::size_t>(y) * static_cast<std::size_t>(width)
                               + static_cast<std::size_t>(x)) * 3u;
        return lum01_u8(rgb[i + 0], rgb[i + 1], rgb[i + 2]);
    };
    return measure_light_circles_impl(width, height, world_bounds, lights, params, get_lum);
}

std::vector<LightCircle>
measure_light_circles_hdr(const float* rgb, int width, int height,
                          const Bounds& world_bounds,
                          std::span<const LightRef> lights,
                          const LightCircleParams& params) {
    if (rgb == nullptr || width <= 0 || height <= 0) {
        return {};
    }
    // First pass: find the frame's max BT.709 luminance so the threshold
    // in `params.bright_threshold` can be interpreted as a fraction of the
    // frame's dynamic range (same 0..1 semantics as the LDR path).
    // NaN/Inf pixels are skipped here and clamped to 0 in `get_lum` so a
    // bad shader doesn't poison the Voronoi / bright-mask / profile pass.
    const std::size_t n_pixels = static_cast<std::size_t>(width) * static_cast<std::size_t>(height);
    float raw_max = 0.0f;
    for (std::size_t i = 0; i < n_pixels; ++i) {
        const float l = lum01_f(rgb[3 * i + 0], rgb[3 * i + 1], rgb[3 * i + 2]);
        if (std::isfinite(l) && l > raw_max) raw_max = l;
    }
    const float inv_max = (raw_max > 1e-6f) ? (1.0f / raw_max) : 1.0f;

    auto get_lum = [rgb, width, inv_max](int x, int y) -> float {
        const std::size_t i = (static_cast<std::size_t>(y) * static_cast<std::size_t>(width)
                               + static_cast<std::size_t>(x)) * 3u;
        const float l = lum01_f(rgb[i + 0], rgb[i + 1], rgb[i + 2]) * inv_max;
        return std::isfinite(l) ? l : 0.0f;
    };
    return measure_light_circles_impl(width, height, world_bounds, lights, params, get_lum);
}

// ───────────────────────────────────────────────────────────────────────────
// analyze_frame
// ───────────────────────────────────────────────────────────────────────────

FrameAnalysis analyze_frame(const uint8_t* rgb, int width, int height,
                            const Bounds& world_bounds,
                            std::span<const LightRef> lights,
                            const float* hdr_rgb,
                            const FrameAnalysisParams& params) {
    FrameAnalysis a;
    if (params.analyze_luminance) {
        a.lum = compute_luminance_stats(rgb, width, height);
    }
    if (params.analyze_color) {
        a.color = compute_color_stats(rgb, width, height, params.saturation_threshold);
    }
    if (params.analyze_circles && !lights.empty()) {
        if (hdr_rgb != nullptr && params.prefer_hdr_circles) {
            a.circles = measure_light_circles_hdr(hdr_rgb, width, height, world_bounds,
                                                  lights, params.circles);
        } else {
            a.circles = measure_light_circles(rgb, width, height, world_bounds,
                                              lights, params.circles);
        }
    }
    return a;
}
