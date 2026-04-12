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
// Image statistics
// ───────────────────────────────────────────────────────────────────────────

inline constexpr int kLumaBins = 256;
inline constexpr int kSaturationBins = 256;
inline constexpr int kHueBins = 36;
inline constexpr int kRgOpponentBins = 511;   // (R - G) + 255
inline constexpr int kYbOpponentBins = 1021;  // (R + G - 2B) + 510

struct ImageStats {
    int width = 0;
    int height = 0;
    float mean_luma = 0.0f;                  // BT.709 mean, normalized [0,1]
    float median_luma = 0.0f;                // 50th percentile luma, [0,1]
    float p05_luma = 0.0f;                   // 5th percentile luma, [0,1]
    float p95_luma = 0.0f;                   // 95th percentile luma, [0,1]
    float near_black_fraction = 0.0f;        // luma <= near_black_luma
    float near_white_fraction = 0.0f;        // luma >= near_white_luma
    float clipped_channel_fraction = 0.0f;   // any channel == 255
    float rms_contrast = 0.0f;               // standard deviation of luma, [0,1]
    float interdecile_luma_range = 0.0f;     // p90_luma - p10_luma
    float interdecile_luma_contrast = 0.0f;  // (p90 - p10) / (p90 + p10 + eps)
    float local_contrast = 0.0f;             // normalized Sobel contrast, [0,1]
    float mean_saturation = 0.0f;            // HSV saturation over all pixels, [0,1]
    float p95_saturation = 0.0f;             // 95th percentile HSV saturation, [0,1]
    float colorfulness = 0.0f;               // normalized opponent-channel colorfulness, [0,1]
    float bright_neutral_fraction = 0.0f;    // bright luma and low saturation
};

struct ImageDebugStats {
    float p01_luma = 0.0f;
    float p10_luma = 0.0f;
    float p90_luma = 0.0f;
    float p99_luma = 0.0f;
    float luma_entropy = 0.0f;
    float luma_entropy_normalized = 0.0f;
    float hue_entropy = 0.0f;
    float colored_fraction = 0.0f;
    float mean_saturation_colored = 0.0f;
    float saturation_coverage = 0.0f;
    float colorfulness_raw = 0.0f;
    std::array<int, kLumaBins> luma_histogram{};
    std::array<int, kSaturationBins> saturation_histogram{};
    std::array<int, kHueBins> hue_histogram{};
};

struct ImageAnalysisInputs {
    std::array<int, kLumaBins> luma_histogram{};
    std::array<int, kSaturationBins> saturation_histogram{};
    std::array<int, kHueBins> hue_histogram{};
    std::array<int, kRgOpponentBins> rg_histogram{};
    std::array<int, kYbOpponentBins> yb_histogram{};
    int clipped = 0;
    int bright_neutral = 0;
    double colored_saturation_sum = 0.0;
    double local_gradient_sum = 0.0;
    int width = 0;
    int height = 0;
};

struct ImageAnalysisThresholds {
    float near_black_luma = 10.0f / 255.0f;
    float near_white_luma = 245.0f / 255.0f;
    float bright_luma_threshold = 0.75f;
    float neutral_saturation_threshold = 0.10f;
    float colored_saturation_threshold = 0.05f;
};

void finalize_image_stats(const ImageAnalysisInputs& inputs,
                          const ImageAnalysisThresholds& thresholds,
                          ImageStats& image,
                          ImageDebugStats& debug);

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
    ImageStats image;
    ImageDebugStats debug;
    std::vector<PointLightAppearance> lights;
};

struct FrameAnalysisParams {
    bool analyze_image = true;
    bool analyze_debug = true;
    bool analyze_lights = true;
    PointLightAppearanceParams lights = {};
    float near_black_luma = 10.0f / 255.0f;
    float near_white_luma = 245.0f / 255.0f;
    float bright_luma_threshold = 0.75f;
    float neutral_saturation_threshold = 0.10f;
    float colored_saturation_threshold = 0.05f;
};

// CPU RGB8 analyzer over a top-left-origin final-frame buffer.
FrameAnalysis analyze_rgb8_frame(std::span<const std::uint8_t> rgb,
                                 int width, int height,
                                 const Bounds& world_bounds,
                                 std::span<const LightRef> lights,
                                 const FrameAnalysisParams& params = {});
