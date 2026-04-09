"""Visual validation of light circle measurements.

Renders a series of simple scenes with controlled light configurations,
measures the apparent circle of each light, and saves annotated PNG images
so the user can visually confirm the metrics match their perception.

Run::

    python -m evaluation.test_light_circle

Output goes to ``renders/light_circle_test/``.
"""

from __future__ import annotations

import numpy as np
from pathlib import Path

from anim import (
    Camera2D,
    Circle,
    Frame,
    FrameContext,
    Look,
    Material,
    PointLight,
    Scene,
    glass,
    mirror_box,
)
from anim.family import _DEFAULT_CAMERA, _STANDARD_LOOK
from anim.renderer import RenderSession, _resolve_frame_shot, save_image
from anim.types import Canvas, Shot, Timeline, TraceDefaults

from .light_circle import LightCircle, measure_light_circles, pixels_to_world, summarize

# ── Constants ────────────────────────────────────────────────────────────

OUT = Path("renders/light_circle_test")
WIDTH, HEIGHT = 1280, 720
RAYS = 2_000_000
CAM_CENTER = (0.0, 0.0)
CAM_WIDTH = 3.2

WALL = Material(metallic=1.0, roughness=0.1, transmission=0.0, cauchy_b=0.0, albedo=1.0)


# ── Helpers ──────────────────────────────────────────────────────────────


def _make_shot(scene: Scene, exposure: float = -5.0) -> Shot:
    shot = Shot(
        scene=scene,
        camera=Camera2D(center=list(CAM_CENTER), width=CAM_WIDTH),
        canvas=Canvas(WIDTH, HEIGHT),
        look=Look(**{**_STANDARD_LOOK, "exposure": exposure}),
        trace=TraceDefaults(rays=RAYS, depth=12),
    )
    return shot


def _render_scene(scene: Scene, exposure: float = -5.0) -> bytes:
    shot = _make_shot(scene, exposure)
    session = RenderSession(WIDTH, HEIGHT, False)
    ctx = FrameContext(frame=0, time=0.0, progress=0.0, fps=30, dt=1 / 30, total_frames=1, duration=1.0)
    frame = Frame(scene=scene, look=Look(**{**_STANDARD_LOOK, "exposure": exposure}))
    cpp_shot = _resolve_frame_shot(shot, frame, None)
    rr = session.render_shot(cpp_shot, 0)
    return rr.pixels


def _annotate_and_save(
    pixels: bytes,
    circles: list[LightCircle],
    path: Path,
    title: str,
) -> None:
    """Save the image and a companion text file with measurements."""
    save_image(str(path), pixels, WIDTH, HEIGHT)

    txt = path.with_suffix(".txt")
    lines = [title, "=" * len(title), ""]
    for c in circles:
        r_world = pixels_to_world(c.radius_px, CAM_WIDTH, WIDTH)
        lines.append(
            f"{c.label}:  peak={c.peak:.3f}  bg={c.background:.3f}  "
            f"radius={c.radius_px:.1f}px ({r_world:.4f}u)  "
            f"sharpness={c.sharpness:.3f}  "
            f"pixel=({c.pixel_pos[0]:.0f},{c.pixel_pos[1]:.0f})"
        )
    txt.write_text("\n".join(lines))
    print(f"  {path.name}: {title}")
    for c in circles:
        r_world = pixels_to_world(c.radius_px, CAM_WIDTH, WIDTH)
        print(f"    {c.label}: peak={c.peak:.3f} bg={c.background:.3f} r={c.radius_px:.1f}px ({r_world:.4f}u) sharp={c.sharpness:.3f}")


# ── Test scenes ──────────────────────────────────────────────────────────


def scene_single_light(intensity: float = 1.0) -> tuple[Scene, list[tuple[float, float]], list[str]]:
    """One point light at the centre, no objects (just mirror walls)."""
    walls = mirror_box(1.6, 0.9, "wall", id_prefix="wall")
    lights = [PointLight(id="center", position=[0.0, 0.0], intensity=intensity)]
    scene = Scene(
        materials={"wall": WALL},
        shapes=walls,
        lights=lights,
    )
    return scene, [(0.0, 0.0)], ["center"]


