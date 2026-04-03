"""Wire-format dataclasses mirroring the C++ scene model."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


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

    def to_dict(self) -> dict:
        return {
            "ior": self.ior, "roughness": self.roughness, "metallic": self.metallic,
            "transmission": self.transmission, "absorption": self.absorption,
            "cauchy_b": self.cauchy_b, "albedo": self.albedo,
        }

    @staticmethod
    def from_dict(d: dict) -> Material:
        return Material(
            ior=d.get("ior", 1.0), roughness=d.get("roughness", 0.0),
            metallic=d.get("metallic", 0.0), transmission=d.get("transmission", 0.0),
            absorption=d.get("absorption", 0.0), cauchy_b=d.get("cauchy_b", 0.0),
            albedo=d.get("albedo", 1.0),
        )


def glass(ior: float, cauchy_b: float = 0.0, absorption: float = 0.0) -> Material:
    return Material(ior=ior, transmission=1.0, absorption=absorption, cauchy_b=cauchy_b)

def mirror(reflectance: float, roughness: float = 0.0) -> Material:
    return Material(roughness=roughness, metallic=1.0, transmission=1.0, albedo=reflectance)

def diffuse(reflectance: float) -> Material:
    return Material(albedo=reflectance)

def absorber() -> Material:
    return Material(albedo=0.0)


# --- Shapes ---

@dataclass
class Circle:
    center: list[float] = field(default_factory=lambda: [0.0, 0.0])
    radius: float = 0.1
    material: Material = field(default_factory=Material)

    def to_dict(self) -> dict:
        return {"type": "circle", "center": self.center, "radius": self.radius,
                "material": self.material.to_dict()}

@dataclass
class Segment:
    a: list[float] = field(default_factory=lambda: [0.0, 0.0])
    b: list[float] = field(default_factory=lambda: [1.0, 0.0])
    material: Material = field(default_factory=Material)

    def to_dict(self) -> dict:
        return {"type": "segment", "a": self.a, "b": self.b,
                "material": self.material.to_dict()}

@dataclass
class Arc:
    center: list[float] = field(default_factory=lambda: [0.0, 0.0])
    radius: float = 0.1
    angle_start: float = 0.0
    angle_end: float = 6.283185307
    material: Material = field(default_factory=Material)

    def to_dict(self) -> dict:
        return {"type": "arc", "center": self.center, "radius": self.radius,
                "angle_start": self.angle_start, "angle_end": self.angle_end,
                "material": self.material.to_dict()}

@dataclass
class Bezier:
    p0: list[float] = field(default_factory=lambda: [0.0, 0.0])
    p1: list[float] = field(default_factory=lambda: [0.5, 0.5])
    p2: list[float] = field(default_factory=lambda: [1.0, 0.0])
    material: Material = field(default_factory=Material)

    def to_dict(self) -> dict:
        return {"type": "bezier", "p0": self.p0, "p1": self.p1, "p2": self.p2,
                "material": self.material.to_dict()}


Shape = Circle | Segment | Arc | Bezier


# --- Lights ---

@dataclass
class PointLight:
    pos: list[float] = field(default_factory=lambda: [0.0, 0.0])
    intensity: float = 1.0
    wavelength_min: float = 380.0
    wavelength_max: float = 780.0

    def to_dict(self) -> dict:
        return {"type": "point", "pos": self.pos, "intensity": self.intensity,
                "wavelength_min": self.wavelength_min, "wavelength_max": self.wavelength_max}

@dataclass
class SegmentLight:
    a: list[float] = field(default_factory=lambda: [0.0, 0.0])
    b: list[float] = field(default_factory=lambda: [1.0, 0.0])
    intensity: float = 1.0
    wavelength_min: float = 380.0
    wavelength_max: float = 780.0

    def to_dict(self) -> dict:
        return {"type": "segment", "a": self.a, "b": self.b, "intensity": self.intensity,
                "wavelength_min": self.wavelength_min, "wavelength_max": self.wavelength_max}

@dataclass
class BeamLight:
    origin: list[float] = field(default_factory=lambda: [0.0, 0.0])
    direction: list[float] = field(default_factory=lambda: [1.0, 0.0])
    angular_width: float = 0.1
    intensity: float = 1.0
    wavelength_min: float = 380.0
    wavelength_max: float = 780.0

    def to_dict(self) -> dict:
        return {"type": "beam", "origin": self.origin, "direction": self.direction,
                "angular_width": self.angular_width, "intensity": self.intensity,
                "wavelength_min": self.wavelength_min, "wavelength_max": self.wavelength_max}


Light = PointLight | SegmentLight | BeamLight


# --- Groups ---

@dataclass
class Transform2D:
    translate: list[float] = field(default_factory=lambda: [0.0, 0.0])
    rotate: float = 0.0
    scale: list[float] = field(default_factory=lambda: [1.0, 1.0])

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
            "name": self.name, "transform": self.transform.to_dict(),
            "shapes": [s.to_dict() for s in self.shapes],
            "lights": [l.to_dict() for l in self.lights],
        }


# --- Per-frame render overrides ---

@dataclass
class RenderConfig:
    rays: int | None = None
    batch: int | None = None
    depth: int | None = None
    exposure: float | None = None
    contrast: float | None = None
    gamma: float | None = None
    tonemap: str | None = None
    white_point: float | None = None
    bounds: list[float] | None = None  # [xmin, ymin, xmax, ymax]

    def to_dict(self) -> dict:
        d: dict = {}
        for k in ("rays", "batch", "depth", "exposure", "contrast", "gamma", "tonemap", "white_point", "bounds"):
            v = getattr(self, k)
            if v is not None:
                d[k] = v
        return d


# --- Scene ---

_SHAPE_PARSERS = {
    "circle": lambda d: Circle(center=d["center"], radius=d["radius"], material=Material.from_dict(d.get("material", {}))),
    "segment": lambda d: Segment(a=d["a"], b=d["b"], material=Material.from_dict(d.get("material", {}))),
    "arc": lambda d: Arc(center=d["center"], radius=d["radius"],
                         angle_start=d.get("angle_start", 0.0), angle_end=d.get("angle_end", 6.283185307),
                         material=Material.from_dict(d.get("material", {}))),
    "bezier": lambda d: Bezier(p0=d["p0"], p1=d["p1"], p2=d["p2"], material=Material.from_dict(d.get("material", {}))),
}

_LIGHT_PARSERS = {
    "point": lambda d: PointLight(pos=d["pos"], intensity=d.get("intensity", 1.0),
                                  wavelength_min=d.get("wavelength_min", 380.0), wavelength_max=d.get("wavelength_max", 780.0)),
    "segment": lambda d: SegmentLight(a=d["a"], b=d["b"], intensity=d.get("intensity", 1.0),
                                      wavelength_min=d.get("wavelength_min", 380.0), wavelength_max=d.get("wavelength_max", 780.0)),
    "beam": lambda d: BeamLight(origin=d["origin"], direction=d["direction"],
                                angular_width=d.get("angular_width", 0.1), intensity=d.get("intensity", 1.0),
                                wavelength_min=d.get("wavelength_min", 380.0), wavelength_max=d.get("wavelength_max", 780.0)),
}


def _parse_shapes(arr: list[dict]) -> list[Shape]:
    shapes = []
    for d in arr:
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
    shapes: list[Shape] = field(default_factory=list)
    lights: list[Light] = field(default_factory=list)
    groups: list[Group] = field(default_factory=list)
    name: str = ""
    render: RenderConfig | None = None

    def to_json(self) -> str:
        """Compact single-line JSON for streaming."""
        d: dict = {"version": 2, "name": self.name}
        d["shapes"] = [s.to_dict() for s in self.shapes]
        d["lights"] = [l.to_dict() for l in self.lights]
        if self.groups:
            d["groups"] = [g.to_dict() for g in self.groups]
        if self.render:
            rd = self.render.to_dict()
            if rd:
                d["render"] = rd
        return json.dumps(d, separators=(",", ":"))

    @staticmethod
    def load(path: str | Path) -> Scene:
        """Load scene from a JSON file."""
        with open(path) as f:
            return Scene.from_json(f.read())

    @staticmethod
    def from_json(s: str) -> Scene:
        """Parse scene from a JSON string."""
        d = json.loads(s)
        scene = Scene(name=d.get("name", ""))
        scene.shapes = _parse_shapes(d.get("shapes", []))
        scene.lights = _parse_lights(d.get("lights", []))
        for gd in d.get("groups", []):
            group = Group(name=gd.get("name", ""))
            if "transform" in gd:
                group.transform = Transform2D.from_dict(gd["transform"])
            group.shapes = _parse_shapes(gd.get("shapes", []))
            group.lights = _parse_lights(gd.get("lights", []))
            scene.groups.append(group)
        return scene
