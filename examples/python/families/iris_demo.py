"""Iris demo runner — preferred random-batch configuration.

Self-contained wrapper around :mod:`iris_batch` that bakes in the curator's
chosen constraints so a single command reproduces a "good" batch:

* branch = ``solo_white``
* pace = ``fast_light``
* layout = 75% ``iris_vertical`` / 25% ``iris_horizontal`` (weighted random)
* light_kind / geom_kind / numeric params: free
* duration: 15 s
* resolution: chosen via ``--resolution {480p, 720p, 1080p}``

Run::

    # Quick preview (~15 min)
    python examples/python/families/iris_demo.py \
        --out renders/iris_demo_preview --resolution 480p

    # Production (~3-4 h)
    python examples/python/families/iris_demo.py \
        --out renders/iris_demo_720p --resolution 720p

The output is a self-contained directory with one subdir per variant plus
``index.html`` ready to upload (see ``docs/VPS_IMAGE_GALLERIES.md``).
"""

from __future__ import annotations

import argparse

from examples.python.families import iris_batch


# Resolution presets keyed by short name. Each dict carries every render-
# related knob; bumping a knob here propagates to every subsequent run.
RESOLUTION_PRESETS: dict[str, dict[str, int]] = {
    "480p":  {"width": 854,  "height": 480,  "rays": 1_000_000, "fps": 24, "depth": 10},
    "720p":  {"width": 1280, "height": 720,  "rays": 4_000_000, "fps": 60, "depth": 12},
    "1080p": {"width": 1920, "height": 1080, "rays": 6_000_000, "fps": 60, "depth": 12},
}

LAYOUT_WEIGHTS = "iris_horizontal:1,iris_vertical:3"  # 25% horizontal, 75% vertical
DURATION_SEC = 15.0


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Iris preferred random batch")
    parser.add_argument("--out", type=str, required=True, help="Output directory")
    parser.add_argument("-n", type=int, default=12, help="Number of variants (default 12)")
    parser.add_argument(
        "--resolution",
        choices=list(RESOLUTION_PRESETS),
        default="720p",
        help="Render resolution preset (default 720p)",
    )
    parser.add_argument("--seed", type=int, default=None, help="RNG seed")
    parser.add_argument(
        "--max-attempts", type=int, default=500,
        help="Search budget per variant (default 500)",
    )
    args = parser.parse_args(argv)

    preset = RESOLUTION_PRESETS[args.resolution]
    batch_argv = [
        "--out", args.out,
        "-n", str(args.n),
        "--max-attempts", str(args.max_attempts),
        "--branch", "solo_white",
        "--pace", "fast_light",
        "--layout-weights", LAYOUT_WEIGHTS,
        "--width", str(preset["width"]),
        "--height", str(preset["height"]),
        "--rays", str(preset["rays"]),
        "--fps", str(preset["fps"]),
        "--depth", str(preset["depth"]),
        "--duration", str(DURATION_SEC),
    ]
    if args.seed is not None:
        batch_argv += ["--seed", str(args.seed)]

    print(f"iris_demo: resolution={args.resolution} {preset}", flush=True)
    iris_batch.main(batch_argv)


if __name__ == "__main__":
    main()
