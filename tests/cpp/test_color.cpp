#include "test_harness.h"
#include "color.h"
#include "spectrum.h"

#include <algorithm>
#include <cmath>

static float shader_light_response(float nm, const LightSpectrum& spectrum) {
    if (spectrum.spectral_c0 == 0.0f &&
        spectrum.spectral_c1 == 0.0f &&
        spectrum.spectral_c2 == 0.0f)
        return 1.0f;

    float t = (nm - 380.0f) / 400.0f;
    float x = spectrum.spectral_c0 + spectrum.spectral_c1 * t + spectrum.spectral_c2 * t * t;
    return 0.5f + x / (2.0f * std::sqrt(1.0f + x * x));
}

static float luminance(float r, float g, float b) {
    return 0.2126f * r + 0.7152f * g + 0.0722f * b;
}

static float luminance(Vec3 rgb) {
    return luminance(rgb.r, rgb.g, rgb.b);
}

// --- wavelength_to_rgb ---

TEST(wavelength_green_peak) {
    // Green channel should peak somewhere around 520-550nm
    Vec3 at520 = wavelength_to_rgb(520.0f);
    Vec3 at380 = wavelength_to_rgb(380.0f);
    Vec3 at700 = wavelength_to_rgb(700.0f);
    ASSERT_TRUE(at520.g > at380.g);
    ASSERT_TRUE(at520.g > at700.g);
}

TEST(wavelength_red_dominant_at_640) {
    Vec3 rgb = wavelength_to_rgb(640.0f);
    ASSERT_TRUE(rgb.r > rgb.g);
    ASSERT_TRUE(rgb.r > rgb.b);
}

TEST(wavelength_blue_dominant_at_450) {
    Vec3 rgb = wavelength_to_rgb(450.0f);
    ASSERT_TRUE(rgb.b > rgb.r);
    ASSERT_TRUE(rgb.b > rgb.g);
}

TEST(wavelength_positive_channels) {
    // All RGB channels should be non-negative across the visible range
    for (float nm = 380.0f; nm <= 780.0f; nm += 10.0f) {
        Vec3 rgb = wavelength_to_rgb(nm);
        ASSERT_TRUE(rgb.r >= 0.0f);
        ASSERT_TRUE(rgb.g >= 0.0f);
        ASSERT_TRUE(rgb.b >= 0.0f);
    }
}

TEST(wavelength_clamps_out_of_range) {
    // Out-of-range wavelengths clamp to edges
    Vec3 below = wavelength_to_rgb(300.0f);
    Vec3 at380 = wavelength_to_rgb(380.0f);
    ASSERT_NEAR(below.r, at380.r, 1e-6f);
    ASSERT_NEAR(below.g, at380.g, 1e-6f);
    ASSERT_NEAR(below.b, at380.b, 1e-6f);

    Vec3 above = wavelength_to_rgb(900.0f);
    Vec3 at780 = wavelength_to_rgb(780.0f);
    ASSERT_NEAR(above.r, at780.r, 1e-6f);
    ASSERT_NEAR(above.g, at780.g, 1e-6f);
    ASSERT_NEAR(above.b, at780.b, 1e-6f);
}

// --- spectral_fill_rgb ---

TEST(spectral_fill_rgb_neutral_white) {
    Vec3 rgb = spectral_fill_rgb(0.0f, 0.0f, 0.0f);
    ASSERT_NEAR(rgb.r, 1.0f, 1e-6f);
    ASSERT_NEAR(rgb.g, 1.0f, 1e-6f);
    ASSERT_NEAR(rgb.b, 1.0f, 1e-6f);
}

TEST(spectral_fill_rgb_max_channel_is_one) {
    // Any non-zero coefficients: max channel should be normalized to 1.0
    auto coeffs = rgb_to_spectral(1.0f, 0.0f, 0.0f);  // pure red
    Vec3 rgb = spectral_fill_rgb(coeffs.c0, coeffs.c1, coeffs.c2);
    float m = std::max({rgb.r, rgb.g, rgb.b});
    ASSERT_NEAR(m, 1.0f, 1e-4f);
}

