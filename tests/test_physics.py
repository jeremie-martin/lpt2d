#!/usr/bin/env python3
"""Physics and geometry verification tests for the 2D light path tracer.

Tests: Snell's law, energy linear scaling, energy depth convergence,
chromatic dispersion, total internal reflection, energy conservation,
lens focusing, and exact ellipse group transforms.
"""

from __future__ import annotations

import json
import math
import subprocess
import sys
from itertools import count

import numpy as np

CLI = "./build/lpt2d-cli"
_SHAPE_IDS = count()
_LIGHT_IDS = count()

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
        "id": f"beam_light_{next(_LIGHT_IDS)}",
        "type": "beam",
        "origin": origin,
        "direction": direction,
        "angular_width": angular_width,
        "intensity": intensity,
        "wavelength_min": wl_min,
        "wavelength_max": wl_max,
    }


def point_light(pos, intensity=1.0):
    return {
        "id": f"point_light_{next(_LIGHT_IDS)}",
        "type": "point",
        "pos": pos,
        "intensity": intensity,
    }


def segment_light(a, b, intensity=1.0, wl_min=380.0, wl_max=780.0):
    return {
        "id": f"segment_light_{next(_LIGHT_IDS)}",
        "type": "segment",
        "a": a,
        "b": b,
        "intensity": intensity,
        "wavelength_min": wl_min,
        "wavelength_max": wl_max,
    }


def polygon_shape(vertices, material):
    return {
        "id": f"polygon_{next(_SHAPE_IDS)}",
        "type": "polygon",
        "vertices": vertices,
        "material": material,
    }


def segment_shape(a, b, material):
    return {
        "id": f"segment_{next(_SHAPE_IDS)}",
        "type": "segment",
        "a": a,
        "b": b,
        "material": material,
    }


def circle_shape(center, radius, material):
    return {
        "id": f"circle_{next(_SHAPE_IDS)}",
        "type": "circle",
        "center": center,
        "radius": radius,
        "material": material,
    }


def ellipse_shape(center, semi_a, semi_b, rotation, material):
    return {
        "id": f"ellipse_{next(_SHAPE_IDS)}",
        "type": "ellipse",
        "center": center,
        "semi_a": semi_a,
        "semi_b": semi_b,
        "rotation": rotation,
        "material": material,
    }


def arc_shape(center, radius, angle_start, sweep, material):
    return {
        "id": f"arc_{next(_SHAPE_IDS)}",
        "type": "arc",
        "center": center,
        "radius": radius,
        "angle_start": angle_start,
        "sweep": sweep,
        "material": material,
    }


