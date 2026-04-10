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

constexpr int kHueBins = 36;

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

LuminanceStats finalize_luminance(const std::array<int, 256>& histogram,
                                  int clipped, int width, int height,
                                  int near_black_bin_max,
                                  int near_white_bin_min) {
    LuminanceStats s;
    s.histogram = histogram;
    s.width = width;
    s.height = height;

    const std::size_t n = static_cast<std::size_t>(width) *
                          static_cast<std::size_t>(height);
    if (n == 0) return s;

    double sum = 0.0;
    double squared_sum = 0.0;
    std::size_t near_black_count = 0;
    std::size_t near_white_count = 0;
    for (int i = 0; i < 256; ++i) {
        const double count = static_cast<double>(histogram[i]);
        sum += count * static_cast<double>(i);
        squared_sum += count * static_cast<double>(i) * static_cast<double>(i);
        if (i <= near_black_bin_max)
            near_black_count += static_cast<std::size_t>(histogram[i]);
        if (i >= near_white_bin_min)
            near_white_count += static_cast<std::size_t>(histogram[i]);
    }

    const double mean = sum / static_cast<double>(n);
    const double var = (squared_sum / static_cast<double>(n)) - mean * mean;

    s.mean = static_cast<float>(mean);
    s.contrast_std = var > 0.0 ? static_cast<float>(std::sqrt(var)) : 0.0f;
    s.near_black_fraction = static_cast<float>(near_black_count) / static_cast<float>(n);
    s.near_white_fraction = static_cast<float>(near_white_count) / static_cast<float>(n);
    s.clipped_channel_fraction = static_cast<float>(clipped) / static_cast<float>(n);

    const auto target = [n](float pct) -> std::size_t {
        return static_cast<std::size_t>(pct * static_cast<float>(n));
    };
    const std::size_t shadow_target = target(0.05f);
    const std::size_t median_target = target(0.50f);
    const std::size_t ceiling_target = target(0.95f);
    const std::size_t peak_target = target(0.99f);

    float shadow_floor = 255.0f;
    float median = 255.0f;
    float highlight_ceiling = 255.0f;
    float highlight_peak = 255.0f;
    bool have_shadow = false;
    bool have_median = false;
    bool have_ceiling = false;
    bool have_peak = false;
    std::size_t cumul = 0;
    for (int i = 0; i < 256; ++i) {
        cumul += static_cast<std::size_t>(histogram[i]);
        if (!have_shadow && cumul >= shadow_target) {
            shadow_floor = static_cast<float>(i);
            have_shadow = true;
        }
        if (!have_median && cumul >= median_target) {
            median = static_cast<float>(i);
            have_median = true;
        }
        if (!have_ceiling && cumul >= ceiling_target) {
            highlight_ceiling = static_cast<float>(i);
            have_ceiling = true;
        }
        if (!have_peak && cumul >= peak_target) {
            highlight_peak = static_cast<float>(i);
            have_peak = true;
            break;
        }
    }

    s.shadow_floor = shadow_floor;
    s.median = median;
    s.highlight_ceiling = highlight_ceiling;
    s.highlight_peak = highlight_peak;
    s.contrast_spread = s.highlight_ceiling - s.shadow_floor;
    return s;
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

    std::array<int, 256> histogram{};
    std::array<int, kHueBins> hue_hist{};
    int clipped = 0;
    std::uint64_t sat_sum_q8 = 0;
    int n_colored = 0;
    std::vector<float> luminance01(n_pixels, 0.0f);

    for (std::size_t i = 0; i < n_pixels; ++i) {
        const std::uint8_t r = rgb[3 * i + 0];
        const std::uint8_t g = rgb[3 * i + 1];
        const std::uint8_t b = rgb[3 * i + 2];
        const int lum = bt709_luminance_u8(r, g, b);
        histogram[lum] += 1;
        luminance01[i] = static_cast<float>(lum) / 255.0f;

        if (r == 255 || g == 255 || b == 255) {
            ++clipped;
        }

        if (params.analyze_color) {
            const std::uint8_t cmax = std::max(r, std::max(g, b));
            const std::uint8_t cmin = std::min(r, std::min(g, b));
            const std::uint8_t delta = static_cast<std::uint8_t>(cmax - cmin);
            if (cmax > 0 && delta > 0) {
                const float sat = static_cast<float>(delta) / static_cast<float>(cmax);
                if (sat > params.saturation_threshold) {
                    ++n_colored;
                    sat_sum_q8 += static_cast<std::uint64_t>(sat * 255.0f + 0.5f);
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
                    const int hbin = std::min(static_cast<int>(std::floor(h * static_cast<float>(kHueBins))),
                                              kHueBins - 1);
                    hue_hist[hbin] += 1;
                }
            }
        }
    }

    if (params.analyze_luminance) {
        out.luminance = finalize_luminance(histogram, clipped, width, height,
                                           params.near_black_bin_max,
                                           params.near_white_bin_min);
    }

    if (params.analyze_color) {
        ColorStats cs;
        cs.n_colored = n_colored;
        cs.hue_histogram = hue_hist;
        cs.colored_fraction = n_pixels > 0
            ? static_cast<float>(n_colored) / static_cast<float>(n_pixels)
            : 0.0f;
        cs.mean_saturation = n_colored > 0
            ? (static_cast<float>(sat_sum_q8) / 255.0f) / static_cast<float>(n_colored)
            : 0.0f;
        if (n_colored > 0) {
            const double inv = 1.0 / static_cast<double>(n_colored);
            double entropy = 0.0;
            for (int k = 0; k < kHueBins; ++k) {
                if (cs.hue_histogram[k] > 0) {
                    const double p = static_cast<double>(cs.hue_histogram[k]) * inv;
                    entropy -= p * std::log2(p);
                }
            }
            cs.hue_entropy = static_cast<float>(entropy);
        }
        cs.richness = cs.hue_entropy * cs.mean_saturation * cs.colored_fraction;
        out.color = cs;
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
        std::vector<float> patch_excess(patch_n, 0.0f);
        std::vector<std::uint8_t> owned(patch_n, 0u);
        std::vector<std::uint8_t> in_radius(patch_n, 0u);
        std::vector<float> owned_values;
        std::vector<float> ring_values;
        owned_values.reserve(patch_n);
        ring_values.reserve(patch_n / 4u + 1u);

        for (int py = y0; py <= y1; ++py) {
            for (int px = x0; px <= x1; ++px) {
                const std::size_t patch_idx = static_cast<std::size_t>(py - y0) *
                                              static_cast<std::size_t>(patch_w) +
                                              static_cast<std::size_t>(px - x0);
                const std::size_t pixel_idx = static_cast<std::size_t>(py) *
                                              static_cast<std::size_t>(width) +
                                              static_cast<std::size_t>(px);
                const float lum = luminance01[pixel_idx];
                patch_luma[patch_idx] = lum;

                if (owner_for_pixel(px, py, projected) != static_cast<int>(i)) {
                    continue;
                }
                owned[patch_idx] = 1u;
                owned_values.push_back(lum);

                const float dx = static_cast<float>(px) - app.image_x;
                const float dy = static_cast<float>(py) - app.image_y;
                const float dist = std::sqrt(dx * dx + dy * dy);
                if (dist <= static_cast<float>(search_radius)) {
                    in_radius[patch_idx] = 1u;
                }
                if (dist >= 0.85f * static_cast<float>(search_radius) &&
                    dist <= static_cast<float>(search_radius)) {
                    ring_values.push_back(lum);
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

        std::vector<float> radial_sum(static_cast<std::size_t>(search_radius) + 1u, 0.0f);
        std::vector<int> radial_count(static_cast<std::size_t>(search_radius) + 1u, 0);
        std::vector<float> bright_distances;
        float peak_excess = 0.0f;

        for (int py = y0; py <= y1; ++py) {
            for (int px = x0; px <= x1; ++px) {
                const std::size_t patch_idx = static_cast<std::size_t>(py - y0) *
                                              static_cast<std::size_t>(patch_w) +
                                              static_cast<std::size_t>(px - x0);
                if (!owned[patch_idx] || !in_radius[patch_idx]) {
                    continue;
                }

                const float lum = patch_luma[patch_idx];
                const float excess = std::max(0.0f, lum - app.background_luminance);
                patch_excess[patch_idx] = excess;
                peak_excess = std::max(peak_excess, excess);

                const float dx = static_cast<float>(px) - app.image_x;
                const float dy = static_cast<float>(py) - app.image_y;
                const float dist = std::sqrt(dx * dx + dy * dy);
                const int rbin = std::min(search_radius, static_cast<int>(std::lround(dist)));
                radial_sum[static_cast<std::size_t>(rbin)] += excess;
                radial_count[static_cast<std::size_t>(rbin)] += 1;

                if (lum >= params.lights.legacy_bright_threshold) {
                    bright_distances.push_back(dist);
                }
            }
        }

        app.peak_contrast = peak_excess;
        app.peak_luminance = clamp01(app.background_luminance + peak_excess);

        const bool enough_bright =
            static_cast<int>(bright_distances.size()) >= params.lights.legacy_min_bright_pixels;
        if (enough_bright) {
            const float pct = std::clamp(params.lights.legacy_radius_percentile / 100.0f,
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
