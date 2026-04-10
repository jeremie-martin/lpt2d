// GPU compute-shader analyzer tests.
//
// Creates an offscreen EGL pbuffer context on first call, uploads synthetic
// RGB8 textures, runs GpuImageAnalyzer, and asserts the output struct
// matches expected values. These tests replace the CPU byte-loop tests in
// tests/cpp/test_image_analysis.cpp (which will be deleted alongside the
// CPU pixel-scanning entry points in PR 2 of the GPU refactor).
//
// Fixture lifetime: one HeadlessGL context is created lazily on first
// `get_gpu_fixture()` call and kept alive until process exit. The analyser
// is initialised once and reused across every test — each test only has
// to allocate its input texture.

#include "test_harness.h"

#include "gpu_image_analysis.h"
#include "headless.h"
#include "image_analysis.h"
#include "scene.h"

#include <GL/glew.h>

#include <cstddef>
#include <cstdint>
#include <vector>

// ── Shared GL fixture ────────────────────────────────────────────────

namespace {

struct GpuFixture {
    HeadlessGL gl;
    GpuImageAnalyzer analyzer;
    bool ready = false;
};

// Lazy-init singleton. Every test calls this and bails via REQUIRE_TRUE
// if the fixture failed to come up.
GpuFixture& get_gpu_fixture() {
    static GpuFixture f;
    if (f.ready) return f;

    if (!f.gl.init()) return f;
    if (!f.gl.make_current()) return f;

    // Mirror renderer.cpp: GLEW experimental + context init on GL 4.3 core.
    glewExperimental = GL_TRUE;
    if (glewContextInit() != GLEW_OK) return f;

    if (!f.analyzer.init()) return f;

    f.ready = true;
    return f;
}

// Create an RGB8 GL texture and upload `data`. Caller owns deletion via
// the returned id. Tests use TextureGuard to RAII it.
struct TextureGuard {
    GLuint id = 0;
    TextureGuard(const std::uint8_t* data, int w, int h) {
        glGenTextures(1, &id);
        glBindTexture(GL_TEXTURE_2D, id);
        glPixelStorei(GL_UNPACK_ALIGNMENT, 1);
        glTexImage2D(GL_TEXTURE_2D, 0, GL_RGB8, w, h, 0, GL_RGB,
                     GL_UNSIGNED_BYTE, data);
        // Nearest filtering so texelFetch is exact regardless of mip/filter.
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_NEAREST);
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_NEAREST);
        glBindTexture(GL_TEXTURE_2D, 0);
    }
    ~TextureGuard() {
        if (id != 0) glDeleteTextures(1, &id);
    }
    TextureGuard(const TextureGuard&) = delete;
    TextureGuard& operator=(const TextureGuard&) = delete;
};

// ── Synthetic texture builders (identical to test_image_analysis.cpp) ──

std::vector<std::uint8_t> make_solid_rgb(int w, int h,
                                         std::uint8_t r, std::uint8_t g, std::uint8_t b) {
    std::vector<std::uint8_t> buf(static_cast<std::size_t>(w) *
                                  static_cast<std::size_t>(h) * 3u);
    for (std::size_t i = 0; i < buf.size() / 3; ++i) {
        buf[3 * i + 0] = r;
        buf[3 * i + 1] = g;
        buf[3 * i + 2] = b;
    }
    return buf;
}

std::vector<std::uint8_t> make_half_black_white(int w, int h) {
    std::vector<std::uint8_t> buf(static_cast<std::size_t>(w) *
                                  static_cast<std::size_t>(h) * 3u, 0);
    for (int y = h / 2; y < h; ++y) {
        for (int x = 0; x < w; ++x) {
            const std::size_t i = (static_cast<std::size_t>(y) *
                                   static_cast<std::size_t>(w) +
                                   static_cast<std::size_t>(x)) * 3u;
            buf[i + 0] = 255;
            buf[i + 1] = 255;
            buf[i + 2] = 255;
        }
    }
    return buf;
}

