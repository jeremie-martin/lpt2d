#!/usr/bin/env python3
"""Physics verification tests for the 2D light path tracer.

Tests: Snell's law, energy linear scaling, energy depth convergence,
chromatic dispersion, total internal reflection, energy conservation,
lens focusing.
"""

from __future__ import annotations

import json
import math
import subprocess
import sys

import numpy as np

CLI = "./build/lpt2d-cli"

# ---------------------------------------------------------------------------
# Rendering helpers
# ---------------------------------------------------------------------------


def render_pixels(
    scene_dict: dict,
    *,
    width: int = 200,
    height: int = 200,
    rays: int = 2_000_000,
    normalize: str = "rays",
    exposure: float = 0.0,
    tonemap: str = "none",
    depth: int = 12,
    intensity: float = 1.0,
    gamma: float = 1.0,
) -> tuple[np.ndarray, dict]:
    """Render and return (H, W, 3) uint8 array + metadata dict."""
    scene_json = json.dumps(scene_dict, separators=(",", ":"))
    cmd = [
        CLI,
        "--stream",
        "--width",
        str(width),
        "--height",
        str(height),
        "--rays",
        str(rays),
        "--normalize",
        normalize,
        "--exposure",
        str(exposure),
        "--tonemap",
        tonemap,
        "--depth",
        str(depth),
        "--intensity",
        str(intensity),
        "--gamma",
        str(gamma),
    ]
    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert proc.stdin and proc.stdout and proc.stderr
    proc.stdin.write((scene_json + "\n").encode())
    proc.stdin.close()

    frame_bytes = width * height * 3
    pixel_data = proc.stdout.read(frame_bytes)
    stderr_text = proc.stderr.read().decode()
    proc.wait()

    if len(pixel_data) != frame_bytes:
        raise RuntimeError(f"Renderer failed. stderr:\n{stderr_text}")

    meta = {}
    for line in stderr_text.strip().splitlines():
        if "max_hdr" in line:
            idx = line.find(": {")
            if idx >= 0:
                meta = json.loads(line[idx + 2 :])

    pixels = np.frombuffer(pixel_data, dtype=np.uint8).reshape(height, width, 3)
    return pixels, meta


# ---------------------------------------------------------------------------
# Scene construction helpers
# ---------------------------------------------------------------------------

GLASS = {"ior": 1.5, "transmission": 1.0}
GLASS_DISPERSIVE = {"ior": 1.5, "transmission": 1.0, "cauchy_b": 20000.0}
ABSORBER = {"albedo": 0.0}
MIRROR_98 = {"metallic": 1.0, "albedo": 0.98, "transmission": 0.0}


def beam_light(origin, direction, angular_width=0.005, intensity=1.0, wl_min=380.0, wl_max=780.0):
    return {
        "type": "beam",
        "origin": origin,
        "direction": direction,
        "angular_width": angular_width,
        "intensity": intensity,
        "wavelength_min": wl_min,
        "wavelength_max": wl_max,
    }


def point_light(pos, intensity=1.0):
    return {"type": "point", "pos": pos, "intensity": intensity}


def polygon_shape(vertices, material):
    return {"type": "polygon", "vertices": vertices, "material": material}


def segment_shape(a, b, material):
    return {"type": "segment", "a": a, "b": b, "material": material}


def circle_shape(center, radius, material):
    return {"type": "circle", "center": center, "radius": radius, "material": material}


def parallel_beam_light(a, b, direction, angular_width=0.0, intensity=1.0):
    return {
        "type": "parallel_beam",
        "a": a,
        "b": b,
        "direction": direction,
        "angular_width": angular_width,
        "intensity": intensity,
    }


def mirror_box_walls(half=0.9):
    return [
        segment_shape([-half, -half], [half, -half], MIRROR_98),
        segment_shape([half, half], [-half, half], MIRROR_98),
        segment_shape([-half, half], [-half, -half], MIRROR_98),
        segment_shape([half, -half], [half, half], MIRROR_98),
    ]


def make_scene(shapes, lights, bounds):
    return {
        "version": 4,
        "name": "test",
        "camera": {"bounds": bounds},
        "shapes": shapes,
        "lights": lights,
        "groups": [],
    }


