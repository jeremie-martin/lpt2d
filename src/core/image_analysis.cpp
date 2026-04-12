#include "image_analysis.h"

#include "scene.h"  // for Bounds, Vec2

#include <algorithm>
#include <array>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <limits>
#include <vector>

namespace {

constexpr float kColorfulnessNormalizingMax = 1.8f;
// Coarse-grid Sobel magnitude is multiplied by grid short side so geometric
// edges remain comparable across resolutions. A scale of 64 maps one full-frame
// hard black/white step to about 0.125 instead of saturating the metric.
constexpr float kLocalContrastGradientScale = 64.0f;

inline int bt709_luminance_u8(std::uint8_t r, std::uint8_t g, std::uint8_t b) {
    const std::uint32_t lum = (218u * r + 732u * g + 74u * b) >> 10;
    return static_cast<int>(std::min<std::uint32_t>(lum, 255u));
}

template <typename T>
T clamp01(T v) {
    return std::clamp(v, static_cast<T>(0), static_cast<T>(1));
}

float quantile_in_place(std::vector<float>& values, float pct) {
    if (values.empty()) return 0.0f;
    const float clamped = std::clamp(pct, 0.0f, 1.0f);
    const std::size_t idx = static_cast<std::size_t>(
        std::floor(clamped * static_cast<float>(values.size() - 1)));
    std::nth_element(values.begin(), values.begin() + static_cast<std::ptrdiff_t>(idx),
                     values.end());
    return values[idx];
}

int local_luma_cell_index(int x, int y) {
    return y * kLocalLumaGridMaxSide + x;
}

template <std::size_t N>
float histogram_quantile_unit(const std::array<int, N>& histogram,
                              std::size_t n,
                              float pct,
                              float denominator) {
    if (n == 0 || denominator <= 0.0f) return 0.0f;
    const double p = std::clamp(static_cast<double>(pct), 0.0, 1.0);
    const auto target = static_cast<std::size_t>(
        std::ceil(p * static_cast<double>(n)));
    const std::size_t rank = std::clamp<std::size_t>(target, 1u, n);
    std::size_t cumul = 0;
    for (std::size_t i = 0; i < N; ++i) {
        cumul += static_cast<std::size_t>(std::max(histogram[i], 0));
        if (cumul >= rank) {
            return static_cast<float>(i) / denominator;
        }
    }
    return static_cast<float>(N - 1u) / denominator;
}

template <std::size_t N>
double entropy_bits_from_histogram(const std::array<int, N>& histogram,
                                   std::size_t total) {
    if (total == 0) return 0.0;
    double entropy = 0.0;
    const double inv = 1.0 / static_cast<double>(total);
    for (int count_i : histogram) {
        if (count_i <= 0) continue;
        const double p = static_cast<double>(count_i) * inv;
        entropy -= p * std::log2(p);
    }
    return entropy;
}

float radius_signal_luminance01(float luminance, float gamma) {
    const float g = std::max(gamma, 0.05f);
    return std::pow(clamp01(luminance), 1.0f / g);
}

struct ProjectedLight {
    float x = 0.0f;
    float y = 0.0f;
};

int owner_for_pixel(int px, int py, std::span<const ProjectedLight> lights) {
    float best_d2 = std::numeric_limits<float>::max();
    int best_i = 0;
    for (int i = 0; i < static_cast<int>(lights.size()); ++i) {
        const float dx = static_cast<float>(px) - lights[i].x;
        const float dy = static_cast<float>(py) - lights[i].y;
        const float d2 = dx * dx + dy * dy;
        if (d2 < best_d2) {
            best_d2 = d2;
            best_i = i;
        }
    }
    return best_i;
}

int first_radius_below(const std::vector<float>& profile, float threshold) {
    for (int r = 0; r < static_cast<int>(profile.size()); ++r) {
        if (profile[r] < threshold) return r;
    }
    return static_cast<int>(profile.size()) - 1;
}

}  // namespace

