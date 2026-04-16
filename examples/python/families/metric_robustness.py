"""Measure image-stat robustness across render resolution and ray count.

The goal is to make metric instability obvious before a family script starts
depending on a statistic.  The script renders a small set of controlled scenes
over a grid of resolutions and ray counts, then writes:

- metrics.csv: one row per render, with all scalar image/debug/light stats
- summary.md: worst resolution and ray-count drift per metric
- optional baseline PNGs for visual inspection

Run a small smoke check:

    python -m examples.python.families.metric_robustness --preset smoke

Run the full 240p..1080p / 64K..4M grid:

    python -m examples.python.families.metric_robustness --preset full
"""

from __future__ import annotations

import argparse
import csv
import html
import json
import math
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable

import _lpt2d
from anim import (
    Camera2D,
    Canvas,
    Circle,
    Frame,
    Look,
    Material,
    PointLight,
    Scene,
    TraceDefaults,
    glass,
    mirror_box,
)
from anim.family import _STANDARD_LOOK
from anim.renderer import RenderSession, _resolve_frame_shot, save_image
from anim.types import Shot

OUT = Path("renders/metric_robustness")
ASPECT = 16.0 / 9.0
CAM_CENTER = (0.0, 0.0)
CAM_WIDTH = 3.2
DEFAULT_EXPOSURE = -5.0
DEFAULT_BATCH = 200_000
DEFAULT_DEPTH = 12

HEIGHT_PRESETS: dict[str, tuple[int, ...]] = {
    "smoke": (240, 360),
    "quick": (240, 360, 480, 720),
    "full": (240, 360, 480, 720, 1080),
}

RAY_PRESETS: dict[str, tuple[int, ...]] = {
    "smoke": (2**16, 2**17, 2**18),
    "quick": (2**16, 2**17, 2**18, 2**19, 2**20),
    "full": (2**16, 2**17, 2**18, 2**19, 2**20, 2**21, 2**22),
}

IMAGE_METRICS = (
    "mean_luma",
    "median_luma",
    "p05_luma",
    "p95_luma",
    "near_black_fraction",
    "near_white_fraction",
    "clipped_channel_fraction",
    "rms_contrast",
    "interdecile_luma_range",
    "interdecile_luma_contrast",
    "local_contrast",
    "mean_saturation",
    "p95_saturation",
    "colorfulness",
    "bright_neutral_fraction",
)

DEBUG_METRICS = (
    "p01_luma",
    "p10_luma",
    "p90_luma",
    "p99_luma",
    "luma_entropy",
    "luma_entropy_normalized",
    "hue_entropy",
    "colored_fraction",
    "mean_saturation_colored",
    "saturation_coverage",
    "colorfulness_raw",
)

LIGHT_METRICS = (
    "light_count",
    "visible_light_count",
    "visible_light_fraction",
    "mean_visible_radius_ratio",
    "max_radius_ratio",
    "mean_light_confidence",
    "max_peak_contrast",
)

SCALAR_METRICS = IMAGE_METRICS + DEBUG_METRICS + LIGHT_METRICS

RAY_PLOT_METRICS = (
    "mean_luma",
    "p05_luma",
    "p95_luma",
    "interdecile_luma_range",
    "local_contrast",
    "mean_saturation",
    "p95_saturation",
    "colorfulness",
)

RESOLUTION_PLOT_METRICS = (
    "mean_luma",
    "interdecile_luma_range",
    "local_contrast",
    "mean_saturation",
    "p95_saturation",
    "colorfulness",
)

DRIFT_PLOT_METRICS = (
    "mean_luma",
    "p05_luma",
    "p95_luma",
    "rms_contrast",
    "interdecile_luma_range",
    "interdecile_luma_contrast",
    "local_contrast",
    "mean_saturation",
    "p95_saturation",
    "colorfulness",
    "near_black_fraction",
    "near_white_fraction",
    "clipped_channel_fraction",
    "bright_neutral_fraction",
)

SCENE_COLORS = {
    "single": "#2f6fb3",
    "color": "#c23b5a",
    "glass": "#15845b",
    "occlusion": "#9a6a00",
}

METADATA_FIELDS = (
    "scene",
    "label",
    "width",
    "height",
    "requested_rays",
    "total_rays",
    "rays_per_pixel",
    "time_ms",
    "exposure",
)

CSV_FIELDS = METADATA_FIELDS + SCALAR_METRICS + ("lights_json",)


@dataclass(frozen=True)
class SceneSpec:
    name: str
    label: str
    build: Callable[[], Scene]
    exposure: float = DEFAULT_EXPOSURE


@dataclass(frozen=True)
class Drift:
    metric: str
    abs_delta: float
    rel_delta: float
    value: float
    baseline: float
    context: str


WALL = Material(metallic=1.0, roughness=0.1, transmission=0.0, cauchy_b=0.0, albedo=1.0)


def _width_for_height(height: int) -> int:
    return max(2, int(round(height * ASPECT / 2.0)) * 2)


def _fmt_rays(rays: int) -> str:
    if rays >= 1_000_000:
        value = rays / 1_000_000.0
        return f"{value:.1f}M" if value != int(value) else f"{int(value)}M"
    if rays >= 1_000:
        value = rays / 1_000.0
        return f"{value:.0f}K" if value == int(value) else f"{value:.1f}K"
    return str(rays)