# ---------------------------------------------------------------------------
# Analysis helpers
# ---------------------------------------------------------------------------


def region_brightness(
    pixels: np.ndarray, row_start: int, row_end: int, col_start: int, col_end: int
) -> float:
    """Mean pixel value in a rectangular region."""
    region = pixels[row_start:row_end, col_start:col_end]
    return float(np.mean(region))


def column_centroid(pixels: np.ndarray, row_start: int, row_end: int) -> float:
    """Brightness-weighted centroid column index within a row range."""
    strip = pixels[row_start:row_end].astype(np.float64)
    lum = strip.mean(axis=2)  # average RGB
    col_brightness = lum.sum(axis=0)  # sum over rows
    total = col_brightness.sum()
    if total < 1e-6:
        return pixels.shape[1] / 2.0
    cols = np.arange(pixels.shape[1], dtype=np.float64)
    return float(np.dot(col_brightness, cols) / total)


def polygon_area2(vertices) -> float:
    area2 = 0.0
    for i, a in enumerate(vertices):
        b = vertices[(i + 1) % len(vertices)]
        area2 += a[0] * b[1] - b[0] * a[1]
    return area2


# ---------------------------------------------------------------------------
# Test 1: Snell's law — beam through glass slab
# ---------------------------------------------------------------------------


def test_snell_law():
    print("\n=== Test 1: Snell's law ===\n")

    # Glass slab: rectangle centered at y=0, CW winding for outward normals
    slab = polygon_shape(
        [[-0.8, -0.15], [-0.8, 0.15], [0.8, 0.15], [0.8, -0.15]],
        GLASS,
    )

    # Beam at 30 degrees from vertical, entering from above
    theta_i = math.radians(30)
    dx, dy = math.sin(theta_i), -math.cos(theta_i)
    light = beam_light([0.0, 0.7], [dx, dy], angular_width=0.003)

    bounds = [-1.0, -1.0, 1.0, 1.0]
    scene = make_scene([slab], [light], bounds)

    W, H = 300, 300
    pixels, _ = render_pixels(scene, width=W, height=H, rays=5_000_000, exposure=-4.0)

    # Step-by-step expected beam position:
    n = 1.5
    slab_top, slab_bot = 0.15, -0.15
    theta_r = math.asin(math.sin(theta_i) / n)

    # Beam from (0, 0.7) along (sin θ_i, -cos θ_i) hits slab top at y=0.15
    t_entry = (0.7 - slab_top) / math.cos(theta_i)
    x_entry = 0.0 + math.sin(theta_i) * t_entry

    # Inside slab, travels at θ_r from vertical for thickness 0.3
    x_exit = x_entry + (slab_top - slab_bot) * math.tan(theta_r)

    # After exit, continues at original θ_i angle
    y_measure = -0.5
    x_measure = x_exit + (slab_bot - y_measure) * math.tan(theta_i)

    # Convert to pixel coords
    x_expected_px = (x_measure - bounds[0]) / (bounds[2] - bounds[0]) * W
    y_row = int((bounds[3] - y_measure) / (bounds[3] - bounds[1]) * H)

    strip_half = 15
    row_lo = max(0, y_row - strip_half)
    row_hi = min(H, y_row + strip_half)
    centroid_px = column_centroid(pixels, row_lo, row_hi)

    error_px = abs(centroid_px - x_expected_px)

    detail = (
        f"expected x={x_expected_px:.1f}px, measured={centroid_px:.1f}px, error={error_px:.1f}px"
    )
    print(f"        {detail}")
    assert error_px < 25, f"Snell's law lateral displacement: {detail}"


