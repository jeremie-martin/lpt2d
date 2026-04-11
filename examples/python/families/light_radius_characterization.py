"""Characterize point-light radius measurements.

This script renders controlled one-light scenes and writes:

- raw PNGs
- overlay PNGs with the official analyzer radius and diagnostic core radius
- per-case shot JSON
- CSV/JSONL metrics
- contact sheets grouped by sweep axis

Run:

    python -m examples.python.families.light_radius_characterization

Fast smoke run:

    python -m examples.python.families.light_radius_characterization --limit 4
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from PIL import Image, ImageDraw, ImageFont

from anim import (
    Camera2D,
    Canvas,
    Circle,
    Look,
    Material,
    PointLight,
    Scene,
    Segment,
    Shot,
    TraceDefaults,
    glass,
    mirror_box,
)
from anim.renderer import RenderSession, save_image


OUT = Path("renders/light_radius_characterization")
CAMERA_WIDTH = 4.0
ROOM_HALF = 1.8
LIGHT_ID = "light_0"


@dataclass(frozen=True)
class Case:
    case_id: str
    group: str
    label: str
    wall: str = "absorber"
    perturbation: str = "none"
    light_position: tuple[float, float] = (0.0, 0.0)
    light_intensity: float = 1.0
    wavelength_min: float = 380.0
    wavelength_max: float = 780.0
    exposure: float = -5.0
    white_point: float = 0.5
    contrast: float = 1.0
    gamma: float = 2.0
    tonemap: str = "reinhardx"


@dataclass
class RenderedCase:
    case: Case
    image_path: Path
    overlay_path: Path
    shot_path: Path
    metrics: dict[str, float | int | str] = field(default_factory=dict)


def _font(size: int) -> ImageFont.ImageFont | ImageFont.FreeTypeFont:
    for candidate in (
        "/usr/share/fonts/TTF/DejaVuSansMono.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
        "/usr/share/fonts/dejavu/DejaVuSansMono.ttf",
    ):
        try:
            return ImageFont.truetype(candidate, size=size)
        except OSError:
            continue
    return ImageFont.load_default()


def _wall_material(kind: str) -> Material:
    if kind == "absorber":
        return Material(albedo=0.0, transmission=0.0, metallic=0.0, absorption=1.0)
    if kind == "diffuse":
        return Material(albedo=0.55, transmission=0.0, metallic=0.0, roughness=0.8)
    if kind == "standard_mirror":
        return Material(metallic=1.0, roughness=0.1, transmission=0.0, albedo=1.0)
    if kind == "rough_mirror":
        return Material(metallic=1.0, roughness=0.35, transmission=0.0, albedo=0.8)
    raise ValueError(f"unknown wall kind: {kind}")


def _base_look(case: Case) -> Look:
    return Look(
        exposure=case.exposure,
        contrast=case.contrast,
        gamma=case.gamma,
        tonemap=case.tonemap,
        white_point=case.white_point,
        normalize="rays",
        ambient=0.0,
        background=[0.0, 0.0, 0.0],
        opacity=1.0,
        saturation=1.0,
        vignette=0.0,
    )


def _build_scene(case: Case) -> Scene:
    materials: dict[str, Material] = {
        "wall": _wall_material(case.wall),
        "absorber": Material(albedo=0.0, transmission=0.0, metallic=0.0, absorption=1.0),
        "glass": glass(1.5, cauchy_b=20_000.0, absorption=1.0, fill=0.0),
        "mirror": Material(metallic=1.0, roughness=0.05, transmission=0.0, albedo=0.95),
    }
    shapes = list(mirror_box(ROOM_HALF, ROOM_HALF, "wall", id_prefix="wall"))

    if case.perturbation == "absorber_near":
        shapes.append(Circle(id="absorber_near", center=[0.34, 0.0], radius=0.12, material_id="absorber"))
    elif case.perturbation == "glass_near":
        shapes.append(Circle(id="glass_near", center=[0.34, 0.0], radius=0.12, material_id="glass"))
    elif case.perturbation == "mirror_near":
        shapes.append(Circle(id="mirror_near", center=[0.34, 0.0], radius=0.12, material_id="mirror"))
    elif case.perturbation == "occluder_bar":
        shapes.append(Segment(id="occluder_bar", a=[0.12, -0.35], b=[0.12, 0.35], material_id="absorber"))
    elif case.perturbation == "none":
        pass
    else:
        raise ValueError(f"unknown perturbation: {case.perturbation}")

    lights = [
        PointLight(
            id=LIGHT_ID,
            position=list(case.light_position),
            intensity=case.light_intensity,
            wavelength_min=case.wavelength_min,
            wavelength_max=case.wavelength_max,
        )
    ]
    return Scene(materials=materials, shapes=shapes, lights=lights)


def _make_shot(case: Case, width: int, height: int, rays: int, batch: int, depth: int) -> Shot:
    scene = _build_scene(case)
    return Shot(
        name=f"light_radius_characterization/{case.case_id}",
        scene=scene,
        camera=Camera2D(center=[0.0, 0.0], width=CAMERA_WIDTH),
        canvas=Canvas(width, height),
        look=_base_look(case),
        trace=TraceDefaults(rays=rays, batch=batch, depth=depth),
    )


def _metrics_for_case(case: Case, rr) -> dict[str, float | int | str]:
    light = next(iter(rr.analysis.lights), None)
    if light is None:
        raise RuntimeError(f"{case.case_id}: render produced no light appearance")
    lum = rr.analysis.luminance
    color = rr.analysis.color
    return {
        "case_id": case.case_id,
        "group": case.group,
        "label": case.label,
        "wall": case.wall,
        "perturbation": case.perturbation,
        "light_x": case.light_position[0],
        "light_y": case.light_position[1],
        "light_intensity": case.light_intensity,
        "wavelength_min": case.wavelength_min,
        "wavelength_max": case.wavelength_max,
        "exposure": case.exposure,
        "white_point": case.white_point,
        "contrast": case.contrast,
        "gamma": case.gamma,
        "tonemap": case.tonemap,
        "width": rr.width,
        "height": rr.height,
        "mean": lum.mean,
        "contrast_spread": lum.contrast_spread,
        "near_black_fraction": lum.near_black_fraction,
        "near_white_fraction": lum.near_white_fraction,
        "clipped_channel_fraction": lum.clipped_channel_fraction,
        "color_richness": color.richness,
        "image_x": light.image_x,
        "image_y": light.image_y,
        "cpp_radius_ratio": light.radius_ratio,
        "cpp_saturated_radius_ratio": light.saturated_radius_ratio,
        "cpp_transition_width_ratio": light.transition_width_ratio,
        "cpp_coverage_fraction": light.coverage_fraction,
        "cpp_peak_contrast": light.peak_contrast,
        "cpp_confidence": light.confidence,
    }


LabelLine = str | tuple[str, tuple[int, int, int, int]]


def _line_text(line: LabelLine) -> str:
    return line[0] if isinstance(line, tuple) else line


def _line_color(line: LabelLine) -> tuple[int, int, int, int]:
    return line[1] if isinstance(line, tuple) else (255, 255, 255, 255)


def _draw_label_block(draw: ImageDraw.ImageDraw, lines: list[LabelLine], width: int, height: int) -> None:
    font = _font(max(11, width // 72))
    padding = max(8, width // 180)
    line_h = max(12, int(font.size * 1.25) if hasattr(font, "size") else 14)
    text_w = max(draw.textlength(_line_text(line), font=font) for line in lines)
    box = (8, 8, int(8 + text_w + 2 * padding), int(8 + line_h * len(lines) + 2 * padding))
    draw.rounded_rectangle(box, radius=5, fill=(0, 0, 0, 180))
    y = box[1] + padding
    for line in lines:
        draw.text((box[0] + padding, y), _line_text(line), fill=_line_color(line), font=font)
        y += line_h


def _draw_ring(
    draw: ImageDraw.ImageDraw,
    cx: float,
    cy: float,
    radius_px: float,
    color: tuple[int, int, int, int],
    width: int = 2,
) -> None:
    if radius_px <= 0.0:
        return
    draw.ellipse(
        (cx - radius_px, cy - radius_px, cx + radius_px, cy + radius_px),
        outline=color,
        width=width,
    )


def _draw_stroked_ring(
    draw: ImageDraw.ImageDraw,
    cx: float,
    cy: float,
    radius_px: float,
    color: tuple[int, int, int, int],
    width: int,
) -> None:
    _draw_ring(draw, cx, cy, radius_px, (0, 0, 0, 255), width=max(width + 4, 6))
    _draw_ring(draw, cx, cy, radius_px, color, width=width)


def _overlay_image(rr, metrics: dict[str, float | int | str], out_path: Path) -> None:
    image = Image.frombytes("RGB", (rr.width, rr.height), rr.pixels).convert("RGBA")
    draw = ImageDraw.Draw(image, "RGBA")
    cx = float(metrics["image_x"])
    cy = float(metrics["image_y"])
    short_side = min(rr.width, rr.height)

    radius_color = (60, 255, 90, 255)
    edge_color = (60, 255, 90, 120)
    core_color = (70, 210, 255, 230)
    white = (255, 255, 255, 255)

    line_width = max(2, rr.width // 640)
    radius_px = float(metrics["cpp_radius_ratio"]) * short_side
    edge_px = float(metrics["cpp_transition_width_ratio"]) * short_side
    if edge_px > 1.0:
        _draw_stroked_ring(draw, cx, cy, max(0.0, radius_px - 0.5 * edge_px), edge_color, line_width)
        _draw_stroked_ring(draw, cx, cy, radius_px + 0.5 * edge_px, edge_color, line_width)
    _draw_stroked_ring(draw, cx, cy, radius_px, radius_color, width=max(line_width + 1, 3))
    _draw_stroked_ring(draw, cx, cy, float(metrics["cpp_saturated_radius_ratio"]) * short_side, core_color, line_width)
    draw.ellipse((cx - 3, cy - 3, cx + 3, cy + 3), fill=(255, 255, 255, 255))

    wave_min = float(metrics["wavelength_min"])
    wave_max = float(metrics["wavelength_max"])
    color_name = "white" if wave_min <= 380.0 and wave_max >= 780.0 else f"{wave_min:g}-{wave_max:g} nm"
    ratio_unit = "% of image short side"
    lines: list[LabelLine] = [
        f"Case: {metrics['case_id']} ({metrics['label']})",
        f"Scene: wall={metrics['wall']}; nearby object={metrics['perturbation']}",
        f"Light: intensity={float(metrics['light_intensity']):.3g}; color={color_name}",
        f"Look: exposure={float(metrics['exposure']):.3g}; white point={float(metrics['white_point']):.3g}; "
        f"contrast={float(metrics['contrast']):.3g}; gamma={float(metrics['gamma']):.3g}",
        f"All radii below are normalized: {ratio_unit}, not pixels.",
        (
            f"GREEN official measured radius: {100*float(metrics['cpp_radius_ratio']):.2f}{ratio_unit}",
            radius_color,
        ),
        (
            f"CYAN diagnostic saturated-core radius: {100*float(metrics['cpp_saturated_radius_ratio']):.2f}{ratio_unit}",
            core_color,
        ),
        (
            f"Edge softness (80% to 20% falloff): {100*float(metrics['cpp_transition_width_ratio']):.2f}{ratio_unit}; "
            f"confidence={float(metrics['cpp_confidence']):.2f}",
            white,
        ),
        f"Image brightness: mean={float(metrics['mean']):.1f}/255; near-white={100*float(metrics['near_white_fraction']):.2f}%; clipped-channel={100*float(metrics['clipped_channel_fraction']):.2f}%",
    ]
    _draw_label_block(draw, lines, rr.width, rr.height)
    image.convert("RGB").save(out_path)


def _write_contact_sheet(cases: list[RenderedCase], out_path: Path, *, cols: int = 4, tile_width: int = 460) -> None:
    if not cases:
        return
    images = [Image.open(c.overlay_path).convert("RGB") for c in cases]
    aspect = images[0].height / images[0].width
    tile_height = int(round(tile_width * aspect))
    caption_h = 76
    rows = math.ceil(len(images) / cols)
    sheet = Image.new("RGB", (cols * tile_width, rows * (tile_height + caption_h)), (24, 24, 24))
    draw = ImageDraw.Draw(sheet)
    font = _font(max(13, tile_width // 33))
    small_font = _font(max(11, tile_width // 42))
    for idx, (case_result, img) in enumerate(zip(cases, images)):
        col = idx % cols
        row = idx // cols
        x = col * tile_width
        y = row * (tile_height + caption_h)
        sheet.paste(img.resize((tile_width, tile_height), Image.Resampling.LANCZOS), (x, y))
        caption = case_result.case.label
        metric = case_result.metrics
        sub1 = (
            f"measured radius {100*float(metric['cpp_radius_ratio']):.2f}% of short side; "
            f"edge softness {100*float(metric['cpp_transition_width_ratio']):.2f}%"
        )
        sub2 = (
            f"I={float(metric['light_intensity']):.3g}; exposure={float(metric['exposure']):.3g}; "
            f"white point={float(metric['white_point']):.3g}; color={float(metric['wavelength_min']):g}-{float(metric['wavelength_max']):g} nm"
        )
        draw.rectangle((x, y + tile_height, x + tile_width, y + tile_height + caption_h), fill=(0, 0, 0))
        draw.text((x + 6, y + tile_height + 4), caption[:42], fill=(255, 255, 255), font=font)
        draw.text((x + 6, y + tile_height + 28), sub1[:78], fill=(190, 255, 200), font=small_font)
        draw.text((x + 6, y + tile_height + 50), sub2[:86], fill=(190, 220, 255), font=small_font)
    sheet.save(out_path)


def _case_sweeps() -> list[Case]:
    base = Case(case_id="base", group="base", label="baseline")

    cases = [base]
    for value in (0.25, 0.5, 1.0, 2.0):
        cases.append(
            Case(
                case_id=f"intensity_{value:g}".replace(".", "p"),
                group="intensity",
                label=f"intensity {value:g}",
                light_intensity=value,
            )
        )
    for value in (-7.0, -6.0, -5.0, -4.0):
        cases.append(
            Case(
                case_id=f"exposure_{value:g}".replace("-", "m").replace(".", "p"),
                group="exposure",
                label=f"exposure {value:g}",
                exposure=value,
            )
        )
    for value in (0.25, 0.5, 1.0, 2.0):
        cases.append(
            Case(
                case_id=f"white_point_{value:g}".replace(".", "p"),
                group="white_point",
                label=f"white point {value:g}",
                white_point=value,
            )
        )
    for value in (0.7, 1.0, 1.5, 2.0):
        cases.append(
            Case(
                case_id=f"contrast_{value:g}".replace(".", "p"),
                group="contrast",
                label=f"contrast {value:g}",
                contrast=value,
            )
        )
    for value in (1.2, 1.6, 2.0, 2.8):
        cases.append(
            Case(
                case_id=f"gamma_{value:g}".replace(".", "p"),
                group="gamma",
                label=f"gamma {value:g}",
                gamma=value,
            )
        )
    for value in ("absorber", "diffuse", "standard_mirror", "rough_mirror"):
        cases.append(Case(case_id=f"wall_{value}", group="wall", label=f"wall {value}", wall=value))
    for value in ("none", "absorber_near", "glass_near", "mirror_near", "occluder_bar"):
        cases.append(
            Case(
                case_id=f"perturb_{value}",
                group="perturbation",
                label=f"perturb {value}",
                perturbation=value,
            )
        )
    for label, position in (
        ("center", (0.0, 0.0)),
        ("right", (0.9, 0.0)),
        ("upper_right", (0.9, 0.9)),
        ("near_edge", (1.45, 0.0)),
    ):
        cases.append(
            Case(
                case_id=f"position_{label}",
                group="position",
                label=f"position {label}",
                light_position=position,
            )
        )
    for label, wavelength in (
        ("white", (380.0, 780.0)),
        ("orange", (585.0, 620.0)),
        ("red", (610.0, 700.0)),
        ("green", (500.0, 570.0)),
        ("blue", (430.0, 490.0)),
    ):
        cases.append(
            Case(
                case_id=f"color_{label}",
                group="color",
                label=f"color {label}",
                wavelength_min=wavelength[0],
                wavelength_max=wavelength[1],
            )
        )

    large_radius_cases = [
        (
            "large_exp_m4_wp0p25",
            "large disk: exposure -4, white point 0.25",
            dict(exposure=-4.0, white_point=0.25),
        ),
        (
            "large_exp_m4_wp0p125",
            "large disk: exposure -4, white point 0.125",
            dict(exposure=-4.0, white_point=0.125),
        ),
        (
            "large_exp_m4_wp0p0625",
            "large disk: exposure -4, white point 0.0625",
            dict(exposure=-4.0, white_point=0.0625),
        ),
        (
            "large_exp_m3p5_wp0p25",
            "large disk: exposure -3.5, white point 0.25",
            dict(exposure=-3.5, white_point=0.25),
        ),
        (
            "large_exp_m3p5_wp0p125",
            "large disk: exposure -3.5, white point 0.125",
            dict(exposure=-3.5, white_point=0.125),
        ),
        (
            "large_exp_m3_wp0p25",
            "large disk: exposure -3, white point 0.25",
            dict(exposure=-3.0, white_point=0.25),
        ),
        (
            "large_exp_m3_wp0p125",
            "large disk: exposure -3, white point 0.125",
            dict(exposure=-3.0, white_point=0.125),
        ),
        (
            "large_intensity4_wp0p25",
            "large disk: intensity 4, white point 0.25",
            dict(light_intensity=4.0, white_point=0.25),
        ),
        (
            "large_intensity8_wp0p25",
            "large disk: intensity 8, white point 0.25",
            dict(light_intensity=8.0, white_point=0.25),
        ),
        (
            "large_limit_exp_m2p5_wp0p125",
            "near-limit disk: exposure -2.5, white point 0.125",
            dict(exposure=-2.5, white_point=0.125),
        ),
        (
            "large_orange_exp_m3_wp0p25",
            "large orange disk: exposure -3, white point 0.25",
            dict(exposure=-3.0, white_point=0.25, wavelength_min=585.0, wavelength_max=620.0),
        ),
        (
            "large_orange_exp_m3p5_wp0p125",
            "large orange disk: exposure -3.5, white point 0.125",
            dict(exposure=-3.5, white_point=0.125, wavelength_min=585.0, wavelength_max=620.0),
        ),
        (
            "large_orange_exp_m4_wp0p25_i2",
            "large orange disk: exposure -4, white point 0.25, intensity 2",
            dict(
                exposure=-4.0,
                white_point=0.25,
                light_intensity=2.0,
                wavelength_min=585.0,
                wavelength_max=620.0,
            ),
        ),
    ]
    for case_id, label, overrides in large_radius_cases:
        cases.append(Case(case_id=case_id, group="large_radius", label=label, **overrides))

    standard_mirror_large_cases = [
        (
            "large_mirror_exp_m7p5_wp0p0625",
            "large standard-mirror disk: exposure -7.5, white point 0.0625",
            dict(exposure=-7.5, white_point=0.0625),
        ),
        (
            "large_mirror_exp_m6_wp0p125",
            "large standard-mirror disk: exposure -6, white point 0.125",
            dict(exposure=-6.0, white_point=0.125),
        ),
        (
            "large_mirror_exp_m5p5_wp0p125",
            "large standard-mirror disk: exposure -5.5, white point 0.125",
            dict(exposure=-5.5, white_point=0.125),
        ),
        (
            "large_mirror_orange_exp_m5_wp0p125",
            "large orange standard-mirror disk: exposure -5, white point 0.125",
            dict(exposure=-5.0, white_point=0.125, wavelength_min=585.0, wavelength_max=620.0),
        ),
    ]
    for case_id, label, overrides in standard_mirror_large_cases:
        cases.append(
            Case(
                case_id=case_id,
                group="large_radius_standard_mirror",
                label=label,
                wall="standard_mirror",
                **overrides,
            )
        )

    # Remove duplicate baseline-like cases while preserving groups.
    seen: set[str] = set()
    unique: list[Case] = []
    for case in cases:
        if case.case_id in seen:
            continue
        seen.add(case.case_id)
        unique.append(case)
    return unique


def _selected_cases(groups: Iterable[str] | None, limit: int | None) -> list[Case]:
    cases = _case_sweeps()
    if groups:
        group_set = set(groups)
        cases = [case for case in cases if case.group in group_set or case.case_id in group_set]
    if limit is not None:
        cases = cases[:limit]
    return cases


def _write_metrics(outputs: list[RenderedCase], out_dir: Path) -> None:
    if not outputs:
        return
    keys = list(outputs[0].metrics.keys())
    with (out_dir / "metrics.csv").open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=keys)
        writer.writeheader()
        for result in outputs:
            writer.writerow(result.metrics)
    with (out_dir / "metrics.jsonl").open("w") as f:
        for result in outputs:
            f.write(json.dumps(result.metrics, sort_keys=True) + "\n")


def run(args: argparse.Namespace) -> None:
    out_dir = Path(args.out)
    image_dir = out_dir / "images"
    overlay_dir = out_dir / "overlays"
    sheet_dir = out_dir / "sheets"
    shot_dir = out_dir / "shots"
    for path in (image_dir, overlay_dir, sheet_dir, shot_dir):
        path.mkdir(parents=True, exist_ok=True)

    cases = _selected_cases(args.group, args.limit)
    if not cases:
        raise SystemExit("no cases selected")

    outputs: list[RenderedCase] = []
    start = time.monotonic()
    for index, case in enumerate(cases, 1):
        shot = _make_shot(case, args.width, args.height, args.rays, args.batch, args.depth)
        shot_path = shot_dir / f"{case.case_id}.json"
        shot.save(shot_path)

        session = RenderSession(args.width, args.height, args.fast)
        t0 = time.monotonic()
        rr = session.render_shot(shot.to_cpp(), 0, True)
        session.close()
        render_ms = (time.monotonic() - t0) * 1000.0

        light = next(iter(rr.analysis.lights), None)
        if light is None:
            raise RuntimeError(f"{case.case_id}: no point-light measurement")
        metrics = _metrics_for_case(case, rr)
        metrics["render_ms"] = render_ms

        image_path = image_dir / f"{case.case_id}.png"
        overlay_path = overlay_dir / f"{case.case_id}.png"
        save_image(str(image_path), rr.pixels, rr.width, rr.height)
        _overlay_image(rr, metrics, overlay_path)
        outputs.append(RenderedCase(case, image_path, overlay_path, shot_path, metrics))

        elapsed = time.monotonic() - start
        sys.stderr.write(
            f"\r{index:3d}/{len(cases)} {case.case_id:<28s} "
            f"{render_ms:6.0f} ms  elapsed {elapsed:5.1f}s"
        )
        sys.stderr.flush()
    sys.stderr.write("\n")

    _write_metrics(outputs, out_dir)
    by_group: dict[str, list[RenderedCase]] = {}
    for result in outputs:
        by_group.setdefault(result.case.group, []).append(result)
    for group, group_results in by_group.items():
        _write_contact_sheet(group_results, sheet_dir / f"{group}.png", cols=args.cols, tile_width=args.tile_width)
    _write_contact_sheet(outputs, sheet_dir / "all.png", cols=args.cols, tile_width=args.tile_width)

    print(f"wrote {len(outputs)} cases to {out_dir}")
    print(f"metrics: {out_dir / 'metrics.csv'}")
    print(f"contact sheets: {sheet_dir}")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default=str(OUT), help="output directory")
    parser.add_argument("--width", type=int, default=512)
    parser.add_argument("--height", type=int, default=512)
    parser.add_argument("--rays", type=int, default=600_000)
    parser.add_argument("--batch", type=int, default=200_000)
    parser.add_argument("--depth", type=int, default=12)
    parser.add_argument("--fast", action="store_true", help="use half-float render target")
    parser.add_argument(
        "--group",
        action="append",
        help="case group or case id to render; may be repeated",
    )
    parser.add_argument("--limit", type=int, help="render only the first N selected cases")
    parser.add_argument("--cols", type=int, default=4, help="contact sheet columns")
    parser.add_argument("--tile-width", type=int, default=460, help="contact sheet tile width in pixels")
    args = parser.parse_args(argv)
    run(args)


if __name__ == "__main__":
    main()