// --- spectral_to_rgb ---

TEST(spectral_to_rgb_neutral_white) {
    Vec3 rgb = spectral_to_rgb(0.0f, 0.0f, 0.0f);
    ASSERT_NEAR(rgb.r, 1.0f, 1e-6f);
    ASSERT_NEAR(rgb.g, 1.0f, 1e-6f);
    ASSERT_NEAR(rgb.b, 1.0f, 1e-6f);
}

TEST(range_to_color_spectrum_orange_is_reddish_and_scales_energy) {
    auto converted = range_to_color_spectrum(550.0f, 700.0f);
    ASSERT_EQ(converted.spectrum.type, LightSpectrumType::Color);
    ASSERT_NEAR(converted.spectrum.linear_r, 1.0f, 1e-6f);
    ASSERT_TRUE(converted.spectrum.linear_g > 0.35f);
    ASSERT_TRUE(converted.spectrum.linear_g < 0.45f);
    ASSERT_TRUE(converted.spectrum.linear_b < 0.01f);
    ASSERT_TRUE(converted.intensity_scale > 1.0f);
}

TEST(range_to_color_spectrum_headroom_dims_rgb_and_raises_scale) {
    auto full = range_to_color_spectrum(550.0f, 700.0f, 1.0f);
    auto half = range_to_color_spectrum(550.0f, 700.0f, 0.5f);
    ASSERT_NEAR(half.spectrum.linear_r, 0.5f, 1e-6f);
    ASSERT_TRUE(half.spectrum.linear_g < full.spectrum.linear_g);
    ASSERT_TRUE(half.intensity_scale > full.intensity_scale);
}

TEST(light_spectrum_color_mid_gray_avoids_white_sentinel) {
    LightSpectrum gray = light_spectrum_color(0.5f, 0.5f, 0.5f);
    ASSERT_EQ(gray.type, LightSpectrumType::Color);
    ASSERT_FALSE(gray.spectral_c0 == 0.0f &&
                 gray.spectral_c1 == 0.0f &&
                 gray.spectral_c2 == 0.0f);
    ASSERT_NEAR(shader_light_response(380.0f, gray), 0.5f, 1e-5f);
    ASSERT_NEAR(shader_light_response(580.0f, gray), 0.5f, 1e-5f);
    ASSERT_NEAR(shader_light_response(780.0f, gray), 0.5f, 1e-5f);

    LightSpectrum mixed_black = light_spectrum_color(0.0f, 0.0f, 0.0f, 0.5f);
    ASSERT_FALSE(mixed_black.spectral_c0 == 0.0f &&
                 mixed_black.spectral_c1 == 0.0f &&
                 mixed_black.spectral_c2 == 0.0f);
    ASSERT_NEAR(shader_light_response(580.0f, mixed_black), 0.5f, 1e-5f);
}

TEST(light_spectrum_color_white_keeps_white_sentinel) {
    LightSpectrum white = light_spectrum_color(1.0f, 1.0f, 1.0f);
    ASSERT_EQ(white.type, LightSpectrumType::Color);
    ASSERT_TRUE(white.spectral_c0 == 0.0f &&
                white.spectral_c1 == 0.0f &&
                white.spectral_c2 == 0.0f);
    ASSERT_NEAR(shader_light_response(580.0f, white), 1.0f, 1e-6f);
}