def test_polygon_winding_is_physics_invariant():
    print("\n=== Test 1b: Polygon winding invariance ===\n")

    clockwise = [[-0.8, -0.15], [-0.8, 0.15], [0.8, 0.15], [0.8, -0.15]]
    counter_clockwise = list(reversed(clockwise))
    assert polygon_area2(clockwise) < 0
    assert polygon_area2(counter_clockwise) > 0

    theta_i = math.radians(30)
    dx, dy = math.sin(theta_i), -math.cos(theta_i)
    light = beam_light([0.0, 0.7], [dx, dy], angular_width=0.003)
    bounds = [-1.0, -1.0, 1.0, 1.0]
    W, H = 240, 240

    def centroid_for(vertices):
        scene = make_scene([polygon_shape(vertices, GLASS)], [light], bounds)
        pixels, _ = render_pixels(scene, width=W, height=H, rays=4_000_000, exposure=-4.0)
        y_measure = -0.5
        y_row = int((bounds[3] - y_measure) / (bounds[3] - bounds[1]) * H)
        row_lo = max(0, y_row - 12)
        row_hi = min(H, y_row + 12)
        return column_centroid(pixels, row_lo, row_hi)

    cw_centroid = centroid_for(clockwise)
    ccw_centroid = centroid_for(counter_clockwise)
    detail = f"CW={cw_centroid:.1f}px, CCW={ccw_centroid:.1f}px"
    print(f"        {detail}")
    assert abs(cw_centroid - ccw_centroid) < 10.0, f"polygon winding changed refraction: {detail}"


# ---------------------------------------------------------------------------
# Test 2: Energy linear scaling
# ---------------------------------------------------------------------------


def test_energy_linear():
    print("\n=== Test 2: Energy linear scaling ===\n")

    walls = mirror_box_walls()
    light = point_light([0.0, 0.0], intensity=1.0)
    bounds = [-1.0, -1.0, 1.0, 1.0]
    scene = make_scene(walls, [light], bounds)

    # Use exposure that puts values in a measurable range without clipping
    # Gamma=1.0 ensures linear output
    px1, _ = render_pixels(
        scene, rays=2_000_000, normalize="rays", tonemap="none", exposure=-8.0, gamma=1.0
    )
    mean1 = float(np.mean(px1))

    # Double intensity
    scene2 = make_scene(walls, [point_light([0.0, 0.0], intensity=2.0)], bounds)
    px2, _ = render_pixels(
        scene2, rays=2_000_000, normalize="rays", tonemap="none", exposure=-8.0, gamma=1.0
    )
    mean2 = float(np.mean(px2))

    ratio = mean2 / mean1 if mean1 > 5 else 0
    detail = f"mean1={mean1:.2f}, mean2={mean2:.2f}, ratio={ratio:.3f} (expected ~2.0)"
    print(f"        {detail}")
    assert abs(ratio - 2.0) < 0.20, f"intensity 2x → brightness 2x: {detail}"


def test_segment_light_emits_both_sides():
    print("\n=== Test 2b: Segment light emits both sides ===\n")

    collectors = [
        segment_shape([-0.9, 0.7], [0.9, 0.7], ABSORBER),
        segment_shape([0.9, -0.7], [-0.9, -0.7], ABSORBER),
    ]
    light = {"type": "segment", "a": [-0.4, 0.0], "b": [0.4, 0.0], "intensity": 2.0}
    scene = make_scene(collectors, [light], [-1.0, -1.0, 1.0, 1.0])

    pixels, _ = render_pixels(scene, width=220, height=220, rays=5_000_000, exposure=-4.0)
    top = region_brightness(pixels, 20, 80, 60, 160)
    bottom = region_brightness(pixels, 140, 200, 60, 160)
    detail = f"top={top:.2f}, bottom={bottom:.2f}"
    print(f"        {detail}")
    assert top > 2.0 and bottom > 2.0, f"segment light should illuminate both sides: {detail}"
    assert abs(top - bottom) / max(top, bottom) < 0.2, f"segment light should be roughly symmetric: {detail}"


