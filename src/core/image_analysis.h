#pragma once

// Frame-analysis data types and the shared CPU-side post-processing helper.
//
// All the pixel-scanning math (luminance histogram, colour histogram,
// per-light Voronoi circle measurement) lives in the GPU compute shader
// `src/shaders/analysis.comp` dispatched by GpuImageAnalyzer. What stays
// in this header is the public data contract — the structs every caller
// reads (GUI Stats panel, Python `rr.analysis`, native tests) plus the
// one pure helper (`finalize_luminance`) that turns a 256-bin histogram
// into a complete LuminanceStats. The GPU and CPU paths share that
// helper so the mean/std/percentile math has a single implementation.

#include <array>
#include <cstdint>
#include <string>
#include <vector>

struct Bounds;  // from scene.h

// ───────────────────────────────────────────────────────────────────────────
// Viewport transform (world AABB → image pixels)
// ───────────────────────────────────────────────────────────────────────────
//
// Shared with renderer.cpp. Kept identical to the historical
// `compute_viewport_xform` helper that used to live as a static function in
// renderer.cpp: aspect-fit the world AABB inside the canvas with equal scale
// on both axes, centre the result, and return {scale, offset_x, offset_y}.
//
// World-to-pixel mapping:
//   px = (wx - bounds.min.x)         * scale + offset_x
//   py = (bounds.max.y - wy)         * scale + offset_y    // y flipped
//
// (The y flip matches the top-left-origin convention of the RGB8 buffer
// returned by Renderer::read_pixels, which already flips the OpenGL rows.)

struct ViewportXform {
    float scale = 1.0f;
    float offset_x = 0.0f;
    float offset_y = 0.0f;
};

ViewportXform viewport_xform(const Bounds& bounds, int width, int height);

// ───────────────────────────────────────────────────────────────────────────
// Luminance statistics
// ───────────────────────────────────────────────────────────────────────────
//
// Superset of the historical FrameMetrics. The first six fields are byte-for-
// byte compatible with the old struct layout so `using FrameMetrics =
// LuminanceStats;` in renderer.h keeps every existing read site compiling:
// .mean_lum, .pct_black, .pct_clipped, .p50, .p95, .histogram all mean
// exactly what they used to mean (BT.709 integer approximation, 0..255).
//
// The new fields (p05, p99, std_dev, lum_min, lum_max, width, height) are
// additive and drive the crystal_field acceptance filter on the Python side.
//
// `finalize_luminance` takes a populated 256-bin histogram plus the clipped
// count and derives every scalar field (mean, std, percentiles, min, max).
// Both the CPU pixel-loop path and the GPU compute-shader path call this
// helper after they've built the histogram, so there is exactly one place
// in the tree that converts a histogram into the public struct.

struct LuminanceStats {
    // === preserved from the historical FrameMetrics (same names, same math) ===
    float mean_lum = 0.0f;      // BT.709 mean, 0..255 scale
    float pct_black = 0.0f;     // fraction in histogram bin 0
    float pct_clipped = 0.0f;   // fraction with any channel == 255
    float p50 = 0.0f;           // median luminance
    float p95 = 0.0f;
    std::array<int, 256> histogram{};

    // === promoted from Python FrameStats / crystal_field/check.py ===
    float p05 = 0.0f;
    float p99 = 0.0f;
    float std_dev = 0.0f;
    int lum_min = 0;            // smallest populated histogram bin (0 if empty)
    int lum_max = 0;            // largest populated histogram bin  (0 if empty)
    int width = 0;
    int height = 0;
};

// Finalise a LuminanceStats from a 256-bin histogram and the pixel counts.
// Derives mean/std/percentiles/min/max from the histogram; `clipped` is
// the number of pixels where any channel saturated (255). Shared by
// every analysis path (GPU shader readback + native test fixtures).
LuminanceStats finalize_luminance(const std::array<int, 256>& histogram,
                                  int clipped, int width, int height);

// ───────────────────────────────────────────────────────────────────────────
// Colour statistics
// ───────────────────────────────────────────────────────────────────────────

struct ColorStats {
    float mean_saturation = 0.0f;    // mean HSV S over chromatic pixels only
    float hue_entropy = 0.0f;        // Shannon bits, 36-bin hue histogram
    float chromatic_fraction = 0.0f; // n_chromatic / n_pixels
    float color_richness = 0.0f;     // entropy * mean_saturation * chromatic_fraction
    int n_chromatic = 0;
    std::array<int, 36> hue_histogram{};
};

// ───────────────────────────────────────────────────────────────────────────
// Light circles
// ───────────────────────────────────────────────────────────────────────────
//
// For each point light in the scene, measure the apparent "overexposed
// circle" produced by the tracer around its world-space position. We run a
// Voronoi assignment in camera pixel space: every pixel is attributed to its
// nearest light, and then per cell we extract:
//
//   - `radius_px`            : the `radius_percentile`-th percentile of the
//                              distance to centre among bright pixels (the
//                              historical metric the crystal_field check
//                              uses).
//   - `radius_half_max_px`   : the smallest integer radius at which the
//                              radial luminance profile first falls to
//                              `half_max_fraction * peak_luminance`. This is
//                              a classic FWHM-style metric that is less
//                              sensitive to speckled bright pixels at the
//                              cell boundary.
//   - `n_bright_pixels`      : number of pixels in the cell above the bright
//                              threshold. Lets callers reject "radius 4 px
//                              but only three bright hits" degenerate cases.
//   - `sharpness`            : luminance drop per pixel across the edge band
//                              [0.5 * radius_px, 1.5 * radius_px] of the
//                              radial profile.
//   - `profile`              : radial profile (size = max_radius_px + 1).
//
// The `mean_luminance` field is the global image mean luminance (0..1),
// identical across every returned circle — it is a property of the frame,
// not of the cell.

struct LightRef {
    std::string id;
    float world_x = 0.0f;
    float world_y = 0.0f;
};

struct LightCircle {
    std::string id;
    float world_x = 0.0f;
    float world_y = 0.0f;
    float pixel_x = 0.0f;
    float pixel_y = 0.0f;

    float radius_px = 0.0f;
    float radius_half_max_px = 0.0f;
    int n_bright_pixels = 0;
    float sharpness = 0.0f;
    float mean_luminance = 0.0f;

    std::vector<float> profile;
};

struct LightCircleParams {
    int max_radius_px = 200;
    // LDR path: threshold on post-tonemap 0..1 luminance. HDR path: the
    // frame max luminance is computed on the fly and every pixel is
    // normalised to 0..1 before this threshold is applied, so the same
    // default (~top 8% of the scene's dynamic range) is meaningful on
    // either buffer without knowing the raw accumulation scale.
    float bright_threshold = 0.92f;
    int min_bright_pixels = 6;        // below this count, radius_px is 0
    float radius_percentile = 90.0f;  // 0..100
    float half_max_fraction = 0.5f;   // fraction of peak for FWHM-style radius
};

// ───────────────────────────────────────────────────────────────────────────
// Aggregate frame analysis
// ───────────────────────────────────────────────────────────────────────────

struct FrameAnalysis {
    LuminanceStats lum;
    ColorStats color;
    std::vector<LightCircle> circles;
};

struct FrameAnalysisParams {
    bool analyze_luminance = true;
    bool analyze_color = true;
    bool analyze_circles = true;
    LightCircleParams circles = {};
    float saturation_threshold = 0.05f;
};
