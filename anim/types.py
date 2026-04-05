"""Scene model and animation types for lpt2d."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field, fields, replace
from enum import Enum
from pathlib import Path

SHOT_JSON_VERSION = 4

# --- Materials ---


@dataclass
class Material:
    ior: float = 1.0
    roughness: float = 0.0
    metallic: float = 0.0
    transmission: float = 0.0
    absorption: float = 0.0
    cauchy_b: float = 0.0
    albedo: float = 1.0
    emission: float = 0.0

    def to_dict(self) -> dict:
        d = {
            "ior": self.ior,
            "roughness": self.roughness,
            "metallic": self.metallic,
            "transmission": self.transmission,
            "absorption": self.absorption,
            "cauchy_b": self.cauchy_b,
            "albedo": self.albedo,
        }
        if self.emission > 0:
            d["emission"] = self.emission
        return d

    @staticmethod
    def from_dict(d: dict) -> Material:
        return Material(
            ior=d.get("ior", 1.0),
            roughness=d.get("roughness", 0.0),
            metallic=d.get("metallic", 0.0),
            transmission=d.get("transmission", 0.0),
            absorption=d.get("absorption", 0.0),
            cauchy_b=d.get("cauchy_b", 0.0),
            albedo=d.get("albedo", 1.0),
            emission=d.get("emission", 0.0),
        )


def glass(ior: float, cauchy_b: float = 0.0, absorption: float = 0.0) -> Material:
    return Material(ior=ior, transmission=1.0, absorption=absorption, cauchy_b=cauchy_b)


def mirror(reflectance: float, roughness: float = 0.0) -> Material:
    """Reflective surface. Unreflected light transmits through (beam splitter behavior).

    For an opaque mirror that absorbs unreflected light, use :func:`opaque_mirror`.
    """
    return Material(roughness=roughness, metallic=1.0, transmission=1.0, albedo=reflectance)


def beam_splitter(reflectance: float, roughness: float = 0.0) -> Material:
    """Beam splitter: reflects *reflectance* fraction, transmits the rest.

    Alias for :func:`mirror` -- identical physics.
    """
    return mirror(reflectance, roughness)


def opaque_mirror(reflectance: float, roughness: float = 0.0) -> Material:
    """Opaque reflective surface. Unreflected light is absorbed (not transmitted)."""
    return Material(roughness=roughness, metallic=1.0, transmission=0.0, albedo=reflectance)


def diffuse(reflectance: float) -> Material:
    return Material(albedo=reflectance)


def absorber() -> Material:
    return Material(albedo=0.0)


def emissive(emission: float, base: Material | None = None) -> Material:
    """Emissive surface: adds energy at hit wavelength.

    Pass an optional *base* material to combine emission with other properties
    (e.g., ``emissive(2.0, glass(1.5))`` for a glowing glass surface).
    """
    if base is not None:
        return replace(base, emission=emission)
    return Material(emission=emission)


def normalize_angle(angle: float) -> float:
    angle = math.fmod(angle, math.tau)
    if angle < 0.0:
        angle += math.tau
    return angle


def clamp_arc_sweep(sweep: float) -> float:
    return min(max(sweep, 0.0), math.tau)


# --- Shapes ---


@dataclass
class Circle:
    center: list[float] = field(default_factory=lambda: [0.0, 0.0])
    radius: float = 0.1
    material: Material = field(default_factory=Material)

    def to_dict(self) -> dict:
        return {
            "type": "circle",
            "center": self.center,
            "radius": self.radius,
            "material": self.material.to_dict(),
        }


@dataclass
class Segment:
    a: list[float] = field(default_factory=lambda: [0.0, 0.0])
    b: list[float] = field(default_factory=lambda: [1.0, 0.0])
    material: Material = field(default_factory=Material)

    def to_dict(self) -> dict:
        return {"type": "segment", "a": self.a, "b": self.b, "material": self.material.to_dict()}


@dataclass
class Arc:
    center: list[float] = field(default_factory=lambda: [0.0, 0.0])
    radius: float = 0.1
    angle_start: float = 0.0
    sweep: float = math.tau
    material: Material = field(default_factory=Material)

    def __post_init__(self) -> None:
        self.angle_start = normalize_angle(self.angle_start)
        self.sweep = clamp_arc_sweep(self.sweep)

    def to_dict(self) -> dict:
        return {
            "type": "arc",
            "center": self.center,
            "radius": self.radius,
            "angle_start": normalize_angle(self.angle_start),
            "sweep": clamp_arc_sweep(self.sweep),
            "material": self.material.to_dict(),
        }


@dataclass
class Bezier:
    p0: list[float] = field(default_factory=lambda: [0.0, 0.0])
    p1: list[float] = field(default_factory=lambda: [0.5, 0.5])
    p2: list[float] = field(default_factory=lambda: [1.0, 0.0])
    material: Material = field(default_factory=Material)

    def to_dict(self) -> dict:
        return {
            "type": "bezier",
            "p0": self.p0,
            "p1": self.p1,
            "p2": self.p2,
            "material": self.material.to_dict(),
        }


@dataclass
class Polygon:
    vertices: list[list[float]] = field(default_factory=list)
    material: Material = field(default_factory=Material)

    def to_dict(self) -> dict:
        return {
            "type": "polygon",
            "vertices": self.vertices,
            "material": self.material.to_dict(),
        }


@dataclass
class Ellipse:
    center: list[float] = field(default_factory=lambda: [0.0, 0.0])
    semi_a: float = 0.2
    semi_b: float = 0.1
    rotation: float = 0.0
    material: Material = field(default_factory=Material)

    def to_dict(self) -> dict:
        return {
            "type": "ellipse",
            "center": self.center,
            "semi_a": self.semi_a,
            "semi_b": self.semi_b,
            "rotation": self.rotation,
            "material": self.material.to_dict(),
        }


Shape = Circle | Segment | Arc | Bezier | Polygon | Ellipse


# --- Lights ---


@dataclass
class PointLight:
    pos: list[float] = field(default_factory=lambda: [0.0, 0.0])
    intensity: float = 1.0
    wavelength_min: float = 380.0
    wavelength_max: float = 780.0

    def to_dict(self) -> dict:
        return {
            "type": "point",
            "pos": self.pos,
            "intensity": self.intensity,
            "wavelength_min": self.wavelength_min,
            "wavelength_max": self.wavelength_max,
        }


@dataclass
class SegmentLight:
    a: list[float] = field(default_factory=lambda: [0.0, 0.0])
    b: list[float] = field(default_factory=lambda: [1.0, 0.0])
    intensity: float = 1.0
    wavelength_min: float = 380.0
    wavelength_max: float = 780.0

    def to_dict(self) -> dict:
        return {
            "type": "segment",
            "a": self.a,
            "b": self.b,
            "intensity": self.intensity,
            "wavelength_min": self.wavelength_min,
            "wavelength_max": self.wavelength_max,
        }


@dataclass
class BeamLight:
    origin: list[float] = field(default_factory=lambda: [0.0, 0.0])
    direction: list[float] = field(default_factory=lambda: [1.0, 0.0])
    angular_width: float = 0.1
    intensity: float = 1.0
    wavelength_min: float = 380.0
    wavelength_max: float = 780.0

    def to_dict(self) -> dict:
        return {
            "type": "beam",
            "origin": self.origin,
            "direction": self.direction,
            "angular_width": self.angular_width,
            "intensity": self.intensity,
            "wavelength_min": self.wavelength_min,
            "wavelength_max": self.wavelength_max,
        }


@dataclass
class ParallelBeamLight:
    a: list[float] = field(default_factory=lambda: [0.0, 0.0])
    b: list[float] = field(default_factory=lambda: [0.0, 0.5])
    direction: list[float] = field(default_factory=lambda: [1.0, 0.0])
    angular_width: float = 0.0
    intensity: float = 1.0
    wavelength_min: float = 380.0
    wavelength_max: float = 780.0

    def to_dict(self) -> dict:
        return {
            "type": "parallel_beam",
            "a": self.a,
            "b": self.b,
            "direction": self.direction,
            "angular_width": self.angular_width,
            "intensity": self.intensity,
            "wavelength_min": self.wavelength_min,
            "wavelength_max": self.wavelength_max,
        }


@dataclass
class SpotLight:
    pos: list[float] = field(default_factory=lambda: [0.0, 0.0])
    direction: list[float] = field(default_factory=lambda: [1.0, 0.0])
    angular_width: float = 0.5
    falloff: float = 2.0
    intensity: float = 1.0
    wavelength_min: float = 380.0
    wavelength_max: float = 780.0

    def to_dict(self) -> dict:
        return {
            "type": "spot",
            "pos": self.pos,
            "direction": self.direction,
            "angular_width": self.angular_width,
            "falloff": self.falloff,
            "intensity": self.intensity,
            "wavelength_min": self.wavelength_min,
            "wavelength_max": self.wavelength_max,
        }


Light = PointLight | SegmentLight | BeamLight | ParallelBeamLight | SpotLight


# --- Groups ---


@dataclass
class Transform2D:
    """2D transform applied as scale -> rotate -> translate.

    Note on non-uniform scale: circles and arcs use the geometric mean of
    (sx, sy), so they remain circular. Ellipses, polygons, segments, beziers,
    and lights transform exactly.
    """

    translate: list[float] = field(default_factory=lambda: [0.0, 0.0])
    rotate: float = 0.0
    scale: list[float] = field(default_factory=lambda: [1.0, 1.0])

    @staticmethod
    def uniform(
        translate: tuple[float, float] = (0.0, 0.0), rotate: float = 0.0, scale: float = 1.0
    ) -> Transform2D:
        """Convenience for uniform scale (safe for all shapes including circles/arcs)."""
        return Transform2D(translate=list(translate), rotate=rotate, scale=[scale, scale])

    def to_dict(self) -> dict:
        return {"translate": self.translate, "rotate": self.rotate, "scale": self.scale}

    @staticmethod
    def from_dict(d: dict) -> Transform2D:
        return Transform2D(
            translate=d.get("translate", [0.0, 0.0]),
            rotate=d.get("rotate", 0.0),
            scale=d.get("scale", [1.0, 1.0]),
        )


@dataclass
class Group:
    name: str = ""
    transform: Transform2D = field(default_factory=Transform2D)
    shapes: list[Shape] = field(default_factory=list)
    lights: list[Light] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "transform": self.transform.to_dict(),
            "shapes": [s.to_dict() for s in self.shapes],
            "lights": [light.to_dict() for light in self.lights],
        }

    def clone(self) -> Group:
        """Deep copy of the group."""
        import copy

        return copy.deepcopy(self)


# --- Scene (content-only: shapes, lights, groups, materials) ---

_SHAPE_PARSERS = {
    "circle": lambda d: Circle(
        center=d["center"], radius=d["radius"], material=Material.from_dict(d.get("material", {}))
    ),
    "segment": lambda d: Segment(
        a=d["a"], b=d["b"], material=Material.from_dict(d.get("material", {}))
    ),
    "arc": lambda d: Arc(
        center=d["center"],
        radius=d["radius"],
        angle_start=d.get("angle_start", 0.0),
        sweep=d.get("sweep", math.tau),
        material=Material.from_dict(d.get("material", {})),
    ),
    "bezier": lambda d: Bezier(
        p0=d["p0"], p1=d["p1"], p2=d["p2"], material=Material.from_dict(d.get("material", {}))
    ),
    "polygon": lambda d: Polygon(
        vertices=d["vertices"], material=Material.from_dict(d.get("material", {}))
    ),
    "ellipse": lambda d: Ellipse(
        center=d["center"],
        semi_a=d.get("semi_a", 0.2),
        semi_b=d.get("semi_b", 0.1),
        rotation=d.get("rotation", 0.0),
        material=Material.from_dict(d.get("material", {})),
    ),
}

_LIGHT_PARSERS = {
    "point": lambda d: PointLight(
        pos=d["pos"],
        intensity=d.get("intensity", 1.0),
        wavelength_min=d.get("wavelength_min", 380.0),
        wavelength_max=d.get("wavelength_max", 780.0),
    ),
    "segment": lambda d: SegmentLight(
        a=d["a"],
        b=d["b"],
        intensity=d.get("intensity", 1.0),
        wavelength_min=d.get("wavelength_min", 380.0),
        wavelength_max=d.get("wavelength_max", 780.0),
    ),
    "beam": lambda d: BeamLight(
        origin=d["origin"],
        direction=d["direction"],
        angular_width=d.get("angular_width", 0.1),
        intensity=d.get("intensity", 1.0),
        wavelength_min=d.get("wavelength_min", 380.0),
        wavelength_max=d.get("wavelength_max", 780.0),
    ),
    "parallel_beam": lambda d: ParallelBeamLight(
        a=d.get("a", [0.0, 0.0]),
        b=d.get("b", [0.0, 0.5]),
        direction=d.get("direction", [1.0, 0.0]),
        angular_width=d.get("angular_width", 0.0),
        intensity=d.get("intensity", 1.0),
        wavelength_min=d.get("wavelength_min", 380.0),
        wavelength_max=d.get("wavelength_max", 780.0),
    ),
    "spot": lambda d: SpotLight(
        pos=d.get("pos", [0.0, 0.0]),
        direction=d.get("direction", [1.0, 0.0]),
        angular_width=d.get("angular_width", 0.5),
        falloff=d.get("falloff", 2.0),
        intensity=d.get("intensity", 1.0),
        wavelength_min=d.get("wavelength_min", 380.0),
        wavelength_max=d.get("wavelength_max", 780.0),
    ),
}


def _resolve_material(d: dict, materials: dict[str, Material]) -> dict:
    """If d["material"] is a string, resolve from the materials dict."""
    mat = d.get("material")
    if isinstance(mat, str) and mat in materials:
        d = dict(d)  # shallow copy to avoid mutating original
        d["material"] = materials[mat].to_dict()
    return d


def _parse_shapes(arr: list[dict], materials: dict[str, Material] | None = None) -> list[Shape]:
    shapes = []
    mats = materials or {}
    for d in arr:
        d = _resolve_material(d, mats)
        parser = _SHAPE_PARSERS.get(d.get("type", ""))
        if parser:
            shapes.append(parser(d))
    return shapes


def _parse_lights(arr: list[dict]) -> list[Light]:
    lights = []
    for d in arr:
        parser = _LIGHT_PARSERS.get(d.get("type", ""))
        if parser:
            lights.append(parser(d))
    return lights


@dataclass
class Scene:
    """Content-only scene data: shapes, lights, groups, materials."""

    shapes: list[Shape] = field(default_factory=list)
    lights: list[Light] = field(default_factory=list)
    groups: list[Group] = field(default_factory=list)
    materials: dict[str, Material] = field(default_factory=dict)

    def to_dict(self) -> dict:
        """Scene content as a dict (no version — used inside Shot)."""
        d: dict = {}
        if self.materials:
            d["materials"] = {name: mat.to_dict() for name, mat in self.materials.items()}
        d["shapes"] = [s.to_dict() for s in self.shapes]
        d["lights"] = [light.to_dict() for light in self.lights]
        if self.groups:
            d["groups"] = [g.to_dict() for g in self.groups]
        return d

    @staticmethod
    def _from_dict(d: dict) -> Scene:
        """Parse scene content from a dict (materials/shapes/lights/groups)."""
        scene = Scene()
        for name, mat_d in d.get("materials", {}).items():
            scene.materials[name] = Material.from_dict(mat_d)
        scene.shapes = _parse_shapes(d.get("shapes", []), scene.materials)
        scene.lights = _parse_lights(d.get("lights", []))
        for gd in d.get("groups", []):
            group = Group(name=gd.get("name", ""))
            if "transform" in gd:
                group.transform = Transform2D.from_dict(gd["transform"])
            group.shapes = _parse_shapes(gd.get("shapes", []), scene.materials)
            group.lights = _parse_lights(gd.get("lights", []))
            scene.groups.append(group)
        return scene

    def find_group(self, name: str) -> Group | None:
        """Find a group by name, or None if not found."""
        for g in self.groups:
            if g.name == name:
                return g
        return None

    def clone(self) -> Scene:
        """Deep copy of the scene. Safe to mutate without affecting the original."""
        import copy

        return copy.deepcopy(self)


# --- Camera ---


@dataclass
class Camera2D:
    """Viewport framing for the 2D scene.

    Specify either `bounds` directly or `center` + `width` (height derived from aspect ratio).
    Leave all None for auto-fit (C++ computes bounds from scene content).
    """

    bounds: list[float] | None = None  # [xmin, ymin, xmax, ymax]
    center: list[float] | None = None  # [cx, cy]
    width: float | None = None  # world units

    def resolve(self, aspect: float) -> list[float] | None:
        """Resolve to [xmin, ymin, xmax, ymax] or None for auto-fit."""
        if self.bounds is not None:
            return list(self.bounds)
        if self.center is not None and self.width is not None:
            cx, cy = self.center
            hw = self.width / 2.0
            hh = hw / aspect
            return [cx - hw, cy - hh, cx + hw, cy + hh]
        if self.center is not None or self.width is not None:
            raise ValueError("Camera2D requires both center and width, or bounds, or neither")
        return None

    def to_dict(self) -> dict | None:
        """Serialize camera. Returns None if empty (auto-fit)."""
        if self.bounds is not None:
            return {"bounds": self.bounds}
        if self.center is not None and self.width is not None:
            return {"center": self.center, "width": self.width}
        return None

    @staticmethod
    def from_dict(d: dict) -> Camera2D:
        return Camera2D(
            bounds=d.get("bounds"),
            center=d.get("center"),
            width=d.get("width"),
        )


# --- Canvas, Look, TraceDefaults ---


@dataclass
class Canvas:
    """Output resolution."""

    width: int = 1920
    height: int = 1080

    @property
    def aspect(self) -> float:
        return self.width / self.height

    def to_dict(self) -> dict:
        return {"width": self.width, "height": self.height}

    @staticmethod
    def from_dict(d: dict) -> Canvas:
        return Canvas(width=d.get("width", 1920), height=d.get("height", 1080))


@dataclass
class Look:
    """Post-processing / display settings."""

    exposure: float = -5.0
    contrast: float = 1.0
    gamma: float = 2.0
    tonemap: str = "reinhardx"
    white_point: float = 0.5
    normalize: str = "rays"  # "max" | "rays" | "fixed" | "off"
    normalize_ref: float = 0.0
    normalize_pct: float = 1.0
    ambient: float = 0.0
    background: list[float] = field(default_factory=lambda: [0.0, 0.0, 0.0])
    opacity: float = 1.0

    def to_dict(self) -> dict:
        """Only emit non-default values."""
        _defaults = Look()
        d: dict = {}
        for f in fields(self):
            val = getattr(self, f.name)
            default_val = getattr(_defaults, f.name)
            if val != default_val:
                d[f.name] = val
        return d

    def with_overrides(self, **overrides) -> Look:
        """Return a new Look with specified fields overridden."""
        return replace(self, **overrides)

    @staticmethod
    def from_dict(d: dict) -> Look:
        return Look(
            exposure=d.get("exposure", -5.0),
            contrast=d.get("contrast", 1.0),
            gamma=d.get("gamma", 2.0),
            tonemap=d.get("tonemap", "reinhardx"),
            white_point=d.get("white_point", 0.5),
            normalize=d.get("normalize", "rays"),
            normalize_ref=d.get("normalize_ref", 0.0),
            normalize_pct=d.get("normalize_pct", 1.0),
            ambient=d.get("ambient", 0.0),
            background=d.get("background", [0.0, 0.0, 0.0]),
            opacity=d.get("opacity", 1.0),
        )


@dataclass
class TraceDefaults:
    """Ray tracing quality defaults."""

    rays: int = 10_000_000
    batch: int = 200_000
    depth: int = 12
    intensity: float = 1.0

    def to_dict(self) -> dict:
        """Only emit non-default values."""
        _defaults = TraceDefaults()
        d: dict = {}
        for f in fields(self):
            val = getattr(self, f.name)
            default_val = getattr(_defaults, f.name)
            if val != default_val:
                d[f.name] = val
        return d

    @staticmethod
    def from_dict(d: dict) -> TraceDefaults:
        return TraceDefaults(
            rays=d.get("rays", 10_000_000),
            batch=d.get("batch", 200_000),
            depth=d.get("depth", 12),
            intensity=d.get("intensity", 1.0),
        )


# --- Quality presets ---


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


# --- Shot: the authored document ---


@dataclass
class Shot:
    """The authored document — what the user saves and expects to reopen unchanged.

    Contains scene content, camera framing, output canvas, display look,
    and trace quality defaults.
    """

    name: str = ""
    scene: Scene = field(default_factory=Scene)
    camera: Camera2D | None = None
    canvas: Canvas = field(default_factory=Canvas)
    look: Look = field(default_factory=Look)
    trace: TraceDefaults = field(default_factory=TraceDefaults)

    def to_dict(self) -> dict:
        """Full v4 format dict."""
        d: dict = {"version": SHOT_JSON_VERSION, "name": self.name}
        if self.camera is not None:
            cam_d = self.camera.to_dict()
            if cam_d:
                d["camera"] = cam_d
        d["canvas"] = self.canvas.to_dict()
        look_d = self.look.to_dict()
        if look_d:
            d["look"] = look_d
        trace_d = self.trace.to_dict()
        if trace_d:
            d["trace"] = trace_d
        # Inline scene content at root level
        d.update(self.scene.to_dict())
        return d

    def to_json(self) -> str:
        """Compact single-line JSON for streaming."""
        return json.dumps(self.to_dict(), separators=(",", ":"))

    @staticmethod
    def load(path: str | Path) -> Shot:
        """Load shot from a JSON file."""
        with open(path) as f:
            return Shot.from_json(f.read())

    @staticmethod
    def from_json(s: str) -> Shot:
        """Parse shot from a JSON string (v4 format)."""
        d = json.loads(s)
        if d.get("version") != SHOT_JSON_VERSION:
            raise ValueError(
                f"unsupported shot version: {d.get('version')} (expected {SHOT_JSON_VERSION})"
            )
        shot = Shot(name=d.get("name", ""))
        # Shot-level blocks
        if "camera" in d:
            shot.camera = Camera2D.from_dict(d["camera"])
        shot.canvas = Canvas.from_dict(d.get("canvas", {}))
        shot.look = Look.from_dict(d.get("look", {}))
        shot.trace = TraceDefaults.from_dict(d.get("trace", {}))
        # Scene content
        shot.scene = Scene._from_dict(d)
        return shot

    def save(self, path: str | Path) -> None:
        """Save shot to a JSON file."""
        with open(path, "w") as f:
            json.dump(self.to_dict(), f, indent=2)
            f.write("\n")

    @staticmethod
    def preset(quality: Quality | str, **overrides) -> Shot:
        """Create a shot from a named quality preset with optional overrides."""
        if isinstance(quality, str):
            quality = Quality(quality)
        preset = _QUALITY_PRESETS[quality]
        shot = Shot(
            canvas=replace(preset["canvas"]),
            trace=replace(preset["trace"]),
        )
        for key, val in overrides.items():
            if hasattr(shot.canvas, key):
                setattr(shot.canvas, key, val)
            elif hasattr(shot.trace, key):
                setattr(shot.trace, key, val)
            elif hasattr(shot.look, key):
                setattr(shot.look, key, val)
            else:
                raise TypeError(f"Shot.preset() got unexpected keyword argument '{key}'")
        return shot

    def with_look(self, **overrides) -> Shot:
        """Return a new Shot with Look fields overridden.

        Example: ``shot.with_look(exposure=3, tonemap="reinhardx")``
        """
        return replace(self, look=self.look.with_overrides(**overrides))

    def with_trace(self, **overrides) -> Shot:
        """Return a new Shot with TraceDefaults fields overridden.

        Example: ``shot.with_trace(rays=50_000_000)``
        """
        return replace(self, trace=replace(self.trace, **overrides))


# --- Timeline ---


@dataclass
class Timeline:
    """Frame timing: duration and fps.

    Rounding policy: total_frames = ceil(duration * fps).
    This ensures the full duration is always covered.
    """

    duration: float
    fps: int = 30

    @property
    def total_frames(self) -> int:
        return math.ceil(self.duration * self.fps)

    @property
    def dt(self) -> float:
        """Time step between frames (seconds)."""
        return 1.0 / self.fps

    def time_at(self, frame: int) -> float:
        """Physical sample time in seconds.  Use for Track evaluation.

        Note: ``time_at(last_frame) < duration`` (the endpoint is not sampled).
        For a 1 s / 30 fps clip: ``time_at(29) = 0.9667 s``.
        """
        return frame / self.fps

    def progress_at(self, frame: int) -> float:
        """Normalised clip position [0.0, 1.0].  Use for fade envelopes.

        Frame 0 = 0.0, last frame = 1.0 exactly.
        This is frame-index normalised, *not* ``time / duration``.
        """
        n = self.total_frames
        if n <= 1:
            return 0.0
        return frame / (n - 1)

    def context_at(self, frame: int) -> FrameContext:
        """Build a :class:`FrameContext` for the given frame index."""
        return FrameContext(
            frame=frame,
            time=self.time_at(frame),
            progress=self.progress_at(frame),
            fps=self.fps,
            dt=self.dt,
            total_frames=self.total_frames,
            duration=self.duration,
        )


# --- Frame context & return types ---


@dataclass(frozen=True)
class FrameContext:
    """Immutable context passed to the animate callback each frame."""

    frame: int  # 0-based frame index
    time: float  # seconds
    progress: float  # 0..1
    fps: int
    dt: float  # 1/fps
    total_frames: int
    duration: float


@dataclass
class Frame:
    """Return type for animate callbacks that need per-frame camera or render control."""

    scene: Scene
    camera: Camera2D | None = None
    look: Look | None = None  # per-frame look overrides
    trace: TraceDefaults | None = None  # per-frame trace overrides


@dataclass(frozen=True)
class FrameReport:
    """Structured per-frame metadata from the C++ renderer."""

    frame: int
    rays: int
    time_ms: int
    max_hdr: float
    total_rays: int
    # Live metrics from C++ stats pipeline (None if unavailable / old binary)
    time_ms_exact: float | None = None
    mean: float | None = None
    pct_black: float | None = None
    pct_clipped: float | None = None
    p50: float | None = None
    p95: float | None = None
    stats_ms: float | None = None
    histogram: list[int] | None = None  # 256-bin luminance histogram (with --histogram)
