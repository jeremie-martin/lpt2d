#include "test_harness.h"
#include "color.h"
#include "spectrum.h"

#include <algorithm>
#include <cmath>

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