def scene_three_lights(intensities: tuple[float, float, float]) -> tuple[Scene, list[tuple[float, float]], list[str]]:
    """Three lights: centre, left, right."""
    walls = mirror_box(1.6, 0.9, "wall", id_prefix="wall")
    positions = [(0.0, 0.0), (-0.8, 0.0), (0.8, 0.0)]
    labels = ["center", "left", "right"]
    lights = [
        PointLight(id=labels[i], position=list(positions[i]), intensity=intensities[i])
        for i in range(3)
    ]
    scene = Scene(materials={"wall": WALL}, shapes=walls, lights=lights)
    return scene, positions, labels


def scene_corner_ambient(ambient_intensity: float, moving_intensity: float) -> tuple[Scene, list[tuple[float, float]], list[str]]:
    """One moving light at centre + 4 corner ambient lights."""
    walls = mirror_box(1.6, 0.9, "wall", id_prefix="wall")
    corners = [(-1.4, 0.75), (1.4, 0.75), (-1.4, -0.75), (1.4, -0.75)]
    lights = [PointLight(id="moving", position=[0.0, 0.0], intensity=moving_intensity)]
    for i, (cx, cy) in enumerate(corners):
        lights.append(PointLight(id=f"amb_{i}", position=[cx, cy], intensity=ambient_intensity))
    positions = [(0.0, 0.0)] + corners
    labels = ["moving", "amb_TL", "amb_TR", "amb_BL", "amb_BR"]
    scene = Scene(materials={"wall": WALL}, shapes=walls, lights=lights)
    return scene, positions, labels


def scene_with_objects(n_obj: int = 20, ambient_intensity: float = 1.0) -> tuple[Scene, list[tuple[float, float]], list[str]]:
    """Grid of glass circles with one moving light and corner ambient."""
    walls = mirror_box(1.6, 0.9, "wall", id_prefix="wall")
    mat_glass = glass(1.5, cauchy_b=20_000, absorption=1.0, fill=0.12)
    shapes = list(walls)
    spacing = 0.3
    cols = 5
    rows = 4
    gw = (cols - 1) * spacing
    gh = (rows - 1) * spacing
    for r in range(rows):
        for c in range(cols):
            x = -gw / 2 + c * spacing
            y = -gh / 2 + r * spacing
            shapes.append(Circle(id=f"obj_{r}_{c}", center=[x, y], radius=0.06, material_id="crystal"))

    corners = [(-1.4, 0.75), (1.4, 0.75), (-1.4, -0.75), (1.4, -0.75)]
    lights = [PointLight(id="moving", position=[0.15, 0.15], intensity=1.0)]
    for i, (cx, cy) in enumerate(corners):
        lights.append(PointLight(id=f"amb_{i}", position=[cx, cy], intensity=ambient_intensity))

    positions = [(0.15, 0.15)] + corners
    labels = ["moving", "amb_TL", "amb_TR", "amb_BL", "amb_BR"]
    scene = Scene(materials={"wall": WALL, "crystal": mat_glass}, shapes=shapes, lights=lights)
    return scene, positions, labels


# ── Main ─────────────────────────────────────────────────────────────────


def _render_scene_at(
    scene: Scene,
    exposure: float,
    width: int,
    height: int,
    rays: int,
) -> bytes:
    """Render at arbitrary resolution and ray count."""
    shot = Shot(
        scene=scene,
        camera=Camera2D(center=list(CAM_CENTER), width=CAM_WIDTH),
        canvas=Canvas(width, height),
        look=Look(**{**_STANDARD_LOOK, "exposure": exposure}),
        trace=TraceDefaults(rays=rays, depth=12),
    )
    session = RenderSession(width, height, False)
    frame = Frame(scene=scene, look=Look(**{**_STANDARD_LOOK, "exposure": exposure}))
    cpp_shot = _resolve_frame_shot(shot, frame, None)
    rr = session.render_shot(cpp_shot, 0)
    return rr.pixels


