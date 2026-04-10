#include "test_harness.h"

#include "image_analysis.h"
#include "scene.h"

#include <cstddef>
#include <cstdint>
#include <vector>

// ── Helpers ──────────────────────────────────────────────────────────────

static std::vector<std::uint8_t> make_solid_rgb(int w, int h,
                                                std::uint8_t r,
                                                std::uint8_t g,
                                                std::uint8_t b) {
    std::vector<std::uint8_t> buf(static_cast<std::size_t>(w) * static_cast<std::size_t>(h) * 3u);
    for (std::size_t i = 0; i < buf.size() / 3; ++i) {
        buf[3 * i + 0] = r;
        buf[3 * i + 1] = g;
        buf[3 * i + 2] = b;
    }
    return buf;
}

static std::vector<std::uint8_t> make_half_black_white(int w, int h) {
    // Top half black, bottom half white.
    std::vector<std::uint8_t> buf(static_cast<std::size_t>(w) * static_cast<std::size_t>(h) * 3u, 0);
    for (int y = h / 2; y < h; ++y) {
        for (int x = 0; x < w; ++x) {
            const std::size_t i = (static_cast<std::size_t>(y) * static_cast<std::size_t>(w)
                                   + static_cast<std::size_t>(x)) * 3u;
            buf[i + 0] = 255;
            buf[i + 1] = 255;
            buf[i + 2] = 255;
        }
    }
    return buf;
}

// Draw a filled disc of `value` in an otherwise-black buffer.
static std::vector<std::uint8_t> make_disc(int w, int h, float cx, float cy, float radius,
                                           std::uint8_t value) {
    std::vector<std::uint8_t> buf(static_cast<std::size_t>(w) * static_cast<std::size_t>(h) * 3u, 0);
    for (int y = 0; y < h; ++y) {
        for (int x = 0; x < w; ++x) {
            const float dx = static_cast<float>(x) - cx;
            const float dy = static_cast<float>(y) - cy;
            if (dx * dx + dy * dy <= radius * radius) {
                const std::size_t i = (static_cast<std::size_t>(y) * static_cast<std::size_t>(w)
                                       + static_cast<std::size_t>(x)) * 3u;
                buf[i + 0] = value;
                buf[i + 1] = value;
                buf[i + 2] = value;
            }
        }
    }
    return buf;
}

static Bounds unit_bounds(float half_w = 1.0f, float half_h = 1.0f) {
    return Bounds{Vec2{-half_w, -half_h}, Vec2{half_w, half_h}};
}

// ── Luminance tests ──────────────────────────────────────────────────────

TEST(luminance_solid_grey) {
    auto buf = make_solid_rgb(16, 16, 128, 128, 128);
    auto s = compute_luminance_stats(buf.data(), 16, 16);
    ASSERT_EQ(s.width, 16);
    ASSERT_EQ(s.height, 16);
    // BT.709 integer: (218*128 + 732*128 + 74*128) >> 10 == 128
    ASSERT_NEAR(s.mean_lum, 128.0f, 0.5f);
    ASSERT_NEAR(s.p05, 128.0f, 0.5f);
    ASSERT_NEAR(s.p50, 128.0f, 0.5f);
    ASSERT_NEAR(s.p95, 128.0f, 0.5f);
    ASSERT_NEAR(s.p99, 128.0f, 0.5f);
    ASSERT_NEAR(s.std_dev, 0.0f, 1e-4f);
    ASSERT_NEAR(s.pct_black, 0.0f, 1e-6f);
    ASSERT_NEAR(s.pct_clipped, 0.0f, 1e-6f);
    ASSERT_EQ(s.lum_min, 128);
    ASSERT_EQ(s.lum_max, 128);
}

TEST(luminance_half_black_half_white) {
    auto buf = make_half_black_white(32, 32);
    auto s = compute_luminance_stats(buf.data(), 32, 32);
    ASSERT_NEAR(s.pct_black, 0.5f, 1e-4f);
    ASSERT_NEAR(s.pct_clipped, 0.5f, 1e-4f);
    ASSERT_NEAR(s.mean_lum, 127.0f, 2.0f);  // half 0, half 255 → mean ≈ 127.5
    ASSERT_NEAR(s.p05, 0.0f, 0.5f);
    ASSERT_NEAR(s.p99, 255.0f, 0.5f);
    ASSERT_TRUE(s.std_dev > 100.0f);  // large spread
    ASSERT_EQ(s.lum_min, 0);
    ASSERT_EQ(s.lum_max, 255);
}