def _fmt_float(value: float) -> str:
    if not math.isfinite(value):
        return "nan"
    if abs(value) >= 100.0:
        return f"{value:.1f}"
    if abs(value) >= 10.0:
        return f"{value:.2f}"
    return f"{value:.4f}"


def _scene_single_light() -> Scene:
    walls = mirror_box(1.6, 0.9, "wall", id_prefix="wall")
    lights = [PointLight(id="center", position=[0.0, 0.0], intensity=1.0)]
    return Scene(materials={"wall": WALL}, shapes=walls, lights=lights)


def _scene_three_color_lights() -> Scene:
    walls = mirror_box(1.6, 0.9, "wall", id_prefix="wall")
    lights = [
        PointLight(id="red", position=[-0.75, 0.0], intensity=1.1, wavelength_min=620, wavelength_max=700),
        PointLight(id="green", position=[0.0, 0.15], intensity=1.0, wavelength_min=500, wavelength_max=570),
        PointLight(id="blue", position=[0.75, 0.0], intensity=1.25, wavelength_min=430, wavelength_max=485),
    ]
    return Scene(materials={"wall": WALL}, shapes=walls, lights=lights)


def _scene_glass_grid() -> Scene:
    walls = mirror_box(1.6, 0.9, "wall", id_prefix="wall")
    mat_glass = glass(1.5, cauchy_b=20_000, absorption=1.0, fill=0.12)
    shapes: list[Any] = list(walls)
    spacing = 0.3
    cols, rows = 5, 4
    grid_w = (cols - 1) * spacing
    grid_h = (rows - 1) * spacing
    for row in range(rows):
        for col in range(cols):
            x = -grid_w / 2.0 + col * spacing
            y = -grid_h / 2.0 + row * spacing
            shapes.append(Circle(id=f"obj_{row}_{col}", center=[x, y], radius=0.06, material_id="crystal"))

    corners = [(-1.4, 0.75), (1.4, 0.75), (-1.4, -0.75), (1.4, -0.75)]
    lights = [PointLight(id="moving", position=[0.15, 0.15], intensity=1.0)]
    lights.extend(
        PointLight(id=f"amb_{i}", position=[x, y], intensity=0.3)
        for i, (x, y) in enumerate(corners)
    )
    return Scene(materials={"wall": WALL, "crystal": mat_glass}, shapes=shapes, lights=lights)


def _scene_absorber_occlusion() -> Scene:
    walls = mirror_box(1.6, 0.9, "wall", id_prefix="wall")
    absorber = Material(albedo=0.0, transmission=0.0, metallic=0.0, absorption=1.0)
    shapes: list[Any] = list(walls)
    shapes.append(Circle(id="absorber_near", center=[0.2, 0.0], radius=0.13, material_id="absorber"))
    lights = [
        PointLight(id="center", position=[0.0, 0.0], intensity=1.0),
        PointLight(id="corner", position=[-1.15, 0.55], intensity=0.35),
    ]
    return Scene(materials={"wall": WALL, "absorber": absorber}, shapes=shapes, lights=lights)


SCENES: dict[str, SceneSpec] = {
    "single": SceneSpec("single", "single neutral point light", _scene_single_light),
    "color": SceneSpec("color", "three colored point lights", _scene_three_color_lights, -7.0),
    "glass": SceneSpec("glass", "glass grid with ambient corners", _scene_glass_grid),
    "occlusion": SceneSpec("occlusion", "absorber near point light", _scene_absorber_occlusion),
}


def _make_shot(spec: SceneSpec, width: int, height: int, rays: int, batch: int, depth: int) -> Shot:
    scene = spec.build()
    return Shot(
        name=f"metric_robustness/{spec.name}",
        scene=scene,
        camera=Camera2D(center=list(CAM_CENTER), width=CAM_WIDTH),
        canvas=Canvas(width, height),
        look=Look(
            **{
                **_STANDARD_LOOK,
                "exposure": spec.exposure,
                "saturation": 1.0,
                "ambient": 0.0,
                "background": [0.0, 0.0, 0.0],
                "opacity": 1.0,
                "vignette": 0.0,
            }
        ),
        trace=TraceDefaults(rays=rays, batch=min(batch, rays), depth=depth, seed_mode="deterministic"),
    )


def _light_entries(lights: Iterable[Any]) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for light in lights:
        entries.append(
            {
                "id": str(light.id),
                "visible": bool(light.visible),
                "radius_ratio": float(light.radius_ratio),
                "saturated_radius_ratio": float(light.saturated_radius_ratio),
                "transition_width_ratio": float(light.transition_width_ratio),
                "coverage_fraction": float(light.coverage_fraction),
                "peak_contrast": float(light.peak_contrast),
                "confidence": float(light.confidence),
                "image_x": float(light.image_x),
                "image_y": float(light.image_y),
            }
        )
    return entries