std::vector<std::uint8_t> make_disc(int w, int h, float cx, float cy,
                                    float radius, std::uint8_t value) {
    std::vector<std::uint8_t> buf(static_cast<std::size_t>(w) *
                                  static_cast<std::size_t>(h) * 3u, 0);
    for (int y = 0; y < h; ++y) {
        for (int x = 0; x < w; ++x) {
            const float dx = static_cast<float>(x) - cx;
            const float dy = static_cast<float>(y) - cy;
            if (dx * dx + dy * dy <= radius * radius) {
                const std::size_t i = (static_cast<std::size_t>(y) *
                                       static_cast<std::size_t>(w) +
                                       static_cast<std::size_t>(x)) * 3u;
                buf[i + 0] = value;
                buf[i + 1] = value;
                buf[i + 2] = value;
            }
        }
    }
    return buf;
}

Bounds unit_bounds(float hw = 1.0f, float hh = 1.0f) {
    return Bounds{Vec2{-hw, -hh}, Vec2{hw, hh}};
}

}  // namespace

// ── Luminance tests ──────────────────────────────────────────────────

TEST(gpu_luminance_solid_grey) {
    auto& f = get_gpu_fixture();
    REQUIRE_TRUE(f.ready);
    auto buf = make_solid_rgb(16, 16, 128, 128, 128);
    TextureGuard tex(buf.data(), 16, 16);

    FrameAnalysisParams params;
    params.analyze_circles = false;
    auto a = f.analyzer.analyze(tex.id, 16, 16, unit_bounds(), {}, params);

    ASSERT_EQ(a.lum.width, 16);
    ASSERT_EQ(a.lum.height, 16);
    ASSERT_NEAR(a.lum.mean_lum, 128.0f, 1.0f);
    ASSERT_NEAR(a.lum.p05, 128.0f, 1.0f);
    ASSERT_NEAR(a.lum.p50, 128.0f, 1.0f);
    ASSERT_NEAR(a.lum.p95, 128.0f, 1.0f);
    ASSERT_NEAR(a.lum.std_dev, 0.0f, 1.0f);
    ASSERT_NEAR(a.lum.pct_black, 0.0f, 1e-6f);
    ASSERT_NEAR(a.lum.pct_clipped, 0.0f, 1e-6f);
    ASSERT_EQ(a.lum.lum_min, 128);
    ASSERT_EQ(a.lum.lum_max, 128);
}

TEST(gpu_luminance_half_black_half_white) {
    auto& f = get_gpu_fixture();
    REQUIRE_TRUE(f.ready);
    auto buf = make_half_black_white(32, 32);
    TextureGuard tex(buf.data(), 32, 32);

    FrameAnalysisParams params;
    params.analyze_circles = false;
    auto a = f.analyzer.analyze(tex.id, 32, 32, unit_bounds(), {}, params);

    ASSERT_NEAR(a.lum.pct_black,   0.5f, 1e-4f);
    ASSERT_NEAR(a.lum.pct_clipped, 0.5f, 1e-4f);
    ASSERT_NEAR(a.lum.mean_lum,    127.0f, 2.0f);
    ASSERT_NEAR(a.lum.p05,         0.0f, 1.0f);
    ASSERT_NEAR(a.lum.p99,         255.0f, 1.0f);
    ASSERT_TRUE(a.lum.std_dev > 100.0f);
    ASSERT_EQ(a.lum.lum_min, 0);
    ASSERT_EQ(a.lum.lum_max, 255);
}

TEST(gpu_luminance_pct_clipped_detects_any_channel) {
    auto& f = get_gpu_fixture();
    REQUIRE_TRUE(f.ready);
    // 2x2 texture all pure red — each pixel has R=255, triggering clipping.
    auto buf = make_solid_rgb(2, 2, 255, 0, 0);
    TextureGuard tex(buf.data(), 2, 2);

    FrameAnalysisParams params;
    params.analyze_circles = false;
    auto a = f.analyzer.analyze(tex.id, 2, 2, unit_bounds(), {}, params);
    ASSERT_NEAR(a.lum.pct_clipped, 1.0f, 1e-6f);
}

// ── Color tests ──────────────────────────────────────────────────────