TEST(luminance_pct_clipped_detects_any_channel) {
    // Pixel that is not "white" but has one channel == 255 still counts as clipped.
    std::vector<std::uint8_t> buf = {255, 0, 0};  // pure red
    auto s = compute_luminance_stats(buf.data(), 1, 1);
    ASSERT_NEAR(s.pct_clipped, 1.0f, 1e-6f);
}

TEST(luminance_rgba_matches_rgb) {
    auto rgb = make_solid_rgb(8, 8, 200, 50, 100);
    std::vector<std::uint8_t> rgba(8 * 8 * 4);
    for (int i = 0; i < 8 * 8; ++i) {
        rgba[4 * i + 0] = rgb[3 * i + 0];
        rgba[4 * i + 1] = rgb[3 * i + 1];
        rgba[4 * i + 2] = rgb[3 * i + 2];
        rgba[4 * i + 3] = 255;
    }
    auto a = compute_luminance_stats(rgb.data(), 8, 8);
    auto b = compute_luminance_stats_rgba(rgba.data(), 8, 8);
    ASSERT_NEAR(a.mean_lum, b.mean_lum, 0.5f);
    ASSERT_EQ(a.p50, b.p50);
    ASSERT_EQ(a.lum_min, b.lum_min);
    ASSERT_EQ(a.lum_max, b.lum_max);
}

TEST(luminance_empty_input_safe) {
    auto s = compute_luminance_stats(nullptr, 0, 0);
    ASSERT_EQ(s.width, 0);
    ASSERT_EQ(s.height, 0);
    ASSERT_NEAR(s.mean_lum, 0.0f, 1e-6f);
}

TEST(luminance_hdr_uniform_frame_is_flat) {
    // 4x4 uniformly at 0.5 linear. After frame-max normalisation every
    // pixel sits at the top of the 0..1 range, so the histogram is a
    // single bin at 255.
    std::vector<float> hdr(4 * 4 * 3, 0.5f);
    auto s = compute_luminance_stats_hdr(hdr.data(), 4, 4);
    ASSERT_NEAR(s.mean_lum, 255.0f, 1.0f);
    ASSERT_NEAR(s.pct_clipped, 0.0f, 1e-6f);
}

TEST(luminance_hdr_clipping_above_one) {
    // 4x4 at R=2.0 — pct_clipped counts pixels whose RAW linear value is
    // already ≥ 1.0 (the "overblown in a naive LDR viewer" set), not the
    // post-normalisation set.
    std::vector<float> hdr(4 * 4 * 3, 0.0f);
    for (int i = 0; i < 4 * 4; ++i) {
        hdr[3 * i + 0] = 2.0f;  // R overblown
    }
    auto s = compute_luminance_stats_hdr(hdr.data(), 4, 4);
    ASSERT_NEAR(s.pct_clipped, 1.0f, 1e-6f);
}

// ── Color tests ──────────────────────────────────────────────────────────

TEST(color_stats_greyscale_zero) {
    auto buf = make_solid_rgb(16, 16, 128, 128, 128);
    auto c = compute_color_stats(buf.data(), 16, 16);
    ASSERT_NEAR(c.chromatic_fraction, 0.0f, 1e-6f);
    ASSERT_NEAR(c.mean_saturation, 0.0f, 1e-6f);
    ASSERT_NEAR(c.hue_entropy, 0.0f, 1e-6f);
    ASSERT_NEAR(c.color_richness, 0.0f, 1e-6f);
}

TEST(color_stats_pure_red_no_entropy) {
    auto buf = make_solid_rgb(16, 16, 255, 0, 0);
    auto c = compute_color_stats(buf.data(), 16, 16);
    ASSERT_NEAR(c.chromatic_fraction, 1.0f, 1e-4f);
    ASSERT_NEAR(c.mean_saturation, 1.0f, 1e-4f);
    ASSERT_NEAR(c.hue_entropy, 0.0f, 1e-4f);  // single bin
    ASSERT_NEAR(c.color_richness, 0.0f, 1e-4f);
}

