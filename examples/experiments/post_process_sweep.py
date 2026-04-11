"""Render once, then write a small grid of post-processing variants.

Run:

    python examples/experiments/post_process_sweep.py

The scene is traced once. Every image after the first is produced by replaying
the post-process shader against the retained frame.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image

from anim import (
    Camera2D,
    Canvas,
    Circle,
    Look,
    Material,
    PointLight,
    Scene,
    Shot,
    Timeline,
    TraceDefaults,
    render_frame_variants,
    save_image,
)


def build_scene() -> Scene:
    return Scene(
        materials={
            "glass": Material(
                ior=1.45,
                transmission=1.0,
                absorption=0.1,
                cauchy_b=500.0,
                fill=0.04,
            )
        },
        shapes=[Circle(material_id="glass", id="lens", center=[0.0, 0.0], radius=0.25)],
        lights=[
            PointLight(
                id="light_0",
                position=[-0.75, 0.12],
                intensity=1.0,
                wavelength_min=500.0,
                wavelength_max=660.0,
            )
        ],
    )


def make_variants() -> dict[str, dict]:
    variants: dict[str, dict] = {}
    for exposure in (-4.2, -3.6, -3.0):
        for gamma in (0.8, 1.2, 1.8):
            name = f"exp_{exposure:+.1f}_gamma_{gamma:.1f}".replace("+", "p").replace("-", "m")
            variants[name] = {"exposure": exposure, "gamma": gamma}
    return variants


def write_sheet(paths: list[Path], out_path: Path, width: int, height: int, cols: int = 3) -> None:
    rows = (len(paths) + cols - 1) // cols
    sheet = Image.new("RGB", (width * cols, height * rows), color=(0, 0, 0))
    for idx, path in enumerate(paths):
        image = Image.open(path).convert("RGB")
        x = (idx % cols) * width
        y = (idx // cols) * height
        sheet.paste(image, (x, y))
    sheet.save(out_path)


def main() -> None:
    parser = argparse.ArgumentParser(description="Render once and sweep post-processing variants")
    parser.add_argument("--out", default="renders/post_process_sweep")
    parser.add_argument("--rays", type=int, default=500_000)
    args = parser.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    scene = build_scene()

    def animate(_ctx):
        return scene

    shot = Shot(
        camera=Camera2D(center=[0.0, 0.0], width=2.0),
        canvas=Canvas(480, 320),
        look=Look(exposure=-3.6, gamma=1.2, tonemap="reinhardx", normalize="rays"),
        trace=TraceDefaults(rays=args.rays, batch=min(args.rays, 200_000), depth=6),
    )

    written: list[Path] = []
    for name, variant in render_frame_variants(
        animate,
        Timeline(1.0, fps=1),
        settings=shot,
        variants=make_variants(),
    ).items():
        path = out / f"{name}.png"
        save_image(str(path), variant.result.pixels, variant.result.width, variant.result.height)
        written.append(path)

    write_sheet(written, out / "sheet.png", shot.canvas.width, shot.canvas.height)
    print(f"wrote {len(written)} variants and sheet.png to {out}")


if __name__ == "__main__":
    main()