TEST(gpu_color_stats_greyscale_zero) {
    auto& f = get_gpu_fixture();
    REQUIRE_TRUE(f.ready);
    auto buf = make_solid_rgb(16, 16, 128, 128, 128);
    TextureGuard tex(buf.data(), 16, 16);

    FrameAnalysisParams params;
    params.analyze_circles = false;
    auto a = f.analyzer.analyze(tex.id, 16, 16, unit_bounds(), {}, params);
    ASSERT_NEAR(a.color.chromatic_fraction, 0.0f, 1e-6f);
    ASSERT_NEAR(a.color.mean_saturation,    0.0f, 1e-6f);
    ASSERT_NEAR(a.color.hue_entropy,        0.0f, 1e-6f);
    ASSERT_NEAR(a.color.color_richness,     0.0f, 1e-6f);
}

TEST(gpu_color_stats_pure_red_no_entropy) {
    auto& f = get_gpu_fixture();
    REQUIRE_TRUE(f.ready);
    auto buf = make_solid_rgb(16, 16, 255, 0, 0);
    TextureGuard tex(buf.data(), 16, 16);

    FrameAnalysisParams params;
    params.analyze_circles = false;
    auto a = f.analyzer.analyze(tex.id, 16, 16, unit_bounds(), {}, params);
    ASSERT_NEAR(a.color.chromatic_fraction, 1.0f, 1e-4f);
    ASSERT_NEAR(a.color.mean_saturation,    1.0f, 0.01f);  // q8 precision
    ASSERT_NEAR(a.color.hue_entropy,        0.0f, 1e-4f);
    ASSERT_NEAR(a.color.color_richness,     0.0f, 1e-4f);
}

TEST(gpu_color_stats_three_primaries) {
    auto& f = get_gpu_fixture();
    REQUIRE_TRUE(f.ready);
    // Columns cycle R, G, B, R, G, B, ...
    const int w = 36, h = 4;
    std::vector<std::uint8_t> buf(static_cast<std::size_t>(w) *
                                  static_cast<std::size_t>(h) * 3u, 0);
    for (int x = 0; x < w; ++x) {
        std::uint8_t r = 0, g = 0, b = 0;
        const int which = x % 3;
        if (which == 0) r = 255;
        else if (which == 1) g = 255;
        else b = 255;
        for (int y = 0; y < h; ++y) {
            const std::size_t i = (static_cast<std::size_t>(y) *
                                   static_cast<std::size_t>(w) +
                                   static_cast<std::size_t>(x)) * 3u;
            buf[i + 0] = r;
            buf[i + 1] = g;
            buf[i + 2] = b;
        }
    }
    TextureGuard tex(buf.data(), w, h);

    FrameAnalysisParams params;
    params.analyze_circles = false;
    auto a = f.analyzer.analyze(tex.id, w, h, unit_bounds(), {}, params);
    ASSERT_NEAR(a.color.chromatic_fraction, 1.0f, 1e-4f);
    ASSERT_NEAR(a.color.mean_saturation,    1.0f, 0.01f);
    // Three equally-populated bins → entropy = log2(3) ≈ 1.585
    ASSERT_NEAR(a.color.hue_entropy, 1.585f, 0.02f);
}

// ── Light-circle tests ───────────────────────────────────────────────

TEST(gpu_light_circle_single_disc) {
    auto& f = get_gpu_fixture();
    REQUIRE_TRUE(f.ready);
    const int W = 128, H = 128;
    const float cx = 64.0f, cy = 64.0f;
    const float disc_r = 20.0f;
    auto buf = make_disc(W, H, cx, cy, disc_r, 255);
    TextureGuard tex(buf.data(), W, H);

    Bounds b = unit_bounds();
    std::vector<LightRef> lights = {LightRef{"light_0", 0.0f, 0.0f}};

    FrameAnalysisParams params;
    params.circles.bright_threshold = 0.8f;
    auto a = f.analyzer.analyze(tex.id, W, H, b, lights, params);

    REQUIRE_TRUE(a.circles.size() == 1);
    const auto& c = a.circles[0];
    ASSERT_NEAR(c.pixel_x, cx, 0.01f);
    ASSERT_NEAR(c.pixel_y, cy, 0.01f);
    ASSERT_TRUE(c.radius_px > 17.0f);
    ASSERT_TRUE(c.radius_px < 23.0f);
    ASSERT_TRUE(c.radius_half_max_px > 15.0f);
    ASSERT_TRUE(c.radius_half_max_px < 25.0f);
    ASSERT_TRUE(c.n_bright_pixels > 1000);  // pi*20² ≈ 1257
    ASSERT_TRUE(c.sharpness > 0.0f);
    ASSERT_TRUE(c.mean_luminance > 0.0f);
    ASSERT_TRUE(c.mean_luminance < 0.2f);
}