LocalLumaGridSize local_luma_grid_size(int width, int height) {
    if (width <= 0 || height <= 0) return {};

    const int image_short = std::max(1, std::min(width, height));
    const int grid_short = std::min(image_short, kLocalLumaGridShortSide);

    if (width >= height) {
        const int grid_width = std::clamp(
            static_cast<int>(std::lround(static_cast<double>(width) *
                                         static_cast<double>(grid_short) /
                                         static_cast<double>(height))),
            1, std::min(width, kLocalLumaGridMaxSide));
        return {grid_width, grid_short};
    }

    const int grid_height = std::clamp(
        static_cast<int>(std::lround(static_cast<double>(height) *
                                     static_cast<double>(grid_short) /
                                     static_cast<double>(width))),
        1, std::min(height, kLocalLumaGridMaxSide));
    return {grid_short, grid_height};
}

double local_luma_grid_gradient_sum(std::span<const float> luma,
                                    LocalLumaGridSize grid) {
    if (grid.width <= 0 || grid.height <= 0 ||
        luma.size() < static_cast<std::size_t>(kLocalLumaGridCells)) {
        return 0.0;
    }

    const auto lum_at = [&](int x, int y) -> float {
        const int cx = std::clamp(x, 0, grid.width - 1);
        const int cy = std::clamp(y, 0, grid.height - 1);
        return luma[static_cast<std::size_t>(local_luma_cell_index(cx, cy))];
    };

    double sum = 0.0;
    for (int y = 0; y < grid.height; ++y) {
        for (int x = 0; x < grid.width; ++x) {
            const float tl = lum_at(x - 1, y - 1);
            const float tc = lum_at(x,     y - 1);
            const float tr = lum_at(x + 1, y - 1);
            const float ml = lum_at(x - 1, y);
            const float mr = lum_at(x + 1, y);
            const float bl = lum_at(x - 1, y + 1);
            const float bc = lum_at(x,     y + 1);
            const float br = lum_at(x + 1, y + 1);
            const float gx = -tl - 2.0f * ml - bl + tr + 2.0f * mr + br;
            const float gy = -tl - 2.0f * tc - tr + bl + 2.0f * bc + br;
            sum += static_cast<double>(std::sqrt(gx * gx + gy * gy));
        }
    }
    return sum;
}