def _analysis_metrics(rr: _lpt2d.RenderResult) -> dict[str, Any]:
    image = rr.analysis.image
    debug = rr.analysis.debug
    lights = list(rr.analysis.lights)
    visible = [light for light in lights if bool(light.visible)]
    radii = [float(light.radius_ratio) for light in visible]
    confidences = [float(light.confidence) for light in lights]
    peak_contrasts = [float(light.peak_contrast) for light in lights]

    row: dict[str, Any] = {name: float(getattr(image, name)) for name in IMAGE_METRICS}
    row.update({name: float(getattr(debug, name)) for name in DEBUG_METRICS})
    row.update(
        {
            "light_count": len(lights),
            "visible_light_count": len(visible),
            "visible_light_fraction": len(visible) / len(lights) if lights else 0.0,
            "mean_visible_radius_ratio": sum(radii) / len(radii) if radii else 0.0,
            "max_radius_ratio": max(radii) if radii else 0.0,
            "mean_light_confidence": sum(confidences) / len(confidences) if confidences else 0.0,
            "max_peak_contrast": max(peak_contrasts) if peak_contrasts else 0.0,
            "lights_json": json.dumps(_light_entries(lights), separators=(",", ":")),
        }
    )
    return row


def _render_case(
    spec: SceneSpec,
    width: int,
    height: int,
    rays: int,
    *,
    batch: int,
    depth: int,
    save_path: Path | None,
) -> dict[str, Any]:
    shot = _make_shot(spec, width, height, rays, batch, depth)
    session = RenderSession(width, height, False)
    frame = Frame(scene=shot.scene, look=shot.look)
    cpp_shot = _resolve_frame_shot(shot, frame, None)
    try:
        rr = session.render_shot(cpp_shot, 0, True)
    finally:
        session.close()

    if save_path is not None:
        save_path.parent.mkdir(parents=True, exist_ok=True)
        save_image(str(save_path), rr.pixels, rr.width, rr.height)

    row: dict[str, Any] = {
        "scene": spec.name,
        "label": spec.label,
        "width": rr.width,
        "height": rr.height,
        "requested_rays": rays,
        "total_rays": rr.total_rays,
        "rays_per_pixel": rr.total_rays / float(rr.width * rr.height),
        "time_ms": rr.time_ms,
        "exposure": spec.exposure,
    }
    row.update(_analysis_metrics(rr))
    return row


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _read_csv(path: Path) -> list[dict[str, Any]]:
    with path.open(newline="") as fh:
        return list(csv.DictReader(fh))