TEST(gpu_light_circle_two_discs_voronoi) {
    auto& f = get_gpu_fixture();
    REQUIRE_TRUE(f.ready);
    const int W = 128, H = 64;
    std::vector<std::uint8_t> buf(static_cast<std::size_t>(W) *
                                  static_cast<std::size_t>(H) * 3u, 0);
    auto draw = [&](float cx, float cy, float r) {
        for (int y = 0; y < H; ++y) {
            for (int x = 0; x < W; ++x) {
                const float dx = static_cast<float>(x) - cx;
                const float dy = static_cast<float>(y) - cy;
                if (dx * dx + dy * dy <= r * r) {
                    const std::size_t i = (static_cast<std::size_t>(y) *
                                           static_cast<std::size_t>(W) +
                                           static_cast<std::size_t>(x)) * 3u;
                    buf[i + 0] = 255;
                    buf[i + 1] = 255;
                    buf[i + 2] = 255;
                }
            }
        }
    };
    draw(32.0f, 32.0f, 10.0f);
    draw(96.0f, 32.0f, 10.0f);
    TextureGuard tex(buf.data(), W, H);

    Bounds b{Vec2{-1.0f, -0.5f}, Vec2{1.0f, 0.5f}};
    std::vector<LightRef> lights = {
        LightRef{"light_0", -0.5f, 0.0f},
        LightRef{"light_1",  0.5f, 0.0f},
    };

    FrameAnalysisParams params;
    params.circles.bright_threshold = 0.8f;
    auto a = f.analyzer.analyze(tex.id, W, H, b, lights, params);
    REQUIRE_TRUE(a.circles.size() == 2);

    ASSERT_NEAR(a.circles[0].pixel_x, 32.0f, 0.5f);
    ASSERT_NEAR(a.circles[1].pixel_x, 96.0f, 0.5f);
    ASSERT_TRUE(a.circles[0].n_bright_pixels > 250);
    ASSERT_TRUE(a.circles[0].n_bright_pixels < 400);
    ASSERT_TRUE(a.circles[1].n_bright_pixels > 250);
    ASSERT_TRUE(a.circles[1].n_bright_pixels < 400);
    ASSERT_TRUE(a.circles[0].radius_px > 7.0f);
    ASSERT_TRUE(a.circles[0].radius_px < 13.0f);
    ASSERT_TRUE(a.circles[1].radius_px > 7.0f);
    ASSERT_TRUE(a.circles[1].radius_px < 13.0f);
}

// Regression for the Y-flip bug in analysis.comp. The earlier
// `single_disc` and `two_discs_voronoi` tests all sit at y=H/2 which
// happens to be a fixed point of the flip transform (H-1-y == y up to
// half-a-pixel), so a buggy shader that compared GL texel gid directly
// against top-left light_px coordinates was numerically masked. This
// test puts the light deliberately near the top of the scene so the
// bug would report the disc at a wildly wrong radius.
TEST(gpu_light_circle_asymmetric_y) {
    auto& f = get_gpu_fixture();
    REQUIRE_TRUE(f.ready);
    const int W = 128, H = 128;

    // Light at world y = -0.75 inside [-1, 1]. viewport_xform gives
    // top-left pixel y = (1 - (-0.75)) * 64 = 112.
    // Upload order: glTexImage2D writes data rows in memory order,
    // which become GL texel rows in the same order; since GL treats
    // texel y=0 as the bottom, data row 15 lands at GL texel y = 15.
    // For the GPU shader (with the Y-flip fix) to find the disc, the
    // effective top-left coordinate H-1-15 = 112 must match the
    // light's top-left py = 112 — so we draw the disc at data-row 15.
    const float cx = 64.0f;
    const float cy_data = 15.0f;
    const float disc_r = 10.0f;
    auto buf = make_disc(W, H, cx, cy_data, disc_r, 255);
    TextureGuard tex(buf.data(), W, H);

    Bounds b = unit_bounds();
    std::vector<LightRef> lights = {LightRef{"light_0", 0.0f, -0.75f}};

    FrameAnalysisParams params;
    params.circles.bright_threshold = 0.8f;
    auto a = f.analyzer.analyze(tex.id, W, H, b, lights, params);

    REQUIRE_TRUE(a.circles.size() == 1);
    const auto& c = a.circles[0];
    // Without the Y-flip fix the shader would measure `d ≈ 97` for
    // every disc pixel (|gid.y=15 - light_py=112|), reporting a
    // ~97 px "radius" and failing this test.
    ASSERT_TRUE(c.radius_px > 7.0f);
    ASSERT_TRUE(c.radius_px < 13.0f);
    ASSERT_TRUE(c.n_bright_pixels > 200);
}