def test_emissive_segment_is_endpoint_order_invariant():
    print("\n=== Test 2c: Emissive segment endpoint order invariance ===\n")

    collectors = [
        segment_shape([-0.9, 0.7], [0.9, 0.7], ABSORBER),
        segment_shape([0.9, -0.7], [-0.9, -0.7], ABSORBER),
    ]
    bounds = [-1.0, -1.0, 1.0, 1.0]

    def measure(a, b):
        scene = make_scene(
            collectors + [segment_shape(a, b, {"albedo": 0.0, "emission": 2.0})],
            [],
            bounds,
        )
        pixels, _ = render_pixels(scene, width=220, height=220, rays=5_000_000, exposure=-4.0)
        top = region_brightness(pixels, 20, 80, 60, 160)
        bottom = region_brightness(pixels, 140, 200, 60, 160)
        return top, bottom

    forward = measure([-0.4, 0.0], [0.4, 0.0])
    reverse = measure([0.4, 0.0], [-0.4, 0.0])
    detail = (
        f"forward(top={forward[0]:.2f}, bottom={forward[1]:.2f}), "
        f"reverse(top={reverse[0]:.2f}, bottom={reverse[1]:.2f})"
    )
    print(f"        {detail}")
    assert abs(forward[0] - reverse[0]) / max(forward[0], reverse[0]) < 0.2, detail
    assert abs(forward[1] - reverse[1]) / max(forward[1], reverse[1]) < 0.2, detail


# ---------------------------------------------------------------------------
# Test 3: Energy depth convergence
# ---------------------------------------------------------------------------


def test_energy_depth_convergence():
    print("\n=== Test 3: Energy depth convergence ===\n")

    walls = [
        segment_shape([-0.9, -0.9], [0.9, -0.9], MIRROR_98),
        segment_shape([0.9, 0.9], [-0.9, 0.9], MIRROR_98),
        segment_shape([-0.9, 0.9], [-0.9, -0.9], MIRROR_98),
        segment_shape([0.9, -0.9], [0.9, 0.9], MIRROR_98),
    ]
    light = point_light([0.0, 0.0])
    bounds = [-1.0, -1.0, 1.0, 1.0]
    scene = make_scene(walls, [light], bounds)

    means = {}
    for d in [4, 16, 20]:
        px, _ = render_pixels(
            scene,
            rays=3_000_000,
            depth=d,
            normalize="rays",
            tonemap="none",
            exposure=-8.0,
            gamma=1.0,
        )
        means[d] = float(np.mean(px))
        print(f"  depth={d:2d}  mean_brightness={means[d]:.2f}")

    detail = f"depth=20: {means[20]:.2f} > depth=4: {means[4]:.2f}"
    print(f"        {detail}")
    assert means[20] > means[4], f"more bounces → more energy: {detail}"

    if means[16] > 0:
        convergence = means[20] / means[16]
        detail = f"ratio depth20/depth16 = {convergence:.4f} (should be < 1.25)"
        print(f"        {detail}")
        assert convergence < 1.25, f"depth=20 ≈ depth=16 (converging): {detail}"


# ---------------------------------------------------------------------------
# Test 4: Chromatic dispersion
# ---------------------------------------------------------------------------


