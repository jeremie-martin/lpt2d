"""Shared helpers for clean-room example animations.

This module is example-layer only. It must not modify core anim package behavior.
"""

from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Callable, Iterable

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from anim import (
    Arc,
    BeamLight,
    Bezier,
    Camera2D,
    Canvas,
    Circle,
    Frame,
    FrameContext,
    Group,
    Look,
    PointLight,
    Scene,
    Segment,
    SegmentLight,
    Shot,
    Timeline,
    TraceDefaults,
    Transform2D,
    beam_splitter,
    glass,
    mirror,
    mirror_box,
    render,
    render_contact_sheet,
)
from anim.renderer import Renderer

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTDIR = REPO_ROOT / "renders" / "clean_room"
BINARY = str(REPO_ROOT / "build" / "lpt2d-cli")

ROOM_HALF_W = 1.78
ROOM_HALF_H = 1.0
ROOM_CAMERA = Camera2D(bounds=[-ROOM_HALF_W, -ROOM_HALF_H, ROOM_HALF_W, ROOM_HALF_H])

BASE_LOOK = Look(
    exposure=3.2,
    contrast=1.0,
    gamma=2.2,
    tonemap="reinhardx",
    white_point=0.5,
    normalize="rays",
)

ROOM_MIRROR = mirror(0.95, roughness=0.1)
FACET_MIRROR = mirror(0.92, roughness=0.04)
SOFT_MIRROR = mirror(0.9, roughness=0.12)
SPLITTER = beam_splitter(0.45, roughness=0.02)

BEAM_INTENSITY_SCALE = 0.32
FILL_INTENSITY_SCALE = 0.28

GLASS_SOFT = glass(1.42, cauchy_b=9_000, absorption=0.08)
GLASS_MEDIUM = glass(1.54, cauchy_b=18_000, absorption=0.14)
GLASS_BOLD = glass(1.68, cauchy_b=28_000, absorption=0.2)
GLASS_FOCUS = glass(1.8, cauchy_b=24_000, absorption=0.16)

LUM_WEIGHTS = np.array([218, 732, 74], dtype=np.uint32)


@dataclass(frozen=True)
class RenderMode:
    name: str
    canvas: Canvas
    trace: TraceDefaults
    fps: int
    sheet_count: int = 6
    sheet_cols: int = 3


@dataclass(frozen=True)
class SceneSpec:
    name: str
    duration: float
    build: Callable[[FrameContext], Frame]
    base_exposure: float
    description: str
    family: str = ""
    ambient: float = 0.0
    white_point: float = 0.5
    hq_duration: float | None = None
    hq_rays: int | None = None


@dataclass(frozen=True)
class CandidateSummary:
    exposure: float
    mean: float
    p95: float
    lit_pct: float
    lit_mean: float
    lit_p90: float
    lit_p97: float
    clipped_pct: float
    score: float

    def to_dict(self) -> dict[str, float]:
        return {
            "exposure": self.exposure,
            "mean": self.mean,
            "p95": self.p95,
            "lit_pct": self.lit_pct,
            "lit_mean": self.lit_mean,
            "lit_p90": self.lit_p90,
            "lit_p97": self.lit_p97,
            "clipped_pct": self.clipped_pct,
            "score": self.score,
        }


@dataclass(frozen=True)
class BoundsAudit:
    fits_room: bool
    max_overrun: float
    bounds: tuple[float, float, float, float]


ANALYSIS_MODE = RenderMode(
    name="analysis",
    canvas=Canvas(320, 180),
    trace=TraceDefaults(rays=140_000, batch=70_000, depth=10),
    fps=12,
)
SHEET_MODE = RenderMode(
    name="sheet",
    canvas=Canvas(240, 135),
    trace=TraceDefaults(rays=180_000, batch=90_000, depth=12),
    fps=14,
    sheet_count=6,
    sheet_cols=3,
)
PREVIEW_MODE = RenderMode(
    name="preview",
    canvas=Canvas(576, 324),
    trace=TraceDefaults(rays=260_000, batch=120_000, depth=12),
    fps=16,
)
HQ_MODE = RenderMode(
    name="hq",
    canvas=Canvas(960, 540),
    trace=TraceDefaults(rays=1_600_000, batch=200_000, depth=14),
    fps=30,
)


