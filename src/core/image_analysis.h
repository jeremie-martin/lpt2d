#pragma once

// Frame-analysis data types and RGB8 analyzer.
//
// The public contract is intentionally about metric meaning, not about a
// specific implementation strategy. All values are measured on the
// post-tonemap RGB8 image that represents the authored camera view.

#include <array>
#include <cstdint>
#include <span>
#include <string>
#include <vector>

struct Bounds;  // from scene.h

// ───────────────────────────────────────────────────────────────────────────
// Viewport transform (world AABB → image pixels)
// ───────────────────────────────────────────────────────────────────────────

struct ViewportXform {
    float scale = 1.0f;
    float offset_x = 0.0f;
    float offset_y = 0.0f;
};

ViewportXform viewport_xform(const Bounds& bounds, int width, int height);

// ───────────────────────────────────────────────────────────────────────────
// Luminance statistics
// ───────────────────────────────────────────────────────────────────────────

struct LuminanceStats {
    float mean = 0.0f;                     // BT.709 mean, 0..255 scale
    float median = 0.0f;                   // 50th percentile, 0..255
    float shadow_floor = 0.0f;             // 5th percentile, 0..255
    float highlight_ceiling = 0.0f;        // 95th percentile, 0..255
    float highlight_peak = 0.0f;           // 99th percentile, 0..255
    float contrast_std = 0.0f;             // standard deviation, 0..255
    float contrast_spread = 0.0f;          // highlight_ceiling - shadow_floor, 0..255
    float near_black_fraction = 0.0f;      // luminance <= near_black_bin_max
    float near_white_fraction = 0.0f;      // luminance >= near_white_bin_min
    float clipped_channel_fraction = 0.0f; // any channel == 255
    std::array<int, 256> histogram{};
    int width = 0;
    int height = 0;
};

LuminanceStats finalize_luminance(const std::array<int, 256>& histogram,
                                  int clipped, int width, int height,
                                  int near_black_bin_max = 5,
                                  int near_white_bin_min = 250);

// ───────────────────────────────────────────────────────────────────────────
// Colour statistics
// ───────────────────────────────────────────────────────────────────────────

struct ColorStats {
    float mean_saturation = 0.0f;
    float hue_entropy = 0.0f;
    float colored_fraction = 0.0f;
    float richness = 0.0f;
    int n_colored = 0;
    std::array<int, 36> hue_histogram{};
};

// ───────────────────────────────────────────────────────────────────────────
// Point-light appearance
// ───────────────────────────────────────────────────────────────────────────

struct LightRef {
    std::string id;
    float world_x = 0.0f;
    float world_y = 0.0f;
};

struct PointLightAppearance {
    std::string id;
    float world_x = 0.0f;
    float world_y = 0.0f;
    float image_x = 0.0f;
    float image_y = 0.0f;

    bool visible = false;
    float radius_ratio = 0.0f;
    // TEMP: GPU radius candidates used while comparing detector variants.
    float radius_candidate_sector_consensus_ratio = 0.0f;
    float radius_candidate_knee_ratio = 0.0f;
    float radius_candidate_robust_sector_edge_ratio = 0.0f;
    float radius_candidate_outer_shoulder_ratio = 0.0f;
    float coverage_fraction = 0.0f;
    float saturated_radius_ratio = 0.0f;
    float transition_width_ratio = 0.0f;
    float peak_luminance = 0.0f;
    float background_luminance = 0.0f;
    float peak_contrast = 0.0f;
    bool touches_frame_edge = false;
    float confidence = 0.0f;
};

struct PointLightAppearanceParams {
    float search_radius_ratio = 0.25f;
    float radius_signal_gamma = 0.5f;
    float saturated_core_threshold = 0.92f;
    float saturated_core_percentile = 90.0f;
    int min_saturated_core_pixels = 6;
    float seed_fraction = 0.70f;
    float grow_fraction = 0.35f;
    int center_snap_px = 3;
};

// ───────────────────────────────────────────────────────────────────────────
// Aggregate frame analysis
// ───────────────────────────────────────────────────────────────────────────

struct FrameAnalysis {
    LuminanceStats luminance;
    ColorStats color;
    std::vector<PointLightAppearance> lights;
};

struct FrameAnalysisParams {
    bool analyze_luminance = true;
    bool analyze_color = true;
    bool analyze_lights = true;
    PointLightAppearanceParams lights = {};
    float saturation_threshold = 0.05f;
    int near_black_bin_max = 5;
    int near_white_bin_min = 250;
};

// CPU RGB8 analyzer over a top-left-origin final-frame buffer.
FrameAnalysis analyze_rgb8_frame(std::span<const std::uint8_t> rgb,
                                 int width, int height,
                                 const Bounds& world_bounds,
                                 std::span<const LightRef> lights,
                                 const FrameAnalysisParams& params = {});
