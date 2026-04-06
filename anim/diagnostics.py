"""Scene diagnostic heuristics for detecting potential rendering issues."""

from __future__ import annotations

from .geometry import _aabb_overlap, _shape_bounds, _shape_material, _transform_shape
from .types import Scene, Shape


def diagnose_scene(scene: Scene) -> list[str]:
    """Fast non-rendering structural analysis for potential clutter issues."""
    warnings: list[str] = []

    # Collect all shapes (top-level + grouped world-space shapes)
    all_shapes: list[Shape] = list(scene.shapes)
    for g in scene.groups:
        all_shapes.extend(_transform_shape(s, g.transform) for s in g.shapes)

    # Count total optical surfaces
    n_surfaces = len(all_shapes)
    if n_surfaces > 20:
        warnings.append(
            f"High surface count ({n_surfaces}): many optical surfaces increase scatter probability"
        )

    # Check for dense transparent shapes without absorption (muddy ray paths)
    glass_no_absorb = [
        s
        for s in all_shapes
        for mat in [_shape_material(s)]
        if mat.transmission > 0.5 and mat.absorption < 0.01
    ]
    if len(glass_no_absorb) > 5:
        warnings.append(
            f"{len(glass_no_absorb)} transparent shapes with near-zero absorption: "
            f"rays may bounce indefinitely, creating muddy renders"
        )

    # Check for overlapping shapes (in world space)
    bounds_list: list[tuple[Shape, tuple[float, float, float, float]]] = []
    for s in all_shapes:
        b = _shape_bounds(s)
        if b is not None:
            bounds_list.append((s, b))
    overlap_count = 0
    for i, (_, bi) in enumerate(bounds_list):
        for _, bj in bounds_list[i + 1 :]:
            if _aabb_overlap(bi, bj):
                overlap_count += 1
    if overlap_count > 10:
        warnings.append(f"{overlap_count} overlapping shape pairs: may cause visual clutter")

    # Check light/source count and diversity
    all_lights = list(scene.lights)
    for g in scene.groups:
        all_lights.extend(g.lights)
    emissive_sources = sum(1 for s in all_shapes if _shape_material(s).emission > 0.0)

    total_sources = len(all_lights) + emissive_sources
    if total_sources > 10:
        warnings.append(f"High light/source count ({total_sources}): may create visual noise")

    return warnings
