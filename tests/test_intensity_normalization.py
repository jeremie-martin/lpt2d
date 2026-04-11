#!/usr/bin/env python3
"""Verify intensity scaling and normalization pipeline.

Theory
------
Each traced ray contributes energy:  color = rgb * uIntensity * power_scale
where  power_scale = W / N  (average light intensity).

The float accumulation buffer sums additively.  For a fixed scene:

    max_hdr ~ R * (W/N) * uIntensity * G      (G = geometry constant)

NormalizeMode controls how pixels are mapped to display:

    Max   — divisor = max_pixel  → display in [0,1], independent of ray count
    Rays  — divisor = total_rays → display independent of ray count
    Fixed — divisor = user value → stable if calibrated correctly
    Off   — divisor = 1.0        → raw accumulation, grows with ray count
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from itertools import count
from pathlib import Path

import _lpt2d

_LIGHT_IDS = count()

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_scene(lights: list[dict], name: str = "test") -> dict:
    return {
        "name": name,
        "materials": {
            "lens_glass": {
                "ior": 1.5,
                "roughness": 0.0,
                "metallic": 0.0,
                "transmission": 1.0,
                "absorption": 0.0,
                "cauchy_b": 0.004,
                "albedo": 1.0,
                "emission": 0.0,
                "spectral_c0": 0.0,
                "spectral_c1": 0.0,
                "spectral_c2": 0.0,
                "fill": 0.0,
            }
        },
        "shapes": [
            {
                "id": "lens",
                "type": "circle",
                "center": [0.0, 0.0],
                "radius": 0.3,
                "material_id": "lens_glass",
            }
        ],
        "lights": lights,
        "groups": [],
    }


def point_light(x: float, y: float, intensity: float = 1.0) -> dict:
    return {
        "id": f"point_light_{next(_LIGHT_IDS)}",
        "type": "point",
        "position": [x, y],
        "intensity": intensity,
        "wavelength_min": 380.0,
        "wavelength_max": 780.0,
    }


@dataclass
class FrameResult:
    rays: int
    time_ms: int
    max_hdr: float
    total_rays: int = 0


def _load_shot_from_json(json_string: str):
    """Parse a JSON string into a C++ Shot."""
    return _lpt2d.load_shot_json_string(json_string)


def _render(
    scene_json: str,
    *,
    width: int = 200,
    height: int = 200,
    rays: int = 2_000_000,
    normalize: str = "max",
    normalize_ref: float = 0.0,
    normalize_pct: float = 1.0,
    exposure: float = 2.0,
    return_pixels: bool = False,
) -> FrameResult | tuple[FrameResult, bytes]:
    """Render one frame via RenderSession and return parsed metadata (+ optional pixels)."""
    scene_dict = json.loads(scene_json)

    # If the input is already a full shot (version 11/12 with canvas/look/trace),
    # use it directly but override canvas, look, and trace with our test parameters.
    if scene_dict.get("version") in (11, 12) and "canvas" in scene_dict:
        shot_dict = scene_dict
        shot_dict["canvas"] = {"width": width, "height": height}
        shot_dict["look"] = {
            "exposure": exposure,
            "contrast": 1.0,
            "gamma": 2.0,
            "tonemap": "reinhardx",
            "white_point": 0.5,
            "normalize": normalize,
            "normalize_ref": normalize_ref,
            "normalize_pct": normalize_pct,
            "ambient": 0.0,
            "background": [0, 0, 0],
            "opacity": 1.0,
            "saturation": 1.0,
            "vignette": 0.0,
            "vignette_radius": 0.7,
            "temperature": 0.0,
            "highlights": 0.0,
            "shadows": 0.0,
            "hue_shift": 0.0,
            "grain": 0.0,
            "grain_seed": 0,
            "chromatic_aberration": 0.0,
        }
        shot_dict["trace"] = {
            "rays": rays,
            "batch": 200000,
            "depth": 12,
            "intensity": 1.0,
            "seed_mode": "deterministic",
        }
    else:
        # Wrap a bare scene dict into a full shot.
        shot_dict = {
            "version": 11,
            "name": "test",
            "camera": scene_dict.get("camera", {}),
            "canvas": {"width": width, "height": height},
            "look": {
                "exposure": exposure,
                "contrast": 1.0,
                "gamma": 2.0,
                "tonemap": "reinhardx",
                "white_point": 0.5,
                "normalize": normalize,
                "normalize_ref": normalize_ref,
                "normalize_pct": normalize_pct,
                "ambient": 0.0,
                "background": [0, 0, 0],
                "opacity": 1.0,
                "saturation": 1.0,
                "vignette": 0.0,
                "vignette_radius": 0.7,
                "temperature": 0.0,
                "highlights": 0.0,
                "shadows": 0.0,
                "hue_shift": 0.0,
                "grain": 0.0,
                "grain_seed": 0,
                "chromatic_aberration": 0.0,
            },
            "trace": {
                "rays": rays,
                "batch": 200000,
                "depth": 12,
                "intensity": 1.0,
                "seed_mode": "deterministic",
            },
            "materials": scene_dict.get("materials", {}),
            "shapes": scene_dict.get("shapes", []),
            "lights": scene_dict.get("lights", []),
            "groups": scene_dict.get("groups", []),
        }

    shot = _load_shot_from_json(json.dumps(shot_dict))
    session = _lpt2d.RenderSession(width, height)
    result = session.render_shot(shot)
    fr = FrameResult(
        rays=result.total_rays,
        time_ms=int(result.time_ms),
        max_hdr=result.max_hdr,
        total_rays=result.total_rays,
    )
    if return_pixels:
        return fr, result.pixels
    return fr


def render(scene_json: str, **kw: object) -> FrameResult:
    kw["return_pixels"] = False
    result = _render(scene_json, **kw)
    assert isinstance(result, FrameResult)
    return result


def render_px(scene_json: str, **kw: object) -> tuple[FrameResult, bytes]:
    kw["return_pixels"] = True
    result = _render(scene_json, **kw)
    assert isinstance(result, tuple)
    return result


def mean_brightness(pixel_data: bytes) -> float:
    return sum(pixel_data) / len(pixel_data)


passed = 0
failed = 0


def check(name: str, condition: bool, detail: str) -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS  {name}")
    else:
        failed += 1
        print(f"  FAIL  {name}")
    print(f"        {detail}")


def ratio_ok(a: float, b: float, expected: float, tol: float = 0.10) -> bool:
    if b == 0:
        return False
    return abs(a / b - expected) <= tol


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

LIGHT_POS = (0.0, 0.6)
RAYS = 5_000_000


# ---------------------------------------------------------------------------
# Tests: Intensity Scaling (from previous session, updated for new API)
# ---------------------------------------------------------------------------


def test_intensity_scaling():
    """max_hdr scales linearly with single-light intensity (power_scale = W/N)."""
    print("\n=== Test 1: Single-light intensity scaling ===")
    print("Theory: 1 light -> power_scale = intensity. max_hdr ~ intensity.\n")

    # Use normalize="max" so compute_max_gpu runs and max_hdr is reported.
    results = {}
    for intensity in [0.5, 1.0, 2.0, 4.0]:
        scene = make_scene([point_light(*LIGHT_POS, intensity=intensity)])
        r = render(json.dumps(scene), rays=RAYS, normalize="max")
        results[intensity] = r.max_hdr
        print(f"  intensity={intensity:<4}  max_hdr={r.max_hdr:>12.1f}")

    base = results[1.0]
    print()
    for k in [0.5, 2.0, 4.0]:
        check(
            f"intensity={k}",
            ratio_ok(results[k], base, k),
            f"expected {k:.1f}x, actual={results[k] / base:.3f}x",
        )


def test_additive_lights():
    """N co-located lights at intensity=1 -> W=N -> max_hdr scales linearly.

    This is the correct IS estimator: adding a light ADDS energy.
    Existing lights keep their brightness; total scene gets brighter.
    """
    print("\n=== Test 2: Additive lights (W = total intensity) ===\n")

    # Use normalize="max" so compute_max_gpu runs and max_hdr is reported.
    results = {}
    for n in [1, 2, 3, 5]:
        lights = [point_light(*LIGHT_POS, intensity=1.0) for _ in range(n)]
        r = render(json.dumps(make_scene(lights)), rays=RAYS, normalize="max")
        results[n] = r.max_hdr
        print(f"  N={n}  max_hdr={r.max_hdr:>12.1f}  expected={n}x")

    base = results[1]
    print()
    for n in [2, 3, 5]:
        check(
            f"N={n} is {n}x",
            ratio_ok(results[n], base, float(n), tol=0.08),
            f"expected {n:.0f}x, actual={results[n] / base:.3f}x",
        )


def test_multi_light_total_power():
    """Co-located lights: max_hdr scales with W (total intensity).

    With W model: 2 lights at (2,1) have W=3 vs 2 lights at (1,1) with W=2.
    Ratio should be W_a / W_b = 3/2 = 1.5.
    """
    print("\n=== Test 3: Multi-light total power ===\n")

    # Use normalize="max" so compute_max_gpu runs and max_hdr is reported.
    base = render(
        json.dumps(
            make_scene(
                [
                    point_light(*LIGHT_POS, 1.0),
                    point_light(*LIGHT_POS, 1.0),
                ]
            )
        ),
        rays=RAYS,
        normalize="max",
    )
    r21 = render(
        json.dumps(
            make_scene(
                [
                    point_light(*LIGHT_POS, 2.0),
                    point_light(*LIGHT_POS, 1.0),
                ]
            )
        ),
        rays=RAYS,
        normalize="max",
    )
    r31 = render(
        json.dumps(
            make_scene(
                [
                    point_light(*LIGHT_POS, 3.0),
                    point_light(*LIGHT_POS, 1.0),
                ]
            )
        ),
        rays=RAYS,
        normalize="max",
    )

    print(f"  (1,1): max_hdr={base.max_hdr:>12.1f}  W=2")
    print(f"  (2,1): max_hdr={r21.max_hdr:>12.1f}  W=3")
    print(f"  (3,1): max_hdr={r31.max_hdr:>12.1f}  W=4")
    print()
    check(
        "(2,1)/(1,1)=3/2",
        ratio_ok(r21.max_hdr, base.max_hdr, 1.5),
        f"actual={r21.max_hdr / base.max_hdr:.3f}",
    )
    check(
        "(3,1)/(1,1)=4/2",
        ratio_ok(r31.max_hdr, base.max_hdr, 2.0),
        f"actual={r31.max_hdr / base.max_hdr:.3f}",
    )


def test_ray_count_scaling():
    """max_hdr ~ ray_count with raw accumulation."""
    print("\n=== Test 4: Ray count scaling ===\n")

    # Use normalize="max" so compute_max_gpu runs and max_hdr is reported.
    # max_hdr is the true HDR peak of the accumulation buffer, which scales
    # linearly with ray count regardless of normalize mode.
    scene_json = json.dumps(make_scene([point_light(*LIGHT_POS)]))
    results = {}
    for rays in [1_000_000, 2_000_000, 5_000_000]:
        r = render(scene_json, rays=rays, normalize="max")
        results[rays] = r.max_hdr
        print(f"  rays={rays:>10,}  max_hdr={r.max_hdr:>12.1f}")

    base = results[1_000_000]
    print()
    check(
        "2M/1M",
        ratio_ok(results[2_000_000], base, 2.0, tol=0.12),
        f"actual={results[2_000_000] / base:.3f}",
    )
    check(
        "5M/1M",
        ratio_ok(results[5_000_000], base, 5.0, tol=0.12),
        f"actual={results[5_000_000] / base:.3f}",
    )


# ---------------------------------------------------------------------------
# Tests: NormalizeMode
# ---------------------------------------------------------------------------


def test_max_mode_ray_independent():
    """Max mode: brightness constant across ray counts (auto-normalize)."""
    print("\n=== Test 5: Max mode -- ray-count independent brightness ===\n")

    scene_json = json.dumps(make_scene([point_light(*LIGHT_POS)]))
    results = {}
    for rays in [1_000_000, 3_000_000, 5_000_000]:
        fr, px = render_px(scene_json, rays=rays, normalize="max")
        bright = mean_brightness(px)
        results[rays] = bright
        print(f"  rays={rays:>10,}  max_hdr={fr.max_hdr:>12.1f}  brightness={bright:.2f}")

    base = results[1_000_000]
    print()
    for rays in [3_000_000, 5_000_000]:
        r = results[rays] / base if base > 0 else 0
        check(f"{rays // 1_000_000}M vs 1M", abs(r - 1.0) < 0.15, f"ratio={r:.3f}")


def test_rays_mode_ray_independent():
    """Rays mode: brightness constant across ray counts (THE key test).

    Theory: divisor = total_rays. Both pixel values and divisor scale with
    ray count -> the ratio is constant -> same display output.
    """
    print("\n=== Test 6: Rays mode -- ray-count independent brightness ===")
    print("Theory: divisor = total_rays. Both numerator and denominator scale")
    print("        with ray count -> display brightness is constant.\n")

    scene_json = json.dumps(make_scene([point_light(*LIGHT_POS)]))
    results = {}
    for rays in [500_000, 2_000_000, 5_000_000]:
        fr, px = render_px(scene_json, rays=rays, normalize="rays")
        bright = mean_brightness(px)
        results[rays] = bright
        print(
            f"  rays={rays:>10,}  max_hdr={fr.max_hdr:>12.1f}  "
            f"total_rays={fr.total_rays:>10,}  brightness={bright:.2f}"
        )

    base = results[500_000]
    print()
    for rays in [2_000_000, 5_000_000]:
        r = results[rays] / base if base > 0 else 0
        check(
            f"{rays // 1_000_000}M vs 500K", abs(r - 1.0) < 0.15, f"ratio={r:.3f} (expected ~1.0)"
        )


def test_rays_mode_intensity_responsive():
    """Rays mode: changing light intensity changes brightness.

    Theory: power_scale = intensity (for 1 light). Divisor = total_rays (fixed).
    So display brightness scales with intensity.
    """
    print("\n=== Test 7: Rays mode -- intensity responsive ===")
    print("Theory: divisor = total_rays (constant). power_scale varies.\n")

    results = {}
    for intensity in [1.0, 2.0, 4.0]:
        scene = make_scene([point_light(*LIGHT_POS, intensity=intensity)])
        _, px = render_px(json.dumps(scene), rays=RAYS, normalize="rays")
        bright = mean_brightness(px)
        results[intensity] = bright
        print(f"  intensity={intensity:<4}  brightness={bright:.2f}")

    print()
    # Brightness should increase with intensity (not necessarily linearly due to tonemap)
    check(
        "intensity=2 > intensity=1",
        results[2.0] > results[1.0],
        f"{results[2.0]:.2f} > {results[1.0]:.2f}",
    )
    check(
        "intensity=4 > intensity=2",
        results[4.0] > results[2.0],
        f"{results[4.0]:.2f} > {results[2.0]:.2f}",
    )


def test_adding_light_preserves_existing():
    """Adding a second light must NOT dim the first one (Off mode, raw max_hdr).

    This is the core user requirement. With the correct IS estimator (W),
    each ray carries W * uIntensity energy. Adding a light increases W,
    compensating for the ray split.
    """
    print("\n=== Test 8: Adding a light preserves existing brightness ===")
    print("Theory: W model. Light A's max_hdr is unchanged when B is added.\n")

    LIGHT_B = (0.0, -0.6)
    r1 = render(json.dumps(make_scene([point_light(*LIGHT_POS)])), rays=RAYS, normalize="off")
    r2 = render(
        json.dumps(make_scene([point_light(*LIGHT_POS), point_light(*LIGHT_B)])),
        rays=RAYS,
        normalize="off",
    )

    print(f"  1 light:   max_hdr={r1.max_hdr:>12.1f}")
    print(f"  2 lights:  max_hdr={r2.max_hdr:>12.1f}")
    ratio = r2.max_hdr / r1.max_hdr if r1.max_hdr > 0 else 0
    print()
    check(
        "max_hdr preserved",
        abs(ratio - 1.0) < 0.10,
        f"ratio={ratio:.3f} (expected ~1.0, adding B doesn't dim A)",
    )


def test_fixed_mode():
    """Fixed mode: normalize_ref captured from Max produces same output."""
    print("\n=== Test 9: Fixed mode -- calibrated reference ===\n")

    scene_json = json.dumps(make_scene([point_light(*LIGHT_POS)]))

    # Capture max from auto-normalize
    fr_max, px_max = render_px(scene_json, rays=RAYS, normalize="max")
    bright_max = mean_brightness(px_max)
    print(f"  Max mode:    max_hdr={fr_max.max_hdr:>12.1f}  brightness={bright_max:.2f}")

    # Use captured max as fixed ref
    _, px_fixed = render_px(scene_json, rays=RAYS, normalize="fixed", normalize_ref=fr_max.max_hdr)
    bright_fixed = mean_brightness(px_fixed)
    print(f"  Fixed mode:  ref={fr_max.max_hdr:>12.1f}  brightness={bright_fixed:.2f}")

    print()
    ratio = bright_fixed / bright_max if bright_max > 0 else 0
    check("Max = Fixed(captured)", abs(ratio - 1.0) < 0.10, f"ratio={ratio:.3f}")


def test_percentile():
    """Percentile (P99) normalization: P99 <= max, so P99-normalized is >= max-normalized."""
    print("\n=== Test 9: Percentile normalization (P99 vs Max) ===")
    print("Theory: P99 <= max -> dividing by P99 gives >= result.\n")

    scene_json = json.dumps(make_scene([point_light(*LIGHT_POS)]))

    fr_max, px_max = render_px(scene_json, rays=RAYS, normalize="max", normalize_pct=1.0)
    bright_max = mean_brightness(px_max)

    fr_p99, px_p99 = render_px(scene_json, rays=RAYS, normalize="max", normalize_pct=0.99)
    bright_p99 = mean_brightness(px_p99)

    print(f"  Max (pct=1.0):  max_hdr={fr_max.max_hdr:>12.1f}  brightness={bright_max:.2f}")
    print(f"  P99 (pct=0.99): max_hdr={fr_p99.max_hdr:>12.1f}  brightness={bright_p99:.2f}")
    print()
    # max_hdr always reports the true max (both should be ~equal).
    # The P99 divisor is smaller -> image is brighter.
    check(
        "P99 brightness > Max brightness",
        bright_p99 > bright_max,
        f"P99={bright_p99:.2f} > Max={bright_max:.2f}",
    )


def test_all_modes_produce_output():
    """All four modes produce a non-black, non-white image."""
    print("\n=== Test 10: All modes produce reasonable output ===\n")

    scene_json = json.dumps(make_scene([point_light(*LIGHT_POS)]))

    for mode in ["max", "rays", "off"]:
        _, px = render_px(scene_json, rays=RAYS, normalize=mode)
        bright = mean_brightness(px)
        print(f"  mode={mode:<6}  brightness={bright:.2f}")
        check(f"{mode} produces visible output", 1.0 < bright < 250.0, f"brightness={bright:.2f}")

    # Fixed mode needs a ref
    fr = render(scene_json, rays=RAYS, normalize="max")
    _, px = render_px(scene_json, rays=RAYS, normalize="fixed", normalize_ref=fr.max_hdr)
    bright = mean_brightness(px)
    print(f"  mode=fixed  brightness={bright:.2f}")
    check("fixed produces visible output", 1.0 < bright < 250.0, f"brightness={bright:.2f}")


def test_existing_scene():
    """Diamond scene (non-uniform intensities) works correctly."""
    print("\n=== Test 12: Existing scene -- diamond ===\n")

    scene_path = Path(__file__).resolve().parent.parent / "scenes" / "diamond.json"
    with open(scene_path) as f:
        scene_json = json.dumps(json.loads(f.read()))

    fr, px = render_px(scene_json, rays=RAYS, normalize="max")
    bright = mean_brightness(px)
    print(f"  max mode:   max_hdr={fr.max_hdr:>12.1f}  brightness={bright:.2f}")

    fr_r, px_r = render_px(scene_json, rays=RAYS, normalize="rays")
    bright_r = mean_brightness(px_r)
    print(f"  rays mode:  max_hdr={fr_r.max_hdr:>12.1f}  brightness={bright_r:.2f}")

    print()
    check("max mode visible", bright > 5.0, f"brightness={bright:.2f}")
    check("rays mode visible", bright_r > 1.0, f"brightness={bright_r:.2f}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    print("=" * 70)
    print("Intensity & Normalization Pipeline -- Full Verification")
    print("=" * 70)
    print(f"Default rays: {RAYS:,}")

    test_intensity_scaling()
    test_additive_lights()
    test_multi_light_total_power()
    test_ray_count_scaling()
    test_max_mode_ray_independent()
    test_rays_mode_ray_independent()
    test_rays_mode_intensity_responsive()
    test_adding_light_preserves_existing()
    test_fixed_mode()
    test_percentile()
    test_all_modes_produce_output()
    test_existing_scene()

    print("\n" + "=" * 70)
    print(f"Results: {passed} passed, {failed} failed")
    print("=" * 70)
    sys.exit(1 if failed > 0 else 0)