def _finite_metric(row: dict[str, Any], metric: str) -> float | None:
    try:
        value = float(row[metric])
    except (KeyError, TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def _drift(metric: str, row: dict[str, Any], baseline: dict[str, Any], context: str) -> Drift | None:
    value = _finite_metric(row, metric)
    base = _finite_metric(baseline, metric)
    if value is None or base is None:
        return None
    abs_delta = abs(value - base)
    scale = max(abs(base), 1e-6)
    rel_delta = abs_delta / scale
    return Drift(metric, abs_delta, rel_delta, value, base, context)


def _worst_by_metric(drifts: Iterable[Drift], metrics: Iterable[str]) -> list[Drift]:
    worst: dict[str, Drift] = {}
    for drift in drifts:
        current = worst.get(drift.metric)
        if current is None or (drift.abs_delta, drift.rel_delta) > (current.abs_delta, current.rel_delta):
            worst[drift.metric] = drift
    return sorted(
        (worst[metric] for metric in metrics if metric in worst),
        key=lambda item: item.abs_delta,
        reverse=True,
    )


def _resolution_drifts(rows: list[dict[str, Any]], metrics: Iterable[str]) -> list[Drift]:
    by_key = {(row["scene"], row["requested_rays"], row["height"]): row for row in rows}
    scenes = sorted({str(row["scene"]) for row in rows})
    rays_values = sorted({int(row["requested_rays"]) for row in rows})
    max_height = max(int(row["height"]) for row in rows)
    drifts: list[Drift] = []

    for scene in scenes:
        for rays in rays_values:
            baseline = by_key.get((scene, rays, max_height))
            if baseline is None:
                continue
            for row in rows:
                if row["scene"] != scene or int(row["requested_rays"]) != rays:
                    continue
                height = int(row["height"])
                if height == max_height:
                    continue
                context = f"{scene}: {height}p vs {max_height}p at {_fmt_rays(rays)} rays"
                for metric in metrics:
                    drift = _drift(metric, row, baseline, context)
                    if drift is not None:
                        drifts.append(drift)
    return drifts


def _ray_drifts(rows: list[dict[str, Any]], metrics: Iterable[str]) -> list[Drift]:
    by_key = {(row["scene"], row["height"], row["requested_rays"]): row for row in rows}
    scenes = sorted({str(row["scene"]) for row in rows})
    heights = sorted({int(row["height"]) for row in rows})
    max_rays = max(int(row["requested_rays"]) for row in rows)
    drifts: list[Drift] = []

    for scene in scenes:
        for height in heights:
            baseline = by_key.get((scene, height, max_rays))
            if baseline is None:
                continue
            for row in rows:
                if row["scene"] != scene or int(row["height"]) != height:
                    continue
                rays = int(row["requested_rays"])
                if rays == max_rays:
                    continue
                context = f"{scene}: {_fmt_rays(rays)} vs {_fmt_rays(max_rays)} rays at {height}p"
                for metric in metrics:
                    drift = _drift(metric, row, baseline, context)
                    if drift is not None:
                        drifts.append(drift)
    return drifts


def _section(title: str, drifts: list[Drift], metrics: tuple[str, ...]) -> list[str]:
    lines = [
        f"### {title}",
        "",
        "| metric | worst abs drift | worst rel drift | observed | baseline | case |",
        "|---|---:|---:|---:|---:|---|",
    ]
    worst = _worst_by_metric(drifts, metrics)
    for item in worst:
        lines.append(
            "| "
            f"{item.metric} | "
            f"{_fmt_float(item.abs_delta)} | "
            f"{_fmt_float(item.rel_delta)}x | "
            f"{_fmt_float(item.value)} | "
            f"{_fmt_float(item.baseline)} | "
            f"{item.context} |"
        )
    if not worst:
        lines.append("| n/a | n/a | n/a | n/a | n/a | no comparable rows |")
    lines.append("")
    return lines


def _write_summary(path: Path, rows: list[dict[str, Any]], *, preset: str) -> None:
    heights = sorted({int(row["height"]) for row in rows})
    rays = sorted({int(row["requested_rays"]) for row in rows})
    scenes = sorted({str(row["scene"]) for row in rows})
    resolution_drifts = _resolution_drifts(rows, SCALAR_METRICS)
    ray_drifts = _ray_drifts(rows, SCALAR_METRICS)

    lines = [
        "# Metric Robustness Summary",
        "",
        f"- preset: `{preset}`",
        f"- scenes: {', '.join(scenes)}",
        f"- heights: {', '.join(f'{height}p' for height in heights)}",
        f"- ray counts: {', '.join(_fmt_rays(ray) for ray in rays)}",
        f"- rows: {len(rows)}",
        "",
        "Resolution drift compares each height to the highest rendered height at the same scene and ray count.",
        "Ray-count drift compares each ray count to the highest rendered ray count at the same scene and height.",
        "The CSV contains the raw rows so more specific comparisons can be made later.",
        "",
        "## Resolution Drift",
        "",
    ]
    lines.extend(_section("Public Image Metrics", resolution_drifts, IMAGE_METRICS))
    lines.extend(_section("Debug Scalars", resolution_drifts, DEBUG_METRICS))
    lines.extend(_section("Light Aggregates", resolution_drifts, LIGHT_METRICS))
    lines.extend(["## Ray-Count Drift", ""])
    lines.extend(_section("Public Image Metrics", ray_drifts, IMAGE_METRICS))
    lines.extend(_section("Debug Scalars", ray_drifts, DEBUG_METRICS))
    lines.extend(_section("Light Aggregates", ray_drifts, LIGHT_METRICS))
    path.write_text("\n".join(lines))


def _metric_label(metric: str) -> str:
    return metric.replace("_", " ")


def _svg_escape(text: object) -> str:
    return html.escape(str(text), quote=True)


def _nice_ticks(low: float, high: float, count: int = 5) -> list[float]:
    if not math.isfinite(low) or not math.isfinite(high):
        return [0.0, 1.0]
    if low == high:
        pad = max(abs(low) * 0.1, 0.01)
        low -= pad
        high += pad
    span = high - low
    raw_step = span / max(count - 1, 1)
    mag = 10.0 ** math.floor(math.log10(raw_step)) if raw_step > 0.0 else 1.0
    for step_mul in (1.0, 2.0, 5.0, 10.0):
        step = step_mul * mag
        if span / step <= count:
            break
    start = math.floor(low / step) * step
    end = math.ceil(high / step) * step
    ticks: list[float] = []
    value = start
    guard = 0
    while value <= end + step * 0.5 and guard < 32:
        ticks.append(0.0 if abs(value) < step * 1e-6 else value)
        value += step
        guard += 1
    return ticks


def _plot_range(values: list[float]) -> tuple[float, float]:
    finite = [value for value in values if math.isfinite(value)]
    if not finite:
        return 0.0, 1.0
    low = min(finite)
    high = max(finite)
    if low == high:
        pad = max(abs(low) * 0.1, 0.01)
        return low - pad, high + pad
    pad = (high - low) * 0.08
    low -= pad
    high += pad
    if low >= 0.0 and high <= 0.12:
        low = 0.0
    return low, high


def _line_plot_svg(
    *,
    title: str,
    x_values: list[float],
    x_labels: list[str],
    series: dict[str, list[float]],
    y_label: str,
    x_label: str,
) -> str:
    width = 980
    height = 560
    left = 82
    right = 180
    top = 58
    bottom = 86
    plot_w = width - left - right
    plot_h = height - top - bottom
    x_min = min(x_values)
    x_max = max(x_values)
    all_y = [value for values in series.values() for value in values]
    y_min, y_max = _plot_range(all_y)
    y_ticks = _nice_ticks(y_min, y_max)

    def sx(value: float) -> float:
        if x_max == x_min:
            return left + plot_w / 2.0
        return left + (value - x_min) * plot_w / (x_max - x_min)

    def sy(value: float) -> float:
        if y_max == y_min:
            return top + plot_h / 2.0
        return top + (y_max - value) * plot_h / (y_max - y_min)

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}">',
        "<style>",
        "text{font-family:Inter,Arial,sans-serif;fill:#20252b}",
        ".title{font-size:22px;font-weight:700}",
        ".axis{font-size:13px;fill:#3a4048}",
        ".tick{font-size:12px;fill:#5a626d}",
        ".grid{stroke:#d9dee5;stroke-width:1}",
        ".axis-line{stroke:#2d333b;stroke-width:1.4}",
        ".legend{font-size:13px}",
        "</style>",
        f'<rect width="{width}" height="{height}" fill="#ffffff"/>',
        f'<text class="title" x="{left}" y="34">{_svg_escape(title)}</text>',
    ]
    for tick in y_ticks:
        y = sy(tick)
        parts.append(f'<line class="grid" x1="{left}" y1="{y:.1f}" x2="{left + plot_w}" y2="{y:.1f}"/>')
        parts.append(f'<text class="tick" x="{left - 10}" y="{y + 4:.1f}" text-anchor="end">{_fmt_float(tick)}</text>')
    parts.append(f'<line class="axis-line" x1="{left}" y1="{top + plot_h}" x2="{left + plot_w}" y2="{top + plot_h}"/>')
    parts.append(f'<line class="axis-line" x1="{left}" y1="{top}" x2="{left}" y2="{top + plot_h}"/>')
    for value, label in zip(x_values, x_labels, strict=True):
        x = sx(value)
        parts.append(f'<line class="grid" x1="{x:.1f}" y1="{top}" x2="{x:.1f}" y2="{top + plot_h}"/>')
        parts.append(f'<text class="tick" x="{x:.1f}" y="{top + plot_h + 24}" text-anchor="middle">{_svg_escape(label)}</text>')
    parts.append(f'<text class="axis" x="{left + plot_w / 2:.1f}" y="{height - 20}" text-anchor="middle">{_svg_escape(x_label)}</text>')
    parts.append(
        f'<text class="axis" x="22" y="{top + plot_h / 2:.1f}" text-anchor="middle" '
        f'transform="rotate(-90 22 {top + plot_h / 2:.1f})">{_svg_escape(y_label)}</text>'
    )

    legend_x = left + plot_w + 30
    legend_y = top + 8
    for i, (name, values) in enumerate(series.items()):
        color = SCENE_COLORS.get(name, "#333333")
        points = [(sx(x), sy(y)) for x, y in zip(x_values, values, strict=True) if math.isfinite(y)]
        if points:
            path = " ".join(
                ("M" if idx == 0 else "L") + f"{x:.1f},{y:.1f}"
                for idx, (x, y) in enumerate(points)
            )
            parts.append(f'<path d="{path}" fill="none" stroke="{color}" stroke-width="2.5"/>')
            for x, y in points:
                parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4" fill="{color}"/>')
        y = legend_y + i * 24
        parts.append(f'<line x1="{legend_x}" y1="{y}" x2="{legend_x + 22}" y2="{y}" stroke="{color}" stroke-width="3"/>')
        parts.append(f'<text class="legend" x="{legend_x + 30}" y="{y + 4}">{_svg_escape(name)}</text>')
    parts.append("</svg>")
    return "\n".join(parts)