def tau(progress: float) -> float:
    return math.tau * progress


def polar(radius: float, angle: float) -> tuple[float, float]:
    return (radius * math.cos(angle), radius * math.sin(angle))


def angle_between(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.atan2(b[1] - a[1], b[0] - a[0])


def room_group() -> Group:
    return Group(name="room", shapes=mirror_box(ROOM_HALF_W, ROOM_HALF_H, ROOM_MIRROR))


def beam_group(
    name: str,
    origin: tuple[float, float],
    angle: float,
    *,
    intensity: float,
    width: float,
    wavelength_min: float = 380.0,
    wavelength_max: float = 780.0,
) -> Group:
    return Group(
        name=name,
        lights=[
            BeamLight(
                origin=[origin[0], origin[1]],
                direction=[math.cos(angle), math.sin(angle)],
                angular_width=width,
                intensity=intensity * BEAM_INTENSITY_SCALE,
                wavelength_min=wavelength_min,
                wavelength_max=wavelength_max,
            )
        ],
    )


def fill_group(
    name: str,
    y: float,
    *,
    intensity: float,
    width: float = 1.4,
    tilt: float = 0.0,
    wavelength_min: float = 430.0,
    wavelength_max: float = 700.0,
) -> Group:
    half_w = width * 0.5
    dy = math.tan(tilt) * half_w
    return Group(
        name=name,
        lights=[
            SegmentLight(
                a=[-half_w, y - dy],
                b=[half_w, y + dy],
                intensity=intensity * FILL_INTENSITY_SCALE,
                wavelength_min=wavelength_min,
                wavelength_max=wavelength_max,
            )
        ],
    )


def slat(height: float, material) -> list[Segment]:
    return [Segment(a=[0.0, -height * 0.5], b=[0.0, height * 0.5], material=material)]


def blade(length: float, material) -> list[Segment]:
    return [Segment(a=[0.0, 0.0], b=[-length, 0.0], material=material)]


def frame_for(groups: list[Group], camera: Camera2D | None = None) -> Frame:
    return Frame(scene=Scene(groups=groups), camera=camera or ROOM_CAMERA)


def with_family(spec: SceneSpec, family: str) -> SceneSpec:
    return replace(spec, family=family)


def look_for(spec: SceneSpec, exposure: float) -> Look:
    return replace(
        BASE_LOOK,
        exposure=exposure,
        ambient=spec.ambient,
        white_point=spec.white_point,
    )


def shot_for(mode: RenderMode, exposure: float, spec: SceneSpec) -> Shot:
    return Shot(canvas=mode.canvas, look=look_for(spec, exposure), trace=mode.trace)


def animate_for(spec: SceneSpec, exposure: float) -> Callable[[FrameContext], Frame]:
    def animate(ctx: FrameContext) -> Frame:
        frame = spec.build(ctx)
        return Frame(
            scene=frame.scene,
            camera=frame.camera or ROOM_CAMERA,
            look=look_for(spec, exposure),
            trace=frame.trace,
        )

    return animate


def wire_json_for(frame: Frame, session_camera: Camera2D | None, aspect: float) -> str:
    payload = frame.scene.to_dict()
    payload["version"] = 4
    render_block: dict[str, object] = {}

    camera = frame.camera if frame.camera is not None else session_camera
    if camera is not None:
        bounds = camera.resolve(aspect)
        if bounds is not None:
            render_block["bounds"] = bounds

    if frame.look is not None:
        render_block.update(frame.look.to_dict())
    if frame.trace is not None:
        render_block.update(frame.trace.to_dict())

    if render_block:
        payload["render"] = render_block
    return json.dumps(payload, separators=(",", ":"))


def frame_metrics(rgb: bytes, width: int, height: int) -> dict[str, float]:
    arr = np.frombuffer(rgb, dtype=np.uint8).reshape(width * height, 3)
    lum = (arr.astype(np.uint32) @ LUM_WEIGHTS >> 10).astype(np.uint8)
    lit = lum[lum > 6]
    clipped = float(np.count_nonzero((arr == 255).any(axis=1)) / arr.shape[0])

    if lit.size == 0:
        lit_mean = 0.0
        lit_p90 = 0.0
        lit_p97 = 0.0
        lit_pct = 0.0
    else:
        lit_mean = float(np.mean(lit))
        lit_p90 = float(np.percentile(lit, 90))
        lit_p97 = float(np.percentile(lit, 97))
        lit_pct = float(lit.size / lum.size)

    return {
        "mean": float(np.mean(lum)),
        "p95": float(np.percentile(lum, 95)),
        "lit_pct": lit_pct,
        "lit_mean": lit_mean,
        "lit_p90": lit_p90,
        "lit_p97": lit_p97,
        "clipped_pct": clipped,
    }


def score_metrics(metrics: dict[str, float]) -> float:
    if metrics["lit_pct"] == 0.0:
        return 1_000.0

    score = 0.0
    score += abs(metrics["lit_p90"] - 178.0) / 56.0
    score += abs(metrics["lit_mean"] - 98.0) / 66.0
    score += max(0.0, 115.0 - metrics["lit_p90"]) / 32.0
    score += max(0.0, metrics["lit_p97"] - 244.0) / 18.0
    score += max(0.0, metrics["clipped_pct"] - 0.004) * 360.0
    score += max(0.0, 0.005 - metrics["lit_pct"]) * 70.0
    score += max(0.0, metrics["mean"] - 105.0) / 18.0
    score += max(0.0, metrics["p95"] - 215.0) / 14.0
    return score


def summarize_candidates(samples: list[dict[str, float]], exposure: float) -> CandidateSummary:
    summary = {
        "mean": sum(s["mean"] for s in samples) / len(samples),
        "p95": sum(s["p95"] for s in samples) / len(samples),
        "lit_pct": sum(s["lit_pct"] for s in samples) / len(samples),
        "lit_mean": sum(s["lit_mean"] for s in samples) / len(samples),
        "lit_p90": sum(s["lit_p90"] for s in samples) / len(samples),
        "lit_p97": sum(s["lit_p97"] for s in samples) / len(samples),
        "clipped_pct": sum(s["clipped_pct"] for s in samples) / len(samples),
    }
    return CandidateSummary(exposure=exposure, score=score_metrics(summary), **summary)


def evaluate_exposure(spec: SceneSpec, exposure: float, mode: RenderMode) -> CandidateSummary:
    shot = shot_for(mode, exposure, spec)
    timeline = Timeline(spec.duration, fps=mode.fps)
    animate = animate_for(spec, exposure)
    sample_frames = sorted(
        {0, timeline.total_frames // 3, (2 * timeline.total_frames) // 3, timeline.total_frames - 1}
    )

    renderer = Renderer(shot, binary=BINARY)
    metrics: list[dict[str, float]] = []
    try:
        for frame_index in sample_frames:
            ctx = timeline.context_at(frame_index)
            frame = animate(ctx)
            wire = wire_json_for(frame, ROOM_CAMERA, shot.canvas.aspect)
            rgb = renderer.render_frame(wire)
            metrics.append(frame_metrics(rgb, shot.canvas.width, shot.canvas.height))
    finally:
        renderer.close()

    return summarize_candidates(metrics, exposure)


def tune_exposure(
    spec: SceneSpec,
    mode: RenderMode = ANALYSIS_MODE,
) -> tuple[float, list[CandidateSummary]]:
    coarse = [
        spec.base_exposure - 0.5,
        spec.base_exposure - 0.2,
        spec.base_exposure,
        spec.base_exposure + 0.2,
    ]
    coarse_summaries = [evaluate_exposure(spec, exposure, mode) for exposure in coarse]
    best = min(coarse_summaries, key=lambda candidate: candidate.score)

    refine = sorted(
        {
            round(best.exposure - 0.12, 3),
            round(best.exposure, 3),
            round(best.exposure + 0.12, 3),
        }
    )
    refine_summaries = [evaluate_exposure(spec, exposure, mode) for exposure in refine]

    all_summaries = {round(candidate.exposure, 3): candidate for candidate in coarse_summaries}
    for candidate in refine_summaries:
        all_summaries[round(candidate.exposure, 3)] = candidate
    ranked = sorted(all_summaries.values(), key=lambda candidate: candidate.score)
    return ranked[0].exposure, ranked


def _normalize_angle(angle: float) -> float:
    angle = math.fmod(angle, math.tau)
    if angle < 0.0:
        angle += math.tau
    return angle


def _angle_in_sweep(angle: float, start: float, sweep: float) -> bool:
    if sweep >= math.tau - 1e-6:
        return True
    rel = _normalize_angle(angle - start)
    return rel <= sweep + 1e-6


def _apply_transform(point: tuple[float, float], transform: Transform2D) -> tuple[float, float]:
    sx, sy = transform.scale
    x = point[0] * sx
    y = point[1] * sy
    c = math.cos(transform.rotate)
    s = math.sin(transform.rotate)
    xr = x * c - y * s
    yr = x * s + y * c
    return (xr + transform.translate[0], yr + transform.translate[1])


def _radius_scale(transform: Transform2D) -> float:
    sx, sy = transform.scale
    return math.sqrt(abs(sx * sy))


def _accumulate_bounds(
    bounds: list[float],
    *,
    x: float,
    y: float,
    radius: float = 0.0,
) -> None:
    bounds[0] = min(bounds[0], x - radius)
    bounds[1] = min(bounds[1], y - radius)
    bounds[2] = max(bounds[2], x + radius)
    bounds[3] = max(bounds[3], y + radius)


def _scene_bounds(scene: Scene) -> tuple[float, float, float, float]:
    bounds = [float("inf"), float("inf"), float("-inf"), float("-inf")]
    groups = list(scene.groups)
    if scene.shapes or scene.lights:
        groups.append(Group(name="root", shapes=scene.shapes, lights=scene.lights))

    for group in groups:
        transform = group.transform
        scale = _radius_scale(transform)
        for shape in group.shapes:
            if isinstance(shape, Circle):
                x, y = _apply_transform((shape.center[0], shape.center[1]), transform)
                _accumulate_bounds(bounds, x=x, y=y, radius=shape.radius * scale)
            elif isinstance(shape, Segment):
                for point in ((shape.a[0], shape.a[1]), (shape.b[0], shape.b[1])):
                    x, y = _apply_transform(point, transform)
                    _accumulate_bounds(bounds, x=x, y=y)
            elif isinstance(shape, Bezier):
                for point in (
                    (shape.p0[0], shape.p0[1]),
                    (shape.p1[0], shape.p1[1]),
                    (shape.p2[0], shape.p2[1]),
                ):
                    x, y = _apply_transform(point, transform)
                    _accumulate_bounds(bounds, x=x, y=y)
            elif isinstance(shape, Arc):
                x, y = _apply_transform((shape.center[0], shape.center[1]), transform)
                radius = shape.radius * scale
                start = _normalize_angle(shape.angle_start + transform.rotate)
                sweep = shape.sweep
                candidate_angles = [start, start + sweep]
                for angle in (0.0, 0.5 * math.pi, math.pi, 1.5 * math.pi):
                    if _angle_in_sweep(angle, start, sweep):
                        candidate_angles.append(angle)
                for angle in candidate_angles:
                    _accumulate_bounds(
                        bounds,
                        x=x + radius * math.cos(angle),
                        y=y + radius * math.sin(angle),
                    )

        for light in group.lights:
            if isinstance(light, BeamLight):
                x, y = _apply_transform((light.origin[0], light.origin[1]), transform)
                _accumulate_bounds(bounds, x=x, y=y)
            elif isinstance(light, SegmentLight):
                for point in ((light.a[0], light.a[1]), (light.b[0], light.b[1])):
                    x, y = _apply_transform(point, transform)
                    _accumulate_bounds(bounds, x=x, y=y)
            elif isinstance(light, PointLight):
                x, y = _apply_transform((light.pos[0], light.pos[1]), transform)
                _accumulate_bounds(bounds, x=x, y=y)

    if math.isinf(bounds[0]):
        return (0.0, 0.0, 0.0, 0.0)
    return (bounds[0], bounds[1], bounds[2], bounds[3])


def audit_room_bounds(
    spec: SceneSpec,
    *,
    duration: float | None = None,
    samples: int = 12,
) -> BoundsAudit:
    timeline = Timeline(duration or spec.duration, fps=samples)
    max_overrun = 0.0
    merged = [float("inf"), float("inf"), float("-inf"), float("-inf")]

    for frame_index in range(timeline.total_frames):
        bounds = _scene_bounds(spec.build(timeline.context_at(frame_index)).scene)
        merged[0] = min(merged[0], bounds[0])
        merged[1] = min(merged[1], bounds[1])
        merged[2] = max(merged[2], bounds[2])
        merged[3] = max(merged[3], bounds[3])
        max_overrun = max(
            max_overrun,
            max(0.0, -ROOM_HALF_W - bounds[0]),
            max(0.0, bounds[2] - ROOM_HALF_W),
            max(0.0, -ROOM_HALF_H - bounds[1]),
            max(0.0, bounds[3] - ROOM_HALF_H),
        )

    return BoundsAudit(
        fits_room=max_overrun <= 1e-6,
        max_overrun=max_overrun,
        bounds=(merged[0], merged[1], merged[2], merged[3]),
    )


def scene_dir(root: Path, spec: SceneSpec) -> Path:
    if spec.family:
        return root / spec.family / spec.name
    return root / spec.name


def ensure_scene_dir(root: Path, spec: SceneSpec) -> Path:
    directory = scene_dir(root, spec)
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def mode_filename(mode: RenderMode) -> str:
    if mode.name.startswith("hq"):
        return "hq.mp4"
    return "preview.mp4"


def write_tuning_report(
    spec: SceneSpec,
    exposure: float,
    summaries: list[CandidateSummary],
    directory: Path,
) -> Path:
    payload = {
        "name": spec.name,
        "description": spec.description,
        "base_exposure": spec.base_exposure,
        "tuned_exposure": exposure,
        "ambient": spec.ambient,
        "white_point": spec.white_point,
        "candidates": [candidate.to_dict() for candidate in summaries],
    }
    path = directory / "tuning.json"
    with path.open("w") as handle:
        json.dump(payload, handle, indent=2)
        handle.write("\n")
    return path


def export_frame_json(
    spec: SceneSpec,
    exposure: float,
    directory: Path,
    *,
    mode: RenderMode,
    frame_index: int = 0,
    duration: float | None = None,
) -> Path:
    timeline = Timeline(duration or spec.duration, fps=mode.fps)
    ctx = timeline.context_at(frame_index)
    frame = animate_for(spec, exposure)(ctx)
    shot = Shot(
        name=spec.name,
        scene=frame.scene,
        camera=frame.camera or ROOM_CAMERA,
        canvas=mode.canvas,
        look=look_for(spec, exposure),
        trace=mode.trace,
    )
    path = directory / f"frame_{frame_index:03d}.json"
    shot.save(path)
    return path


def render_sheet(spec: SceneSpec, exposure: float, directory: Path, mode: RenderMode = SHEET_MODE) -> Path:
    animate = animate_for(spec, exposure)
    output = directory / "sheet.png"
    render_contact_sheet(
        animate,
        Timeline(spec.duration, fps=mode.fps),
        str(output),
        cols=mode.sheet_cols,
        count=mode.sheet_count,
        settings=shot_for(mode, exposure, spec),
        camera=ROOM_CAMERA,
        binary=BINARY,
    )
    return output


def render_video(spec: SceneSpec, exposure: float, directory: Path, mode: RenderMode) -> Path:
    animate = animate_for(spec, exposure)
    output = directory / mode_filename(mode)
    render(
        animate,
        Timeline(spec.duration, fps=mode.fps),
        str(output),
        settings=shot_for(mode, exposure, spec),
        camera=ROOM_CAMERA,
        binary=BINARY,
        crf=20 if mode.name.startswith("preview") else 18,
    )
    return output


def _overview_tile(source: Path, label: str) -> Image.Image:
    font = ImageFont.load_default()
    label_height = 18
    tile = Image.open(source).convert("RGB")
    framed = Image.new("RGB", (tile.width, tile.height + label_height), (8, 8, 8))
    framed.paste(tile, (0, label_height))
    draw = ImageDraw.Draw(framed)
    draw.text((6, 3), label, fill=(235, 235, 235), font=font)
    return framed


def _overview_chunk(
    tiles: list[Image.Image],
    *,
    cols: int,
) -> Image.Image:
    rows = math.ceil(len(tiles) / cols)
    cell_w = max(tile.width for tile in tiles)
    cell_h = max(tile.height for tile in tiles)
    overview = Image.new("RGB", (cols * cell_w, rows * cell_h), (12, 12, 12))

    for index, tile in enumerate(tiles):
        x = (index % cols) * cell_w
        y = (index // cols) * cell_h
        overview.paste(tile, (x, y))
    return overview


def assemble_overview_pages(
    specs: Iterable[SceneSpec],
    root: Path,
    *,
    subdir: str = "overview_pages",
    stem: str = "overview",
    page_size: int = 32,
    cols: int = 2,
) -> list[Path]:
    spec_list = list(specs)
    if not spec_list:
        return []

    target_dir = root / subdir
    target_dir.mkdir(parents=True, exist_ok=True)
    pages: list[Path] = []
    for page_index in range(0, len(spec_list), page_size):
        chunk = spec_list[page_index : page_index + page_size]
        tiles = [
            _overview_tile(scene_dir(root, spec) / "sheet.png", spec.name.replace("_", " "))
            for spec in chunk
        ]
        overview = _overview_chunk(tiles, cols=cols)
        target = target_dir / f"{stem}_{page_index // page_size + 1:02d}.png"
        overview.save(target)
        pages.append(target)

    if pages and subdir == "overview_pages":
        first_page = Image.open(pages[0]).convert("RGB")
        first_page.save(root / "overview_sheet.png")
    return pages


def assemble_family_overviews(specs: Iterable[SceneSpec], root: Path) -> dict[str, list[Path]]:
    grouped: dict[str, list[SceneSpec]] = defaultdict(list)
    for spec in specs:
        grouped[spec.family or "misc"].append(spec)

    pages_by_family: dict[str, list[Path]] = {}
    for family, family_specs in sorted(grouped.items()):
        pages_by_family[family] = assemble_overview_pages(
            family_specs,
            root,
            subdir=f"{family}/overview_pages",
            stem=f"{family}_overview",
            page_size=24,
            cols=2,
        )
    return pages_by_family


def _relative_to_root(root: Path, path: Path) -> str:
    return str(path.relative_to(root))


def write_manifest(
    specs: Iterable[SceneSpec],
    root: Path,
    *,
    overview_pages: Iterable[Path] = (),
    family_overviews: dict[str, list[Path]] | None = None,
) -> Path:
    spec_list = list(specs)
    grouped: dict[str, list[str]] = defaultdict(list)
    scenes_payload: list[dict[str, object]] = []

    for spec in spec_list:
        directory = scene_dir(root, spec)
        if not directory.exists():
            assets: list[str] = []
        else:
            assets = sorted(path.name for path in directory.iterdir() if path.is_file())
        audit = audit_room_bounds(spec, duration=spec.duration)
        grouped[spec.family or "misc"].append(spec.name)
        scenes_payload.append(
            {
                "name": spec.name,
                "family": spec.family or "misc",
                "description": spec.description,
                "directory": _relative_to_root(root, directory),
                "assets": assets,
                "room_fit": audit.fits_room,
                "max_overrun": audit.max_overrun,
            }
        )

    payload = {
        "canonical_root": _relative_to_root(REPO_ROOT, root),
        "overview": "overview_sheet.png",
        "overview_pages": sorted(_relative_to_root(root, path) for path in overview_pages),
        "scene_count": len(spec_list),
        "family_count": len(grouped),
        "families": [
            {
                "name": family,
                "scene_count": len(names),
                "overview_pages": sorted(
                    _relative_to_root(root, path)
                    for path in (family_overviews or {}).get(family, [])
                ),
            }
            for family, names in sorted(grouped.items())
        ],
        "scenes": scenes_payload,
    }
    target = root / "manifest.json"
    with target.open("w") as handle:
        json.dump(payload, handle, indent=2)
        handle.write("\n")
    return target


def _build_scene_parser(description: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--sheet", action="store_true", help="render a contact sheet instead of video")
    parser.add_argument("--hq", action="store_true", help="render the HQ video variant")
    parser.add_argument("--duration", type=float, help="override duration in seconds")
    parser.add_argument("--rays", type=int, help="override ray count")
    parser.add_argument("--batch", type=int, help="override batch size")
    parser.add_argument("--depth", type=int, help="override max depth")
    parser.add_argument("--fps", type=int, help="override fps")
    parser.add_argument("--width", type=int, help="override render width")
    parser.add_argument("--height", type=int, help="override render height")
    parser.add_argument("--exposure", type=float, help="explicit exposure override")
    parser.add_argument("--skip-tune", action="store_true", help="skip exposure tuning")
    parser.add_argument("--export-json", action="store_true", help="export a representative frame JSON")
    parser.add_argument("--frame", type=int, default=0, help="frame index for JSON export")
    parser.add_argument("--no-render", action="store_true", help="skip image/video rendering")
    parser.add_argument("--outdir", type=Path, default=DEFAULT_OUTDIR, help="output root")
    return parser


def _build_gallery_parser(description: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--list", action="store_true", help="list scene names and exit")
    parser.add_argument(
        "--name",
        action="append",
        dest="names",
        help="render only the named scene (repeatable); defaults to all scenes",
    )
    parser.add_argument(
        "--family",
        action="append",
        dest="families",
        help="render only the named family (repeatable)",
    )
    parser.add_argument(
        "--match",
        action="append",
        dest="matches",
        help="render only scenes whose name contains the substring",
    )
    parser.add_argument("--video", action="store_true", help="render videos instead of sheets")
    parser.add_argument("--hq", action="store_true", help="use HQ video mode")
    parser.add_argument("--duration", type=float, help="override duration in seconds")
    parser.add_argument("--rays", type=int, help="override ray count")
    parser.add_argument("--batch", type=int, help="override batch size")
    parser.add_argument("--depth", type=int, help="override max depth")
    parser.add_argument("--fps", type=int, help="override fps")
    parser.add_argument("--width", type=int, help="override render width")
    parser.add_argument("--height", type=int, help="override render height")
    parser.add_argument("--exposure", type=float, help="explicit exposure override")
    parser.add_argument("--skip-tune", action="store_true", help="skip exposure tuning")
    parser.add_argument("--export-json", action="store_true", help="export representative frame JSONs")
    parser.add_argument("--frame", type=int, default=0, help="frame index for JSON export")
    parser.add_argument("--no-render", action="store_true", help="skip image/video rendering")
    parser.add_argument("--no-overview", action="store_true", help="skip overview image")
    parser.add_argument("--outdir", type=Path, default=DEFAULT_OUTDIR, help="output root")
    return parser


def resolve_mode(spec: SceneSpec, args: argparse.Namespace, *, gallery: bool = False) -> RenderMode:
    if gallery and not args.video:
        base = SHEET_MODE
    else:
        base = HQ_MODE if args.hq else PREVIEW_MODE

    rays = args.rays
    if rays is None and args.hq and spec.hq_rays is not None:
        rays = spec.hq_rays
    if rays is None:
        rays = base.trace.rays

    width = args.width or base.canvas.width
    height = args.height or base.canvas.height
    if base.name != "sheet":
        if width % 2 != 0:
            width += 1
        if height % 2 != 0:
            height += 1

    canvas = Canvas(width, height)
    trace = TraceDefaults(
        rays=rays,
        batch=args.batch or base.trace.batch,
        depth=args.depth or base.trace.depth,
        intensity=base.trace.intensity,
    )
    return RenderMode(
        name=base.name,
        canvas=canvas,
        trace=trace,
        fps=args.fps or base.fps,
        sheet_count=base.sheet_count,
        sheet_cols=base.sheet_cols,
    )


def resolve_duration(spec: SceneSpec, args: argparse.Namespace) -> float:
    if args.duration is not None:
        return args.duration
    if args.hq and spec.hq_duration is not None:
        return spec.hq_duration
    return spec.duration


def _with_duration(spec: SceneSpec, duration: float) -> SceneSpec:
    return replace(spec, duration=duration)


def _resolve_exposure(spec: SceneSpec, args: argparse.Namespace) -> tuple[float, list[CandidateSummary]]:
    if args.exposure is not None:
        return args.exposure, []
    if args.skip_tune:
        return spec.base_exposure, []
    return tune_exposure(spec)


def process_scene(
    spec: SceneSpec,
    args: argparse.Namespace,
    *,
    gallery: bool = False,
) -> tuple[SceneSpec, RenderMode, float, BoundsAudit, Path]:
    spec = _with_duration(spec, resolve_duration(spec, args))
    directory = ensure_scene_dir(args.outdir, spec)
    mode = resolve_mode(spec, args, gallery=gallery)
    exposure, summaries = _resolve_exposure(spec, args)
    if summaries:
        best = min(summaries, key=lambda candidate: candidate.score)
        print(
            f"{spec.name:24} exposure {spec.base_exposure:.2f} -> {best.exposure:.2f} "
            f"(lit_p90={best.lit_p90:.1f}, clipped={best.clipped_pct:.2%})"
        )
        write_tuning_report(spec, exposure, summaries, directory)
    audit = audit_room_bounds(spec, duration=spec.duration)
    print(
        f"{spec.name:24} room_fit={audit.fits_room} "
        f"max_overrun={audit.max_overrun:.4f} "
        f"bounds=({audit.bounds[0]:.3f}, {audit.bounds[1]:.3f}, "
        f"{audit.bounds[2]:.3f}, {audit.bounds[3]:.3f})"
    )
    if args.export_json:
        path = export_frame_json(spec, exposure, directory, mode=mode, frame_index=args.frame, duration=spec.duration)
        print(f"json    {path}")
    if not args.no_render:
        if gallery:
            if args.video:
                path = render_video(spec, exposure, directory, mode=mode)
                print(f"video   {path}")
            else:
                path = render_sheet(spec, exposure, directory, mode=SHEET_MODE if mode.name != "sheet" else mode)
                print(f"sheet   {path}")
        elif args.sheet:
            path = render_sheet(spec, exposure, directory, mode=SHEET_MODE)
            print(f"sheet   {path}")
        else:
            path = render_video(spec, exposure, directory, mode=mode)
            print(f"video   {path}")
    return spec, mode, exposure, audit, directory


def run_scene_cli(spec: SceneSpec, description: str) -> None:
    args = _build_scene_parser(description).parse_args()
    process_scene(spec, args, gallery=False)


def run_gallery_cli(specs: list[SceneSpec], description: str) -> None:
    parser = _build_gallery_parser(description)
    args = parser.parse_args()
    if args.list:
        for spec in specs:
            family = spec.family or "misc"
            print(f"{spec.name:24} {family:12} {spec.description}")
        return

    selected = list(specs)
    if args.names:
        wanted_names = set(args.names)
        selected = [spec for spec in selected if spec.name in wanted_names]
    if args.families:
        wanted_families = set(args.families)
        selected = [spec for spec in selected if (spec.family or "misc") in wanted_families]
    if args.matches:
        lowered = [pattern.lower() for pattern in args.matches]
        selected = [
            spec for spec in selected if any(pattern in spec.name.lower() for pattern in lowered)
        ]

    missing = sorted(set(args.names or []) - {spec.name for spec in specs})
    if missing:
        raise SystemExit(f"unknown scene(s): {', '.join(missing)}")
    missing_families = sorted(set(args.families or []) - {(spec.family or "misc") for spec in specs})
    if missing_families:
        raise SystemExit(f"unknown family/families: {', '.join(missing_families)}")
    if not selected:
        raise SystemExit("no scenes matched the requested filters")

    rendered_for_overview: list[SceneSpec] = []
    for spec in selected:
        processed_spec, _, _, _, _ = process_scene(spec, args, gallery=True)
        if not args.no_render and not args.video:
            rendered_for_overview.append(processed_spec)

    if rendered_for_overview and not args.no_overview:
        overview_pages = assemble_overview_pages(rendered_for_overview, args.outdir)
        family_overviews = assemble_family_overviews(rendered_for_overview, args.outdir)
        for overview in overview_pages:
            print(f"overview {overview}")
        for family, pages in sorted(family_overviews.items()):
            for page in pages:
                print(f"family   {family:12} {page}")
    else:
        overview_pages = []
        family_overviews = {}

    full_selection = {spec.name for spec in selected} == {spec.name for spec in specs}
    if full_selection:
        manifest = write_manifest(specs, args.outdir, overview_pages=overview_pages, family_overviews=family_overviews)
        print(f"manifest {manifest}")
