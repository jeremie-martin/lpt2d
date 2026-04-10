"""Binding-level tests for the new C++ image_analysis module.

These tests exercise the pure analyzer helpers (no renderer involvement)
by constructing synthetic RGB8 byte buffers with ``bytearray`` — no numpy
dependency, matching the "no pixel math in Python" direction of the port.
"""

from __future__ import annotations

import math

import _lpt2d


def _solid_rgb(width: int, height: int, r: int, g: int, b: int) -> bytes:
    row = bytes((r, g, b)) * width
    return row * height


def _disc_rgb(width: int, height: int, cx: float, cy: float, radius: float,
              value: int) -> bytes:
    buf = bytearray(width * height * 3)
    r2 = radius * radius
    for y in range(height):
        for x in range(width):
            dx = x - cx
            dy = y - cy
            if dx * dx + dy * dy <= r2:
                i = (y * width + x) * 3
                buf[i] = value
                buf[i + 1] = value
                buf[i + 2] = value
    return bytes(buf)


# ── Luminance ──────────────────────────────────────────────────────────


def test_luminance_solid_grey():
    rgb = _solid_rgb(16, 16, 128, 128, 128)
    s = _lpt2d.compute_luminance_stats(rgb, 16, 16)
    assert s.width == 16
    assert s.height == 16
    assert abs(s.mean_lum - 128.0) < 1.0
    assert abs(s.p05 - 128.0) < 1.0
    assert abs(s.p50 - 128.0) < 1.0
    assert abs(s.p95 - 128.0) < 1.0
    assert abs(s.p99 - 128.0) < 1.0
    assert abs(s.std_dev) < 1e-4
    assert abs(s.pct_black) < 1e-6
    assert abs(s.pct_clipped) < 1e-6
    assert s.lum_min == 128
    assert s.lum_max == 128
    assert len(s.histogram) == 256
    assert s.histogram[128] == 16 * 16