def _bar_plot_svg(*, title: str, items: list[tuple[str, float]], x_label: str) -> str:
    width = 980
    row_h = 28
    height = max(360, 120 + row_h * len(items))
    left = 250
    right = 110
    top = 58
    bottom = 64
    plot_w = width - left - right
    plot_h = height - top - bottom
    max_value = max((value for _, value in items), default=1.0)
    max_value = max(max_value, 1e-9)
    ticks = _nice_ticks(0.0, max_value, 5)
    ticks = [tick for tick in ticks if tick >= 0.0]

    def sx(value: float) -> float:
        return left + value * plot_w / max(ticks[-1], max_value)

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}">',
        "<style>",
        "text{font-family:Inter,Arial,sans-serif;fill:#20252b}",
        ".title{font-size:22px;font-weight:700}",
        ".axis{font-size:13px;fill:#3a4048}",
        ".tick{font-size:12px;fill:#5a626d}",
        ".grid{stroke:#d9dee5;stroke-width:1}",
        "</style>",
        f'<rect width="{width}" height="{height}" fill="#ffffff"/>',
        f'<text class="title" x="{left}" y="34">{_svg_escape(title)}</text>',
    ]
    for tick in ticks:
        x = sx(tick)
        parts.append(f'<line class="grid" x1="{x:.1f}" y1="{top}" x2="{x:.1f}" y2="{top + plot_h}"/>')
        parts.append(f'<text class="tick" x="{x:.1f}" y="{top + plot_h + 22}" text-anchor="middle">{_fmt_float(tick)}</text>')
    for i, (label, value) in enumerate(items):
        y = top + i * row_h + 5
        bar_w = max(1.0, sx(value) - left)
        parts.append(f'<text class="tick" x="{left - 12}" y="{y + 14}" text-anchor="end">{_svg_escape(_metric_label(label))}</text>')
        parts.append(f'<rect x="{left}" y="{y}" width="{bar_w:.1f}" height="18" fill="#287c8e"/>')
        parts.append(f'<text class="tick" x="{left + bar_w + 8:.1f}" y="{y + 14}">{_fmt_float(value)}</text>')
    parts.append(f'<text class="axis" x="{left + plot_w / 2:.1f}" y="{height - 18}" text-anchor="middle">{_svg_escape(x_label)}</text>')
    parts.append("</svg>")
    return "\n".join(parts)


def _rows_by_key(rows: list[dict[str, Any]]) -> dict[tuple[str, int, int], dict[str, Any]]:
    return {
        (str(row["scene"]), int(row["height"]), int(row["requested_rays"])): row
        for row in rows
    }