void finalize_image_stats(const ImageAnalysisInputs& inputs,
                          const ImageAnalysisThresholds& thresholds,
                          ImageStats& image,
                          ImageDebugStats& debug) {
    image = {};
    debug = {};
    image.width = inputs.width;
    image.height = inputs.height;
    debug.luma_histogram = inputs.luma_histogram;
    debug.saturation_histogram = inputs.saturation_histogram;
    debug.hue_histogram = inputs.hue_histogram;

    const std::size_t n = static_cast<std::size_t>(std::max(inputs.width, 0)) *
                          static_cast<std::size_t>(std::max(inputs.height, 0));
    if (n == 0) return;

    const int near_black_cutoff_bin = std::clamp(
        static_cast<int>(std::floor(static_cast<double>(thresholds.near_black_luma) * 255.0 +
                                    1.0e-6)),
        0, 255);
    const int near_white_cutoff_bin = std::clamp(
        static_cast<int>(std::ceil(static_cast<double>(thresholds.near_white_luma) * 255.0 -
                                   1.0e-6)),
        0, 255);

    double luma_sum = 0.0;
    double luma_squared_sum = 0.0;
    std::size_t near_black_count = 0;
    std::size_t near_white_count = 0;
    for (int i = 0; i < kLumaBins; ++i) {
        const int count_i = std::max(inputs.luma_histogram[i], 0);
        const double count = static_cast<double>(count_i);
        const double luma = static_cast<double>(i) / 255.0;
        luma_sum += count * luma;
        luma_squared_sum += count * luma * luma;
        if (i <= near_black_cutoff_bin) {
            near_black_count += static_cast<std::size_t>(count_i);
        }
        if (i >= near_white_cutoff_bin) {
            near_white_count += static_cast<std::size_t>(count_i);
        }
    }

    const double inv_n = 1.0 / static_cast<double>(n);
    const double mean = luma_sum * inv_n;
    const double variance = std::max(0.0, luma_squared_sum * inv_n - mean * mean);
    image.mean_luma = static_cast<float>(mean);
    image.median_luma = histogram_quantile_unit(inputs.luma_histogram, n, 0.50f, 255.0f);
    image.p05_luma = histogram_quantile_unit(inputs.luma_histogram, n, 0.05f, 255.0f);
    image.p95_luma = histogram_quantile_unit(inputs.luma_histogram, n, 0.95f, 255.0f);
    debug.p01_luma = histogram_quantile_unit(inputs.luma_histogram, n, 0.01f, 255.0f);
    debug.p10_luma = histogram_quantile_unit(inputs.luma_histogram, n, 0.10f, 255.0f);
    debug.p90_luma = histogram_quantile_unit(inputs.luma_histogram, n, 0.90f, 255.0f);
    debug.p99_luma = histogram_quantile_unit(inputs.luma_histogram, n, 0.99f, 255.0f);
    image.near_black_fraction =
        static_cast<float>(static_cast<double>(near_black_count) * inv_n);
    image.near_white_fraction =
        static_cast<float>(static_cast<double>(near_white_count) * inv_n);
    image.clipped_channel_fraction =
        static_cast<float>(static_cast<double>(std::max(inputs.clipped, 0)) * inv_n);
    image.rms_contrast = static_cast<float>(std::sqrt(variance));
    image.interdecile_luma_range = std::max(0.0f, debug.p90_luma - debug.p10_luma);
    image.interdecile_luma_contrast =
        image.interdecile_luma_range /
        std::max(debug.p90_luma + debug.p10_luma, 1.0e-6f);
    const int local_width = inputs.local_gradient_width > 0
        ? inputs.local_gradient_width
        : inputs.width;
    const int local_height = inputs.local_gradient_height > 0
        ? inputs.local_gradient_height
        : inputs.height;
    const std::size_t local_n =
        static_cast<std::size_t>(std::max(local_width, 0)) *
        static_cast<std::size_t>(std::max(local_height, 0));
    const float local_short_side =
        static_cast<float>(std::max(1, std::min(local_width, local_height)));
    image.local_contrast = local_n > 0
        ? clamp01(static_cast<float>((inputs.local_gradient_sum /
                                      static_cast<double>(local_n)) *
                                     local_short_side /
                                     static_cast<double>(kLocalContrastGradientScale)))
        : 0.0f;
    image.bright_neutral_fraction =
        static_cast<float>(static_cast<double>(std::max(inputs.bright_neutral, 0)) * inv_n);

    double sat_sum = 0.0;
    for (int i = 0; i < kSaturationBins; ++i) {
        const int count_i = std::max(inputs.saturation_histogram[i], 0);
        const double count = static_cast<double>(count_i);
        const double sat = static_cast<double>(i) / 255.0;
        sat_sum += count * sat;
    }
    image.mean_saturation = static_cast<float>(sat_sum * inv_n);
    image.p95_saturation =
        histogram_quantile_unit(inputs.saturation_histogram, n, 0.95f, 255.0f);

    std::size_t colored_count = 0;
    for (int count_i : inputs.hue_histogram) {
        colored_count += static_cast<std::size_t>(std::max(count_i, 0));
    }
    debug.colored_fraction =
        static_cast<float>(static_cast<double>(colored_count) * inv_n);
    debug.mean_saturation_colored = colored_count > 0
        ? static_cast<float>(inputs.colored_saturation_sum /
                             static_cast<double>(colored_count))
        : 0.0f;
    debug.saturation_coverage = debug.mean_saturation_colored * debug.colored_fraction;

    debug.luma_entropy =
        static_cast<float>(entropy_bits_from_histogram(inputs.luma_histogram, n));
    debug.luma_entropy_normalized =
        static_cast<float>(std::clamp(static_cast<double>(debug.luma_entropy) / 8.0,
                                      0.0, 1.0));
    const double hue_total =
        static_cast<double>(std::max<std::size_t>(colored_count, 1u));
    double hue_entropy = 0.0;
    for (int count_i : inputs.hue_histogram) {
        if (count_i <= 0) continue;
        const double p = static_cast<double>(count_i) / hue_total;
        hue_entropy -= p * std::log2(p);
    }
    debug.hue_entropy = static_cast<float>(hue_entropy);

    double rg_sum = 0.0;
    double rg_squared_sum = 0.0;
    for (int i = 0; i < kRgOpponentBins; ++i) {
        const double count = static_cast<double>(std::max(inputs.rg_histogram[i], 0));
        const double value = static_cast<double>(i - 255) / 255.0;
        rg_sum += count * value;
        rg_squared_sum += count * value * value;
    }
    double yb_sum = 0.0;
    double yb_squared_sum = 0.0;
    for (int i = 0; i < kYbOpponentBins; ++i) {
        const double count = static_cast<double>(std::max(inputs.yb_histogram[i], 0));
        const double value = static_cast<double>(i - 510) / 510.0;
        yb_sum += count * value;
        yb_squared_sum += count * value * value;
    }
    const double rg_mean = rg_sum * inv_n;
    const double yb_mean = yb_sum * inv_n;
    const double rg_var = std::max(0.0, rg_squared_sum * inv_n - rg_mean * rg_mean);
    const double yb_var = std::max(0.0, yb_squared_sum * inv_n - yb_mean * yb_mean);
    const double colorfulness =
        std::sqrt(rg_var + yb_var) + 0.3 * std::sqrt(rg_mean * rg_mean + yb_mean * yb_mean);
    debug.colorfulness_raw = static_cast<float>(colorfulness);
    image.colorfulness =
        clamp01(static_cast<float>(colorfulness / static_cast<double>(kColorfulnessNormalizingMax)));
}

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