TEST(color_stats_rainbow_high_entropy) {
    // 36-column buffer where each column is a distinct fully-saturated hue.
    const int w = 36, h = 4;
    std::vector<std::uint8_t> buf(static_cast<std::size_t>(w) * static_cast<std::size_t>(h) * 3u, 0);
    for (int x = 0; x < w; ++x) {
        // Map x to a hue bin. Use primary colours at bin 0, 12, 24.
        std::uint8_t r = 0, g = 0, b = 0;
        const int which = x % 3;
        if (which == 0) r = 255;
        else if (which == 1) g = 255;
        else b = 255;
        for (int y = 0; y < h; ++y) {
            const std::size_t i = (static_cast<std::size_t>(y) * static_cast<std::size_t>(w)
                                   + static_cast<std::size_t>(x)) * 3u;
            buf[i + 0] = r;
            buf[i + 1] = g;
            buf[i + 2] = b;
        }
    }
    auto c = compute_color_stats(buf.data(), w, h);
    ASSERT_NEAR(c.chromatic_fraction, 1.0f, 1e-4f);
    ASSERT_NEAR(c.mean_saturation, 1.0f, 1e-4f);
    // Three equally-populated bins → entropy = log2(3) ≈ 1.585
    ASSERT_NEAR(c.hue_entropy, 1.585f, 0.01f);
}

// ── Light-circle tests ──────────────────────────────────────────────────

TEST(light_circle_single_disc) {
    const int W = 128, H = 128;
    const float cx = 64.0f, cy = 64.0f;
    const float disc_r = 20.0f;
    auto buf = make_disc(W, H, cx, cy, disc_r, 255);

    // World bounds: [-1,1] × [-1,1], so scale = 64 px/unit, and the light
    // at world (0,0) maps to pixel (64, 64) — the centre of the disc.
    Bounds b = unit_bounds(1.0f, 1.0f);
    std::vector<LightRef> lights = {LightRef{"light_0", 0.0f, 0.0f}};

    LightCircleParams p;
    p.bright_threshold = 0.8f;  // disc is pure white (lum = 1.0)
    auto circles = measure_light_circles(buf.data(), W, H, b, lights, p);

    REQUIRE_TRUE(circles.size() == 1);
    const auto& c = circles[0];
    ASSERT_NEAR(c.pixel_x, cx, 0.01f);
    ASSERT_NEAR(c.pixel_y, cy, 0.01f);
    // 90th-percentile radius should land close to the disc edge.
    ASSERT_TRUE(c.radius_px > 17.0f);
    ASSERT_TRUE(c.radius_px < 23.0f);
    // FWHM half-max: the disc is a hard edge, so profile is roughly 1 inside
    // and drops sharply past disc_r. The first r where profile < 0.5 peak
    // should sit within a couple of pixels of disc_r.
    ASSERT_TRUE(c.radius_half_max_px > 15.0f);
    ASSERT_TRUE(c.radius_half_max_px < 25.0f);
    ASSERT_TRUE(c.n_bright_pixels > 1000);  // pi*20² ≈ 1257
    ASSERT_TRUE(c.sharpness > 0.0f);
    ASSERT_TRUE(c.mean_luminance > 0.0f);
    ASSERT_TRUE(c.mean_luminance < 0.2f);  // mostly black frame
}