def _metric_series_by_scene(
    rows: list[dict[str, Any]],
    *,
    metric: str,
    heights: list[int],
    rays: list[int],
    fixed_height: int | None = None,
    fixed_rays: int | None = None,
) -> tuple[list[float], list[str], dict[str, list[float]]]:
    by_key = _rows_by_key(rows)
    scenes = sorted({str(row["scene"]) for row in rows})
    if fixed_height is not None:
        x_values = [math.log2(ray) for ray in rays]
        x_labels = [_fmt_rays(ray) for ray in rays]
        series = {
            scene: [
                value if (value := _finite_metric(by_key[(scene, fixed_height, ray)], metric)) is not None
                else float("nan")
                for ray in rays
            ]
            for scene in scenes
        }
        return x_values, x_labels, series
    if fixed_rays is not None:
        x_values = [float(height) for height in heights]
        x_labels = [f"{height}p" for height in heights]
        series = {
            scene: [
                value if (value := _finite_metric(by_key[(scene, height, fixed_rays)], metric)) is not None
                else float("nan")
                for height in heights
            ]
            for scene in scenes
        }
        return x_values, x_labels, series
    raise ValueError("expected either fixed_height or fixed_rays")


def _worst_ray_drift_items(
    rows: list[dict[str, Any]],
    *,
    compare_rays: int,
    baseline_rays: int,
    metrics: tuple[str, ...],
) -> list[tuple[str, float]]:
    by_key = _rows_by_key(rows)
    scenes = sorted({str(row["scene"]) for row in rows})
    heights = sorted({int(row["height"]) for row in rows})
    items: list[tuple[str, float]] = []
    for metric in metrics:
        worst = 0.0
        for scene in scenes:
            for height in heights:
                row = by_key.get((scene, height, compare_rays))
                base = by_key.get((scene, height, baseline_rays))
                if row is None or base is None:
                    continue
                value = _finite_metric(row, metric)
                baseline = _finite_metric(base, metric)
                if value is None or baseline is None:
                    continue
                worst = max(worst, abs(value - baseline))
        items.append((metric, worst))
    return sorted(items, key=lambda item: item[1], reverse=True)


def _worst_resolution_drift_items(
    rows: list[dict[str, Any]],
    *,
    baseline_height: int,
    fixed_rays: int,
    metrics: tuple[str, ...],
) -> list[tuple[str, float]]:
    by_key = _rows_by_key(rows)
    scenes = sorted({str(row["scene"]) for row in rows})
    heights = sorted({int(row["height"]) for row in rows if int(row["height"]) != baseline_height})
    items: list[tuple[str, float]] = []
    for metric in metrics:
        worst = 0.0
        for scene in scenes:
            base = by_key.get((scene, baseline_height, fixed_rays))
            if base is None:
                continue
            for height in heights:
                row = by_key.get((scene, height, fixed_rays))
                if row is None:
                    continue
                value = _finite_metric(row, metric)
                baseline = _finite_metric(base, metric)
                if value is None or baseline is None:
                    continue
                worst = max(worst, abs(value - baseline))
        items.append((metric, worst))
    return sorted(items, key=lambda item: item[1], reverse=True)


def _write_plot_index(
    run_dir: Path,
    plots: list[tuple[str, str, str]],
    *,
    max_height: int,
    max_rays: int,
    compare_rays: int | None,
) -> None:
    plot_dir = run_dir / "plots"
    lines = [
        "# Metric Robustness Plots",
        "",
        f"- ray convergence plots use `{max_height}p` and compare each ray count to the rendered value.",
        f"- resolution plots use `{_fmt_rays(max_rays)}` rays and compare heights from low to high.",
    ]
    if compare_rays is not None:
        lines.append(
            f"- drift bars show the worst absolute drift from `{_fmt_rays(compare_rays)}` to `{_fmt_rays(max_rays)}` over all scenes and heights."
        )
    lines.extend(
        [
            "",
            "## Quick Read",
            "",
            "- Brightness and clipping metrics are visually flat.",
            "- Local contrast is mostly resolution-stable but still relaxes downward as rays increase.",
            "- Saturation and colorfulness are the clearest noise-sensitive metrics in neutral/glass scenes.",
            "",
        ]
    )
    for filename, title, description in plots:
        lines.extend(
            [
                f"## {title}",
                "",
                description,
                "",
                f"![{title}](plots/{filename})",
                "",
            ]
        )
    (run_dir / "plots.md").write_text("\n".join(lines))

    html_lines = [
        "<!doctype html>",
        '<html lang="en">',
        "<head>",
        '<meta charset="utf-8">',
        "<title>Metric Robustness Plots</title>",
        "<style>",
        "body{font-family:Inter,Arial,sans-serif;margin:32px;color:#20252b;background:#fff}",
        "h1{margin-bottom:4px}",
        "section{margin:34px 0}",
        "img{max-width:100%;border:1px solid #d9dee5}",
        "p,li{max-width:900px;line-height:1.45}",
        "</style>",
        "</head>",
        "<body>",
        "<h1>Metric Robustness Plots</h1>",
        f"<p>Ray plots use {max_height}p. Resolution plots use {_fmt_rays(max_rays)} rays.</p>",
        "<ul>",
        "<li>Brightness and clipping metrics are visually flat.</li>",
        "<li>Local contrast is mostly resolution-stable, but still relaxes downward with more rays.</li>",
        "<li>Saturation and colorfulness are the most noise-sensitive metrics.</li>",
        "</ul>",
    ]
    for filename, title, description in plots:
        html_lines.extend(
            [
                "<section>",
                f"<h2>{_svg_escape(title)}</h2>",
                f"<p>{_svg_escape(description)}</p>",
                f'<img src="{_svg_escape(filename)}" alt="{_svg_escape(title)}">',
                "</section>",
            ]
        )
    html_lines.extend(["</body>", "</html>"])
    (plot_dir / "index.html").write_text("\n".join(html_lines))


