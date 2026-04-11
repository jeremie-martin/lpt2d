"""Export catalog parameter JSONs as authored Shot JSONs loadable by ``./build/lpt2d``.

For every ``renders/families/crystal_field/catalog/<material>/<tag>.json`` parameter
file produced by ``catalog.py``, reconstruct the :class:`Params`, rebuild the
animate callback, resolve it at the same clear-light frame selected by
``check.py``, and save the resulting authored :class:`Shot` JSON (the strict
``version: 10`` format) to the output directory.

No images are rendered.

Run::

    python -m examples.python.families.crystal_field catalog_shots
    python -m examples.python.families.crystal_field catalog_shots \
        --in renders/families/crystal_field/catalog \
        --out renders/families/crystal_field/catalog_shots
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from anim import Camera2D, Shot
from anim.examples_support import _authored_shot
from anim.params import params_from_dict

from .catalog import _CAM
from .check import measurement_context
from .params import Params
from .scene import build


def _base_settings() -> Shot:
    """Copy the catalog's production Shot and bake in the catalog camera."""
    settings = Shot.preset("production", width=1920, height=1080, rays=10_000_000, depth=12)
    settings.camera = Camera2D(center=_CAM.center, width=_CAM.width)
    return settings


def run_catalog_shots(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Export catalog param JSONs as authored Shot JSONs"
    )
    parser.add_argument(
        "--in",
        dest="in_dir",
        type=str,
        default="renders/families/crystal_field/catalog",
        help="directory containing <material>/<tag>.json parameter files",
    )
    parser.add_argument(
        "--out",
        type=str,
        default="renders/families/crystal_field/catalog_shots",
        help="output directory for authored Shot JSONs",
    )
    args = parser.parse_args(argv)

    in_dir = Path(args.in_dir)
    out_dir = Path(args.out)

    settings = _base_settings()

    param_files = sorted(
        p
        for p in in_dir.glob("*/*.json")
        if not p.name.endswith(".shot.json") and not p.name.endswith(".metrics.json")
    )
    if not param_files:
        print(f"No parameter JSONs found under {in_dir}")
        return

    print(f"Exporting {len(param_files)} shot JSONs from {in_dir} → {out_dir}")
    t0 = time.monotonic()

    ok = 0
    fail = 0
    for src in param_files:
        mat_name = src.parent.name
        tag = src.stem
        dst_dir = out_dir / mat_name
        dst_dir.mkdir(parents=True, exist_ok=True)
        dst = dst_dir / f"{tag}.json"

        try:
            data = json.loads(src.read_text())
            p = params_from_dict(Params, data)
            animate = build(p)
            ctx = measurement_context(p, animate)
            authored = _authored_shot(settings, animate, ctx)
            authored.name = f"crystal_field/{mat_name}/{tag}"
            authored.save(dst)
            ok += 1
        except Exception as exc:  # noqa: BLE001 — report and continue
            fail += 1
            print(f"  FAIL {mat_name}/{tag}: {exc}", flush=True)

    elapsed = time.monotonic() - t0
    print(f"Done: {ok} saved, {fail} failed in {elapsed:.1f}s")
    print(f"Output: {out_dir}/")


if __name__ == "__main__":
    run_catalog_shots()