def test_resolution_scaling() -> None:
    """Verify that world-space radius is stable across resolutions and ray counts."""
    print("Resolution scaling test")
    print("=" * 60)

    scene, positions, labels = scene_with_objects(ambient_intensity=0.3)
    exposure = -5.0

    resolutions = [(320, 180), (640, 360), (1280, 720)]
    ray_counts = [100_000, 200_000, 2_000_000]

    # Collect world-radius for each (resolution, rays) pair.
    # results[label][(w, rays)] = world_radius
    from collections import defaultdict
    results: dict[str, dict[tuple[int, int], float]] = defaultdict(dict)

    for w, h in resolutions:
        for rays in ray_counts:
            print(f"  rendering {w}x{h} @ {rays // 1000}K rays ...", end="", flush=True)
            pixels = _render_scene_at(scene, exposure, w, h, rays)
            circles = measure_light_circles(
                pixels, w, h, positions,
                camera_center=CAM_CENTER, camera_width=CAM_WIDTH,
                labels=labels,
            )
            for c in circles:
                r_world = pixels_to_world(c.radius_px, CAM_WIDTH, w)
                results[c.label][(w, rays)] = r_world
            print(f" moving r={circles[0].radius_px:.1f}px ({results[circles[0].label][(w, rays)]:.4f}u)")

    # Print comparison table.
    print(f"\n{'Label':>12s}", end="")
    for w, h in resolutions:
        for rays in ray_counts:
            print(f"  {w}x{h}/{rays // 1000}K", end="")
    print("   max_dev")

    for label in labels:
        vals = results[label]
        print(f"{label:>12s}", end="")
        world_radii = []
        for w, h in resolutions:
            for rays in ray_counts:
                r = vals.get((w, rays), 0.0)
                world_radii.append(r)
                print(f"  {r:12.4f}", end="")
        # Compute max relative deviation from mean.
        nonzero = [r for r in world_radii if r > 0.001]
        if len(nonzero) >= 2:
            mean = sum(nonzero) / len(nonzero)
            max_dev = max(abs(r - mean) / mean for r in nonzero)
            print(f"   {max_dev:.1%}")
        else:
            print("   n/a")

    print()


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    print(f"Light circle measurement validation → {OUT}/\n")

    tests = [
        # (filename, title, scene_fn, exposure)
        ("01_single_exp-5", "Single light, exposure=-5", lambda: scene_single_light(1.0), -5.0),
        ("02_single_exp-4", "Single light, exposure=-4", lambda: scene_single_light(1.0), -4.0),
        ("03_single_exp-6", "Single light, exposure=-6", lambda: scene_single_light(1.0), -6.0),
        ("04_single_intense", "Single light, intensity=3.0, exp=-5", lambda: scene_single_light(3.0), -5.0),
        ("05_three_equal", "Three lights, all 1.0, exp=-5", lambda: scene_three_lights((1.0, 1.0, 1.0)), -5.0),
        ("06_three_dim_sides", "Three lights, center=1.0 sides=0.3, exp=-5", lambda: scene_three_lights((1.0, 0.3, 0.3)), -5.0),
        ("07_ambient_1.0", "Center + corners at 1.0, exp=-5", lambda: scene_corner_ambient(1.0, 1.0), -5.0),
        ("08_ambient_0.3", "Center=1.0 + corners at 0.3, exp=-5", lambda: scene_corner_ambient(0.3, 1.0), -5.0),
        ("09_ambient_0.1", "Center=1.0 + corners at 0.1, exp=-5", lambda: scene_corner_ambient(0.1, 1.0), -5.0),
        ("10_objects_amb1.0", "Glass grid + corners at 1.0, exp=-5", lambda: scene_with_objects(ambient_intensity=1.0), -5.0),
        ("11_objects_amb0.3", "Glass grid + corners at 0.3, exp=-5", lambda: scene_with_objects(ambient_intensity=0.3), -5.0),
        ("12_objects_amb0.1", "Glass grid + corners at 0.1, exp=-5", lambda: scene_with_objects(ambient_intensity=0.1), -5.0),
    ]

    for fname, title, scene_fn, exposure in tests:
        scene, positions, labels = scene_fn()
        pixels = _render_scene(scene, exposure)
        circles = measure_light_circles(
            pixels, WIDTH, HEIGHT, positions,
            camera_center=CAM_CENTER, camera_width=CAM_WIDTH,
            labels=labels,
        )
        _annotate_and_save(pixels, circles, OUT / f"{fname}.png", title)
        print()

    print(f"Done — {len(tests)} test images in {OUT}/\n")

    test_resolution_scaling()


if __name__ == "__main__":
    main()
