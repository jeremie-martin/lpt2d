#!/usr/bin/env python3
"""Physics verification tests for the 2D light path tracer.

Tests: Snell's law, energy linear scaling, energy depth convergence,
chromatic dispersion, total internal reflection.
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
        CLI, "--stream",
        "--width", str(width), "--height", str(height),
        "--rays", str(rays),
        "--normalize", normalize,
        "--exposure", str(exposure),
        "--tonemap", tonemap,
        "--depth", str(depth),
        "--intensity", str(intensity),
        "--gamma", str(gamma),
    ]
    proc = subprocess.Popen(
        cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
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
                meta = json.loads(line[idx + 2:])

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
        "type": "beam", "origin": origin, "direction": direction,
        "angular_width": angular_width, "intensity": intensity,
        "wavelength_min": wl_min, "wavelength_max": wl_max,
    }


def point_light(pos, intensity=1.0):
    return {"type": "point", "pos": pos, "intensity": intensity}


def polygon_shape(vertices, material):
    return {"type": "polygon", "vertices": vertices, "material": material}


def segment_shape(a, b, material):
    return {"type": "segment", "a": a, "b": b, "material": material}


def mirror_box_walls(half=0.9):
    return [
        segment_shape([-half, -half], [half, -half], MIRROR_98),
        segment_shape([half, half], [-half, half], MIRROR_98),
        segment_shape([-half, half], [-half, -half], MIRROR_98),
        segment_shape([half, -half], [half, half], MIRROR_98),
    ]


def make_scene(shapes, lights, bounds):
    return {
        "version": 4, "name": "test",
        "camera": {"bounds": bounds},
        "shapes": shapes, "lights": lights, "groups": [],
    }


# ---------------------------------------------------------------------------
# Analysis helpers
# ---------------------------------------------------------------------------


def region_brightness(pixels: np.ndarray, row_start: int, row_end: int,
                      col_start: int, col_end: int) -> float:
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


# ---------------------------------------------------------------------------
# Test tracking
# ---------------------------------------------------------------------------

passed = 0
failed = 0


def check(name: str, condition: bool, detail: str):
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS  {name}")
    else:
        failed += 1
        print(f"  FAIL  {name}")
    print(f"        {detail}")


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

    check(
        "Snell's law lateral displacement",
        error_px < 25,
        f"expected x={x_expected_px:.1f}px, measured={centroid_px:.1f}px, error={error_px:.1f}px",
    )


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
    px1, _ = render_pixels(scene, rays=2_000_000, normalize="rays", tonemap="none", exposure=-8.0, gamma=1.0)
    mean1 = float(np.mean(px1))

    # Double intensity
    scene2 = make_scene(walls, [point_light([0.0, 0.0], intensity=2.0)], bounds)
    px2, _ = render_pixels(scene2, rays=2_000_000, normalize="rays", tonemap="none", exposure=-8.0, gamma=1.0)
    mean2 = float(np.mean(px2))

    ratio = mean2 / mean1 if mean1 > 5 else 0
    check(
        "intensity 2x → brightness 2x",
        abs(ratio - 2.0) < 0.20,
        f"mean1={mean1:.2f}, mean2={mean2:.2f}, ratio={ratio:.3f} (expected ~2.0)",
    )


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
        px, _ = render_pixels(scene, rays=3_000_000, depth=d, normalize="rays", tonemap="none", exposure=-8.0, gamma=1.0)
        means[d] = float(np.mean(px))
        print(f"  depth={d:2d}  mean_brightness={means[d]:.2f}")

    check(
        "more bounces → more energy",
        means[20] > means[4],
        f"depth=20: {means[20]:.2f} > depth=4: {means[4]:.2f}",
    )

    if means[16] > 0:
        convergence = means[20] / means[16]
        check(
            "depth=20 ≈ depth=16 (converging)",
            convergence < 1.25,
            f"ratio depth20/depth16 = {convergence:.4f} (should be < 1.25)",
        )


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
        {"ior": 1.5, "transmission": 1.0, "cauchy_b": 30000.0, "absorption": 0.3},
    )

    # Beam aimed directly at the left face for maximum throughput
    light = beam_light([-0.8, -0.05], [0.7, 0.15], angular_width=0.01)

    bounds = [-1.3, -0.9, 1.3, 0.9]
    scene = make_scene([prism], [light], bounds)

    W, H = 400, 300
    pixels, _ = render_pixels(scene, width=W, height=H, rays=15_000_000, exposure=-1.0, gamma=1.0)

    # Dispersed light exits to the right through the right face.
    # Measure R vs B row centroid in the right portion of the image.
    right = pixels[:, W * 2 // 3:, :]

    r_rows = right[:, :, 0].astype(np.float64).sum(axis=1)
    b_rows = right[:, :, 2].astype(np.float64).sum(axis=1)
    r_total, b_total = r_rows.sum(), b_rows.sum()
    if r_total > 100 and b_total > 100:
        rows = np.arange(H, dtype=np.float64)
        r_centroid = np.dot(r_rows, rows) / r_total
        b_centroid = np.dot(b_rows, rows) / b_total
        separation = abs(r_centroid - b_centroid)

        check(
            "red and blue peaks are separated",
            separation > 1.0,
            f"R centroid row={r_centroid:.1f}, B centroid row={b_centroid:.1f}, separation={separation:.1f}px",
        )
    else:
        check(
            "dispersion detectable",
            r_total > 100 and b_total > 100,
            f"R total={r_total:.0f}, B total={b_total:.0f} (need > 100 each)",
        )


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
    left_region = px_a[:, :W // 4, :]
    bright_a_left = float(np.mean(left_region))

    left_region_b = px_b[:, :W // 4, :]
    bright_b_left = float(np.mean(left_region_b))

    print(f"  High IOR (TIR expected):    left brightness = {bright_a_left:.2f}")
    print(f"  Low IOR  (no TIR):          left brightness = {bright_b_left:.2f}")

    # With TIR (ior=1.5), more light reflects to the left face
    # Without TIR (ior=1.2), light transmits through hypotenuse → less goes left
    check(
        "TIR: high-IOR reflects more light to left side",
        bright_a_left > bright_b_left * 2.0,
        f"high_ior_left={bright_a_left:.2f}, low_ior_left={bright_b_left:.2f}, ratio={bright_a_left / max(bright_b_left, 0.01):.2f}x",
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    test_snell_law()
    test_energy_linear()
    test_energy_depth_convergence()
    test_dispersion()
    test_tir()

    print(f"\n{'=' * 70}")
    print(f"Results: {passed} passed, {failed} failed")
    print(f"{'=' * 70}")
    sys.exit(1 if failed > 0 else 0)
