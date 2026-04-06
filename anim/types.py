"""Scene model and animation types for lpt2d."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field, replace
from enum import Enum
from pathlib import Path

SHOT_JSON_VERSION = 5
_CANONICAL_TONEMAPS = {"none", "reinhard", "reinhardx", "aces", "log"}
_CANONICAL_NORMALIZE = {"max", "rays", "fixed", "off"}


def _require_dict(value, context: str) -> dict:
    if not isinstance(value, dict):
        raise ValueError(f"{context} must be an object")
    return value


def _require_exact_keys(d: dict, keys: tuple[str, ...], context: str) -> None:
    missing = [key for key in keys if key not in d]
    if missing:
        raise ValueError(f"{context} requires key: {missing[0]}")
    extras = [key for key in d if key not in keys]
    if extras:
        raise ValueError(f"unknown key in {context}: {extras[0]}")


def _reject_unknown_keys(d: dict, keys: tuple[str, ...], context: str) -> None:
    extras = [key for key in d if key not in keys]
    if extras:
        raise ValueError(f"unknown key in {context}: {extras[0]}")


def _require_string(value, context: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{context} must be a string")
    return value


def _require_int(value, context: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{context} must be an integer")
    return value


def _require_number(value, context: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{context} must be a number")
    return float(value)


def _require_vec(value, size: int, context: str) -> list[float]:
    if not isinstance(value, list) or len(value) != size:
        raise ValueError(f"{context} must contain exactly {size} numbers")
    return [_require_number(item, f"{context}[{i}]") for i, item in enumerate(value)]

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

    def to_dict(self, *, explicit: bool = False) -> dict:
        d = {
            "ior": self.ior,
            "roughness": self.roughness,
            "metallic": self.metallic,
            "transmission": self.transmission,
            "absorption": self.absorption,
            "cauchy_b": self.cauchy_b,
            "albedo": self.albedo,
            "emission": self.emission,
        }
        if not explicit and self.emission <= 0:
            d.pop("emission")
        return d

    @staticmethod
    def from_dict(d: dict, *, explicit: bool = True) -> Material:
        d = _require_dict(d, "material")
        keys = ("ior", "roughness", "metallic", "transmission", "absorption", "cauchy_b", "albedo", "emission")
        if explicit:
            _require_exact_keys(d, keys, "material")
        else:
            extras = [key for key in d if key not in keys]
            if extras:
                raise ValueError(f"unknown key in material: {extras[0]}")
        return Material(
            ior=_require_number(d["ior"], "material.ior") if "ior" in d else 1.0,
            roughness=_require_number(d["roughness"], "material.roughness") if "roughness" in d else 0.0,
            metallic=_require_number(d["metallic"], "material.metallic") if "metallic" in d else 0.0,
            transmission=_require_number(d["transmission"], "material.transmission") if "transmission" in d else 0.0,
            absorption=_require_number(d["absorption"], "material.absorption") if "absorption" in d else 0.0,
            cauchy_b=_require_number(d["cauchy_b"], "material.cauchy_b") if "cauchy_b" in d else 0.0,
            albedo=_require_number(d["albedo"], "material.albedo") if "albedo" in d else 1.0,
            emission=_require_number(d["emission"], "material.emission") if "emission" in d else 0.0,
        )


def _material_payload(material: Material, material_id: str | None, *, explicit_material: bool = False) -> dict:
    if material_id:
        return {"material_id": material_id}
    return {"material": material.to_dict(explicit=explicit_material)}


def _clone_material(material: Material) -> Material:
    return replace(material)


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
    id: str = ""
    center: list[float] = field(default_factory=lambda: [0.0, 0.0])
    radius: float = 0.1
    material: Material = field(default_factory=Material)
    material_id: str | None = None

    def to_dict(self, *, explicit_material: bool = False) -> dict:
        d = {
            "id": self.id,
            "type": "circle",
            "center": self.center,
            "radius": self.radius,
        }
        d.update(_material_payload(self.material, self.material_id, explicit_material=explicit_material))
        return d


@dataclass
class Segment:
    id: str = ""
    a: list[float] = field(default_factory=lambda: [0.0, 0.0])
    b: list[float] = field(default_factory=lambda: [1.0, 0.0])
    material: Material = field(default_factory=Material)
    material_id: str | None = None

    def to_dict(self, *, explicit_material: bool = False) -> dict:
        d = {"id": self.id, "type": "segment", "a": self.a, "b": self.b}
        d.update(_material_payload(self.material, self.material_id, explicit_material=explicit_material))
        return d


@dataclass
class Arc:
    id: str = ""
    center: list[float] = field(default_factory=lambda: [0.0, 0.0])
    radius: float = 0.1
    angle_start: float = 0.0
    sweep: float = math.tau
    material: Material = field(default_factory=Material)
    material_id: str | None = None

    def __post_init__(self) -> None:
        self.angle_start = normalize_angle(self.angle_start)
        self.sweep = clamp_arc_sweep(self.sweep)

    def to_dict(self, *, explicit_material: bool = False) -> dict:
        d = {
            "id": self.id,
            "type": "arc",
            "center": self.center,
            "radius": self.radius,
            "angle_start": normalize_angle(self.angle_start),
            "sweep": clamp_arc_sweep(self.sweep),
        }
        d.update(_material_payload(self.material, self.material_id, explicit_material=explicit_material))
        return d


@dataclass
class Bezier:
    id: str = ""
    p0: list[float] = field(default_factory=lambda: [0.0, 0.0])
    p1: list[float] = field(default_factory=lambda: [0.5, 0.5])
    p2: list[float] = field(default_factory=lambda: [1.0, 0.0])
    material: Material = field(default_factory=Material)
    material_id: str | None = None

    def to_dict(self, *, explicit_material: bool = False) -> dict:
        d = {
            "id": self.id,
            "type": "bezier",
            "p0": self.p0,
            "p1": self.p1,
            "p2": self.p2,
        }
        d.update(_material_payload(self.material, self.material_id, explicit_material=explicit_material))
        return d


@dataclass
class Polygon:
    id: str = ""
    vertices: list[list[float]] = field(default_factory=list)
    material: Material = field(default_factory=Material)
    material_id: str | None = None

    def to_dict(self, *, explicit_material: bool = False) -> dict:
        d = {
            "id": self.id,
            "type": "polygon",
            "vertices": self.vertices,
        }
        d.update(_material_payload(self.material, self.material_id, explicit_material=explicit_material))
        return d


@dataclass
class Ellipse:
    id: str = ""
    center: list[float] = field(default_factory=lambda: [0.0, 0.0])
    semi_a: float = 0.2
    semi_b: float = 0.1
    rotation: float = 0.0
    material: Material = field(default_factory=Material)
    material_id: str | None = None

    def to_dict(self, *, explicit_material: bool = False) -> dict:
        d = {
            "id": self.id,
            "type": "ellipse",
            "center": self.center,
            "semi_a": self.semi_a,
            "semi_b": self.semi_b,
            "rotation": self.rotation,
        }
        d.update(_material_payload(self.material, self.material_id, explicit_material=explicit_material))
        return d


Shape = Circle | Segment | Arc | Bezier | Polygon | Ellipse


# --- Lights ---


@dataclass
class PointLight:
    id: str = ""
    pos: list[float] = field(default_factory=lambda: [0.0, 0.0])
    intensity: float = 1.0
    wavelength_min: float = 380.0
    wavelength_max: float = 780.0

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "type": "point",
            "pos": self.pos,
            "intensity": self.intensity,
            "wavelength_min": self.wavelength_min,
            "wavelength_max": self.wavelength_max,
        }


@dataclass
class SegmentLight:
    id: str = ""
    a: list[float] = field(default_factory=lambda: [0.0, 0.0])
    b: list[float] = field(default_factory=lambda: [1.0, 0.0])
    intensity: float = 1.0
    wavelength_min: float = 380.0
    wavelength_max: float = 780.0

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "type": "segment",
            "a": self.a,
            "b": self.b,
            "intensity": self.intensity,
            "wavelength_min": self.wavelength_min,
            "wavelength_max": self.wavelength_max,
        }


@dataclass
class BeamLight:
    id: str = ""
    origin: list[float] = field(default_factory=lambda: [0.0, 0.0])
    direction: list[float] = field(default_factory=lambda: [1.0, 0.0])
    angular_width: float = 0.1
    intensity: float = 1.0
    wavelength_min: float = 380.0
    wavelength_max: float = 780.0

    def to_dict(self) -> dict:
        return {
            "id": self.id,
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
    id: str = ""
    a: list[float] = field(default_factory=lambda: [0.0, 0.0])
    b: list[float] = field(default_factory=lambda: [0.0, 0.5])
    direction: list[float] = field(default_factory=lambda: [1.0, 0.0])
    angular_width: float = 0.0
    intensity: float = 1.0
    wavelength_min: float = 380.0
    wavelength_max: float = 780.0

    def to_dict(self) -> dict:
        return {
            "id": self.id,
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
    id: str = ""
    pos: list[float] = field(default_factory=lambda: [0.0, 0.0])
    direction: list[float] = field(default_factory=lambda: [1.0, 0.0])
    angular_width: float = 0.5
    falloff: float = 2.0
    intensity: float = 1.0
    wavelength_min: float = 380.0
    wavelength_max: float = 780.0

    def to_dict(self) -> dict:
        return {
            "id": self.id,
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
        d = _require_dict(d, "transform")
        _require_exact_keys(d, ("translate", "rotate", "scale"), "transform")
        return Transform2D(
            translate=_require_vec(d["translate"], 2, "transform.translate"),
            rotate=_require_number(d["rotate"], "transform.rotate"),
            scale=_require_vec(d["scale"], 2, "transform.scale"),
        )


@dataclass
class Group:
    id: str = ""
    transform: Transform2D = field(default_factory=Transform2D)
    shapes: list[Shape] = field(default_factory=list)
    lights: list[Light] = field(default_factory=list)

    def to_dict(self, *, explicit_material: bool = False) -> dict:
        return {
            "id": self.id,
            "transform": self.transform.to_dict(),
            "shapes": [s.to_dict(explicit_material=explicit_material) for s in self.shapes],
            "lights": [light.to_dict() for light in self.lights],
        }

    def clone(self) -> Group:
        """Deep copy of the group."""
        import copy

        return copy.deepcopy(self)


# --- Scene (content-only: shapes, lights, groups, materials) ---


def shape_type_name(shape: Shape) -> str:
    if isinstance(shape, Circle):
        return "circle"
    if isinstance(shape, Segment):
        return "segment"
    if isinstance(shape, Arc):
        return "arc"
    if isinstance(shape, Bezier):
        return "bezier"
    if isinstance(shape, Polygon):
        return "polygon"
    return "ellipse"


def light_type_name(light: Light) -> str:
    if isinstance(light, PointLight):
        return "point_light"
    if isinstance(light, SegmentLight):
        return "segment_light"
    if isinstance(light, BeamLight):
        return "beam_light"
    if isinstance(light, ParallelBeamLight):
        return "parallel_beam_light"
    return "spot_light"


def _require_entity_id(d: dict, kind: str) -> str:
    entity_id = d.get("id")
    if not isinstance(entity_id, str) or not entity_id:
        raise ValueError(f"{kind} entries require a non-empty id")
    return entity_id


def _parse_shape_material(d: dict, materials: dict[str, Material]) -> tuple[Material, str | None]:
    has_inline = "material" in d
    has_binding = "material_id" in d
    if has_inline and has_binding:
        raise ValueError("shape entries cannot declare both material and material_id")
    if not has_inline and not has_binding:
        raise ValueError("shape entries must declare exactly one of material and material_id")
    if has_binding:
        material_id = d.get("material_id")
        if not isinstance(material_id, str) or not material_id:
            raise ValueError("material_id must be a non-empty string")
        if material_id not in materials:
            raise ValueError(f"unknown material_id: {material_id}")
        return materials[material_id], material_id
    return Material.from_dict(d["material"], explicit=True), None


def _parse_shape(d: dict, materials: dict[str, Material]) -> Shape:
    d = _require_dict(d, "shape")
    shape_id = _require_entity_id(d, "shape")
    material, material_id = _parse_shape_material(d, materials)
    shape_type = d.get("type", "")
    if shape_type == "circle":
        _reject_unknown_keys(d, ("id", "type", "center", "radius", "material", "material_id"), "shape")
        _require_exact_keys(
            {key: d[key] for key in ("id", "type", "center", "radius") if key in d},
            ("id", "type", "center", "radius"),
            "shape",
        )
        return Circle(
            id=shape_id,
            center=_require_vec(d["center"], 2, "shape.center"),
            radius=_require_number(d["radius"], "shape.radius"),
            material=material,
            material_id=material_id,
        )
    if shape_type == "segment":
        _reject_unknown_keys(d, ("id", "type", "a", "b", "material", "material_id"), "shape")
        _require_exact_keys(
            {key: d[key] for key in ("id", "type", "a", "b") if key in d},
            ("id", "type", "a", "b"),
            "shape",
        )
        return Segment(
            id=shape_id,
            a=_require_vec(d["a"], 2, "shape.a"),
            b=_require_vec(d["b"], 2, "shape.b"),
            material=material,
            material_id=material_id,
        )
    if shape_type == "arc":
        _reject_unknown_keys(
            d, ("id", "type", "center", "radius", "angle_start", "sweep", "material", "material_id"), "shape"
        )
        _require_exact_keys(
            {key: d[key] for key in ("id", "type", "center", "radius", "angle_start", "sweep") if key in d},
            ("id", "type", "center", "radius", "angle_start", "sweep"),
            "shape",
        )
        return Arc(
            id=shape_id,
            center=_require_vec(d["center"], 2, "shape.center"),
            radius=_require_number(d["radius"], "shape.radius"),
            angle_start=_require_number(d["angle_start"], "shape.angle_start"),
            sweep=_require_number(d["sweep"], "shape.sweep"),
            material=material,
            material_id=material_id,
        )
    if shape_type == "bezier":
        _reject_unknown_keys(d, ("id", "type", "p0", "p1", "p2", "material", "material_id"), "shape")
        _require_exact_keys(
            {key: d[key] for key in ("id", "type", "p0", "p1", "p2") if key in d},
            ("id", "type", "p0", "p1", "p2"),
            "shape",
        )
        return Bezier(
            id=shape_id,
            p0=_require_vec(d["p0"], 2, "shape.p0"),
            p1=_require_vec(d["p1"], 2, "shape.p1"),
            p2=_require_vec(d["p2"], 2, "shape.p2"),
            material=material,
            material_id=material_id,
        )
    if shape_type == "polygon":
        _reject_unknown_keys(d, ("id", "type", "vertices", "material", "material_id"), "shape")
        _require_exact_keys(
            {key: d[key] for key in ("id", "type", "vertices") if key in d},
            ("id", "type", "vertices"),
            "shape",
        )
        vertices = d["vertices"]
        if not isinstance(vertices, list):
            raise ValueError("shape.vertices must be an array")
        return Polygon(
            id=shape_id,
            vertices=[_require_vec(vertex, 2, f"shape.vertices[{i}]") for i, vertex in enumerate(vertices)],
            material=material,
            material_id=material_id,
        )
    if shape_type == "ellipse":
        _reject_unknown_keys(
            d, ("id", "type", "center", "semi_a", "semi_b", "rotation", "material", "material_id"), "shape"
        )
        _require_exact_keys(
            {key: d[key] for key in ("id", "type", "center", "semi_a", "semi_b", "rotation") if key in d},
            ("id", "type", "center", "semi_a", "semi_b", "rotation"),
            "shape",
        )
        return Ellipse(
            id=shape_id,
            center=_require_vec(d["center"], 2, "shape.center"),
            semi_a=_require_number(d["semi_a"], "shape.semi_a"),
            semi_b=_require_number(d["semi_b"], "shape.semi_b"),
            rotation=_require_number(d["rotation"], "shape.rotation"),
            material=material,
            material_id=material_id,
        )
    raise ValueError(f"unknown shape type: {shape_type}")


def _parse_shapes(arr: list[dict], materials: dict[str, Material]) -> list[Shape]:
    return [_parse_shape(d, materials) for d in arr]


def _parse_light(d: dict) -> Light:
    d = _require_dict(d, "light")
    light_id = _require_entity_id(d, "light")
    light_type = d.get("type", "")
    if light_type == "point":
        _require_exact_keys(d, ("id", "type", "pos", "intensity", "wavelength_min", "wavelength_max"), "light")
        return PointLight(
            id=light_id,
            pos=_require_vec(d["pos"], 2, "light.pos"),
            intensity=_require_number(d["intensity"], "light.intensity"),
            wavelength_min=_require_number(d["wavelength_min"], "light.wavelength_min"),
            wavelength_max=_require_number(d["wavelength_max"], "light.wavelength_max"),
        )
    if light_type == "segment":
        _require_exact_keys(d, ("id", "type", "a", "b", "intensity", "wavelength_min", "wavelength_max"), "light")
        return SegmentLight(
            id=light_id,
            a=_require_vec(d["a"], 2, "light.a"),
            b=_require_vec(d["b"], 2, "light.b"),
            intensity=_require_number(d["intensity"], "light.intensity"),
            wavelength_min=_require_number(d["wavelength_min"], "light.wavelength_min"),
            wavelength_max=_require_number(d["wavelength_max"], "light.wavelength_max"),
        )
    if light_type == "beam":
        _require_exact_keys(
            d,
            ("id", "type", "origin", "direction", "angular_width", "intensity", "wavelength_min", "wavelength_max"),
            "light",
        )
        return BeamLight(
            id=light_id,
            origin=_require_vec(d["origin"], 2, "light.origin"),
            direction=_require_vec(d["direction"], 2, "light.direction"),
            angular_width=_require_number(d["angular_width"], "light.angular_width"),
            intensity=_require_number(d["intensity"], "light.intensity"),
            wavelength_min=_require_number(d["wavelength_min"], "light.wavelength_min"),
            wavelength_max=_require_number(d["wavelength_max"], "light.wavelength_max"),
        )
    if light_type == "parallel_beam":
        _require_exact_keys(
            d,
            ("id", "type", "a", "b", "direction", "angular_width", "intensity", "wavelength_min", "wavelength_max"),
            "light",
        )
        return ParallelBeamLight(
            id=light_id,
            a=_require_vec(d["a"], 2, "light.a"),
            b=_require_vec(d["b"], 2, "light.b"),
            direction=_require_vec(d["direction"], 2, "light.direction"),
            angular_width=_require_number(d["angular_width"], "light.angular_width"),
            intensity=_require_number(d["intensity"], "light.intensity"),
            wavelength_min=_require_number(d["wavelength_min"], "light.wavelength_min"),
            wavelength_max=_require_number(d["wavelength_max"], "light.wavelength_max"),
        )
    if light_type == "spot":
        _require_exact_keys(
            d,
            ("id", "type", "pos", "direction", "angular_width", "falloff", "intensity", "wavelength_min", "wavelength_max"),
            "light",
        )
        return SpotLight(
            id=light_id,
            pos=_require_vec(d["pos"], 2, "light.pos"),
            direction=_require_vec(d["direction"], 2, "light.direction"),
            angular_width=_require_number(d["angular_width"], "light.angular_width"),
            falloff=_require_number(d["falloff"], "light.falloff"),
            intensity=_require_number(d["intensity"], "light.intensity"),
            wavelength_min=_require_number(d["wavelength_min"], "light.wavelength_min"),
            wavelength_max=_require_number(d["wavelength_max"], "light.wavelength_max"),
        )
    raise ValueError(f"unknown light type: {light_type}")


def _parse_lights(arr: list[dict]) -> list[Light]:
    return [_parse_light(d) for d in arr]


@dataclass
class Scene:
    """Content-only scene data: shapes, lights, groups, materials."""

    shapes: list[Shape] = field(default_factory=list)
    lights: list[Light] = field(default_factory=list)
    groups: list[Group] = field(default_factory=list)
    materials: dict[str, Material] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self._link_known_material_bindings()

    def _iter_shapes(self):
        for shape in self.shapes:
            yield shape
        for group in self.groups:
            for shape in group.shapes:
                yield shape

    def _iter_lights(self):
        for light in self.lights:
            yield light
        for group in self.groups:
            for light in group.lights:
                yield light

    def _link_known_material_bindings(self) -> None:
        for shape in self._iter_shapes():
            material_id = getattr(shape, "material_id", None)
            if material_id and material_id in self.materials:
                shape.material = self.materials[material_id]

    def _next_entity_id(self, prefix: str, used: set[str]) -> str:
        suffix = 0
        while True:
            candidate = f"{prefix}_{suffix}"
            if candidate not in used:
                return candidate
            suffix += 1

    def ensure_ids(self) -> Scene:
        used: set[str] = set()
        for shape in self._iter_shapes():
            shape_id = shape.id
            if not shape_id or shape_id in used:
                shape.id = self._next_entity_id(shape_type_name(shape), used)
            used.add(shape.id)
        for light in self._iter_lights():
            light_id = light.id
            if not light_id or light_id in used:
                light.id = self._next_entity_id(light_type_name(light), used)
            used.add(light.id)
        for group in self.groups:
            group_id = group.id
            if not group_id or group_id in used:
                group.id = self._next_entity_id("group", used)
            used.add(group.id)
        return self

    def sync_material_bindings(self) -> Scene:
        for shape in self._iter_shapes():
            material_id = getattr(shape, "material_id", None)
            if material_id:
                if material_id not in self.materials:
                    raise ValueError(f"unknown material_id: {material_id}")
                shape.material = self.materials[material_id]
        return self

    def validate(self) -> Scene:
        used: set[str] = set()
        for material_id in self.materials:
            if not material_id:
                raise ValueError("material ids must be non-empty")
        for shape in self._iter_shapes():
            if not shape.id:
                raise ValueError("shape ids must be non-empty")
            if shape.id in used:
                raise ValueError(f"duplicate entity id: {shape.id}")
            used.add(shape.id)
            if shape.material_id and shape.material_id not in self.materials:
                raise ValueError(f"unknown material_id: {shape.material_id}")
        for light in self._iter_lights():
            if not light.id:
                raise ValueError("light ids must be non-empty")
            if light.id in used:
                raise ValueError(f"duplicate entity id: {light.id}")
            used.add(light.id)
        for group in self.groups:
            if not group.id:
                raise ValueError("group ids must be non-empty")
            if group.id in used:
                raise ValueError(f"duplicate entity id: {group.id}")
            used.add(group.id)
        return self

    def _normalized_copy(self, *, sync_material_bindings: bool) -> Scene:
        scene = self.clone()
        scene.ensure_ids()
        if sync_material_bindings:
            scene.sync_material_bindings()
        scene.validate()
        return scene

    def _to_dict_unchecked(self, *, explicit_materials: bool, include_empty: bool) -> dict:
        d: dict = {}
        if include_empty or self.materials:
            d["materials"] = {
                name: mat.to_dict(explicit=explicit_materials) for name, mat in self.materials.items()
            }
        d["shapes"] = [s.to_dict(explicit_material=explicit_materials) for s in self.shapes]
        d["lights"] = [light.to_dict() for light in self.lights]
        if include_empty or self.groups:
            d["groups"] = [g.to_dict(explicit_material=explicit_materials) for g in self.groups]
        return d

    def to_dict(self) -> dict:
        """Scene content as a dict (no version — used inside Shot)."""
        return self._normalized_copy(sync_material_bindings=True)._to_dict_unchecked(
            explicit_materials=True, include_empty=True
        )

    def to_wire_dict(self) -> dict:
        """Scene content for transient renderer wire JSON."""
        return self._normalized_copy(sync_material_bindings=False)._to_dict_unchecked(
            explicit_materials=False, include_empty=False
        )

    @staticmethod
    def _from_dict(d: dict) -> Scene:
        """Parse scene content from a dict (materials/shapes/lights/groups)."""
        d = _require_dict(d, "shot")
        _require_exact_keys(d, ("version", "name", "camera", "canvas", "look", "trace", "materials", "shapes", "lights", "groups"), "shot")
        scene = Scene()
        materials = _require_dict(d["materials"], "materials")
        for name, mat_d in materials.items():
            if not name:
                raise ValueError("material ids must be non-empty")
            scene.materials[name] = Material.from_dict(mat_d, explicit=True)
        shapes = d["shapes"]
        if not isinstance(shapes, list):
            raise ValueError("shapes must be an array")
        scene.shapes = _parse_shapes(shapes, scene.materials)
        lights = d["lights"]
        if not isinstance(lights, list):
            raise ValueError("lights must be an array")
        scene.lights = _parse_lights(lights)
        groups = d["groups"]
        if not isinstance(groups, list):
            raise ValueError("groups must be an array")
        for gd in groups:
            gd = _require_dict(gd, "group")
            _require_exact_keys(gd, ("id", "transform", "shapes", "lights"), "group")
            group = Group(id=_require_entity_id(gd, "group"))
            group.transform = Transform2D.from_dict(gd["transform"])
            if not isinstance(gd["shapes"], list):
                raise ValueError("group.shapes must be an array")
            if not isinstance(gd["lights"], list):
                raise ValueError("group.lights must be an array")
            group.shapes = _parse_shapes(gd["shapes"], scene.materials)
            group.lights = _parse_lights(gd["lights"])
            scene.groups.append(group)
        scene.sync_material_bindings().validate()
        return scene

    def find_group(self, entity_id: str) -> Group | None:
        for g in self.groups:
            if g.id == entity_id:
                return g
        return None

    def require_group(self, entity_id: str) -> Group:
        group = self.find_group(entity_id)
        if group is None:
            raise ValueError(f"unknown group id: {entity_id}")
        return group

    def find_shape(self, entity_id: str) -> Shape | None:
        for shape in self._iter_shapes():
            if shape.id == entity_id:
                return shape
        return None

    def require_shape(self, entity_id: str) -> Shape:
        shape = self.find_shape(entity_id)
        if shape is None:
            raise ValueError(f"unknown shape id: {entity_id}")
        return shape

    def find_light(self, entity_id: str) -> Light | None:
        for light in self._iter_lights():
            if light.id == entity_id:
                return light
        return None

    def require_light(self, entity_id: str) -> Light:
        light = self.find_light(entity_id)
        if light is None:
            raise ValueError(f"unknown light id: {entity_id}")
        return light

    def find_material(self, material_id: str) -> Material | None:
        return self.materials.get(material_id)

    def require_material(self, material_id: str) -> Material:
        material = self.find_material(material_id)
        if material is None:
            raise ValueError(f"unknown material_id: {material_id}")
        return material

    def set_material(self, material_id: str, material: Material) -> Material:
        if not material_id:
            raise ValueError("material ids must be non-empty")
        self.materials[material_id] = material
        for shape in self._iter_shapes():
            if shape.material_id == material_id:
                shape.material = material
        return material

    def bind_material(self, shape_id: str, material_id: str) -> Shape:
        material = self.require_material(material_id)
        shape = self.require_shape(shape_id)
        shape.material_id = material_id
        shape.material = material
        return shape

    def detach_material(self, shape_id: str) -> Shape:
        shape = self.require_shape(shape_id)
        shape.material_id = None
        shape.material = _clone_material(shape.material)
        return shape

    def rename_material(self, old_id: str, new_id: str) -> None:
        material = self.require_material(old_id)
        if not new_id:
            raise ValueError("material ids must be non-empty")
        if old_id != new_id and new_id in self.materials:
            raise ValueError(f"duplicate material_id: {new_id}")
        self.materials.pop(old_id)
        self.materials[new_id] = material
        for shape in self._iter_shapes():
            if shape.material_id == old_id:
                shape.material_id = new_id
                shape.material = material

    def delete_material(self, material_id: str) -> Material:
        material = self.require_material(material_id)
        self.materials.pop(material_id)
        for shape in self._iter_shapes():
            if shape.material_id == material_id:
                shape.material_id = None
                shape.material = _clone_material(material)
        return material

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
        """Serialize camera using the explicit authored schema."""
        if self.bounds is not None:
            return {"bounds": self.bounds}
        if self.center is not None and self.width is not None:
            return {"center": self.center, "width": self.width}
        return {}

    @staticmethod
    def from_dict(d: dict) -> Camera2D:
        d = _require_dict(d, "camera")
        _reject_unknown_keys(d, ("bounds", "center", "width"), "camera")
        has_bounds = "bounds" in d
        has_center = "center" in d
        has_width = "width" in d
        if has_bounds and (has_center or has_width):
            raise ValueError("camera cannot mix bounds with center/width")
        if has_center != has_width:
            raise ValueError("camera requires both center and width, or neither")
        if has_bounds:
            bounds = _require_vec(d["bounds"], 4, "camera.bounds")
            return Camera2D(bounds=bounds)
        if has_center:
            return Camera2D(
                center=_require_vec(d["center"], 2, "camera.center"),
                width=_require_number(d["width"], "camera.width"),
            )
        return Camera2D()


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
        d = _require_dict(d, "canvas")
        _require_exact_keys(d, ("width", "height"), "canvas")
        return Canvas(width=_require_int(d["width"], "canvas.width"), height=_require_int(d["height"], "canvas.height"))


_LOOK_FIELDS = (
    "exposure",
    "contrast",
    "gamma",
    "tonemap",
    "white_point",
    "normalize",
    "normalize_ref",
    "normalize_pct",
    "ambient",
    "background",
    "opacity",
    "saturation",
    "vignette",
    "vignette_radius",
)
_LOOK_UNSET = object()


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
    saturation: float = 1.0
    vignette: float = 0.0
    vignette_radius: float = 0.7
    _explicit_fields: frozenset[str] = field(
        default_factory=frozenset, init=False, repr=False, compare=False
    )

    def __init__(
        self,
        exposure: float | object = _LOOK_UNSET,
        contrast: float | object = _LOOK_UNSET,
        gamma: float | object = _LOOK_UNSET,
        tonemap: str | object = _LOOK_UNSET,
        white_point: float | object = _LOOK_UNSET,
        normalize: str | object = _LOOK_UNSET,
        normalize_ref: float | object = _LOOK_UNSET,
        normalize_pct: float | object = _LOOK_UNSET,
        ambient: float | object = _LOOK_UNSET,
        background: list[float] | object = _LOOK_UNSET,
        opacity: float | object = _LOOK_UNSET,
        saturation: float | object = _LOOK_UNSET,
        vignette: float | object = _LOOK_UNSET,
        vignette_radius: float | object = _LOOK_UNSET,
    ) -> None:
        explicit: set[str] = set()

        def choose(name: str, value: object, default):
            if value is _LOOK_UNSET:
                return list(default) if isinstance(default, list) else default
            explicit.add(name)
            return list(value) if name == "background" else value

        object.__setattr__(self, "exposure", choose("exposure", exposure, -5.0))
        object.__setattr__(self, "contrast", choose("contrast", contrast, 1.0))
        object.__setattr__(self, "gamma", choose("gamma", gamma, 2.0))
        object.__setattr__(self, "tonemap", choose("tonemap", tonemap, "reinhardx"))
        object.__setattr__(self, "white_point", choose("white_point", white_point, 0.5))
        object.__setattr__(self, "normalize", choose("normalize", normalize, "rays"))
        object.__setattr__(self, "normalize_ref", choose("normalize_ref", normalize_ref, 0.0))
        object.__setattr__(self, "normalize_pct", choose("normalize_pct", normalize_pct, 1.0))
        object.__setattr__(self, "ambient", choose("ambient", ambient, 0.0))
        object.__setattr__(self, "background", choose("background", background, [0.0, 0.0, 0.0]))
        object.__setattr__(self, "opacity", choose("opacity", opacity, 1.0))
        object.__setattr__(self, "saturation", choose("saturation", saturation, 1.0))
        object.__setattr__(self, "vignette", choose("vignette", vignette, 0.0))
        object.__setattr__(self, "vignette_radius", choose("vignette_radius", vignette_radius, 0.7))
        object.__setattr__(self, "_explicit_fields", frozenset(explicit))

    def to_dict(self) -> dict:
        """Emit the full authored look block."""
        return {
            "exposure": self.exposure,
            "contrast": self.contrast,
            "gamma": self.gamma,
            "tonemap": self.tonemap,
            "white_point": self.white_point,
            "normalize": self.normalize,
            "normalize_ref": self.normalize_ref,
            "normalize_pct": self.normalize_pct,
            "ambient": self.ambient,
            "background": list(self.background),
            "opacity": self.opacity,
            "saturation": self.saturation,
            "vignette": self.vignette,
            "vignette_radius": self.vignette_radius,
        }

    def to_override_dict(self) -> dict:
        """Only emit fields explicitly provided by the caller.

        This preserves partial override semantics for ``Frame.look`` while still
        allowing explicit resets back to default-valued fields such as
        ``vignette=0.0``.
        """
        d: dict = {}
        for name in self._explicit_fields:
            val = getattr(self, name)
            d[name] = list(val) if name == "background" else val
        return d

    def with_overrides(self, **overrides) -> Look:
        """Return a new Look with specified fields overridden."""
        values = {name: getattr(self, name) for name in _LOOK_FIELDS}
        values.update(overrides)
        updated = Look(**values)
        updated._explicit_fields = frozenset(set(self._explicit_fields) | set(overrides))
        return updated

    @staticmethod
    def from_dict(d: dict) -> Look:
        d = _require_dict(d, "look")
        _require_exact_keys(d, _LOOK_FIELDS, "look")
        tonemap = _require_string(d["tonemap"], "look.tonemap")
        if tonemap not in _CANONICAL_TONEMAPS:
            raise ValueError(f"invalid tonemap: {tonemap}")
        normalize = _require_string(d["normalize"], "look.normalize")
        if normalize not in _CANONICAL_NORMALIZE:
            raise ValueError(f"invalid normalize mode: {normalize}")
        return Look(
            exposure=_require_number(d["exposure"], "look.exposure"),
            contrast=_require_number(d["contrast"], "look.contrast"),
            gamma=_require_number(d["gamma"], "look.gamma"),
            tonemap=tonemap,
            white_point=_require_number(d["white_point"], "look.white_point"),
            normalize=normalize,
            normalize_ref=_require_number(d["normalize_ref"], "look.normalize_ref"),
            normalize_pct=_require_number(d["normalize_pct"], "look.normalize_pct"),
            ambient=_require_number(d["ambient"], "look.ambient"),
            background=_require_vec(d["background"], 3, "look.background"),
            opacity=_require_number(d["opacity"], "look.opacity"),
            saturation=_require_number(d["saturation"], "look.saturation"),
            vignette=_require_number(d["vignette"], "look.vignette"),
            vignette_radius=_require_number(d["vignette_radius"], "look.vignette_radius"),
        )


@dataclass
class TraceDefaults:
    """Ray tracing quality defaults."""

    rays: int = 10_000_000
    batch: int = 200_000
    depth: int = 12
    intensity: float = 1.0

    def to_dict(self) -> dict:
        return {
            "rays": self.rays,
            "batch": self.batch,
            "depth": self.depth,
            "intensity": self.intensity,
        }

    @staticmethod
    def from_dict(d: dict) -> TraceDefaults:
        d = _require_dict(d, "trace")
        _require_exact_keys(d, ("rays", "batch", "depth", "intensity"), "trace")
        return TraceDefaults(
            rays=_require_int(d["rays"], "trace.rays"),
            batch=_require_int(d["batch"], "trace.batch"),
            depth=_require_int(d["depth"], "trace.depth"),
            intensity=_require_number(d["intensity"], "trace.intensity"),
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
        """Full v5 format dict."""
        d: dict = {"version": SHOT_JSON_VERSION, "name": self.name}
        d["camera"] = (self.camera or Camera2D()).to_dict()
        d["canvas"] = self.canvas.to_dict()
        d["look"] = self.look.to_dict()
        d["trace"] = self.trace.to_dict()
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
        """Parse shot from JSON."""
        d = _require_dict(json.loads(s), "shot")
        version = d.get("version")
        if version != SHOT_JSON_VERSION:
            raise ValueError(f"unsupported shot version: {version} (expected {SHOT_JSON_VERSION})")
        _require_exact_keys(d, ("version", "name", "camera", "canvas", "look", "trace", "materials", "shapes", "lights", "groups"), "shot")
        shot = Shot(name=_require_string(d["name"], "shot.name"))
        shot.camera = Camera2D.from_dict(d["camera"])
        shot.canvas = Canvas.from_dict(d["canvas"])
        shot.look = Look.from_dict(d["look"])
        shot.trace = TraceDefaults.from_dict(d["trace"])
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
