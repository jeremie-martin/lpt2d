"""Scene model and animation types for lpt2d.

C++ types (Material, shapes, lights, Scene, Look, etc.) are imported from
the _lpt2d native extension module. Python-only animation types (Frame,
Timeline, FrameContext, Quality, FrameReport) are defined here.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable

import _lpt2d

# ─── Re-export C++ types ─────────────────────────────────────────

Material = _lpt2d.Material
Circle = _lpt2d.Circle
Segment = _lpt2d.Segment
Arc = _lpt2d.Arc
Bezier = _lpt2d.Bezier
Polygon = _lpt2d.Polygon
Ellipse = _lpt2d.Ellipse
PointLight = _lpt2d.PointLight
SegmentLight = _lpt2d.SegmentLight
BeamLight = _lpt2d.BeamLight
ParallelBeamLight = _lpt2d.ParallelBeamLight
SpotLight = _lpt2d.SpotLight
Transform2D = _lpt2d.Transform2D
Group = _lpt2d.Group
Scene = _lpt2d.Scene
Camera2D = _lpt2d.Camera2D
Canvas = _lpt2d.Canvas
Look = _lpt2d.Look
TraceDefaults = _lpt2d.TraceDefaults
Bounds = _lpt2d.Bounds
ToneMap = _lpt2d.ToneMap
NormalizeMode = _lpt2d.NormalizeMode
SeedMode = _lpt2d.SeedMode
RenderSession = _lpt2d.RenderSession
RenderResult = _lpt2d.RenderResult
FrameMetrics = _lpt2d.FrameMetrics
TraceConfig = _lpt2d.TraceConfig
PostProcess = _lpt2d.PostProcess

# ─── Re-export convenience constructors ──────────────────────────

glass = _lpt2d.glass
mirror = _lpt2d.mirror
opaque_mirror = _lpt2d.opaque_mirror
diffuse = _lpt2d.diffuse
absorber = _lpt2d.absorber
emissive = _lpt2d.emissive
beam_splitter = _lpt2d.beam_splitter

# ─── Geometry helpers ────────────────────────────────────────────

TAU = 2.0 * math.pi


def normalize_angle(angle: float) -> float:
    """Normalize angle to [0, 2pi)."""
    angle = angle % TAU
    return angle if angle >= 0 else angle + TAU


def clamp_arc_sweep(sweep: float) -> float:
    """Clamp arc sweep to [0, 2pi]."""
    return max(0.0, min(sweep, TAU))


def shape_type_name(shape) -> str:
    """Return the type name of a shape variant."""
    return type(shape).__name__.lower()


def light_type_name(light) -> str:
    """Return the type name of a light variant."""
    return type(light).__name__.lower()


# ─── Type aliases ────────────────────────────────────────────────

Shape = Circle | Segment | Arc | Bezier | Polygon | Ellipse
Light = PointLight | SegmentLight | BeamLight | ParallelBeamLight | SpotLight


# ─── Scene convenience methods (monkey-patched onto C++ Scene) ───


def scene_find_shape(scene: Scene, entity_id: str):
    """Find a shape by ID, searching top-level and groups. Returns None if not found."""
    for s in scene.shapes:
        if s.id == entity_id:
            return s
    for g in scene.groups:
        for s in g.shapes:
            if s.id == entity_id:
                return s
    return None


def scene_find_light(scene: Scene, entity_id: str):
    """Find a light by ID, searching top-level and groups. Returns None if not found."""
    for l in scene.lights:
        if l.id == entity_id:
            return l
    for g in scene.groups:
        for l in g.lights:
            if l.id == entity_id:
                return l
    return None


def scene_find_group(scene: Scene, entity_id: str):
    """Find a group by ID. Returns None if not found."""
    for g in scene.groups:
        if g.id == entity_id:
            return g
    return None


def scene_clone(scene: Scene) -> Scene:
    """Create a copy of a scene."""
    return Scene(
        shapes=list(scene.shapes),
        lights=list(scene.lights),
        groups=list(scene.groups),
        materials=dict(scene.materials),
    )


# Patch convenience methods onto the C++ Scene class
Scene.find_shape = scene_find_shape
Scene.find_light = scene_find_light
Scene.find_group = scene_find_group
Scene.clone = scene_clone


def _require(result, kind: str, entity_id: str):
    if result is None:
        raise ValueError(f"{kind} not found: {entity_id}")
    return result


Scene.require_shape = lambda self, eid: _require(scene_find_shape(self, eid), "shape", eid)
Scene.require_light = lambda self, eid: _require(scene_find_light(self, eid), "light", eid)
Scene.require_group = lambda self, eid: _require(scene_find_group(self, eid), "group", eid)
Scene.require_material = lambda self, mid: _require(
    self.materials.get(mid), "material", mid
)


# ─── Look.with_overrides / Transform2D.uniform ──────────────────


def _look_with_overrides(self, **overrides):
    """Return a new Look with specified fields overridden."""
    return _apply_look_override(self, overrides)


Look.with_overrides = _look_with_overrides


def _transform2d_uniform(translate=(0, 0), rotate=0.0, scale=1.0):
    """Create a Transform2D with uniform scale."""
    return Transform2D(translate=list(translate), rotate=rotate, scale=[scale, scale])


Transform2D.uniform = staticmethod(_transform2d_uniform)


# ─── Quality presets ─────────────────────────────────────────────


class Quality(Enum):
    DRAFT = "draft"
    PREVIEW = "preview"
    PRODUCTION = "production"
    FINAL = "final"


_QUALITY_PRESETS: dict[Quality, dict] = {
    Quality.DRAFT: dict(
        canvas=Canvas(480, 480), trace=TraceDefaults(rays=200_000, batch=100_000, depth=6)
    ),
    Quality.PREVIEW: dict(
        canvas=Canvas(720, 720), trace=TraceDefaults(rays=1_000_000, batch=200_000, depth=10)
    ),
    Quality.PRODUCTION: dict(
        canvas=Canvas(1080, 1080), trace=TraceDefaults(rays=5_000_000, batch=200_000, depth=12)
    ),
    Quality.FINAL: dict(
        canvas=Canvas(1920, 1080), trace=TraceDefaults(rays=50_000_000, batch=500_000, depth=16)
    ),
}


# ─── Shot: authored document with Python convenience methods ─────


@dataclass
class Shot:
    """The authored document — what the user saves and expects to reopen unchanged."""

    name: str = ""
    scene: Scene = field(default_factory=Scene)
    camera: Camera2D | None = None
    canvas: Canvas = field(default_factory=Canvas)
    look: Look = field(default_factory=Look)
    trace: TraceDefaults = field(default_factory=TraceDefaults)

    def to_cpp(self) -> _lpt2d.Shot:
        """Convert to C++ Shot for rendering."""
        return _lpt2d.Shot(
            name=self.name,
            scene=self.scene,
            camera=self.camera if self.camera is not None else Camera2D(),
            canvas=self.canvas,
            look=self.look,
            trace=self.trace,
        )

    @staticmethod
    def load(path: str | Path) -> Shot:
        """Load shot from a JSON file (via C++ serializer)."""
        cpp = _lpt2d.load_shot(str(path))
        return Shot(
            name=cpp.name,
            scene=cpp.scene,
            camera=cpp.camera if not cpp.camera.empty() else None,
            canvas=cpp.canvas,
            look=cpp.look,
            trace=cpp.trace,
        )

    def save(self, path: str | Path) -> None:
        """Save shot to a JSON file (via C++ serializer)."""
        _lpt2d.save_shot(self.to_cpp(), str(path))

    @staticmethod
    def preset(quality: Quality | str, **overrides: Any) -> Shot:
        """Create a shot from a named quality preset with optional overrides."""
        if isinstance(quality, str):
            quality = Quality(quality)
        preset = _QUALITY_PRESETS[quality]
        canvas = Canvas(preset["canvas"].width, preset["canvas"].height)
        trace = TraceDefaults(
            rays=preset["trace"].rays,
            batch=preset["trace"].batch,
            depth=preset["trace"].depth,
        )
        shot = Shot(canvas=canvas, trace=trace)
        for key, val in overrides.items():
            if key in ("width", "height"):
                setattr(shot.canvas, key, val)
            elif key in ("rays", "batch", "depth", "intensity", "seed_mode"):
                setattr(shot.trace, key, val)
            elif hasattr(shot.look, key):
                setattr(shot.look, key, val)
            else:
                raise TypeError(f"Shot.preset() got unexpected keyword argument '{key}'")
        return shot

    def with_look(self, **overrides: Any) -> Shot:
        """Return a new Shot with Look fields overridden."""
        new_look = _apply_look_override(self.look, overrides)
        return Shot(
            name=self.name,
            scene=self.scene,
            camera=self.camera,
            canvas=self.canvas,
            look=new_look,
            trace=self.trace,
        )

    def with_trace(self, **overrides: Any) -> Shot:
        """Return a new Shot with TraceDefaults fields overridden."""
        new_trace = TraceDefaults(
            rays=overrides.get("rays", self.trace.rays),
            batch=overrides.get("batch", self.trace.batch),
            depth=overrides.get("depth", self.trace.depth),
            intensity=overrides.get("intensity", self.trace.intensity),
            seed_mode=overrides.get("seed_mode", self.trace.seed_mode),
        )
        return Shot(
            name=self.name,
            scene=self.scene,
            camera=self.camera,
            canvas=self.canvas,
            look=self.look,
            trace=new_trace,
        )


# ─── Override resolution ─────────────────────────────────────────


def _apply_look_override(base: Look, override: Look | dict[str, Any] | None) -> Look:
    """Resolve per-frame Look overrides into a full Look."""
    if override is None:
        return base
    if isinstance(override, Look):
        return override
    if isinstance(override, dict):
        result = Look(
            exposure=base.exposure,
            contrast=base.contrast,
            gamma=base.gamma,
            tonemap=base.tonemap,
            white_point=base.white_point,
            normalize=base.normalize,
            normalize_ref=base.normalize_ref,
            normalize_pct=base.normalize_pct,
            ambient=base.ambient,
            background=list(base.background),
            opacity=base.opacity,
            saturation=base.saturation,
            vignette=base.vignette,
            vignette_radius=base.vignette_radius,
        )
        for k, v in override.items():
            setattr(result, k, v)
        return result
    raise TypeError(f"Look override must be Look, dict, or None, got {type(override)}")


def _apply_trace_override(
    base: TraceDefaults, override: TraceDefaults | dict[str, Any] | None
) -> TraceDefaults:
    """Resolve per-frame TraceDefaults overrides."""
    if override is None:
        return base
    if isinstance(override, TraceDefaults):
        return override
    if isinstance(override, dict):
        return TraceDefaults(
            rays=override.get("rays", base.rays),
            batch=override.get("batch", base.batch),
            depth=override.get("depth", base.depth),
            intensity=override.get("intensity", base.intensity),
            seed_mode=override.get("seed_mode", base.seed_mode),
        )
    raise TypeError(f"Trace override must be TraceDefaults, dict, or None, got {type(override)}")


# ─── Timeline ────────────────────────────────────────────────────


@dataclass
class Timeline:
    """Frame timing: duration and fps."""

    duration: float
    fps: int = 30

    @property
    def total_frames(self) -> int:
        return math.ceil(self.duration * self.fps)

    @property
    def dt(self) -> float:
        return 1.0 / self.fps

    def time_at(self, frame: int) -> float:
        return frame / self.fps

    def progress_at(self, frame: int) -> float:
        n = self.total_frames
        if n <= 1:
            return 0.0
        return frame / (n - 1)

    def context_at(self, frame: int) -> FrameContext:
        return FrameContext(
            frame=frame,
            time=self.time_at(frame),
            progress=self.progress_at(frame),
            fps=self.fps,
            dt=self.dt,
            total_frames=self.total_frames,
            duration=self.duration,
        )


# ─── Frame context & return types ────────────────────────────────


@dataclass(frozen=True)
class FrameContext:
    """Immutable context passed to the animate callback each frame."""

    frame: int
    time: float
    progress: float
    fps: int
    dt: float
    total_frames: int
    duration: float


@dataclass
class Frame:
    """Return type for animate callbacks that need per-frame camera or render control."""

    scene: Scene
    camera: Camera2D | None = None
    look: Look | dict[str, Any] | None = None
    trace: TraceDefaults | dict[str, Any] | None = None


AnimateFn = Callable[["FrameContext"], "Scene | Frame"]


@dataclass(frozen=True)
class FrameReport:
    """Structured per-frame metadata from the C++ renderer."""

    frame: int
    rays: int
    time_ms: int
    max_hdr: float
    total_rays: int
    time_ms_exact: float | None = None
    mean: float | None = None
    pct_black: float | None = None
    pct_clipped: float | None = None
    p50: float | None = None
    p95: float | None = None
    stats_ms: float | None = None
    histogram: list[int] | None = None


def _report_from_result(result: RenderResult, frame_idx: int, time_ms: float) -> FrameReport:
    """Create a FrameReport from a C++ RenderResult."""
    m = result.metrics
    return FrameReport(
        frame=frame_idx,
        rays=result.total_rays,
        time_ms=int(time_ms),
        max_hdr=result.max_hdr,
        total_rays=result.total_rays,
        time_ms_exact=time_ms,
        mean=m.mean_lum,
        pct_black=m.pct_black,
        pct_clipped=m.pct_clipped,
        p50=m.p50,
        p95=m.p95,
        histogram=m.histogram,
    )