TEST(light_spectrum_color_fit_preserves_ambient_luminance_targets) {
    struct Case { float r, g, b, white_mix; };
    const Case cases[] = {
        {0.0f, 0.0f, 1.0f, 0.25f},
        {0.0f, 0.0f, 1.0f, 0.50f},
        {0.0f, 0.0f, 1.0f, 0.75f},
        {0.0f, 1.0f, 1.0f, 0.50f},
        {0.5f, 0.0f, 1.0f, 0.50f},
        {1.0f, 0.4f, 0.0f, 0.50f},
        {0.0f, 1.0f, 0.0f, 0.25f},
        {1.0f, 0.0f, 0.0f, 0.25f},
    };

    for (const Case& c : cases) {
        LightSpectrum spectrum = light_spectrum_color(c.r, c.g, c.b, c.white_mix);
        Vec3 fitted = spectral_to_rgb(spectrum.spectral_c0, spectrum.spectral_c1, spectrum.spectral_c2);
        float tr = c.r + (1.0f - c.r) * c.white_mix;
        float tg = c.g + (1.0f - c.g) * c.white_mix;
        float tb = c.b + (1.0f - c.b) * c.white_mix;
        float target_luminance = luminance(tr, tg, tb);
        ASSERT_TRUE(std::abs(luminance(fitted) - target_luminance) / target_luminance < 0.05f);
    }
}

// --- rgb_to_spectral / spectral_to_rgb roundtrip ---

TEST(spectral_roundtrip_red) {
    // Sigmoid model is an approximation; pure primaries don't round-trip exactly.
    // The key contract is that the dominant channel stays dominant.
    auto c = rgb_to_spectral(1.0f, 0.0f, 0.0f);
    Vec3 rgb = spectral_to_rgb(c.c0, c.c1, c.c2);
    ASSERT_TRUE(rgb.r > rgb.g);
    ASSERT_TRUE(rgb.r > rgb.b);
    ASSERT_TRUE(rgb.r > 0.5f);
}

TEST(spectral_roundtrip_green) {
    auto c = rgb_to_spectral(0.0f, 1.0f, 0.0f);
    Vec3 rgb = spectral_to_rgb(c.c0, c.c1, c.c2);
    ASSERT_TRUE(rgb.g > rgb.r);
    ASSERT_TRUE(rgb.g > rgb.b);
    ASSERT_TRUE(rgb.g > 0.5f);
}

TEST(spectral_roundtrip_blue) {
    auto c = rgb_to_spectral(0.0f, 0.0f, 1.0f);
    Vec3 rgb = spectral_to_rgb(c.c0, c.c1, c.c2);
    ASSERT_TRUE(rgb.b > rgb.r);
    ASSERT_TRUE(rgb.b > rgb.g);
    ASSERT_TRUE(rgb.b > 0.5f);
}

TEST(spectral_roundtrip_neutral) {
    // White (1,1,1) roundtrips through spectral_to_rgb back to balanced channels
    auto c = rgb_to_spectral(1.0f, 1.0f, 1.0f);
    Vec3 rgb = spectral_to_rgb(c.c0, c.c1, c.c2);
    // Should be roughly balanced (all channels within 20% of each other)
    float range = std::max({rgb.r, rgb.g, rgb.b}) - std::min({rgb.r, rgb.g, rgb.b});
    ASSERT_TRUE(range < 0.2f);
}

// --- Named colors ---

TEST(named_color_count_positive) {
    ASSERT_TRUE(named_color_count() > 0);
}

TEST(named_color_red_resolves) {
    auto c = named_color("red");
    ASSERT_TRUE(c.has_value());
}

TEST(named_color_green_resolves) {
    auto c = named_color("green");
    ASSERT_TRUE(c.has_value());
}

TEST(named_color_blue_resolves) {
    auto c = named_color("blue");
    ASSERT_TRUE(c.has_value());
}

TEST(named_color_unknown_returns_nullopt) {
    auto c = named_color("nonexistent_color_xyz");
    ASSERT_FALSE(c.has_value());
}

TEST(named_color_red_produces_reddish_rgb) {
    auto c = named_color("red");
    ASSERT_TRUE(c.has_value());
    Vec3 rgb = spectral_to_rgb(c->c0, c->c1, c->c2);
    ASSERT_TRUE(rgb.r > rgb.g);
    ASSERT_TRUE(rgb.r > rgb.b);
}