TEST(light_circle_two_discs_voronoi) {
    const int W = 128, H = 64;
    // Two discs at pixel x=32 and x=96, y=32, radius 10.
    std::vector<std::uint8_t> buf(static_cast<std::size_t>(W) * static_cast<std::size_t>(H) * 3u, 0);
    auto draw = [&](float cx, float cy, float r) {
        for (int y = 0; y < H; ++y) {
            for (int x = 0; x < W; ++x) {
                const float dx = static_cast<float>(x) - cx;
                const float dy = static_cast<float>(y) - cy;
                if (dx * dx + dy * dy <= r * r) {
                    const std::size_t i = (static_cast<std::size_t>(y) * static_cast<std::size_t>(W)
                                           + static_cast<std::size_t>(x)) * 3u;
                    buf[i + 0] = 255;
                    buf[i + 1] = 255;
                    buf[i + 2] = 255;
                }
            }
        }
    };
    draw(32.0f, 32.0f, 10.0f);
    draw(96.0f, 32.0f, 10.0f);

    // World bounds: [-1,1] × [-0.5,0.5] → 64 px/unit horizontally, 64 px/unit
    // vertically. Light A at world (-0.5, 0) → pixel (32, 32). Light B at
    // world (0.5, 0) → pixel (96, 32).
    Bounds b{Vec2{-1.0f, -0.5f}, Vec2{1.0f, 0.5f}};
    std::vector<LightRef> lights = {
        LightRef{"light_0", -0.5f, 0.0f},
        LightRef{"light_1",  0.5f, 0.0f},
    };

    LightCircleParams p;
    p.bright_threshold = 0.8f;
    auto circles = measure_light_circles(buf.data(), W, H, b, lights, p);
    REQUIRE_TRUE(circles.size() == 2);

    ASSERT_NEAR(circles[0].pixel_x, 32.0f, 0.5f);
    ASSERT_NEAR(circles[1].pixel_x, 96.0f, 0.5f);
    // Each cell owns a disc ≈ pi * 10² ≈ 314 bright pixels. Voronoi cells are
    // the left/right halves of the image, and the two discs are fully
    // separated by the vertical midline at x=64.
    ASSERT_TRUE(circles[0].n_bright_pixels > 250);
    ASSERT_TRUE(circles[0].n_bright_pixels < 400);
    ASSERT_TRUE(circles[1].n_bright_pixels > 250);
    ASSERT_TRUE(circles[1].n_bright_pixels < 400);
    ASSERT_TRUE(circles[0].radius_px > 7.0f);
    ASSERT_TRUE(circles[0].radius_px < 13.0f);
    ASSERT_TRUE(circles[1].radius_px > 7.0f);
    ASSERT_TRUE(circles[1].radius_px < 13.0f);
}

TEST(light_circle_no_bright_pixels_safe) {
    const int W = 32, H = 32;
    auto buf = make_solid_rgb(W, H, 0, 0, 0);
    Bounds b = unit_bounds();
    std::vector<LightRef> lights = {LightRef{"light_0", 0.0f, 0.0f}};
    auto circles = measure_light_circles(buf.data(), W, H, b, lights);
    REQUIRE_TRUE(circles.size() == 1);
    ASSERT_NEAR(circles[0].radius_px, 0.0f, 1e-6f);
    ASSERT_NEAR(circles[0].radius_half_max_px, 0.0f, 1e-6f);
    ASSERT_EQ(circles[0].n_bright_pixels, 0);
    ASSERT_NEAR(circles[0].sharpness, 0.0f, 1e-6f);
    ASSERT_NEAR(circles[0].mean_luminance, 0.0f, 1e-6f);
}

TEST(light_circle_empty_lights_returns_empty) {
    const int W = 16, H = 16;
    auto buf = make_solid_rgb(W, H, 200, 200, 200);
    Bounds b = unit_bounds();
    auto circles = measure_light_circles(buf.data(), W, H, b, {});
    ASSERT_TRUE(circles.empty());
}

TEST(light_circle_hdr_vs_ldr_overblown) {
    // 64x64 buffer: a 10-pixel disc at linear luminance 5.0 over a
    // background clipped at 1.0. In the LDR path (after tonemap) both
    // disc and background read as 255, so the circle metric degenerates.
    // The HDR path normalises by the frame max (5.0) so the default
    // bright_threshold of 0.92 is equivalent to "lum >= 4.6" in raw
    // units — recovering the disc cleanly.
    const int W = 64, H = 64;
    std::vector<float> hdr(static_cast<std::size_t>(W) * static_cast<std::size_t>(H) * 3u, 0.0f);
    // Background = 1.0 everywhere.
    for (int i = 0; i < W * H; ++i) {
        hdr[3 * i + 0] = 1.0f;
        hdr[3 * i + 1] = 1.0f;
        hdr[3 * i + 2] = 1.0f;
    }
    // Disc at raw linear 5.0, centred at pixel (32, 32), radius 10.
    const float cx = 32.0f, cy = 32.0f, disc_r = 10.0f;
    for (int y = 0; y < H; ++y) {
        for (int x = 0; x < W; ++x) {
            const float dx = static_cast<float>(x) - cx;
            const float dy = static_cast<float>(y) - cy;
            if (dx * dx + dy * dy <= disc_r * disc_r) {
                const std::size_t i = (static_cast<std::size_t>(y) * static_cast<std::size_t>(W)
                                       + static_cast<std::size_t>(x)) * 3u;
                hdr[i + 0] = 5.0f;
                hdr[i + 1] = 5.0f;
                hdr[i + 2] = 5.0f;
            }
        }
    }

    Bounds b = unit_bounds(1.0f, 1.0f);  // 32 px/unit
    std::vector<LightRef> lights = {LightRef{"light_0", 0.0f, 0.0f}};

    // Default LightCircleParams: bright_threshold 0.92. In the HDR path
    // this is interpreted as "0.92 * frame_max_lum" = 4.6 raw, so only
    // the disc pixels count.
    auto circles = measure_light_circles_hdr(hdr.data(), W, H, b, lights);

    REQUIRE_TRUE(circles.size() == 1);
    const auto& c = circles[0];
    ASSERT_TRUE(c.n_bright_pixels > 250);  // pi*10² ≈ 314
    ASSERT_TRUE(c.n_bright_pixels < 400);
    ASSERT_TRUE(c.radius_px > 7.0f);
    ASSERT_TRUE(c.radius_px < 13.0f);
}

