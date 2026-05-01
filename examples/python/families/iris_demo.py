"""Iris demo runner — preferred random-batch configuration.

Self-contained wrapper around :mod:`iris_batch` that bakes in the curator's
chosen constraints so a single command reproduces a "good" batch:

* branch = ``solo_white``
* light-motion regime / geom_kind / all numeric params: free
* duration: 15 s
* aspect: 9:16 portrait
* resolution: chosen via ``--resolution {360p, 480p, 720p, 1080p}``

Run::

    # Quick preview (~15 min)
    python examples/python/families/iris_demo.py \
        --out renders/iris_demo_preview --resolution 480p

    # Production
    python examples/python/families/iris_demo.py \
        --out renders/iris_demo_1080p --resolution 1080p

The output is a self-contained directory with one subdir per variant plus
``index.html`` ready to upload (see ``docs/VPS_IMAGE_GALLERIES.md``).
"""

from __future__ import annotations

import argparse

from examples.python.families import iris_batch


# Resolution presets keyed by short name. All in 9:16 portrait orientation.
# Each dict carries every render-related knob; bumping a knob here
# propagates to every subsequent run.
# ``fast`` enables half-float precision (RGBA16F instead of RGBA32F) — much
# faster, slightly less fidelity in extreme highlights. Useful for quick
# preview/exploration runs at low resolution.
RESOLUTION_PRESETS: dict[str, dict[str, object]] = {
    "360p":  {"width": 360,  "height": 640,  "rays": 1_000_000, "fps": 30, "depth": 12, "fast": False, "crf": 18},
    "480p":  {"width": 480,  "height": 854,  "rays": 1_000_000, "fps": 24, "depth": 12, "fast": False, "crf": 18},
    "720p":  {"width": 720,  "height": 1280, "rays": 4_000_000, "fps": 60, "depth": 12, "fast": False, "crf": 15},
    "1080p": {"width": 1080, "height": 1920, "rays": 6_000_000, "fps": 60, "depth": 12, "fast": False, "crf": 15},
}

DURATION_SEC = 15.0


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Iris preferred random batch")
    parser.add_argument("--out", type=str, required=True, help="Output directory")
    parser.add_argument("-n", type=int, default=12, help="Number of variants (default 12)")
    parser.add_argument(
        "--resolution",
        choices=list(RESOLUTION_PRESETS),
        default="1080p",
        help="Render resolution preset (default 1080p)",
    )
    parser.add_argument("--seed", type=int, default=None, help="RNG seed")
    parser.add_argument(
        "--max-attempts", type=int, default=500,
        help="Search budget per variant (default 500)",
    )
    parser.add_argument("--no-index", action="store_true",
                        help="Skip index.html (passes through to iris_batch).")
    args = parser.parse_args(argv)

    preset = RESOLUTION_PRESETS[args.resolution]
    batch_argv = [
        "--out", args.out,
        "-n", str(args.n),
        "--max-attempts", str(args.max_attempts),
        "--branch", "solo_white",
        "--width", str(preset["width"]),
        "--height", str(preset["height"]),
        "--rays", str(preset["rays"]),
        "--fps", str(preset["fps"]),
        "--depth", str(preset["depth"]),
        "--duration", str(DURATION_SEC),
        "--crf", str(preset.get("crf", 18)),
    ]
    if preset.get("fast"):
        batch_argv.append("--fast")
    if args.seed is not None:
        batch_argv += ["--seed", str(args.seed)]
    if args.no_index:
        batch_argv.append("--no-index")

    print(f"iris_demo: resolution={args.resolution} {preset}", flush=True)
    iris_batch.main(batch_argv)


if __name__ == "__main__":
    main()