def _write_plots(run_dir: Path, rows: list[dict[str, Any]]) -> None:
    plot_dir = run_dir / "plots"
    plot_dir.mkdir(parents=True, exist_ok=True)
    for stale in plot_dir.glob("*.svg"):
        stale.unlink()
    for stale_name in ("index.html",):
        stale_path = plot_dir / stale_name
        if stale_path.exists():
            stale_path.unlink()

    heights = sorted({int(row["height"]) for row in rows})
    rays = sorted({int(row["requested_rays"]) for row in rows})
    if not heights or not rays:
        return
    max_height = max(heights)
    max_rays = max(rays)
    compare_rays = 2**19 if 2**19 in rays else (rays[-2] if len(rays) > 1 else None)
    plots: list[tuple[str, str, str]] = []

    for metric in RAY_PLOT_METRICS:
        x_values, x_labels, series = _metric_series_by_scene(
            rows,
            metric=metric,
            heights=heights,
            rays=rays,
            fixed_height=max_height,
        )
        filename = f"ray_{metric}.svg"
        (plot_dir / filename).write_text(
            _line_plot_svg(
                title=f"{_metric_label(metric)} vs rays at {max_height}p",
                x_values=x_values,
                x_labels=x_labels,
                series=series,
                y_label=_metric_label(metric),
                x_label="requested rays",
            )
        )
        plots.append(
            (
                filename,
                f"{_metric_label(metric)} vs rays",
                f"Convergence at fixed {max_height}p. Flat lines indicate ray-count stability.",
            )
        )

    for metric in RESOLUTION_PLOT_METRICS:
        x_values, x_labels, series = _metric_series_by_scene(
            rows,
            metric=metric,
            heights=heights,
            rays=rays,
            fixed_rays=max_rays,
        )
        filename = f"resolution_{metric}.svg"
        (plot_dir / filename).write_text(
            _line_plot_svg(
                title=f"{_metric_label(metric)} vs resolution at {_fmt_rays(max_rays)} rays",
                x_values=x_values,
                x_labels=x_labels,
                series=series,
                y_label=_metric_label(metric),
                x_label="height",
            )
        )
        plots.append(
            (
                filename,
                f"{_metric_label(metric)} vs resolution",
                f"Resolution stability at fixed {_fmt_rays(max_rays)} rays.",
            )
        )

    if compare_rays is not None:
        ray_drift = _worst_ray_drift_items(
            rows,
            compare_rays=compare_rays,
            baseline_rays=max_rays,
            metrics=DRIFT_PLOT_METRICS,
        )
        filename = f"drift_{compare_rays}_vs_{max_rays}.svg"
        (plot_dir / filename).write_text(
            _bar_plot_svg(
                title=f"Worst absolute drift: {_fmt_rays(compare_rays)} vs {_fmt_rays(max_rays)}",
                items=ray_drift,
                x_label="absolute metric delta",
            )
        )
        plots.insert(
            0,
            (
                filename,
                f"{_fmt_rays(compare_rays)} vs {_fmt_rays(max_rays)} drift",
                "Worst absolute metric drift over every scene and resolution.",
            ),
        )

    resolution_drift = _worst_resolution_drift_items(
        rows,
        baseline_height=max_height,
        fixed_rays=max_rays,
        metrics=DRIFT_PLOT_METRICS,
    )
    filename = f"drift_resolution_at_{max_rays}.svg"
    (plot_dir / filename).write_text(
        _bar_plot_svg(
            title=f"Worst absolute resolution drift at {_fmt_rays(max_rays)} rays",
            items=resolution_drift,
            x_label="absolute metric delta",
        )
    )
    plots.insert(
        1,
        (
            filename,
            f"Resolution drift at {_fmt_rays(max_rays)}",
            f"Worst absolute drift from lower resolutions to {max_height}p at the final ray count.",
        ),
    )

    _write_plot_index(
        run_dir,
        plots,
        max_height=max_height,
        max_rays=max_rays,
        compare_rays=compare_rays,
    )


def _parse_ints(raw: str) -> tuple[int, ...]:
    values: list[int] = []
    for part in raw.split(","):
        item = part.strip().lower().replace("_", "")
        if not item:
            continue
        multiplier = 1
        if item.endswith("k"):
            multiplier = 1_000
            item = item[:-1]
        elif item.endswith("m"):
            multiplier = 1_000_000
            item = item[:-1]
        values.append(int(float(item) * multiplier))
    if not values:
        raise argparse.ArgumentTypeError("expected at least one integer")
    return tuple(values)