// ── Aggregate ────────────────────────────────────────────────────────────

TEST(analyze_frame_aggregates_lum_color_circles) {
    const int W = 64, H = 64;
    auto buf = make_disc(W, H, 32.0f, 32.0f, 12.0f, 255);
    Bounds b = unit_bounds();
    std::vector<LightRef> lights = {LightRef{"light_0", 0.0f, 0.0f}};
    FrameAnalysisParams params;
    params.circles.bright_threshold = 0.8f;
    auto a = analyze_frame(buf.data(), W, H, b, lights, nullptr, params);
    ASSERT_EQ(a.lum.width, W);
    ASSERT_EQ(a.lum.height, H);
    ASSERT_NEAR(a.color.chromatic_fraction, 0.0f, 1e-6f);  // pure white/black
    REQUIRE_TRUE(a.circles.size() == 1);
    ASSERT_TRUE(a.circles[0].n_bright_pixels > 300);
}

TEST(analyze_frame_skip_circles_when_no_lights) {
    const int W = 16, H = 16;
    auto buf = make_solid_rgb(W, H, 128, 128, 128);
    Bounds b = unit_bounds();
    auto a = analyze_frame(buf.data(), W, H, b, {}, nullptr, {});
    ASSERT_TRUE(a.circles.empty());
}

// ── viewport_xform ───────────────────────────────────────────────────────

TEST(viewport_xform_square_roundtrip) {
    Bounds b{Vec2{-1.0f, -1.0f}, Vec2{1.0f, 1.0f}};
    auto vp = viewport_xform(b, 128, 128);
    ASSERT_NEAR(vp.scale, 64.0f, 1e-4f);
    ASSERT_NEAR(vp.offset_x, 0.0f, 1e-4f);
    ASSERT_NEAR(vp.offset_y, 0.0f, 1e-4f);
    // world (-1,-1) → pixel (0, 128) because y is flipped at the use-site.
    const float px = (-1.0f - b.min.x) * vp.scale + vp.offset_x;
    const float py = (b.max.y - -1.0f) * vp.scale + vp.offset_y;
    ASSERT_NEAR(px, 0.0f, 1e-3f);
    ASSERT_NEAR(py, 128.0f, 1e-3f);
}

TEST(viewport_xform_aspect_fit_letterboxed) {
    // Wide world bounds into a square canvas → letterbox on y.
    Bounds b{Vec2{-2.0f, -0.5f}, Vec2{2.0f, 0.5f}};  // 4 × 1
    auto vp = viewport_xform(b, 128, 128);
    // min of (128/4, 128/1) = 32
    ASSERT_NEAR(vp.scale, 32.0f, 1e-4f);
    ASSERT_NEAR(vp.offset_x, 0.0f, 1e-4f);
    // y gets centred: (128 - 32) / 2 = 48
    ASSERT_NEAR(vp.offset_y, 48.0f, 1e-4f);
}

TEST(viewport_xform_degenerate_safe) {
    Bounds b{Vec2{0.0f, 0.0f}, Vec2{0.0f, 0.0f}};
    auto vp = viewport_xform(b, 64, 64);
    ASSERT_NEAR(vp.scale, 1.0f, 1e-6f);
}
