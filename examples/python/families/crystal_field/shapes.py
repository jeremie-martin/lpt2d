"""Grid object construction (circles and polygons)."""

from __future__ import annotations

import random

from anim import Circle, Polygon, regular_polygon

from .params import ShapeConfig


def build_object(
    idx: int,
    center: tuple[float, float],
    shape_cfg: ShapeConfig,
    material_id: str,
    rng: random.Random,
) -> Circle | Polygon:
    """Build one grid object according to the shape config."""
    if shape_cfg.kind == "circle":
        return Circle(
            id=f"obj_{idx}",
            center=list(center),
            radius=shape_cfg.size,
            material_id=material_id,
        )

    # Polygon
    rotation = 0.0
    if shape_cfg.rotation is not None:
        rotation = shape_cfg.rotation.base_angle
        if shape_cfg.rotation.jitter > 0:
            rotation += rng.uniform(-shape_cfg.rotation.jitter, shape_cfg.rotation.jitter)

    return regular_polygon(
        center=center,
        radius=shape_cfg.size,
        n=shape_cfg.n_sides,
        material_id=material_id,
        rotation=rotation,
        corner_radius=shape_cfg.corner_radius,
        id_prefix=f"obj_{idx}",
    )