def test_luminance_half_black_white():
    # Top half (0..7) black, bottom half (8..15) white.
    W, H = 16, 16
    buf = bytearray(W * H * 3)
    for y in range(H // 2, H):
        for x in range(W):
            i = (y * W + x) * 3
            buf[i] = 255
            buf[i + 1] = 255
            buf[i + 2] = 255
    s = _lpt2d.compute_luminance_stats(bytes(buf), W, H)
    assert abs(s.pct_black - 0.5) < 1e-4
    assert abs(s.pct_clipped - 0.5) < 1e-4
    assert s.lum_min == 0
    assert s.lum_max == 255
    assert s.std_dev > 100.0


def test_luminance_empty_size_safe():
    s = _lpt2d.compute_luminance_stats(b"", 0, 0)
    assert s.width == 0
    assert s.height == 0
    assert s.mean_lum == 0.0


def test_luminance_short_buffer_raises():
    import pytest
    with pytest.raises(ValueError):
        _lpt2d.compute_luminance_stats(b"\x00\x00\x00", 4, 4)


# ── Colour ─────────────────────────────────────────────────────────────


def test_color_stats_greyscale_zero():
    rgb = _solid_rgb(16, 16, 128, 128, 128)
    c = _lpt2d.compute_color_stats(rgb, 16, 16)
    assert c.chromatic_fraction == 0.0
    assert c.mean_saturation == 0.0
    assert c.hue_entropy == 0.0
    assert c.color_richness == 0.0
    assert c.n_chromatic == 0


def test_color_stats_pure_red_single_bin():
    rgb = _solid_rgb(16, 16, 255, 0, 0)
    c = _lpt2d.compute_color_stats(rgb, 16, 16)
    assert abs(c.chromatic_fraction - 1.0) < 1e-4
    assert abs(c.mean_saturation - 1.0) < 1e-4
    # Single populated bin → entropy 0.
    assert abs(c.hue_entropy) < 1e-4
    assert abs(c.color_richness) < 1e-4
    assert c.n_chromatic == 16 * 16


def test_color_stats_rgb_three_bins():
    # Three primary colours striped across a 3x1 buffer → three equal hue bins
    # → entropy = log2(3).
    buf = bytes([
        255, 0, 0,
        0, 255, 0,
        0, 0, 255,
    ])
    c = _lpt2d.compute_color_stats(buf, 3, 1)
    assert abs(c.hue_entropy - math.log2(3)) < 1e-3
    assert abs(c.chromatic_fraction - 1.0) < 1e-4


# ── Light circles ──────────────────────────────────────────────────────


def test_measure_light_circles_single_disc():
    W, H = 128, 128
    rgb = _disc_rgb(W, H, 64.0, 64.0, 20.0, 255)
    bounds = _lpt2d.Bounds([-1.0, -1.0], [1.0, 1.0])
    light = _lpt2d.LightRef("light_0", 0.0, 0.0)
    params = _lpt2d.LightCircleParams()
    params.bright_threshold = 0.8
    circles = _lpt2d.measure_light_circles(rgb, W, H, bounds, [light], params)
    assert len(circles) == 1
    c = circles[0]
    assert c.id == "light_0"
    assert abs(c.pixel_x - 64.0) < 0.5
    assert abs(c.pixel_y - 64.0) < 0.5
    # Disc radius 20 px → measurement should land in a ±3 px band.
    assert 17.0 < c.radius_px < 23.0
    assert 15.0 < c.radius_half_max_px < 25.0
    # pi * 20² ≈ 1257 bright pixels inside the cell.
    assert c.n_bright_pixels > 1000
    assert c.sharpness > 0.0
    # Mean luminance: disc is ~1/13th of the frame → well below 0.2.
    assert 0.0 < c.mean_luminance < 0.2
    # Profile is the radial mean luminance; inside the disc should be ~1.0.
    assert len(c.profile) > 20
    assert c.profile[0] > 0.9


def test_measure_light_circles_two_discs_voronoi():
    W, H = 128, 64
    rgb = bytearray(W * H * 3)
    for (cx, cy) in [(32.0, 32.0), (96.0, 32.0)]:
        for y in range(H):
            for x in range(W):
                dx = x - cx
                dy = y - cy
                if dx * dx + dy * dy <= 100.0:  # radius 10
                    i = (y * W + x) * 3
                    rgb[i] = 255
                    rgb[i + 1] = 255
                    rgb[i + 2] = 255
    bounds = _lpt2d.Bounds([-1.0, -0.5], [1.0, 0.5])
    lights = [
        _lpt2d.LightRef("light_0", -0.5, 0.0),
        _lpt2d.LightRef("light_1", 0.5, 0.0),
    ]
    params = _lpt2d.LightCircleParams()
    params.bright_threshold = 0.8
    circles = _lpt2d.measure_light_circles(bytes(rgb), W, H, bounds, lights, params)
    assert len(circles) == 2
    assert abs(circles[0].pixel_x - 32.0) < 0.5
    assert abs(circles[1].pixel_x - 96.0) < 0.5
    for c in circles:
        # pi*10² ≈ 314 bright pixels per cell.
        assert 250 < c.n_bright_pixels < 400
        assert 7.0 < c.radius_px < 13.0


def test_measure_light_circles_no_lights():
    rgb = _solid_rgb(16, 16, 255, 255, 255)
    bounds = _lpt2d.Bounds([-1.0, -1.0], [1.0, 1.0])
    circles = _lpt2d.measure_light_circles(rgb, 16, 16, bounds, [])
    assert circles == []


def test_measure_light_circles_black_frame():
    rgb = _solid_rgb(32, 32, 0, 0, 0)
    bounds = _lpt2d.Bounds([-1.0, -1.0], [1.0, 1.0])
    light = _lpt2d.LightRef("light_0", 0.0, 0.0)
    circles = _lpt2d.measure_light_circles(rgb, 32, 32, bounds, [light])
    assert len(circles) == 1
    c = circles[0]
    assert c.radius_px == 0.0
    assert c.radius_half_max_px == 0.0
    assert c.n_bright_pixels == 0
    assert c.sharpness == 0.0
    assert c.mean_luminance == 0.0


# ── Aggregate ──────────────────────────────────────────────────────────


def test_analyze_frame_aggregates_all_three():
    W, H = 64, 64
    rgb = _disc_rgb(W, H, 32.0, 32.0, 12.0, 255)
    bounds = _lpt2d.Bounds([-1.0, -1.0], [1.0, 1.0])
    light = _lpt2d.LightRef("light_0", 0.0, 0.0)
    params = _lpt2d.FrameAnalysisParams()
    params.circles.bright_threshold = 0.8
    a = _lpt2d.analyze_frame(rgb, W, H, bounds, [light], params)
    # lum
    assert a.lum.width == W
    assert a.lum.height == H
    assert a.lum.mean_lum > 0.0
    # color — pure white/black, so no chroma.
    assert a.color.chromatic_fraction == 0.0
    # circles — one measured circle for the light.
    assert len(a.circles) == 1
    assert a.circles[0].n_bright_pixels > 300


def test_analyze_frame_skip_flags():
    W, H = 16, 16
    rgb = _solid_rgb(W, H, 128, 128, 128)
    bounds = _lpt2d.Bounds([-1.0, -1.0], [1.0, 1.0])
    light = _lpt2d.LightRef("light_0", 0.0, 0.0)
    params = _lpt2d.FrameAnalysisParams()
    params.analyze_color = False
    params.analyze_circles = False
    a = _lpt2d.analyze_frame(rgb, W, H, bounds, [light], params)
    assert a.lum.width == W
    # ColorStats with default-constructed zero fields.
    assert a.color.chromatic_fraction == 0.0
    assert a.color.color_richness == 0.0
    assert a.circles == []