FrameAnalysis analyze_rgb8_frame(std::span<const std::uint8_t> rgb,
                                 int width, int height,
                                 const Bounds& world_bounds,
                                 std::span<const LightRef> lights,
                                 const FrameAnalysisParams& params) {
    FrameAnalysis out;
    const std::size_t n_pixels = static_cast<std::size_t>(width) *
                                 static_cast<std::size_t>(height);
    if (width <= 0 || height <= 0 || rgb.size() < n_pixels * 3u) {
        return out;
    }

    ImageAnalysisInputs image_inputs;
    image_inputs.width = width;
    image_inputs.height = height;
    std::vector<float> luminance01(n_pixels, 0.0f);
    const LocalLumaGridSize local_grid = local_luma_grid_size(width, height);
    std::array<double, kLocalLumaGridCells> local_luma_sums{};
    std::array<int, kLocalLumaGridCells> local_luma_counts{};

    for (std::size_t i = 0; i < n_pixels; ++i) {
        const std::uint8_t r = rgb[3 * i + 0];
        const std::uint8_t g = rgb[3 * i + 1];
        const std::uint8_t b = rgb[3 * i + 2];
        const int lum = bt709_luminance_u8(r, g, b);
        image_inputs.luma_histogram[lum] += 1;
        luminance01[i] = static_cast<float>(lum) / 255.0f;
        if (local_grid.width > 0 && local_grid.height > 0) {
            const int x = static_cast<int>(i % static_cast<std::size_t>(width));
            const int y = static_cast<int>(i / static_cast<std::size_t>(width));
            const int local_x = std::min(
                static_cast<int>((static_cast<std::uint64_t>(x) *
                                  static_cast<std::uint64_t>(local_grid.width)) /
                                 static_cast<std::uint64_t>(width)),
                local_grid.width - 1);
            const int local_y = std::min(
                static_cast<int>((static_cast<std::uint64_t>(y) *
                                  static_cast<std::uint64_t>(local_grid.height)) /
                                 static_cast<std::uint64_t>(height)),
                local_grid.height - 1);
            const int local_idx = local_luma_cell_index(local_x, local_y);
            local_luma_sums[static_cast<std::size_t>(local_idx)] +=
                static_cast<double>(luminance01[i]);
            local_luma_counts[static_cast<std::size_t>(local_idx)] += 1;
        }

        if (r == 255 || g == 255 || b == 255) {
            ++image_inputs.clipped;
        }

        const std::uint8_t cmax = std::max(r, std::max(g, b));
        const std::uint8_t cmin = std::min(r, std::min(g, b));
        const std::uint8_t delta = static_cast<std::uint8_t>(cmax - cmin);
        const float sat = (cmax > 0)
            ? static_cast<float>(delta) / static_cast<float>(cmax)
            : 0.0f;
        const int sat_bin = std::clamp(static_cast<int>(std::lround(sat * 255.0f)), 0, 255);
        image_inputs.saturation_histogram[sat_bin] += 1;
        if (luminance01[i] >= params.bright_luma_threshold &&
            sat <= params.neutral_saturation_threshold) {
            ++image_inputs.bright_neutral;
        }
        image_inputs.rg_histogram[static_cast<int>(r) - static_cast<int>(g) + 255] += 1;
        image_inputs.yb_histogram[static_cast<int>(r) + static_cast<int>(g) -
                                  2 * static_cast<int>(b) + 510] += 1;

        if (delta > 0 && sat > params.colored_saturation_threshold) {
            image_inputs.colored_saturation_sum +=
                static_cast<double>(sat_bin) / 255.0;
            float h_raw = 0.0f;
            if (r == cmax) {
                h_raw = static_cast<float>(static_cast<int>(g) - static_cast<int>(b)) /
                        static_cast<float>(delta);
            } else if (g == cmax) {
                h_raw = 2.0f + static_cast<float>(static_cast<int>(b) - static_cast<int>(r)) /
                                static_cast<float>(delta);
            } else {
                h_raw = 4.0f + static_cast<float>(static_cast<int>(r) - static_cast<int>(g)) /
                                static_cast<float>(delta);
            }
            float h = h_raw / 6.0f;
            h = h - std::floor(h);
            const int hbin = std::min(
                static_cast<int>(std::floor(h * static_cast<float>(kHueBins))),
                kHueBins - 1);
            image_inputs.hue_histogram[hbin] += 1;
        }
    }

    if (params.analyze_image || params.analyze_debug) {
        std::array<float, kLocalLumaGridCells> local_luma{};
        for (int y = 0; y < local_grid.height; ++y) {
            for (int x = 0; x < local_grid.width; ++x) {
                const int idx = local_luma_cell_index(x, y);
                const int count = local_luma_counts[static_cast<std::size_t>(idx)];
                local_luma[static_cast<std::size_t>(idx)] = count > 0
                    ? static_cast<float>(local_luma_sums[static_cast<std::size_t>(idx)] /
                                         static_cast<double>(count))
                    : 0.0f;
            }
        }
        image_inputs.local_gradient_sum =
            local_luma_grid_gradient_sum(local_luma, local_grid);
        image_inputs.local_gradient_width = local_grid.width;
        image_inputs.local_gradient_height = local_grid.height;

        const ImageAnalysisThresholds thresholds{
            .near_black_luma = params.near_black_luma,
            .near_white_luma = params.near_white_luma,
            .bright_luma_threshold = params.bright_luma_threshold,
            .neutral_saturation_threshold = params.neutral_saturation_threshold,
            .colored_saturation_threshold = params.colored_saturation_threshold,
        };
        finalize_image_stats(image_inputs, thresholds, out.image, out.debug);
        if (!params.analyze_debug) {
            out.debug = {};
        }
        if (!params.analyze_image) {
            out.image = {};
            out.image.width = width;
            out.image.height = height;
        }
    }

    if (lights.empty()) {
        return out;
    }

    const auto vp = viewport_xform(world_bounds, width, height);
    std::vector<ProjectedLight> projected(lights.size());
    for (std::size_t i = 0; i < lights.size(); ++i) {
        projected[i].x =
            (lights[i].world_x - world_bounds.min.x) * vp.scale + vp.offset_x;
        projected[i].y =
            (world_bounds.max.y - lights[i].world_y) * vp.scale + vp.offset_y;
    }

    out.lights.reserve(lights.size());
    const float short_side = static_cast<float>(std::min(width, height));
    const int search_radius = std::max(
        2, static_cast<int>(std::ceil(params.lights.search_radius_ratio * short_side)));

    for (std::size_t i = 0; i < lights.size(); ++i) {
        PointLightAppearance app;
        app.id = lights[i].id;
        app.world_x = lights[i].world_x;
        app.world_y = lights[i].world_y;
        app.image_x = projected[i].x;
        app.image_y = projected[i].y;

        if (!params.analyze_lights) {
            out.lights.push_back(std::move(app));
            continue;
        }

        const int x0 = std::max(0, static_cast<int>(std::floor(app.image_x)) - search_radius);
        const int x1 = std::min(width - 1, static_cast<int>(std::ceil(app.image_x)) + search_radius);
        const int y0 = std::max(0, static_cast<int>(std::floor(app.image_y)) - search_radius);
        const int y1 = std::min(height - 1, static_cast<int>(std::ceil(app.image_y)) + search_radius);
        if (x0 > x1 || y0 > y1) {
            out.lights.push_back(std::move(app));
            continue;
        }

        const int patch_w = x1 - x0 + 1;
        const int patch_h = y1 - y0 + 1;
        const std::size_t patch_n = static_cast<std::size_t>(patch_w) *
                                    static_cast<std::size_t>(patch_h);

        std::vector<float> patch_luma(patch_n, 0.0f);
        std::vector<float> patch_radius_signal(patch_n, 0.0f);
        std::vector<float> patch_excess(patch_n, 0.0f);
        std::vector<std::uint8_t> owned(patch_n, 0u);
        std::vector<std::uint8_t> in_radius(patch_n, 0u);
        std::vector<float> owned_values;
        std::vector<float> ring_values;
        std::vector<float> radius_owned_values;
        std::vector<float> radius_ring_values;
        owned_values.reserve(patch_n);
        ring_values.reserve(patch_n / 4u + 1u);
        radius_owned_values.reserve(patch_n);
        radius_ring_values.reserve(patch_n / 4u + 1u);

        for (int py = y0; py <= y1; ++py) {
            for (int px = x0; px <= x1; ++px) {
                const std::size_t patch_idx = static_cast<std::size_t>(py - y0) *
                                              static_cast<std::size_t>(patch_w) +
                                              static_cast<std::size_t>(px - x0);
                const std::size_t pixel_idx = static_cast<std::size_t>(py) *
                                              static_cast<std::size_t>(width) +
                                              static_cast<std::size_t>(px);
                const float lum = luminance01[pixel_idx];
                const float radius_signal =
                    radius_signal_luminance01(lum, params.lights.radius_signal_gamma);
                patch_luma[patch_idx] = lum;
                patch_radius_signal[patch_idx] = radius_signal;

                if (owner_for_pixel(px, py, projected) != static_cast<int>(i)) {
                    continue;
                }
                owned[patch_idx] = 1u;
                owned_values.push_back(lum);
                radius_owned_values.push_back(radius_signal);

                const float dx = static_cast<float>(px) - app.image_x;
                const float dy = static_cast<float>(py) - app.image_y;
                const float dist = std::sqrt(dx * dx + dy * dy);
                if (dist <= static_cast<float>(search_radius)) {
                    in_radius[patch_idx] = 1u;
                }
                if (dist >= 0.85f * static_cast<float>(search_radius) &&
                    dist <= static_cast<float>(search_radius)) {
                    ring_values.push_back(lum);
                    radius_ring_values.push_back(radius_signal);
                }
            }
        }

        float background = 0.0f;
        if (ring_values.size() >= 8u) {
            background = quantile_in_place(ring_values, 0.5f);
        } else if (!owned_values.empty()) {
            background = quantile_in_place(owned_values, 0.25f);
        }
        app.background_luminance = clamp01(background);
        float radius_background = 0.0f;
        if (radius_ring_values.size() >= 8u) {
            radius_background = quantile_in_place(radius_ring_values, 0.5f);
        } else if (!radius_owned_values.empty()) {
            radius_background = quantile_in_place(radius_owned_values, 0.25f);
        }

        std::vector<float> radial_sum(static_cast<std::size_t>(search_radius) + 1u, 0.0f);
        std::vector<int> radial_count(static_cast<std::size_t>(search_radius) + 1u, 0);
        std::vector<float> bright_distances;
        float actual_peak_luminance = app.background_luminance;
        float peak_excess = 0.0f;

        for (int py = y0; py <= y1; ++py) {
            for (int px = x0; px <= x1; ++px) {
                const std::size_t patch_idx = static_cast<std::size_t>(py - y0) *
                                              static_cast<std::size_t>(patch_w) +
                                              static_cast<std::size_t>(px - x0);
                if (!owned[patch_idx] || !in_radius[patch_idx]) {
                    continue;
                }

                const float excess =
                    std::max(0.0f, patch_radius_signal[patch_idx] - radius_background);
                patch_excess[patch_idx] = excess;
                peak_excess = std::max(peak_excess, excess);
                actual_peak_luminance =
                    std::max(actual_peak_luminance, patch_luma[patch_idx]);

                const float dx = static_cast<float>(px) - app.image_x;
                const float dy = static_cast<float>(py) - app.image_y;
                const float dist = std::sqrt(dx * dx + dy * dy);
                const int rbin = std::min(search_radius, static_cast<int>(std::lround(dist)));
                radial_sum[static_cast<std::size_t>(rbin)] += excess;
                radial_count[static_cast<std::size_t>(rbin)] += 1;

                if (patch_luma[patch_idx] >= params.lights.saturated_core_threshold) {
                    bright_distances.push_back(dist);
                }
            }
        }

        app.peak_luminance = clamp01(actual_peak_luminance);
        app.peak_contrast = std::max(0.0f, app.peak_luminance - app.background_luminance);

        const bool enough_bright =
            static_cast<int>(bright_distances.size()) >= params.lights.min_saturated_core_pixels;
        if (enough_bright) {
            const float pct = std::clamp(params.lights.saturated_core_percentile / 100.0f,
                                         0.0f, 1.0f);
            const std::size_t idx = static_cast<std::size_t>(
                std::floor(pct * static_cast<float>(bright_distances.size() - 1)));
            std::nth_element(bright_distances.begin(),
                             bright_distances.begin() + static_cast<std::ptrdiff_t>(idx),
                             bright_distances.end());
            app.saturated_radius_ratio = bright_distances[idx] / short_side;
        }

        if (peak_excess <= 0.0f) {
            out.lights.push_back(std::move(app));
            continue;
        }

        const float seed_threshold = params.lights.seed_fraction * peak_excess;
        const float grow_threshold = params.lights.grow_fraction * peak_excess;
        int seed_x = -1;
        int seed_y = -1;
        float snap_distance = static_cast<float>(params.lights.center_snap_px) + 1.0f;

        const int center_px = static_cast<int>(std::lround(app.image_x));
        const int center_py = static_cast<int>(std::lround(app.image_y));
        if (center_px >= x0 && center_px <= x1 && center_py >= y0 && center_py <= y1) {
            const std::size_t center_idx = static_cast<std::size_t>(center_py - y0) *
                                           static_cast<std::size_t>(patch_w) +
                                           static_cast<std::size_t>(center_px - x0);
            if (owned[center_idx] && in_radius[center_idx] &&
                patch_excess[center_idx] >= seed_threshold) {
                seed_x = center_px;
                seed_y = center_py;
                snap_distance = 0.0f;
            }
        }

        if (seed_x < 0) {
            for (int py = y0; py <= y1; ++py) {
                for (int px = x0; px <= x1; ++px) {
                    const std::size_t patch_idx = static_cast<std::size_t>(py - y0) *
                                                  static_cast<std::size_t>(patch_w) +
                                                  static_cast<std::size_t>(px - x0);
                    if (!owned[patch_idx] || !in_radius[patch_idx] ||
                        patch_excess[patch_idx] < seed_threshold) {
                        continue;
                    }
                    const float dx = static_cast<float>(px - center_px);
                    const float dy = static_cast<float>(py - center_py);
                    const float dist = std::sqrt(dx * dx + dy * dy);
                    if (dist <= static_cast<float>(params.lights.center_snap_px) &&
                        dist < snap_distance) {
                        seed_x = px;
                        seed_y = py;
                        snap_distance = dist;
                    }
                }
            }
        }

        if (seed_x < 0) {
            out.lights.push_back(std::move(app));
            continue;
        }

        std::vector<std::uint8_t> visited(patch_n, 0u);
        std::vector<int> queue_x;
        std::vector<int> queue_y;
        queue_x.reserve(patch_n);
        queue_y.reserve(patch_n);
        queue_x.push_back(seed_x);
        queue_y.push_back(seed_y);

        const auto enqueue = [&](int px, int py) -> void {
            if (px < x0 || px > x1 || py < y0 || py > y1) return;
            const std::size_t patch_idx = static_cast<std::size_t>(py - y0) *
                                          static_cast<std::size_t>(patch_w) +
                                          static_cast<std::size_t>(px - x0);
            if (visited[patch_idx] || !owned[patch_idx] || !in_radius[patch_idx] ||
                patch_excess[patch_idx] < grow_threshold) {
                return;
            }
            visited[patch_idx] = 1u;
            queue_x.push_back(px);
            queue_y.push_back(py);
        };

        const std::size_t seed_idx = static_cast<std::size_t>(seed_y - y0) *
                                     static_cast<std::size_t>(patch_w) +
                                     static_cast<std::size_t>(seed_x - x0);
        visited[seed_idx] = 1u;

        std::size_t head = 0;
        int component_pixels = 0;
        while (head < queue_x.size()) {
            const int px = queue_x[head];
            const int py = queue_y[head];
            ++head;
            ++component_pixels;

            if (px == 0 || px == width - 1 || py == 0 || py == height - 1) {
                app.touches_frame_edge = true;
            }

            for (int dy = -1; dy <= 1; ++dy) {
                for (int dx = -1; dx <= 1; ++dx) {
                    if (dx == 0 && dy == 0) continue;
                    enqueue(px + dx, py + dy);
                }
            }
        }

        if (component_pixels > 0) {
            app.visible = true;
            app.coverage_fraction = static_cast<float>(component_pixels) /
                                    static_cast<float>(n_pixels);
            app.radius_ratio = std::sqrt(static_cast<float>(component_pixels) /
                                         PI) / short_side;
        }

        std::vector<float> radial_profile(static_cast<std::size_t>(search_radius) + 1u, 0.0f);
        for (int r = 0; r <= search_radius; ++r) {
            if (radial_count[static_cast<std::size_t>(r)] > 0) {
                radial_profile[static_cast<std::size_t>(r)] =
                    radial_sum[static_cast<std::size_t>(r)] /
                    static_cast<float>(radial_count[static_cast<std::size_t>(r)]);
            }
        }

        const int r80 = first_radius_below(radial_profile, 0.8f * peak_excess);
        const int r20 = first_radius_below(radial_profile, 0.2f * peak_excess);
        app.transition_width_ratio =
            static_cast<float>(std::max(0, r20 - r80)) / short_side;

        const float center_score = snap_distance <= 0.0f
            ? 1.0f
            : std::max(0.0f, 1.0f - snap_distance /
                                 static_cast<float>(std::max(params.lights.center_snap_px, 1)));
        const float contrast_score = clamp01(app.peak_contrast / 0.15f);
        const float area_score = clamp01(static_cast<float>(component_pixels) / 16.0f);
        const float truncation_score = app.touches_frame_edge ? 0.5f : 1.0f;
        app.confidence = center_score * contrast_score * area_score * truncation_score;

        out.lights.push_back(std::move(app));
    }

    return out;
}