def test_dispersion():
    print("\n=== Test 4: Chromatic dispersion ===\n")

    # Equilateral prism with strong Cauchy dispersion.
    # Beam enters left face, exits right face, dispersing into a spectrum.
    # Wide view with long path from prism to screen so separation is measurable.
    # Prism geometry matching prism.json convention (CW winding, outward normals).
    prism = polygon_shape(
        [[-0.1, -0.208], [0.3, 0.139], [-0.5, 0.139]],
        {"ior": 1.5, "transmission": 1.0, "cauchy_b": 80000.0, "absorption": 0.3},
    )

    # Beam aimed directly at the left face for maximum throughput
    light = beam_light([-0.8, -0.05], [0.7, 0.15], angular_width=0.01)

    bounds = [-1.3, -0.9, 1.3, 0.9]
    scene = make_scene([prism], [light], bounds)

    W, H = 400, 300
    pixels, _ = render_pixels(scene, width=W, height=H, rays=15_000_000, exposure=-1.0, gamma=1.0)

    # Dispersed light exits to the right through the right face.
    # Measure R vs B row centroid in the right portion of the image.
    right = pixels[:, W * 2 // 3 :, :]

    r_rows = right[:, :, 0].astype(np.float64).sum(axis=1)
    b_rows = right[:, :, 2].astype(np.float64).sum(axis=1)
    r_total, b_total = r_rows.sum(), b_rows.sum()
    if r_total > 100 and b_total > 100:
        rows = np.arange(H, dtype=np.float64)
        r_centroid = np.dot(r_rows, rows) / r_total
        b_centroid = np.dot(b_rows, rows) / b_total
        separation = abs(r_centroid - b_centroid)

        detail = f"R centroid row={r_centroid:.1f}, B centroid row={b_centroid:.1f}, separation={separation:.1f}px"
        print(f"        {detail}")
        assert separation > 1.0, f"red and blue peaks are separated: {detail}"
    else:
        detail = f"R total={r_total:.0f}, B total={b_total:.0f} (need > 100 each)"
        print(f"        {detail}")
        assert r_total > 100 and b_total > 100, f"dispersion detectable: {detail}"


# ---------------------------------------------------------------------------
# Test 5: Total internal reflection (TIR)
# ---------------------------------------------------------------------------


def test_tir():
    print("\n=== Test 5: Total internal reflection ===\n")

    # Right-angle prism (isosceles right triangle).
    # CW winding for outward normals. Short sides along bottom and right.
    # Hypotenuse from top-left to bottom-right.
    #
    # A beam entering the bottom face vertically hits the hypotenuse at 45°.
    # For ior=1.5: critical angle = 41.8°. Since 45° > 41.8° → TIR.
    # For ior=1.2: critical angle = 56.4°. Since 45° < 56.4° → transmission.
    #
    # After TIR at the hypotenuse, the reflected beam goes LEFT and exits
    # the left face. Transmitted light (no TIR) exits through the hypotenuse
    # toward the upper-right.
    sz = 0.6
    # CW: bottom-left → top-left → bottom-right
    verts = [[-sz / 2, -sz / 2], [-sz / 2, sz / 2], [sz / 2, -sz / 2]]
    prism_high = polygon_shape(verts, {"ior": 1.5, "transmission": 1.0})
    prism_low = polygon_shape(verts, {"ior": 1.2, "transmission": 1.0})

    # Beam enters from below, going straight up into the bottom face
    light = beam_light([0.0, -0.7], [0.0, 1.0], angular_width=0.02)

    bounds = [-1.0, -1.0, 1.0, 1.0]
    W, H = 200, 200

    scene_a = make_scene([prism_high], [light], bounds)
    px_a, _ = render_pixels(scene_a, width=W, height=H, rays=3_000_000, exposure=-3.0, gamma=1.0)

    scene_b = make_scene([prism_low], [light], bounds)
    px_b, _ = render_pixels(scene_b, width=W, height=H, rays=3_000_000, exposure=-3.0, gamma=1.0)

    # Measure the LEFT side (where TIR-reflected light exits the left face)
    left_region = px_a[:, : W // 4, :]
    bright_a_left = float(np.mean(left_region))

    left_region_b = px_b[:, : W // 4, :]
    bright_b_left = float(np.mean(left_region_b))

    print(f"  High IOR (TIR expected):    left brightness = {bright_a_left:.2f}")
    print(f"  Low IOR  (no TIR):          left brightness = {bright_b_left:.2f}")

    # With TIR (ior=1.5), more light reflects to the left face
    # Without TIR (ior=1.2), light transmits through hypotenuse → less goes left
    detail = f"high_ior_left={bright_a_left:.2f}, low_ior_left={bright_b_left:.2f}, ratio={bright_a_left / max(bright_b_left, 0.01):.2f}x"
    print(f"        {detail}")
    assert bright_a_left > bright_b_left * 2.0, (
        f"TIR: high-IOR reflects more light to left side: {detail}"
    )


# ---------------------------------------------------------------------------
# Test 6: Energy conservation — mirror box geometric series
# ---------------------------------------------------------------------------


def test_energy_conservation():
    print("\n=== Test 6: Energy conservation ===\n")

    # Mirror box with 98% reflective walls and a point light.
    # At depth D, the captured energy fraction is sum(0.98^k, k=0..D-1).
    # Ratio of depth20/depth4 should match the theoretical ratio.
    walls = mirror_box_walls()
    light = point_light([0.0, 0.0])
    bounds = [-1.0, -1.0, 1.0, 1.0]
    scene = make_scene(walls, [light], bounds)

    depths = [4, 12, 20]
    means = {}
    for d in depths:
        px, _ = render_pixels(
            scene,
            rays=3_000_000,
            depth=d,
            normalize="rays",
            tonemap="none",
            exposure=-8.0,
            gamma=1.0,
        )
        means[d] = float(np.mean(px))
        print(f"  depth={d:2d}  mean_brightness={means[d]:.2f}")

    # Theoretical geometric series: S(D) = sum(r^k, k=0..D-1) = (1 - r^D) / (1 - r)
    r = 0.98
    s4 = (1 - r**4) / (1 - r)
    s12 = (1 - r**12) / (1 - r)
    s20 = (1 - r**20) / (1 - r)

    # Verify ratios match theory within tolerance
    if means[4] > 2:
        ratio_12_4 = means[12] / means[4]
        expected_12_4 = s12 / s4
        error_12_4 = abs(ratio_12_4 - expected_12_4) / expected_12_4
        detail = f"ratio d12/d4: measured={ratio_12_4:.3f}, expected={expected_12_4:.3f}, error={error_12_4:.1%}"
        print(f"        {detail}")
        assert error_12_4 < 0.20, f"energy depth ratio d12/d4: {detail}"

        ratio_20_4 = means[20] / means[4]
        expected_20_4 = s20 / s4
        error_20_4 = abs(ratio_20_4 - expected_20_4) / expected_20_4
        detail = f"ratio d20/d4: measured={ratio_20_4:.3f}, expected={expected_20_4:.3f}, error={error_20_4:.1%}"
        print(f"        {detail}")
        assert error_20_4 < 0.20, f"energy depth ratio d20/d4: {detail}"
    else:
        raise AssertionError(f"scene too dark to measure: mean_d4={means[4]:.2f}")


# ---------------------------------------------------------------------------
# Test 7: Lens focusing — parallel beam through glass circle
# ---------------------------------------------------------------------------


def test_lens_focus():
    print("\n=== Test 7: Lens focusing ===\n")

    # Glass circle acts as a ball lens. A parallel beam from above should
    # converge to a focal region below the lens.
    lens = circle_shape([0.0, 0.0], 0.25, GLASS)

    # Wide parallel beam from above, covering the lens diameter
    light = parallel_beam_light([-0.3, 0.7], [0.3, 0.7], [0.0, -1.0])

    bounds = [-1.0, -1.0, 1.0, 1.0]
    W, H = 200, 200
    scene = make_scene([lens], [light], bounds)

    pixels, _ = render_pixels(scene, width=W, height=H, rays=5_000_000, exposure=-3.0, gamma=1.0)

    # Measure brightness in horizontal strips below the lens.
    # The focal region should have concentrated brightness in a narrow
    # column range compared to the full beam width.
    # Look at a strip well below the lens (y around -0.4 to -0.6)
    focal_row_start = int((bounds[3] - (-0.3)) / (bounds[3] - bounds[1]) * H)
    focal_row_end = int((bounds[3] - (-0.7)) / (bounds[3] - bounds[1]) * H)

    strip = pixels[focal_row_start:focal_row_end].astype(np.float64)
    col_brightness = strip.mean(axis=2).sum(axis=0)  # brightness per column
    total = col_brightness.sum()

    if total < 100:
        raise AssertionError(f"too dark below lens to measure focus: total={total:.1f}")

    # Compute the fraction of brightness in the central 20% of columns
    center_start = int(W * 0.4)
    center_end = int(W * 0.6)
    center_fraction = col_brightness[center_start:center_end].sum() / total

    # Without a lens, a beam this wide would spread 60% of width = 30% of image width
    # With a lens, most light should concentrate in the center
    detail = f"center 20% of columns contains {center_fraction:.1%} of light (expect > 50%)"
    print(f"        {detail}")
    assert center_fraction > 0.50, f"lens focus concentration: {detail}"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    tests = [
        test_snell_law,
        test_energy_linear,
        test_energy_depth_convergence,
        test_dispersion,
        test_tir,
        test_energy_conservation,
        test_lens_focus,
    ]
    passed = 0
    failed = 0
    for t in tests:
        try:
            t()
            passed += 1
            print(f"  PASS  {t.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"  FAIL  {t.__name__}: {e}")
    print(f"\n{'=' * 70}")
    print(f"Results: {passed} passed, {failed} failed")
    print(f"{'=' * 70}")
    sys.exit(1 if failed > 0 else 0)