def parallel_beam_light(a, b, direction, angular_width=0.0, intensity=1.0):
    return {
        "id": f"parallel_beam_light_{next(_LIGHT_IDS)}",
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
        "version": 7,
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


def normalize2(v):
    x, y = float(v[0]), float(v[1])
    length = math.hypot(x, y)
    if length < 1e-12:
        raise ValueError("zero-length vector")
    return [x / length, y / length]


def refract_exit(direction, outward_normal, n_inside: float, n_outside: float = 1.0):
    d = normalize2(direction)
    n = normalize2(outward_normal)
    cos_i = d[0] * n[0] + d[1] * n[1]
    eta = n_inside / n_outside
    sin_t_sq = eta * eta * max(0.0, 1.0 - cos_i * cos_i)
    if sin_t_sq >= 1.0:
        return None
    cos_t = math.sqrt(max(0.0, 1.0 - sin_t_sq))
    return normalize2(
        [
            eta * d[0] + (cos_t - eta * cos_i) * n[0],
            eta * d[1] + (cos_t - eta * cos_i) * n[1],
        ]
    )


def measure_emissive_shape_both_sides(
    shape: dict,
    *,
    bounds: list[float] | None = None,
    width: int = 180,
    height: int = 180,
    rays: int = 1_500_000,
) -> tuple[float, float]:
    if bounds is None:
        bounds = [-1.0, -1.0, 1.0, 1.0]

    collectors = [
        segment_shape([-0.9, 0.75], [0.9, 0.75], ABSORBER),
        segment_shape([0.9, -0.75], [-0.9, -0.75], ABSORBER),
    ]
    scene = make_scene(collectors + [shape], [], bounds)
    pixels, _ = render_pixels(
        scene,
        width=width,
        height=height,
        rays=rays,
        normalize="rays",
        tonemap="none",
        exposure=-4.0,
        gamma=1.0,
    )
    top = region_brightness(pixels, 10, 50, 40, width - 40)
    bottom = region_brightness(pixels, height - 50, height - 10, 40, width - 40)
    return top, bottom


def assert_emissive_shape_lights_both_sides(
    name: str,
    shape: dict,
    *,
    min_brightness: float = 0.75,
    max_imbalance: float = 0.35,
) -> None:
    top, bottom = measure_emissive_shape_both_sides(shape)
    detail = f"top={top:.2f}, bottom={bottom:.2f}"
    print(f"        {name}: {detail}")
    assert top > min_brightness and bottom > min_brightness, (
        f"{name} should light both sides: {detail}"
    )
    assert abs(top - bottom) / max(top, bottom) < max_imbalance, (
        f"{name} should be roughly symmetric above/below: {detail}"
    )


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
    light = segment_light([-0.4, 0.0], [0.4, 0.0], intensity=2.0)
    scene = make_scene(collectors, [light], [-1.0, -1.0, 1.0, 1.0])

    pixels, _ = render_pixels(scene, width=220, height=220, rays=5_000_000, exposure=-4.0)
    top = region_brightness(pixels, 20, 80, 60, 160)
    bottom = region_brightness(pixels, 140, 200, 60, 160)
    detail = f"top={top:.2f}, bottom={bottom:.2f}"
    print(f"        {detail}")
    assert top > 2.0 and bottom > 2.0, f"segment light should illuminate both sides: {detail}"
    assert abs(top - bottom) / max(top, bottom) < 0.2, (
        f"segment light should be roughly symmetric: {detail}"
    )


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


def test_emissive_circle_lights_both_sides():
    print("\n=== Test 2d: Emissive circle lights both sides ===\n")

    assert_emissive_shape_lights_both_sides(
        "circle",
        circle_shape([0.0, 0.0], 0.32, {"albedo": 0.0, "emission": 2.0}),
        max_imbalance=0.25,
    )


def test_emissive_polygon_lights_both_sides():
    print("\n=== Test 2e: Emissive polygon lights both sides ===\n")

    assert_emissive_shape_lights_both_sides(
        "polygon",
        polygon_shape(
            [[-0.32, -0.32], [-0.32, 0.32], [0.32, 0.32], [0.32, -0.32]],
            {"albedo": 0.0, "emission": 2.0},
        ),
        max_imbalance=0.25,
    )


def test_emissive_arc_lights_both_sides():
    print("\n=== Test 2f: Emissive arc lights both sides ===\n")

    assert_emissive_shape_lights_both_sides(
        "arc",
        arc_shape([0.0, 0.0], 0.42, -math.pi / 2, math.pi, {"albedo": 0.0, "emission": 2.0}),
        max_imbalance=0.35,
    )


def test_emissive_ellipse_lights_both_sides():
    print("\n=== Test 2g: Emissive ellipse lights both sides ===\n")

    assert_emissive_shape_lights_both_sides(
        "ellipse",
        ellipse_shape([0.0, 0.0], 0.42, 0.24, 0.0, {"albedo": 0.0, "emission": 2.0}),
        max_imbalance=0.25,
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
# Test 4: Chromatic dispersion vs Cauchy prediction
# ---------------------------------------------------------------------------


def test_dispersion():
    print("\n=== Test 4: Chromatic dispersion ===\n")

    cauchy_b = 60_000.0
    prism = polygon_shape(
        [[-0.4, -0.25], [0.25, -0.1], [0.35, 0.1], [-0.4, 0.25]],
        {"ior": 1.5, "transmission": 1.0, "cauchy_b": cauchy_b, "absorption": 0.0},
    )
    screen = segment_shape([0.9, -0.35], [0.9, 0.75], ABSORBER)
    bounds = [-1.1, -0.6, 1.1, 0.9]
    exit_point = [0.3, 0.0]
    exit_normal = normalize2([0.2, -0.1])
    screen_x = 0.9
    width, height = 420, 300

    def measure_row(wavelength_nm):
        scene = make_scene(
            [prism, screen],
            [
                beam_light(
                    [-0.8, 0.0],
                    [1.0, 0.0],
                    angular_width=0.002,
                    wl_min=wavelength_nm,
                    wl_max=wavelength_nm,
                )
            ],
            bounds,
        )
        pixels, _ = render_pixels(
            scene,
            width=width,
            height=height,
            rays=9_000_000,
            normalize="rays",
            tonemap="none",
            exposure=-3.5,
            gamma=1.0,
        )
        screen_col = int((screen_x - bounds[0]) / (bounds[2] - bounds[0]) * width)
        col_lo = max(0, screen_col - 16)
        col_hi = min(width, screen_col + 16)
        strip = pixels[:, col_lo:col_hi].astype(np.float64)
        row_energy = strip.mean(axis=2).sum(axis=1)
        total = row_energy.sum()
        if total < 100.0:
            raise AssertionError(
                f"screen too dark to measure at {wavelength_nm:.0f} nm: total={total:.1f}"
            )
        peak = int(np.argmax(row_energy))
        # Escape-path overlays can add low-level energy outside the main screen hit.
        # Measure a local centroid around the dominant lobe instead of the whole strip.
        row_lo = max(0, peak - 16)
        row_hi = min(height, peak + 17)
        local_energy = row_energy[row_lo:row_hi]
        rows = np.arange(row_lo, row_hi, dtype=np.float64)
        return float(np.dot(local_energy, rows) / local_energy.sum())

    measured_rows = {}
    expected_rows = {}
    for wavelength in [450.0, 650.0]:
        ior = 1.5 + cauchy_b / (wavelength * wavelength)
        out_dir = refract_exit([1.0, 0.0], exit_normal, ior)
        assert out_dir is not None
        y_screen = exit_point[1] + out_dir[1] / out_dir[0] * (screen_x - exit_point[0])
        expected_rows[wavelength] = (bounds[3] - y_screen) / (bounds[3] - bounds[1]) * height
        measured_rows[wavelength] = measure_row(wavelength)

    offsets = {}
    for wavelength in [450.0, 650.0]:
        offsets[wavelength] = measured_rows[wavelength] - expected_rows[wavelength]
        detail = (
            f"{wavelength:.0f} nm: expected row={expected_rows[wavelength]:.1f}, "
            f"measured={measured_rows[wavelength]:.1f}, offset={offsets[wavelength]:.1f}px"
        )
        print(f"        {detail}")

    measured_separation = abs(measured_rows[450.0] - measured_rows[650.0])
    expected_separation = abs(expected_rows[450.0] - expected_rows[650.0])
    separation_error = abs(measured_separation - expected_separation)
    detail = (
        f"separation expected={expected_separation:.1f}px, "
        f"measured={measured_separation:.1f}px, error={separation_error:.1f}px"
    )
    print(f"        {detail}")
    assert separation_error < 8.0, f"dispersion separation mismatch: {detail}"
    assert abs(offsets[450.0] - offsets[650.0]) < 5.0, (
        "red and blue should share the same screen-measurement bias"
    )
    assert measured_rows[450.0] < measured_rows[650.0], (
        "shorter wavelengths should deflect more strongly"
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
# Test 8: Ellipse group transforms stay exact under non-uniform scale
# ---------------------------------------------------------------------------


def test_grouped_ellipse_matches_direct_ellipse():
    print("\n=== Test 8: Grouped ellipse transform exactness ===\n")

    local = dict(center=[0.06, -0.04], semi_a=0.18, semi_b=0.09, rotation=0.0)
    group_transform = dict(translate=[0.08, -0.03], rotate=0.55, scale=[1.8, 0.65])
    sx, sy = group_transform["scale"]
    tc = math.cos(group_transform["rotate"])
    ts = math.sin(group_transform["rotate"])
    scaled_center = [local["center"][0] * sx, local["center"][1] * sy]
    direct = {
        "center": [
            scaled_center[0] * tc - scaled_center[1] * ts + group_transform["translate"][0],
            scaled_center[0] * ts + scaled_center[1] * tc + group_transform["translate"][1],
        ],
        "semi_a": local["semi_a"] * sx,
        "semi_b": local["semi_b"] * sy,
        "rotation": group_transform["rotate"],
    }

    collectors = [
        segment_shape([-1.0, 0.88], [1.0, 0.88], ABSORBER),
        segment_shape([1.0, -0.88], [-1.0, -0.88], ABSORBER),
    ]
    light = parallel_beam_light([-0.55, 0.72], [0.55, 0.72], [0.0, -1.0], intensity=1.2)
    bounds = [-1.0, -1.0, 1.0, 1.0]
    material = {"ior": 1.5, "transmission": 1.0, "absorption": 0.1}

    grouped_scene = {
        "version": 7,
        "name": "grouped-ellipse",
        "camera": {"bounds": bounds},
        "shapes": collectors,
        "lights": [light],
        "groups": [
            {
                "id": "ellipse",
                "transform": group_transform,
                "shapes": [
                    ellipse_shape(
                        local["center"],
                        local["semi_a"],
                        local["semi_b"],
                        local["rotation"],
                        material,
                    )
                ],
                "lights": [],
            }
        ],
    }
    direct_scene = make_scene(
        collectors
        + [
            ellipse_shape(
                direct["center"], direct["semi_a"], direct["semi_b"], direct["rotation"], material
            )
        ],
        [light],
        bounds,
    )

    grouped_pixels, _ = render_pixels(
        grouped_scene,
        width=260,
        height=260,
        rays=5_000_000,
        normalize="rays",
        tonemap="none",
        exposure=-3.5,
        gamma=1.0,
    )
    direct_pixels, _ = render_pixels(
        direct_scene,
        width=260,
        height=260,
        rays=5_000_000,
        normalize="rays",
        tonemap="none",
        exposure=-3.5,
        gamma=1.0,
    )

    diff = np.abs(grouped_pixels.astype(np.int16) - direct_pixels.astype(np.int16))
    mean_diff = float(diff.mean())
    max_diff = int(diff.max())
    detail = f"mean abs diff={mean_diff:.3f}, max diff={max_diff}"
    print(f"        {detail}")
    assert mean_diff < 1.0 and max_diff < 24, (
        f"grouped ellipse diverged from direct ellipse: {detail}"
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    tests = [
        test_snell_law,
        test_polygon_winding_is_physics_invariant,
        test_energy_linear,
        test_segment_light_emits_both_sides,
        test_emissive_segment_is_endpoint_order_invariant,
        test_emissive_circle_lights_both_sides,
        test_emissive_polygon_lights_both_sides,
        test_emissive_arc_lights_both_sides,
        test_emissive_ellipse_lights_both_sides,
        test_energy_depth_convergence,
        test_dispersion,
        test_tir,
        test_energy_conservation,
        test_lens_focus,
        test_grouped_ellipse_matches_direct_ellipse,
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
