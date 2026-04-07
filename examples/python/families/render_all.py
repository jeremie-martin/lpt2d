"""Render all animation families — 4 variants each, HQ 1080p.

Usage:
    python examples/python/families/render_all.py          # low-res preview
    python examples/python/families/render_all.py --hq     # full 1080p 5M rays
"""

from __future__ import annotations

import random
import sys
import time
from pathlib import Path

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

HQ = "--hq" in sys.argv
VARIANTS_PER_FAMILY = 4
BASE_SEED = 2026_04_07

WIDTH = 1920 if HQ else 320
HEIGHT = 1080 if HQ else 180
RAYS = 5_000_000 if HQ else 2_000_000

BASE_DIR = Path("renders/families")

# ---------------------------------------------------------------------------
# Family registry
# ---------------------------------------------------------------------------

FAMILIES = [
    "glass_turbine",
    "fractal_tree",
    "lens_caustics",
    "mirror_corridor",
    "crystal_pendulum",
]


def render_family(family_name: str, n: int, seed: int) -> None:
    """Generate n valid variants for one family."""
    print(f"\n{'='*60}")
    print(f"FAMILY: {family_name} ({n} variants, seed={seed})")
    print(f"{'='*60}")

    if family_name == "glass_turbine":
        from families.glass_turbine import random_params, check_beauty, render_and_save
    elif family_name == "fractal_tree":
        from families.fractal_tree import random_params, check_beauty, render_and_save
    elif family_name == "lens_caustics":
        from families.lens_caustics import random_params, check_beauty, render_and_save
    elif family_name == "mirror_corridor":
        from families.mirror_corridor import random_params, check_beauty, render_and_save
    elif family_name == "crystal_pendulum":
        from families.crystal_pendulum import random_params, check_beauty, render_and_save
    else:
        print(f"Unknown family: {family_name}")
        return

    rng = random.Random(seed)
    out_base = BASE_DIR / family_name
    found = 0
    max_attempts = 500

    for attempt in range(1, max_attempts + 1):
        p = random_params(rng)
        result = check_beauty(p)
        ok = result[0]

        if not ok:
            print(f"  [{attempt}] rejected")
            continue

        found += 1
        out_dir = out_base / f"{found:03d}"
        print(f"  [{attempt}] FOUND #{found} — rendering {WIDTH}x{HEIGHT} {RAYS/1e6:.0f}M rays...")
        t0 = time.monotonic()
        render_and_save(p, out_dir, WIDTH, HEIGHT, RAYS)
        elapsed = time.monotonic() - t0
        print(f"  done in {elapsed:.0f}s")

        if found >= n:
            break

    if found < n:
        print(f"  WARNING: only found {found}/{n} valid variants")


def main() -> None:
    print(f"Rendering all families: {VARIANTS_PER_FAMILY} variants each")
    print(f"Resolution: {WIDTH}x{HEIGHT}, Rays: {RAYS/1e6:.0f}M, HQ={HQ}")

    total_start = time.monotonic()

    for i, family in enumerate(FAMILIES):
        family_seed = BASE_SEED + i * 1000
        render_family(family, VARIANTS_PER_FAMILY, family_seed)

    total_elapsed = time.monotonic() - total_start
    print(f"\n{'='*60}")
    print(f"ALL DONE — {len(FAMILIES)} families x {VARIANTS_PER_FAMILY} variants = {len(FAMILIES)*VARIANTS_PER_FAMILY} videos")
    print(f"Total time: {total_elapsed/60:.1f} minutes")
    print(f"Output: {BASE_DIR}/")


if __name__ == "__main__":
    main()
