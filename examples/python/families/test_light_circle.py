"""Visual validation of point-light appearance measurements.

Renders a series of simple scenes with controlled light configurations,
measures the apparent circle of each light via the C++ analyzer, and saves
annotated PNG images so the user can visually confirm the metrics match
their perception.

Run::

    python -m examples.python.families.test_light_circle

Output goes to ``renders/light_circle_test/``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import _lpt2d

from anim import (
    Camera2D,
    Circle,
    Frame,
    Look,
    Material,
    PointLight,
    Scene,
    glass,
    mirror_box,
)
from anim.family import _STANDARD_LOOK
from anim.renderer import RenderSession, _resolve_frame_shot, save_image
from anim.types import Canvas, Shot, TraceDefaults

# ── Constants ────────────────────────────────────────────────────────────

OUT = Path("renders/light_circle_test")
WIDTH, HEIGHT = 1280, 720
RAYS = 2_000_000
CAM_CENTER = (0.0, 0.0)
CAM_WIDTH = 3.2

WALL = Material(metallic=1.0, roughness=0.1, transmission=0.0, cauchy_b=0.0, albedo=1.0)


# ── Helpers ──────────────────────────────────────────────────────────────


def _make_shot(scene: Scene, exposure: float = -5.0, width: int = WIDTH,
               height: int = HEIGHT, rays: int = RAYS) -> Shot:
    return Shot(
        scene=scene,
        camera=Camera2D(center=list(CAM_CENTER), width=CAM_WIDTH),
        canvas=Canvas(width, height),
        look=Look(**{**_STANDARD_LOOK, "exposure": exposure}),
        trace=TraceDefaults(rays=rays, depth=12),
    )


def _render_scene(scene: Scene, exposure: float = -5.0) -> _lpt2d.RenderResult:
    shot = _make_shot(scene, exposure)
    session = RenderSession(WIDTH, HEIGHT, False)
    frame = Frame(scene=scene, look=Look(**{**_STANDARD_LOOK, "exposure": exposure}))
    cpp_shot = _resolve_frame_shot(shot, frame, None)
    rr = session.render_shot(cpp_shot, 0, True)
    session.close()
    return rr


def _short_side_world_span(canvas_width: int, canvas_height: int) -> float:
    if canvas_width <= canvas_height:
        return CAM_WIDTH
    return CAM_WIDTH * canvas_height / canvas_width


def _annotate_and_save(
    rr: _lpt2d.RenderResult,
    path: Path,
    title: str,
) -> None:
    """Save the image and a companion text file with authored-camera measurements."""
    save_image(str(path), rr.pixels, rr.width, rr.height)

    appearances = list(rr.analysis.lights)
    short_side_px = min(rr.width, rr.height)
    short_side_world = _short_side_world_span(rr.width, rr.height)
    txt = path.with_suffix(".txt")
    lines = [title, "=" * len(title), ""]
    for c in appearances:
        radius_px = c.radius_ratio * short_side_px
        edge_px = c.transition_width_ratio * short_side_px
        radius_world = c.radius_ratio * short_side_world
        lines.append(
            f"{c.id}:  radius={c.radius_ratio:.4f} "
            f"({radius_px:.1f}px, {radius_world:.4f}u)  "
            f"edge={c.transition_width_ratio:.4f} ({edge_px:.1f}px)  "
            f"coverage={c.coverage_fraction:.6f}  contrast={c.peak_contrast:.3f}  "
            f"conf={c.confidence:.2f}  image=({c.image_x:.0f},{c.image_y:.0f})"
        )
    txt.write_text("\n".join(lines))
    print(f"  {path.name}: {title}")
    for c in appearances:
        radius_px = c.radius_ratio * short_side_px
        radius_world = c.radius_ratio * short_side_world
        print(
            f"    {c.id}: radius={c.radius_ratio:.4f} "
            f"({radius_px:.1f}px, {radius_world:.4f}u) "
            f"edge={c.transition_width_ratio:.4f} contrast={c.peak_contrast:.3f} "
            f"conf={c.confidence:.2f}"
        )


# ── Test scenes ──────────────────────────────────────────────────────────


def scene_single_light(intensity: float = 1.0) -> Scene:
    """One point light at the centre, no objects (just mirror walls)."""
    walls = mirror_box(1.6, 0.9, "wall", id_prefix="wall")
    lights = [PointLight(id="center", position=[0.0, 0.0], intensity=intensity)]
    return Scene(materials={"wall": WALL}, shapes=walls, lights=lights)


def scene_three_lights(intensities: tuple[float, float, float]) -> Scene:
    """Three lights: centre, left, right."""
    walls = mirror_box(1.6, 0.9, "wall", id_prefix="wall")
    positions = [(0.0, 0.0), (-0.8, 0.0), (0.8, 0.0)]
    labels = ["center", "left", "right"]
    lights = [
        PointLight(id=labels[i], position=list(positions[i]), intensity=intensities[i])
        for i in range(3)
    ]
    return Scene(materials={"wall": WALL}, shapes=walls, lights=lights)


def scene_corner_ambient(ambient_intensity: float, moving_intensity: float) -> Scene:
    """One moving light at centre + 4 corner ambient lights."""
    walls = mirror_box(1.6, 0.9, "wall", id_prefix="wall")
    corners = [(-1.4, 0.75), (1.4, 0.75), (-1.4, -0.75), (1.4, -0.75)]
    lights = [PointLight(id="moving", position=[0.0, 0.0], intensity=moving_intensity)]
    for i, (cx, cy) in enumerate(corners):
        lights.append(PointLight(id=f"amb_{i}", position=[cx, cy], intensity=ambient_intensity))
    return Scene(materials={"wall": WALL}, shapes=walls, lights=lights)


def scene_with_objects(ambient_intensity: float = 1.0) -> Scene:
    """Grid of glass circles with one moving light and corner ambient."""
    walls = mirror_box(1.6, 0.9, "wall", id_prefix="wall")
    mat_glass = glass(1.5, cauchy_b=20_000, absorption=1.0, fill=0.12)
    shapes: list[Any] = list(walls)
    spacing = 0.3
    cols, rows = 5, 4
    gw = (cols - 1) * spacing
    gh = (rows - 1) * spacing
    for r in range(rows):
        for c in range(cols):
            x = -gw / 2 + c * spacing
            y = -gh / 2 + r * spacing
            shapes.append(
                Circle(id=f"obj_{r}_{c}", center=[x, y], radius=0.06, material_id="crystal")
            )

    corners = [(-1.4, 0.75), (1.4, 0.75), (-1.4, -0.75), (1.4, -0.75)]
    lights = [PointLight(id="moving", position=[0.15, 0.15], intensity=1.0)]
    for i, (cx, cy) in enumerate(corners):
        lights.append(PointLight(id=f"amb_{i}", position=[cx, cy], intensity=ambient_intensity))

    return Scene(materials={"wall": WALL, "crystal": mat_glass}, shapes=shapes, lights=lights)


# ── Main ─────────────────────────────────────────────────────────────────


def _render_scene_at(scene: Scene, exposure: float, width: int, height: int,
                     rays: int) -> _lpt2d.RenderResult:
    """Render at arbitrary resolution and ray count."""
    shot = _make_shot(scene, exposure, width=width, height=height, rays=rays)
    session = RenderSession(width, height, False)
    frame = Frame(scene=scene, look=Look(**{**_STANDARD_LOOK, "exposure": exposure}))
    cpp_shot = _resolve_frame_shot(shot, frame, None)
    rr = session.render_shot(cpp_shot, 0, True)
    session.close()
    return rr


def test_resolution_scaling() -> None:
    """Verify that normalized radius is stable across resolutions and ray counts."""
    print("Resolution scaling test")
    print("=" * 60)

    scene = scene_with_objects(ambient_intensity=0.3)
    exposure = -5.0

    resolutions = [(320, 180), (640, 360), (1280, 720)]
    ray_counts = [100_000, 200_000, 2_000_000]

    from collections import defaultdict
    results: dict[str, dict[tuple[int, int], float]] = defaultdict(dict)
    labels_seen: list[str] = []

    for w, h in resolutions:
        for rays in ray_counts:
            print(f"  rendering {w}x{h} @ {rays // 1000}K rays ...", end="", flush=True)
            rr = _render_scene_at(scene, exposure, w, h, rays)
            appearances = list(rr.analysis.lights)
            moving = next((c for c in appearances if c.id == "moving"), None)
            for c in appearances:
                results[c.id][(w, rays)] = c.radius_ratio
                if c.id not in labels_seen:
                    labels_seen.append(c.id)
            moving_ratio = moving.radius_ratio if moving else 0.0
            print(f" moving radius_ratio={moving_ratio:.4f}")

    # Print comparison table.
    print(f"\n{'Label':>12s}", end="")
    for w, h in resolutions:
        for rays in ray_counts:
            print(f"  {w}x{h}/{rays // 1000}K", end="")
    print("   max_dev")

    for label in labels_seen:
        vals = results[label]
        print(f"{label:>12s}", end="")
        radius_ratios = []
        for w, h in resolutions:
            for rays in ray_counts:
                r = vals.get((w, rays), 0.0)
                radius_ratios.append(r)
                print(f"  {r:12.4f}", end="")
        nonzero = [r for r in radius_ratios if r > 0.001]
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
        ("01_single_exp-5", "Single light, exposure=-5", lambda: scene_single_light(1.0), -5.0),
        ("02_single_exp-4", "Single light, exposure=-4", lambda: scene_single_light(1.0), -4.0),
        ("03_single_exp-6", "Single light, exposure=-6", lambda: scene_single_light(1.0), -6.0),
        ("04_single_intense", "Single light, intensity=3.0, exp=-5", lambda: scene_single_light(3.0), -5.0),
        ("05_three_equal", "Three lights, all 1.0, exp=-5", lambda: scene_three_lights((1.0, 1.0, 1.0)), -5.0),
        ("06_three_dim_sides", "Three lights, center=1.0 sides=0.3, exp=-5", lambda: scene_three_lights((1.0, 0.3, 0.3)), -5.0),
        ("07_ambient_1.0", "Center + corners at 1.0, exp=-5", lambda: scene_corner_ambient(1.0, 1.0), -5.0),
        ("08_ambient_0.3", "Center=1.0 + corners at 0.3, exp=-5", lambda: scene_corner_ambient(0.3, 1.0), -5.0),
        ("09_ambient_0.1", "Center=1.0 + corners at 0.1, exp=-5", lambda: scene_corner_ambient(0.1, 1.0), -5.0),
        ("10_objects_amb1.0", "Glass grid + corners at 1.0, exp=-5", lambda: scene_with_objects(1.0), -5.0),
        ("11_objects_amb0.3", "Glass grid + corners at 0.3, exp=-5", lambda: scene_with_objects(0.3), -5.0),
        ("12_objects_amb0.1", "Glass grid + corners at 0.1, exp=-5", lambda: scene_with_objects(0.1), -5.0),
    ]

    for fname, title, scene_fn, exposure in tests:
        scene = scene_fn()
        rr = _render_scene(scene, exposure)
        _annotate_and_save(rr, OUT / f"{fname}.png", title)
        print()

    print(f"Done — {len(tests)} test images in {OUT}/\n")

    test_resolution_scaling()


if __name__ == "__main__":
    main()
