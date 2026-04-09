"""Parameter distribution analysis for the crystal_field family.

Generates thousands of parameter sets without rendering and prints
distribution tables so the sampling logic can be understood at a glance.

Run::

    python -m examples.python.families.crystal_field stats
    python -m examples.python.families.crystal_field stats -n 50000 --seed 99
"""

from __future__ import annotations

import argparse
import random
from collections import Counter

from .sampling import sample


def run_stats(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Crystal field parameter distributions")
    parser.add_argument("-n", type=int, default=10_000, help="Number of samples (default 10000)")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args(argv)

    rng = random.Random(args.seed)
    n = args.n

    # Accumulators
    shapes = Counter()
    mat_styles = Counter()
    diffuse_styles = Counter()
    amb_styles = Counter()
    n_lights_dist = Counter()
    path_styles = Counter()
    n_sides_dist = Counter()
    has_rotation = 0
    has_jitter = 0
    polygon_count = 0
    n_color_dist = Counter()
    colored_light = 0
    small_grid = 0

    iors: list[float] = []
    speeds: list[float] = []
    exposures: list[float] = []
    rows_list: list[int] = []
    cols_list: list[int] = []
    spacings: list[float] = []
    amb_intensities: list[float] = []

    for _ in range(n):
        p = sample(rng)
        shapes[p.shape.kind] += 1
        mat_styles[p.material.style] += 1
        if p.material.style == "diffuse":
            diffuse_styles[p.material.diffuse_style] += 1
        amb_styles[p.light.ambient.style] += 1
        n_lights_dist[p.light.n_lights] += 1
        path_styles[p.light.path_style] += 1
        n_color_dist[p.material.n_color_groups] += 1

        if p.shape.kind == "polygon":
            polygon_count += 1
            n_sides_dist[p.shape.n_sides] += 1
            if p.shape.rotation is not None:
                has_rotation += 1
                if p.shape.rotation.jitter > 0:
                    has_jitter += 1

        if p.material.style == "glass":
            iors.append(p.material.ior)
        speeds.append(p.light.speed)
        exposures.append(p.exposure)
        rows_list.append(p.grid.rows)
        cols_list.append(p.grid.cols)
        spacings.append(p.grid.spacing)

        if p.light.ambient.style != "none":
            amb_intensities.append(p.light.ambient.intensity)

        if p.light.wavelength_max - p.light.wavelength_min < 300:
            colored_light += 1

        if p.grid.rows <= 5 and p.grid.cols <= 7:
            small_grid += 1

    def pct(count: int) -> str:
        return f"{100 * count / n:.1f}%"

    def dist(values: list[float]) -> str:
        if not values:
            return "n/a"
        s = sorted(values)
        return (
            f"min={s[0]:.2f}  p25={s[len(s)//4]:.2f}  "
            f"median={s[len(s)//2]:.2f}  p75={s[3*len(s)//4]:.2f}  max={s[-1]:.2f}"
        )

    def counter_line(c: Counter, total: int | None = None) -> str:
        t = total or sum(c.values())
        return "  ".join(f"{k}={100*v/t:.1f}%" for k, v in sorted(c.items()))

    print(f"Crystal Field Parameter Distributions (n={n}, seed={args.seed})")
    print()

    print("── Grid ──────────────────────────────────────────────")
    print(f"  rows       {dist([float(r) for r in rows_list])}")
    print(f"  cols       {dist([float(c) for c in cols_list])}")
    print(f"  spacing    {dist(spacings)}")
    print(f"  small_grid {pct(small_grid)} (≤5 rows, ≤7 cols)")
    print()

    print("── Shape ─────────────────────────────────────────────")
    print(f"  kind       {counter_line(shapes)}")
    if polygon_count > 0:
        print(f"  n_sides    {counter_line(n_sides_dist, polygon_count)} (of polygons)")
        print(f"  rotation   {100*has_rotation/polygon_count:.1f}% of polygons")
        print(f"  jitter     {100*has_jitter/polygon_count:.1f}% of polygons")
    print()

    print("── Material ──────────────────────────────────────────")
    print(f"  style      {counter_line(mat_styles)}")
    if iors:
        print(f"  ior        {dist(iors)}")
    if diffuse_styles:
        print(f"  diffuse    {counter_line(diffuse_styles)} (of diffuse)")
    print(f"  colors     {counter_line(n_color_dist)}")
    print()

    print("── Light ─────────────────────────────────────────────")
    print(f"  n_lights   {counter_line(n_lights_dist)}")
    print(f"  path       {counter_line(path_styles)}")
    print(f"  speed      {dist(speeds)}")
    print(f"  colored    {pct(colored_light)} (spectral narrowing)")
    print()

    print("── Ambient ───────────────────────────────────────────")
    print(f"  style      {counter_line(amb_styles)}")
    if amb_intensities:
        print(f"  intensity  {dist(amb_intensities)} (when present)")
    print()

    print("── Exposure ──────────────────────────────────────────")
    print(f"  exposure   {dist(exposures)}")
    print()
