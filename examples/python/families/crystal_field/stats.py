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
    shapes: Counter[str] = Counter()
    outcomes: Counter[str] = Counter()
    brushed_color_subcase: Counter[str] = Counter()
    amb_styles: Counter[str] = Counter()
    n_lights_dist: Counter[int] = Counter()
    path_styles: Counter[str] = Counter()
    n_sides_dist: Counter[int] = Counter()
    has_rotation = 0
    has_jitter = 0
    polygon_count = 0
    n_color_dist: Counter[int] = Counter()
    colored_light = 0
    colored_ambient = 0
    small_grid = 0

    iors: list[float] = []
    cauchy_bs: list[float] = []
    fills_by_outcome: dict[str, list[float]] = {}
    speeds: list[float] = []
    exposures: list[float] = []
    rows_list: list[int] = []
    cols_list: list[int] = []
    spacings: list[float] = []
    amb_intensities: list[float] = []
    amb_white_mixes: list[float] = []
    mov_intensities: list[float] = []
    gammas: list[float] = []
    contrasts: list[float] = []
    white_points: list[float] = []
    temperatures: list[float] = []
    vignettes: list[float] = []
    ca_values: list[float] = []
    albedos_by_outcome: dict[str, list[float]] = {}

    for _ in range(n):
        p = sample(rng)
        shapes[p.shape.kind] += 1
        outcomes[p.material.outcome] += 1
        amb_styles[p.light.ambient.style] += 1
        n_lights_dist[p.light.n_lights] += 1
        path_styles[p.light.path_style] += 1
        n_color_dist[len(p.material.color_names)] += 1

        if p.shape.kind == "polygon":
            polygon_count += 1
            n_sides_dist[p.shape.n_sides] += 1
            if p.shape.rotation is not None:
                has_rotation += 1
                if p.shape.rotation.jitter > 0:
                    has_jitter += 1

        if p.material.outcome == "glass":
            iors.append(p.material.ior)
            cauchy_bs.append(p.material.cauchy_b)
        fills_by_outcome.setdefault(p.material.outcome, []).append(p.material.fill)
        albedos_by_outcome.setdefault(p.material.outcome, []).append(p.material.albedo)

        # Brushed-metal internal color sub-case distribution.
        if p.material.outcome == "brushed_metal":
            cnames = p.material.color_names
            if not cnames:
                brushed_color_subcase["no_color"] += 1
            elif len(cnames) == 1:
                brushed_color_subcase["one_color"] += 1
            elif len(cnames) == 2 and None in cnames:
                brushed_color_subcase["mixed"] += 1
            else:
                brushed_color_subcase["two_colors"] += 1

        speeds.append(p.light.speed)
        exposures.append(p.look.exposure)
        gammas.append(p.look.gamma)
        contrasts.append(p.look.contrast)
        white_points.append(p.look.white_point)
        temperatures.append(p.look.temperature)
        vignettes.append(p.look.vignette)
        ca_values.append(p.look.chromatic_aberration)
        mov_intensities.append(p.light.moving_intensity)
        rows_list.append(p.grid.rows)
        cols_list.append(p.grid.cols)
        spacings.append(p.grid.spacing)

        if p.light.ambient.style != "none":
            amb_intensities.append(p.light.ambient.intensity)
            if p.light.ambient.spectrum.type == "color":
                colored_ambient += 1
                amb_white_mixes.append(p.light.ambient.spectrum.white_mix)

        if (
            p.light.spectrum.type == "range"
            and p.light.spectrum.wavelength_max - p.light.spectrum.wavelength_min < 300
        ) or (
            p.light.spectrum.type == "color"
            and p.light.spectrum.linear_rgb != [1.0, 1.0, 1.0]
        ):
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
            f"min={s[0]:.3f}  p25={s[len(s) // 4]:.3f}  "
            f"median={s[len(s) // 2]:.3f}  p75={s[3 * len(s) // 4]:.3f}  max={s[-1]:.3f}"
        )

    def counter_line(c: Counter, total: int | None = None) -> str:
        t = total or sum(c.values())
        return "  ".join(f"{k}={100 * v / t:.1f}%" for k, v in sorted(c.items()))

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
        print(f"  rotation   {100 * has_rotation / polygon_count:.1f}% of polygons")
        print(f"  jitter     {100 * has_jitter / polygon_count:.1f}% of polygons")
    print()

    print("── Material outcomes (active peers, equal probability) ─")
    print(f"  {counter_line(outcomes)}")
    print()

    print("── Glass ─────────────────────────────────────────────")
    if iors:
        print(f"  ior        {dist(iors)}")
        print(f"  cauchy_b   {dist(cauchy_bs)}")
    print()

    print("── Albedo per outcome ────────────────────────────────")
    for outcome in sorted(albedos_by_outcome):
        print(f"  {outcome:<17} {dist(albedos_by_outcome[outcome])}")
    print()

    print("── Fill per outcome ──────────────────────────────────")
    for outcome in sorted(fills_by_outcome):
        print(f"  {outcome:<17} {dist(fills_by_outcome[outcome])}")
    print()

    print("── Brushed metal color sub-cases (25% each target) ──")
    if brushed_color_subcase:
        print(f"  {counter_line(brushed_color_subcase)}")
    print()

    print("── Light ─────────────────────────────────────────────")
    print(f"  n_lights   {counter_line(n_lights_dist)}")
    print(f"  path       {counter_line(path_styles)}")
    print(f"  speed      {dist(speeds)}")
    print(f"  colored    {pct(colored_light)} (spectral narrowing)")
    print(f"  color_grps {counter_line(n_color_dist)}  (len of material.color_names)")
    print()

    print("── Ambient ───────────────────────────────────────────")
    print(f"  style      {counter_line(amb_styles)}")
    if amb_intensities:
        print(f"  intensity  {dist(amb_intensities)} (when present)")
    print(f"  colored    {pct(colored_ambient)}")
    if amb_white_mixes:
        print(f"  white_mix  {dist(amb_white_mixes)} (colored ambient)")
    print(f"  moving_int {dist(mov_intensities)}")
    print()

    print("── Look dims ─────────────────────────────────────────")
    print(f"  exposure    {dist(exposures)}")
    print(f"  gamma       {dist(gammas)}")
    print(f"  contrast    {dist(contrasts)}")
    print(f"  white_point {dist(white_points)}")
    # Temperature / vignette / CA are probabilistically off — split the stats.
    temp_on = [v for v in temperatures if v > 0]
    vig_on = [v for v in vignettes if v > 0]
    ca_on = [v for v in ca_values if v > 0]
    print(f"  temperature on={pct(len(temp_on))} {dist(temp_on) if temp_on else ''}")
    print(f"  vignette    on={pct(len(vig_on))} {dist(vig_on) if vig_on else ''}")
    print(f"  ca          on={pct(len(ca_on))} {dist(ca_on) if ca_on else ''}")
    print()
