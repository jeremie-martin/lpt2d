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
import subprocess
from dataclasses import dataclass
from itertools import count

CLI = "./build/lpt2d-cli"
RAYS = 5_000_000
_LIGHT_IDS = count()


def make_scene(lights, name="test"):
    return {
        "version": 6,
        "name": name,
        "shapes": [
            {
                "id": "lens",
                "type": "circle",
                "center": [0.0, 0.0],
                "radius": 0.3,
                "material": {"ior": 1.5, "transmission": 1.0, "cauchy_b": 0.004},
            }
        ],
        "lights": lights,
        "groups": [],
    }


def point_light(x, y, intensity=1.0):
    return {
        "id": f"point_light_{next(_LIGHT_IDS)}",
        "type": "point",
        "pos": [x, y],
        "intensity": intensity,
        "wavelength_min": 380.0,
        "wavelength_max": 780.0,
    }


@dataclass
class R:
    max_hdr: float
    brightness: float


def render(scene_json, normalize="off", rays=RAYS):
    cmd = [
        CLI,
        "--stream",
        "--width",
        "200",
        "--height",
        "200",
        "--rays",
        str(rays),
        "--normalize",
        normalize,
    ]
    proc = subprocess.Popen(
        cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    proc.stdin.write((scene_json + "\n").encode())
    proc.stdin.close()
    px = proc.stdout.read(200 * 200 * 3)
    stderr = proc.stderr.read().decode()
    proc.wait()
    # parse max_hdr
    max_hdr = 0.0
    for line in stderr.splitlines():
        if "max_hdr" in line:
            idx = line.find(": {")
            if idx >= 0:
                data = json.loads(line[idx + 2 :])
                max_hdr = data["max_hdr"]
    brightness = sum(px) / len(px) if px else 0
    return R(max_hdr=max_hdr, brightness=brightness)


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
r3_co = render(json.dumps(make_scene([point_light(*LIGHT_A)] * 3)))

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