def _parse_heights(raw: str) -> tuple[int, ...]:
    values: list[int] = []
    for part in raw.split(","):
        item = part.strip().lower()
        if not item:
            continue
        if "x" in item:
            item = item.split("x", 1)[1]
        if item.endswith("p"):
            item = item[:-1]
        values.append(int(item))
    if not values:
        raise argparse.ArgumentTypeError("expected at least one height")
    return tuple(values)


def _parse_scene_names(raw: str) -> tuple[str, ...]:
    names = tuple(name.strip() for name in raw.split(",") if name.strip())
    unknown = [name for name in names if name not in SCENES]
    if unknown:
        raise argparse.ArgumentTypeError(
            f"unknown scene(s): {', '.join(unknown)}; choices: {', '.join(SCENES)}"
        )
    if not names:
        raise argparse.ArgumentTypeError("expected at least one scene")
    return names


def _default_scene_names(preset: str) -> tuple[str, ...]:
    if preset == "smoke":
        return ("single", "glass")
    return ("single", "color", "glass", "occlusion")


def _run_dir(base: Path, run_name: str | None) -> Path:
    name = run_name or time.strftime("%Y%m%d-%H%M%S")
    return base / name


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preset", choices=("smoke", "quick", "full"), default="quick")
    parser.add_argument("--out", type=Path, default=OUT, help="base output directory")
    parser.add_argument("--run-name", help="output subdirectory name; defaults to timestamp")
    parser.add_argument("--scenes", type=_parse_scene_names, help=f"comma list; choices: {', '.join(SCENES)}")
    parser.add_argument("--heights", type=_parse_heights, help="comma list like 240,360,480,720,1080")
    parser.add_argument("--rays", type=_parse_ints, help="comma list like 64k,128k,256k,1m")
    parser.add_argument("--batch", type=int, default=DEFAULT_BATCH)
    parser.add_argument("--depth", type=int, default=DEFAULT_DEPTH)
    parser.add_argument(
        "--plots-only",
        action="store_true",
        help="regenerate summary/plots from an existing metrics.csv without rendering",
    )
    parser.add_argument("--skip-plots", action="store_true", help="write CSV/summary but no plots")
    parser.add_argument(
        "--save-images",
        choices=("none", "baseline", "all"),
        default="baseline",
        help="save no PNGs, one highest-height/highest-ray PNG per scene, or every render",
    )
    args = parser.parse_args()

    scene_names = args.scenes or _default_scene_names(args.preset)
    heights = args.heights or HEIGHT_PRESETS[args.preset]
    ray_counts = args.rays or RAY_PRESETS[args.preset]
    max_height = max(heights)
    max_rays = max(ray_counts)
    run_dir = (
        args.out
        if args.plots_only and args.run_name is None and (args.out / "metrics.csv").exists()
        else _run_dir(args.out, args.run_name)
    )
    image_dir = run_dir / "images"
    rows: list[dict[str, Any]] = []

    if args.plots_only:
        rows = _read_csv(run_dir / "metrics.csv")
        _write_summary(run_dir / "summary.md", rows, preset=args.preset)
        if not args.skip_plots:
            _write_plots(run_dir, rows)
        print(f"wrote {run_dir / 'summary.md'}")
        if not args.skip_plots:
            print(f"wrote {run_dir / 'plots.md'}")
            print(f"wrote {run_dir / 'plots' / 'index.html'}")
        return

    run_dir.mkdir(parents=True, exist_ok=True)
    if image_dir.exists():
        for stale_image in image_dir.glob("*.png"):
            stale_image.unlink()
    config = {
        "preset": args.preset,
        "scenes": list(scene_names),
        "heights": list(heights),
        "ray_counts": list(ray_counts),
        "batch": args.batch,
        "depth": args.depth,
        "save_images": args.save_images,
    }
    (run_dir / "config.json").write_text(json.dumps(config, indent=2, sort_keys=True))

    total_cases = len(scene_names) * len(heights) * len(ray_counts)
    case_index = 0
    print(f"metric robustness -> {run_dir}")
    for scene_name in scene_names:
        spec = SCENES[scene_name]
        for height in heights:
            width = _width_for_height(height)
            for rays in ray_counts:
                case_index += 1
                print(
                    f"[{case_index:03d}/{total_cases:03d}] "
                    f"{scene_name:9s} {width}x{height} {_fmt_rays(rays):>5s} rays",
                    flush=True,
                )
                save_path = None
                if args.save_images == "all" or (
                    args.save_images == "baseline" and height == max_height and rays == max_rays
                ):
                    save_path = image_dir / f"{scene_name}_{height}p_{rays}.png"
                rows.append(
                    _render_case(
                        spec,
                        width,
                        height,
                        rays,
                        batch=args.batch,
                        depth=args.depth,
                        save_path=save_path,
                    )
                )

    _write_csv(run_dir / "metrics.csv", rows)
    _write_summary(run_dir / "summary.md", rows, preset=args.preset)
    if not args.skip_plots:
        _write_plots(run_dir, rows)
    print(f"wrote {run_dir / 'metrics.csv'}")
    print(f"wrote {run_dir / 'summary.md'}")
    if not args.skip_plots:
        print(f"wrote {run_dir / 'plots.md'}")
        print(f"wrote {run_dir / 'plots' / 'index.html'}")


if __name__ == "__main__":
    main()