// Regression for the MAX_LIGHTS=20 truncation. Before the dynamic-SSBO
// refactor, scenes with > 20 point lights silently dropped the extras.
// This test uses 25 discrete lights — one per small disc — and asserts
// every one gets a LightCircle entry in the output.
TEST(gpu_light_circle_many_lights_no_truncation) {
    auto& f = get_gpu_fixture();
    REQUIRE_TRUE(f.ready);
    const int W = 256, H = 256;
    const int N = 25;
    std::vector<std::uint8_t> buf(static_cast<std::size_t>(W) *
                                  static_cast<std::size_t>(H) * 3u, 0);

    // 5x5 grid of small discs across the image — use a uniform grid
    // inside [-0.9, 0.9] so every light has its own Voronoi cell.
    std::vector<LightRef> lights;
    lights.reserve(static_cast<std::size_t>(N));
    int idx = 0;
    for (int gy = 0; gy < 5; ++gy) {
        for (int gx = 0; gx < 5; ++gx) {
            const float wx = -0.9f + 0.45f * static_cast<float>(gx);
            const float wy = -0.9f + 0.45f * static_cast<float>(gy);
            lights.push_back({std::string("light_") + std::to_string(idx++),
                              wx, wy});
            // Draw the disc at the corresponding pixel coordinate.
            // bounds = [-1,1]x[-1,1], W=H=256 → scale = 128.
            // Top-left pixel y = (1 - wy) * 128; but glTexImage2D will
            // place that data row at the same GL texel y, and the
            // shader's Y-flip restores the top-left alignment with the
            // light centres. So drawing at the top-left convention
            // works here.
            const float cx_f = (wx + 1.0f) * 128.0f;
            const float cy_f = (1.0f - wy) * 128.0f;
            const int   rad  = 4;
            for (int y = 0; y < H; ++y) {
                for (int x = 0; x < W; ++x) {
                    const float dx = static_cast<float>(x) - cx_f;
                    const float dy = static_cast<float>(y) - cy_f;
                    if (dx * dx + dy * dy <= rad * rad) {
                        const std::size_t i =
                            (static_cast<std::size_t>(y) *
                             static_cast<std::size_t>(W) +
                             static_cast<std::size_t>(x)) * 3u;
                        buf[i + 0] = 255;
                        buf[i + 1] = 255;
                        buf[i + 2] = 255;
                    }
                }
            }
        }
    }

    TextureGuard tex(buf.data(), W, H);
    FrameAnalysisParams params;
    params.circles.bright_threshold = 0.8f;
    auto a = f.analyzer.analyze(tex.id, W, H, unit_bounds(), lights, params);

    REQUIRE_TRUE(static_cast<int>(a.circles.size()) == N);
    // Every light should have measured its own disc (at least a few
    // bright pixels, sub-10px radius).
    int measured = 0;
    for (const auto& c : a.circles) {
        if (c.n_bright_pixels > 0) ++measured;
    }
    ASSERT_EQ(measured, N);
}

