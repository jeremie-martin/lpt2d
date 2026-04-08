#!/usr/bin/env python3
"""Diagnose the "adding a light dims existing lights" issue.

With power_scale = W/N (current):
  Adding a co-located light of the same intensity does NOT change power_scale
  (W/N stays 1), but importance sampling splits the ray budget — so each
  existing light gets fewer rays, becoming dimmer.

With power_scale = W (correct IS estimator):
  Each ray carries W * uIntensity energy. Adding a light increases W,
  compensating for the ray split. Existing lights keep their brightness.

This test measures the issue and predicts the expected behavior under both models.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from itertools import count

import numpy as np

import _lpt2d

RAYS = 5_000_000
_LIGHT_IDS = count()


def make_scene(lights, name="test"):
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


def point_light(x, y, intensity=1.0):
    return {
        "id": f"point_light_{next(_LIGHT_IDS)}",
        "type": "point",
        "position": [x, y],
        "intensity": intensity,
        "wavelength_min": 380.0,
        "wavelength_max": 780.0,
    }


@dataclass
class R:
    max_hdr: float
    brightness: float


_MATERIAL_DEFAULTS = {
    "ior": 1.0, "roughness": 0.0, "metallic": 0.0, "transmission": 0.0,
    "absorption": 0.0, "cauchy_b": 0.0, "albedo": 1.0, "emission": 0.0,
    "spectral_c0": 0.0, "spectral_c1": 0.0, "spectral_c2": 0.0, "fill": 0.0,
}


def _complete_material(mat):
    return {**_MATERIAL_DEFAULTS, **mat}


def _complete_scene_materials(scene_dict):
    """Fill in missing library material fields so strict v10 parsing succeeds."""
    for name, mat in scene_dict.get("materials", {}).items():
        scene_dict["materials"][name] = _complete_material(mat)
    return scene_dict


def render(scene_json, normalize="off", rays=RAYS):
    scene_dict = _complete_scene_materials(json.loads(scene_json))
    shot_dict = {
        "version": 11,
        "name": "test",
        "camera": {},
        "canvas": {"width": 200, "height": 200},
        "look": {
            "exposure": -5.0, "contrast": 1.0, "gamma": 2.0,
            "tonemap": "reinhardx", "white_point": 0.5,
            "normalize": normalize, "normalize_ref": 0.0, "normalize_pct": 1.0,
            "ambient": 0.0, "background": [0, 0, 0], "opacity": 1.0,
            "saturation": 1.0, "vignette": 0.0, "vignette_radius": 0.7,
            "temperature": 0.0, "highlights": 0.0, "shadows": 0.0,
            "hue_shift": 0.0, "grain": 0.0, "grain_seed": 0,
            "chromatic_aberration": 0.0,
        },
        "trace": {
            "rays": rays, "batch": 200000, "depth": 12,
            "intensity": 1.0, "seed_mode": "deterministic",
        },
        "materials": scene_dict.get("materials", {}),
        "shapes": scene_dict.get("shapes", []),
        "lights": scene_dict.get("lights", []),
        "groups": scene_dict.get("groups", []),
    }
    shot = _lpt2d.load_shot_json_string(json.dumps(shot_dict))
    session = _lpt2d.RenderSession(200, 200)
    result = session.render_shot(shot)
    pixels = np.frombuffer(result.pixels, dtype=np.uint8)
    brightness = float(np.mean(pixels))
    return R(max_hdr=result.max_hdr, brightness=brightness)


# --- Scenario: light at (0, 0.6), then add another at (0, -0.6) ---
# Lights are far apart so they illuminate different regions.

LIGHT_A = (0.0, 0.6)
LIGHT_B = (0.0, -0.6)  # opposite side

print("=" * 70)
print("Diagnosing: adding a light dims existing lights")
print("=" * 70)

# 1. One light (A)
scene_1 = json.dumps(make_scene([point_light(*LIGHT_A)]))
r1 = render(scene_1)
print(f"\n1 light (A):              max_hdr={r1.max_hdr:>12.1f}  brightness={r1.brightness:.2f}")

# 2. Two lights (A + B)
scene_2 = json.dumps(make_scene([point_light(*LIGHT_A), point_light(*LIGHT_B)]))
r2 = render(scene_2)
print(f"2 lights (A+B):           max_hdr={r2.max_hdr:>12.1f}  brightness={r2.brightness:.2f}")

# 3. One light A at intensity=2 (should match 2 co-located lights)
scene_1x2 = json.dumps(make_scene([point_light(*LIGHT_A, intensity=2.0)]))
r1x2 = render(scene_1x2)
print(f"1 light A (intensity=2):  max_hdr={r1x2.max_hdr:>12.1f}  brightness={r1x2.brightness:.2f}")

print("\n--- Analysis (Off mode, raw values) ---")
if r1.max_hdr > 0:
    print(f"max_hdr ratio (2 lights / 1 light): {r2.max_hdr / r1.max_hdr:.3f}")
    print("  Under W/N model: expect ~0.5 (ray budget split, same per-ray energy)")
    print("  Under W model:   expect ~1.0 (ray budget split but 2x per-ray energy)")
    print(f"  Actual: {r2.max_hdr / r1.max_hdr:.3f}")
else:
    print("max_hdr not available (normalize mode does not compute it)")

print(f"\nbrightness ratio (2 lights / 1 light): {r2.brightness / r1.brightness:.3f}")
print("  Under W/N: expect ~1.0 (brightness redistributed, total same)")
print("  Under W:   expect ~2.0 (each light adds its own brightness)")

# Now test with Rays normalization
print("\n--- With Rays normalization ---")
r1_rays = render(scene_1, normalize="rays")
r2_rays = render(scene_2, normalize="rays")
print(f"1 light (A):     brightness={r1_rays.brightness:.2f}")
print(f"2 lights (A+B):  brightness={r2_rays.brightness:.2f}")
print(f"Brightness ratio: {r2_rays.brightness / r1_rays.brightness:.3f}")
print("  Under W/N: light A region dims when B is added")
print("  Under W:   light A region stays same, B adds its own contribution")

# Co-located test: same position, different light count
print("\n--- Co-located lights (same position) ---")
r1_co = render(json.dumps(make_scene([point_light(*LIGHT_A)])))
r2_co = render(json.dumps(make_scene([point_light(*LIGHT_A), point_light(*LIGHT_A)])))
r3_co = render(json.dumps(make_scene([point_light(*LIGHT_A), point_light(*LIGHT_A), point_light(*LIGHT_A)])))

print(f"1 light: max_hdr={r1_co.max_hdr:>12.1f}")
if r1_co.max_hdr > 0:
    print(f"2 lights: max_hdr={r2_co.max_hdr:>12.1f}  ratio={r2_co.max_hdr / r1_co.max_hdr:.3f}")
    print(f"3 lights: max_hdr={r3_co.max_hdr:>12.1f}  ratio={r3_co.max_hdr / r1_co.max_hdr:.3f}")
else:
    print(f"2 lights: max_hdr={r2_co.max_hdr:>12.1f}")
    print(f"3 lights: max_hdr={r3_co.max_hdr:>12.1f}")
print("\n  Under W/N: all three should be ~1.0x (current behavior)")
print("  Under W:   ratios should be 2.0x, 3.0x (additive, physically correct)")
print("  Correct IS: W. Adding light sources adds energy to the scene.")

print("\n" + "=" * 70)
print("CONCLUSION: power_scale should be W (not W/N) for correct IS estimator")
print("=" * 70)
