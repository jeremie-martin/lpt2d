#pragma once

// Pure-CPU frame and light-circle analysis.
//
// This module is deliberately free of any OpenGL / GLEW / EGL dependency so
// it can be unit-tested on raw pixel buffers without a GPU context. Both the
// interactive Renderer and the headless RenderSession funnel their readback
// buffers through these functions, so Python, CLI, and GUI all see the same
// numbers.
//
// Everything operates on either:
//   - a post-tonemap RGB8 or RGBA8 pixel buffer (0..255), OR
//   - a pre-tonemap linear HDR RGBA float buffer (0..inf in linear units).
//
// The HDR path exists to fix the "all clipped whites look the same"
// degeneracy that the RGB8 path has: a scene blown out above 1.0 reads as
// white regardless of how overblown it is, so a washed-out frame trivially
// passes a "luminance >= 0.92" bright test. On the HDR buffer we can set a
// meaningful threshold relative to the image mean.

#include <array>
#include <cstdint>
#include <span>
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

// RGB8 input (channels-stride 3). Top-left-origin, row-major.
LuminanceStats compute_luminance_stats(const uint8_t* rgb, int width, int height);

// RGBA8 variant — uses .rgb, ignores .a. Stride 4.
LuminanceStats compute_luminance_stats_rgba(const uint8_t* rgba, int width, int height);

// HDR variant. Operates on a linear-light RGB float buffer
// (channels-stride 3, matching the renderer's GL_RGB32F / GL_RGB16F
// accumulation texture). Luminance is computed with the same BT.709
// weights as the LDR path, then each pixel is normalised by the frame's
// maximum luminance so the resulting 0..255 histogram is directly
// comparable to the LDR histogram regardless of the raw accumulation
// scale. `pct_clipped` counts pixels whose raw linear luminance is at
// or above 1.0 (pre-normalisation) — i.e. the post-tonemap clipping a
// naive LDR viewer would see.
LuminanceStats compute_luminance_stats_hdr(const float* rgb, int width, int height);

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

// RGB8 input. `saturation_threshold` in [0, 1]; pixels below this S are
// treated as achromatic and excluded from the hue histogram.
ColorStats compute_color_stats(const uint8_t* rgb, int width, int height,
                               float saturation_threshold = 0.05f);

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

// LDR path — RGB8 post-tonemap buffer.
std::vector<LightCircle>
measure_light_circles(const uint8_t* rgb, int width, int height,
                      const Bounds& world_bounds,
                      std::span<const LightRef> lights,
                      const LightCircleParams& params = {});

// HDR path — pre-tonemap linear RGB float buffer (stride 3). The
// frame-max normalisation is computed internally so `bright_threshold`
// keeps the same 0..1 semantics as the LDR path.
std::vector<LightCircle>
measure_light_circles_hdr(const float* rgb, int width, int height,
                          const Bounds& world_bounds,
                          std::span<const LightRef> lights,
                          const LightCircleParams& params = {});

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
    // HDR light-circle measurement is available (see
    // `measure_light_circles_hdr`) but defaults to off: for normally-exposed
    // scenes the post-tonemap LDR buffer is what the user actually sees, so
    // LDR circles track the perceived "bright halo" better. The HDR path is
    // an escape hatch for pathologically clipped frames where the LDR
    // buffer is uniformly saturated; flip this on when you want the
    // frame-max-normalised HDR measurement.
    bool prefer_hdr_circles = false;
    LightCircleParams circles = {};
    float saturation_threshold = 0.05f;
};

// Single entry point used by the renderer and session. `rgb` must be a
// top-left-origin RGB8 buffer (what Renderer::read_pixels returns). The
// optional `hdr_rgb` is a pre-tonemap linear RGB float buffer (stride 3)
// at the same dimensions and same top-left orientation; when provided
// and `prefer_hdr_circles` is true, circles are measured on the HDR
// buffer instead of the RGB8 buffer.
FrameAnalysis analyze_frame(const uint8_t* rgb, int width, int height,
                            const Bounds& world_bounds,
                            std::span<const LightRef> lights,
                            const float* hdr_rgb = nullptr,
                            const FrameAnalysisParams& params = {});
