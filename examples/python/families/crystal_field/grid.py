"""Grid position generation and hole removal."""

from __future__ import annotations

import random

from .params import GridConfig


def build_grid(cfg: GridConfig) -> list[tuple[float, float]]:
    """Generate grid positions centered at the origin."""
    grid_w = (cfg.cols - 1) * cfg.spacing
    grid_h = (cfg.rows - 1) * cfg.spacing
    x0 = -grid_w / 2
    y0 = -grid_h / 2
    positions = []
    for r in range(cfg.rows):
        for c in range(cfg.cols):
            x = x0 + c * cfg.spacing
            y = y0 + r * cfg.spacing
            if cfg.offset_rows and r % 2 == 1:
                x += cfg.spacing / 2
            positions.append((x, y))
    return positions


def remove_holes(
    positions: list[tuple[float, float]],
    fraction: float,
    rng: random.Random,
) -> list[tuple[float, float]]:
    """Randomly remove a fraction of positions."""
    n_remove = int(len(positions) * fraction)
    if n_remove <= 0 or len(positions) <= 1:
        return positions
    drop = set(rng.sample(range(len(positions)), min(n_remove, len(positions) - 1)))
    return [p for i, p in enumerate(positions) if i not in drop]
