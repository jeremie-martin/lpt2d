// Frame-analysis tests.
//
// `GpuImageAnalyzer` is the production path for rendered frames. The CPU RGB8
// analyzer is still covered here as a deterministic reference utility.

#include "test_harness.h"

#include "gpu_image_analysis.h"
#include "headless.h"
#include "image_analysis.h"
#include "scene.h"
#include "session.h"

#include <GL/glew.h>

#include <algorithm>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <vector>

namespace {

constexpr float kPi = 3.14159265358979323846f;

struct GpuFixture {
    HeadlessGL gl;
    GpuImageAnalyzer analyzer;
    bool ready = false;
};

void init_gpu_fixture(GpuFixture& f) {
    if (!f.gl.init()) return;
    if (!f.gl.make_current()) return;

    glewExperimental = GL_TRUE;
    if (glewContextInit() != GLEW_OK) return;
    if (!f.analyzer.init()) return;

    f.ready = true;
}

struct TextureGuard {
    GLuint id = 0;

    TextureGuard(const std::uint8_t* data, int w, int h) {
        glGenTextures(1, &id);
        glBindTexture(GL_TEXTURE_2D, id);
        glPixelStorei(GL_UNPACK_ALIGNMENT, 1);
        glTexImage2D(GL_TEXTURE_2D, 0, GL_RGB8, w, h, 0, GL_RGB,
                     GL_UNSIGNED_BYTE, data);
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

std::vector<std::uint8_t> make_solid_rgb(int w, int h,
                                         std::uint8_t r,
                                         std::uint8_t g,
                                         std::uint8_t b) {
    std::vector<std::uint8_t> buf(static_cast<std::size_t>(w) *
                                  static_cast<std::size_t>(h) * 3u);
    for (std::size_t i = 0; i < buf.size() / 3u; ++i) {
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

std::vector<std::uint8_t> make_disc_rgb(int w, int h, float cx, float cy,
                                        float radius,
                                        std::uint8_t r,
                                        std::uint8_t g,
                                        std::uint8_t b) {
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
                buf[i + 0] = r;
                buf[i + 1] = g;
                buf[i + 2] = b;
            }
        }
    }
    return buf;
}

void draw_disc(std::vector<std::uint8_t>& buf, int w, int h,
               float cx, float cy, float radius, std::uint8_t value) {
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
}

Bounds unit_bounds(float hw = 1.0f, float hh = 1.0f) {
    return Bounds{Vec2{-hw, -hh}, Vec2{hw, hh}};
}

FrameAnalysis analyze_cpu(const std::vector<std::uint8_t>& rgb, int w, int h,
                          const Bounds& bounds = unit_bounds(),
                          std::span<const LightRef> lights = {},
                          const FrameAnalysisParams& params = {}) {
    return analyze_rgb8_frame(rgb, w, h, bounds, lights, params);
}

float expected_disc_coverage(float radius_px, int w, int h) {
    return (kPi * radius_px * radius_px) / static_cast<float>(w * h);
}

}  // namespace

TEST(frame_luminance_solid_grey_cpu) {
    auto buf = make_solid_rgb(16, 16, 128, 128, 128);
    auto a = analyze_cpu(buf, 16, 16);

    ASSERT_EQ(a.luminance.width, 16);
    ASSERT_EQ(a.luminance.height, 16);
    ASSERT_NEAR(a.luminance.mean, 128.0f, 1.0f);
    ASSERT_NEAR(a.luminance.shadow_floor, 128.0f, 1.0f);
    ASSERT_NEAR(a.luminance.median, 128.0f, 1.0f);
    ASSERT_NEAR(a.luminance.highlight_ceiling, 128.0f, 1.0f);
    ASSERT_NEAR(a.luminance.highlight_peak, 128.0f, 1.0f);
    ASSERT_NEAR(a.luminance.contrast_std, 0.0f, 1.0f);
    ASSERT_NEAR(a.luminance.near_black_fraction, 0.0f, 1e-6f);
    ASSERT_NEAR(a.luminance.near_white_fraction, 0.0f, 1e-6f);
    ASSERT_NEAR(a.luminance.clipped_channel_fraction, 0.0f, 1e-6f);
}

TEST(frame_luminance_tiny_solid_grey_percentiles_cpu) {
    for (int size : {1, 4}) {
        auto buf = make_solid_rgb(size, size, 128, 128, 128);
        auto a = analyze_cpu(buf, size, size);

        ASSERT_NEAR(a.luminance.shadow_floor, 128.0f, 1.0f);
        ASSERT_NEAR(a.luminance.median, 128.0f, 1.0f);
        ASSERT_NEAR(a.luminance.highlight_ceiling, 128.0f, 1.0f);
        ASSERT_NEAR(a.luminance.highlight_peak, 128.0f, 1.0f);
    }
}

TEST(frame_luminance_half_black_half_white_cpu) {
    auto buf = make_half_black_white(32, 32);
    auto a = analyze_cpu(buf, 32, 32);

    ASSERT_NEAR(a.luminance.mean, 127.0f, 2.0f);
    ASSERT_NEAR(a.luminance.shadow_floor, 0.0f, 1.0f);
    ASSERT_NEAR(a.luminance.highlight_peak, 255.0f, 1.0f);
    ASSERT_TRUE(a.luminance.contrast_std > 100.0f);
    ASSERT_NEAR(a.luminance.near_black_fraction, 0.5f, 1e-4f);
    ASSERT_NEAR(a.luminance.near_white_fraction, 0.5f, 1e-4f);
    ASSERT_NEAR(a.luminance.clipped_channel_fraction, 0.5f, 1e-4f);
}

TEST(frame_luminance_clipped_channel_fraction_detects_any_channel_cpu) {
    auto buf = make_solid_rgb(2, 2, 255, 0, 0);
    auto a = analyze_cpu(buf, 2, 2);
    ASSERT_NEAR(a.luminance.clipped_channel_fraction, 1.0f, 1e-6f);
}

TEST(frame_color_stats_greyscale_zero_cpu) {
    auto buf = make_solid_rgb(16, 16, 128, 128, 128);
    auto a = analyze_cpu(buf, 16, 16);

    ASSERT_NEAR(a.color.colored_fraction, 0.0f, 1e-6f);
    ASSERT_NEAR(a.color.mean_saturation, 0.0f, 1e-6f);
    ASSERT_NEAR(a.color.hue_entropy, 0.0f, 1e-6f);
    ASSERT_NEAR(a.color.richness, 0.0f, 1e-6f);
}

TEST(frame_color_stats_three_primaries_cpu) {
    const int w = 36;
    const int h = 4;
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

    auto a = analyze_cpu(buf, w, h);
    ASSERT_NEAR(a.color.colored_fraction, 1.0f, 1e-4f);
    ASSERT_NEAR(a.color.mean_saturation, 1.0f, 0.01f);
    ASSERT_NEAR(a.color.hue_entropy, 1.585f, 0.02f);
    ASSERT_TRUE(a.color.richness > 1.5f);
}

TEST(point_light_appearance_single_disc_cpu) {
    const int w = 128;
    const int h = 128;
    const float cx = 64.0f;
    const float cy = 64.0f;
    const float disc_r = 20.0f;
    auto buf = make_disc(w, h, cx, cy, disc_r, 255);

    const std::vector<LightRef> lights = {LightRef{"light_0", 0.0f, 0.0f}};
    auto a = analyze_cpu(buf, w, h, unit_bounds(), lights);

    REQUIRE_TRUE(a.lights.size() == 1);
    const auto& light = a.lights[0];
    ASSERT_TRUE(light.visible);
    ASSERT_NEAR(light.image_x, cx, 0.1f);
    ASSERT_NEAR(light.image_y, cy, 0.1f);
    ASSERT_NEAR(light.radius_ratio, disc_r / 128.0f, 0.02f);
    ASSERT_NEAR(light.saturated_radius_ratio, disc_r / 128.0f, 0.02f);
    ASSERT_NEAR(light.coverage_fraction, expected_disc_coverage(disc_r, w, h), 0.01f);
    ASSERT_NEAR(light.background_luminance, 0.0f, 1e-6f);
    ASSERT_NEAR(light.peak_luminance, 1.0f, 1e-6f);
    ASSERT_NEAR(light.peak_contrast, 1.0f, 1e-6f);
    ASSERT_TRUE(light.transition_width_ratio <= 0.02f);
    ASSERT_TRUE(!light.touches_frame_edge);
    ASSERT_TRUE(light.confidence > 0.9f);
}

TEST(point_light_appearance_two_discs_stay_separate_cpu) {
    const int w = 128;
    const int h = 64;
    std::vector<std::uint8_t> buf(static_cast<std::size_t>(w) *
                                  static_cast<std::size_t>(h) * 3u, 0);
    draw_disc(buf, w, h, 32.0f, 32.0f, 10.0f, 255);
    draw_disc(buf, w, h, 96.0f, 32.0f, 10.0f, 255);

    const Bounds bounds{Vec2{-1.0f, -0.5f}, Vec2{1.0f, 0.5f}};
    const std::vector<LightRef> lights = {
        LightRef{"light_0", -0.5f, 0.0f},
        LightRef{"light_1", 0.5f, 0.0f},
    };
    auto a = analyze_cpu(buf, w, h, bounds, lights);

    REQUIRE_TRUE(a.lights.size() == 2);
    ASSERT_NEAR(a.lights[0].image_x, 32.0f, 0.5f);
    ASSERT_NEAR(a.lights[1].image_x, 96.0f, 0.5f);
    ASSERT_TRUE(a.lights[0].visible);
    ASSERT_TRUE(a.lights[1].visible);
    ASSERT_NEAR(a.lights[0].radius_ratio, 10.0f / 64.0f, 0.03f);
    ASSERT_NEAR(a.lights[1].radius_ratio, 10.0f / 64.0f, 0.03f);
    ASSERT_TRUE(a.lights[0].confidence > 0.5f);
    ASSERT_TRUE(a.lights[1].confidence > 0.5f);
}

TEST(point_light_appearance_edge_truncation_reduces_confidence_cpu) {
    const int w = 128;
    const int h = 128;
    auto buf = make_disc(w, h, 8.0f, 64.0f, 16.0f, 255);

    const std::vector<LightRef> lights = {LightRef{"edge_light", -0.875f, 0.0f}};
    auto a = analyze_cpu(buf, w, h, unit_bounds(), lights);

    REQUIRE_TRUE(a.lights.size() == 1);
    const auto& light = a.lights[0];
    ASSERT_TRUE(light.visible);
    ASSERT_TRUE(light.touches_frame_edge);
    ASSERT_TRUE(light.confidence < 0.8f);
    ASSERT_TRUE(light.radius_ratio > 0.0f);
}

TEST(point_light_appearance_opt_out_preserves_light_list_cpu) {
    const int w = 64;
    const int h = 64;
    auto buf = make_disc(w, h, 32.0f, 32.0f, 10.0f, 255);

    FrameAnalysisParams params;
    params.analyze_lights = false;
    const std::vector<LightRef> lights = {
        LightRef{"light_0", -0.3f, 0.0f},
        LightRef{"light_1", 0.3f, 0.0f},
    };
    auto a = analyze_cpu(buf, w, h, unit_bounds(), lights, params);

    REQUIRE_TRUE(a.lights.size() == 2);
    ASSERT_EQ(a.lights[0].id, std::string("light_0"));
    ASSERT_EQ(a.lights[1].id, std::string("light_1"));
    ASSERT_TRUE(!a.lights[0].visible);
    ASSERT_TRUE(!a.lights[1].visible);
    ASSERT_NEAR(a.lights[0].radius_ratio, 0.0f, 1e-6f);
    ASSERT_NEAR(a.lights[1].radius_ratio, 0.0f, 1e-6f);
}

TEST(point_light_appearance_resolution_invariance_cpu) {
    const std::vector<LightRef> lights = {LightRef{"light_0", 0.0f, 0.0f}};

    auto low = make_disc(64, 64, 32.0f, 32.0f, 9.0f, 255);
    auto a_low = analyze_cpu(low, 64, 64, unit_bounds(), lights);

    auto high = make_disc(128, 128, 64.0f, 64.0f, 18.0f, 255);
    auto a_high = analyze_cpu(high, 128, 128, unit_bounds(), lights);

    REQUIRE_TRUE(a_low.lights.size() == 1);
    REQUIRE_TRUE(a_high.lights.size() == 1);
    ASSERT_NEAR(a_low.lights[0].radius_ratio, a_high.lights[0].radius_ratio, 0.02f);
    ASSERT_NEAR(a_low.lights[0].saturated_radius_ratio,
                a_high.lights[0].saturated_radius_ratio, 0.02f);
    ASSERT_NEAR(a_low.lights[0].transition_width_ratio,
                a_high.lights[0].transition_width_ratio, 0.02f);
}

TEST(point_light_appearance_empty_lights_returns_empty_cpu) {
    auto buf = make_solid_rgb(16, 16, 200, 200, 200);
    auto a = analyze_cpu(buf, 16, 16);
    ASSERT_TRUE(a.lights.empty());
}

TEST(gpu_analyzer_smoke_luminance_color_contract) {
    GpuFixture f;
    init_gpu_fixture(f);
    REQUIRE_TRUE(f.ready);
    auto buf = make_solid_rgb(16, 16, 128, 128, 128);
    TextureGuard tex(buf.data(), 16, 16);

    FrameAnalysisParams params;
    params.analyze_lights = false;
    auto a = f.analyzer.analyze(tex.id, 16, 16, unit_bounds(), {}, params);

    ASSERT_EQ(a.luminance.width, 16);
    ASSERT_EQ(a.luminance.height, 16);
    ASSERT_NEAR(a.luminance.mean, 128.0f, 1.0f);
    ASSERT_NEAR(a.color.colored_fraction, 0.0f, 1e-6f);
    ASSERT_TRUE(a.lights.empty());
}

TEST(gpu_analyzer_smoke_light_contract) {
    GpuFixture f;
    init_gpu_fixture(f);
    REQUIRE_TRUE(f.ready);
    const int w = 128;
    const int h = 128;
    auto buf = make_disc(w, h, 64.0f, 64.0f, 20.0f, 255);
    TextureGuard tex(buf.data(), w, h);

    const std::vector<LightRef> lights = {LightRef{"light_0", 0.0f, 0.0f}};
    auto a = f.analyzer.analyze(tex.id, w, h, unit_bounds(), lights, {});

    REQUIRE_TRUE(a.lights.size() == 1);
    ASSERT_NEAR(a.lights[0].image_x, 64.0f, 0.5f);
    ASSERT_NEAR(a.lights[0].image_y, 64.0f, 0.5f);
    ASSERT_TRUE(a.lights[0].visible);
    ASSERT_NEAR(a.lights[0].radius_ratio, 20.0f / 128.0f, 0.035f);
    ASSERT_NEAR(a.lights[0].saturated_radius_ratio, 20.0f / 128.0f, 0.035f);
    ASSERT_NEAR(a.lights[0].coverage_fraction, expected_disc_coverage(20.0f, w, h), 0.025f);
    ASSERT_TRUE(a.lights[0].peak_contrast > 0.9f);
    ASSERT_TRUE(a.lights[0].transition_width_ratio <= 0.06f);
    ASSERT_TRUE(a.lights[0].confidence > 0.0f);
}

TEST(gpu_analyzer_colored_light_uses_channel_signal_not_luminance_only) {
    GpuFixture f;
    init_gpu_fixture(f);
    REQUIRE_TRUE(f.ready);
    const int w = 128;
    const int h = 128;
    auto buf = make_disc_rgb(w, h, 64.0f, 64.0f, 20.0f, 0, 255, 0);
    TextureGuard tex(buf.data(), w, h);

    const std::vector<LightRef> lights = {LightRef{"green_light", 0.0f, 0.0f}};
    auto a = f.analyzer.analyze(tex.id, w, h, unit_bounds(), lights, {});

    REQUIRE_TRUE(a.lights.size() == 1);
    ASSERT_TRUE(a.lights[0].visible);
    ASSERT_NEAR(a.lights[0].radius_ratio, 20.0f / 128.0f, 0.035f);
    ASSERT_NEAR(a.lights[0].saturated_radius_ratio, 20.0f / 128.0f, 0.035f);
    ASSERT_NEAR(a.lights[0].peak_luminance, 0.7152f, 0.05f);
    ASSERT_TRUE(a.lights[0].confidence > 0.0f);
}

TEST(render_session_analysis_keeps_display_texture_y_convention) {
    constexpr int w = 128;
    constexpr int h = 128;

    Scene scene;
    Material fill;
    fill.fill = 5.0f;
    scene.materials["fill"] = fill;
    scene.shapes.emplace_back(Circle{"disc", Vec2{0.0f, 0.5f}, 0.2f, "fill"});
    scene.lights.emplace_back(PointLight{"light_0", Vec2{0.0f, 0.5f}, 1.0f});

    Shot shot;
    shot.scene = scene;
    shot.camera.center = Vec2{0.0f, 0.0f};
    shot.camera.width = 2.0f;
    shot.canvas = Canvas{w, h};
    shot.look.exposure = 0.0f;
    shot.look.gamma = 1.0f;
    shot.look.tonemap = ToneMap::None;
    shot.look.normalize = NormalizeMode::Fixed;
    shot.look.normalize_ref = 1.0f;
    shot.trace.rays = 0;
    shot.trace.batch = 1;
    shot.trace.depth = 1;

    RenderSession session(w, h);
    RenderResult rr = session.render_shot(shot, 0, true);

    double sum_x = 0.0;
    double sum_y = 0.0;
    int bright = 0;
    for (int y = 0; y < h; ++y) {
        for (int x = 0; x < w; ++x) {
            const std::size_t i =
                (static_cast<std::size_t>(y) * static_cast<std::size_t>(w) +
                 static_cast<std::size_t>(x)) * 3u;
            const auto mx = std::max({rr.pixels[i + 0], rr.pixels[i + 1], rr.pixels[i + 2]});
            if (mx > 100u) {
                sum_x += static_cast<double>(x);
                sum_y += static_cast<double>(y);
                ++bright;
            }
        }
    }

    REQUIRE_TRUE(bright > 0);
    const double image_cx = sum_x / static_cast<double>(bright);
    const double image_cy = sum_y / static_cast<double>(bright);
    REQUIRE_TRUE(rr.analysis.lights.size() == 1);
    const auto& light = rr.analysis.lights[0];

    ASSERT_NEAR(image_cx, 63.5, 1.0);
    ASSERT_NEAR(image_cy, 31.5, 1.0);
    ASSERT_NEAR(light.image_x, 64.0f, 0.5f);
    ASSERT_NEAR(light.image_y, 32.0f, 0.5f);
    ASSERT_TRUE(light.visible);
    ASSERT_NEAR(light.radius_ratio, 0.10f, 0.03f);
    ASSERT_TRUE(light.confidence > 0.0f);
}

TEST(render_session_large_standard_mirror_batch_stays_finite) {
    constexpr int w = 1280;
    constexpr int h = 720;
    constexpr float room_half = 1.8f;

    Scene scene;
    scene.materials["wall"] = mat_opaque_mirror(1.0f, 0.1f);
    scene.shapes.emplace_back(Segment{"wall_bottom", Vec2{-room_half, -room_half}, Vec2{ room_half, -room_half}, "wall"});
    scene.shapes.emplace_back(Segment{"wall_right",  Vec2{ room_half, -room_half}, Vec2{ room_half,  room_half}, "wall"});
    scene.shapes.emplace_back(Segment{"wall_top",    Vec2{ room_half,  room_half}, Vec2{-room_half,  room_half}, "wall"});
    scene.shapes.emplace_back(Segment{"wall_left",   Vec2{-room_half,  room_half}, Vec2{-room_half, -room_half}, "wall"});
    scene.lights.emplace_back(PointLight{"light_0", Vec2{0.0f, 0.0f}, 1.0f});

    Shot shot;
    shot.scene = scene;
    shot.camera.center = Vec2{0.0f, 0.0f};
    shot.camera.width = 4.0f;
    shot.canvas = Canvas{w, h};
    shot.look.exposure = -6.0f;
    shot.look.white_point = 0.125f;
    shot.look.gamma = 2.0f;
    shot.look.tonemap = ToneMap::ReinhardExtended;
    shot.look.normalize = NormalizeMode::Rays;
    shot.trace.rays = 10'000'000;
    shot.trace.batch = 1'000'000;
    shot.trace.depth = 12;

    RenderSession session(w, h);
    RenderResult rr = session.render_shot(shot, 0, true);

    const auto max_px = *std::max_element(rr.pixels.begin(), rr.pixels.end());
    REQUIRE_TRUE(max_px > 0);

    const auto& lum = rr.analysis.luminance;
    ASSERT_TRUE(lum.mean >= 0.0f && lum.mean <= 255.0f);
    ASSERT_TRUE(lum.near_black_fraction >= 0.0f && lum.near_black_fraction <= 1.0f);
    ASSERT_TRUE(lum.near_white_fraction >= 0.0f && lum.near_white_fraction <= 1.0f);
    ASSERT_TRUE(lum.clipped_channel_fraction >= 0.0f && lum.clipped_channel_fraction <= 1.0f);

    REQUIRE_TRUE(rr.analysis.lights.size() == 1);
    const auto& light = rr.analysis.lights[0];
    ASSERT_TRUE(light.visible);
    ASSERT_TRUE(light.radius_ratio > 0.03f);
    ASSERT_TRUE(light.radius_ratio < 0.10f);
    ASSERT_TRUE(light.confidence > 0.5f);
}