// Regression for the `analyze_circles=false` opt-out: when the caller
// sets the flag off, the returned circles vector must still contain
// one entry per input light (with zeroed measurement fields), and the
// GPU shouldn't actually run the per-pixel Voronoi loop. We can only
// assert the first half of that contract here; the perf is validated
// by inspection of n_lights_gpu in the debugger.
TEST(gpu_analyze_circles_opt_out_preserves_light_list) {
    auto& f = get_gpu_fixture();
    REQUIRE_TRUE(f.ready);
    const int W = 64, H = 64;
    auto buf = make_disc(W, H, 32.0f, 32.0f, 10.0f, 255);
    TextureGuard tex(buf.data(), W, H);

    std::vector<LightRef> lights = {
        LightRef{"light_0", -0.3f, 0.0f},
        LightRef{"light_1",  0.3f, 0.0f},
    };
    FrameAnalysisParams params;
    params.analyze_circles = false;  // opt out

    auto a = f.analyzer.analyze(tex.id, W, H, unit_bounds(), lights, params);

    // The caller still sees one LightCircle per input light, with id
    // and world coordinates populated but measurement fields zeroed.
    REQUIRE_TRUE(a.circles.size() == 2);
    ASSERT_EQ(a.circles[0].id, std::string("light_0"));
    ASSERT_EQ(a.circles[1].id, std::string("light_1"));
    ASSERT_NEAR(a.circles[0].radius_px, 0.0f, 1e-6f);
    ASSERT_EQ(a.circles[0].n_bright_pixels, 0);
    ASSERT_NEAR(a.circles[1].radius_px, 0.0f, 1e-6f);
    ASSERT_EQ(a.circles[1].n_bright_pixels, 0);
}

TEST(gpu_light_circle_no_bright_pixels_safe) {
    auto& f = get_gpu_fixture();
    REQUIRE_TRUE(f.ready);
    const int W = 32, H = 32;
    auto buf = make_solid_rgb(W, H, 0, 0, 0);
    TextureGuard tex(buf.data(), W, H);

    std::vector<LightRef> lights = {LightRef{"light_0", 0.0f, 0.0f}};
    auto a = f.analyzer.analyze(tex.id, W, H, unit_bounds(), lights, {});
    REQUIRE_TRUE(a.circles.size() == 1);
    ASSERT_NEAR(a.circles[0].radius_px,          0.0f, 1e-6f);
    ASSERT_NEAR(a.circles[0].radius_half_max_px, 0.0f, 1e-6f);
    ASSERT_EQ(a.circles[0].n_bright_pixels, 0);
    ASSERT_NEAR(a.circles[0].sharpness,      0.0f, 1e-6f);
    ASSERT_NEAR(a.circles[0].mean_luminance, 0.0f, 1e-6f);
}

TEST(gpu_light_circle_empty_lights_returns_empty) {
    auto& f = get_gpu_fixture();
    REQUIRE_TRUE(f.ready);
    const int W = 16, H = 16;
    auto buf = make_solid_rgb(W, H, 200, 200, 200);
    TextureGuard tex(buf.data(), W, H);
    auto a = f.analyzer.analyze(tex.id, W, H, unit_bounds(), {}, {});
    ASSERT_TRUE(a.circles.empty());
}

// ── Aggregate analysis ───────────────────────────────────────────────

TEST(gpu_analyze_frame_aggregates_lum_color_circles) {
    auto& f = get_gpu_fixture();
    REQUIRE_TRUE(f.ready);
    const int W = 64, H = 64;
    auto buf = make_disc(W, H, 32.0f, 32.0f, 12.0f, 255);
    TextureGuard tex(buf.data(), W, H);

    std::vector<LightRef> lights = {LightRef{"light_0", 0.0f, 0.0f}};
    FrameAnalysisParams params;
    params.circles.bright_threshold = 0.8f;
    auto a = f.analyzer.analyze(tex.id, W, H, unit_bounds(), lights, params);

    ASSERT_EQ(a.lum.width, W);
    ASSERT_EQ(a.lum.height, H);
    ASSERT_NEAR(a.color.chromatic_fraction, 0.0f, 1e-6f);
    REQUIRE_TRUE(a.circles.size() == 1);
    ASSERT_TRUE(a.circles[0].n_bright_pixels > 300);
}

TEST(gpu_analyze_frame_skip_circles_when_no_lights) {
    auto& f = get_gpu_fixture();
    REQUIRE_TRUE(f.ready);
    const int W = 16, H = 16;
    auto buf = make_solid_rgb(W, H, 128, 128, 128);
    TextureGuard tex(buf.data(), W, H);
    auto a = f.analyzer.analyze(tex.id, W, H, unit_bounds(), {}, {});
    ASSERT_TRUE(a.circles.empty());
}
