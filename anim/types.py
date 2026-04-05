"""Scene model and animation types for lpt2d."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field, fields, replace
from enum import Enum
from pathlib import Path

SHOT_JSON_VERSION = 5

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


def _material_payload(material: Material, material_id: str | None) -> dict:
    if material_id:
        return {"material_id": material_id}
    return {"material": material.to_dict()}


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

    def to_dict(self) -> dict:
        d = {
            "id": self.id,
            "type": "circle",
            "center": self.center,
            "radius": self.radius,
        }
        d.update(_material_payload(self.material, self.material_id))
        return d


@dataclass
class Segment:
    id: str = ""
    a: list[float] = field(default_factory=lambda: [0.0, 0.0])
    b: list[float] = field(default_factory=lambda: [1.0, 0.0])
    material: Material = field(default_factory=Material)
    material_id: str | None = None

    def to_dict(self) -> dict:
        d = {"id": self.id, "type": "segment", "a": self.a, "b": self.b}
        d.update(_material_payload(self.material, self.material_id))
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

    def to_dict(self) -> dict:
        d = {
            "id": self.id,
            "type": "arc",
            "center": self.center,
            "radius": self.radius,
            "angle_start": normalize_angle(self.angle_start),
            "sweep": clamp_arc_sweep(self.sweep),
        }
        d.update(_material_payload(self.material, self.material_id))
        return d


@dataclass
class Bezier:
    id: str = ""
    p0: list[float] = field(default_factory=lambda: [0.0, 0.0])
    p1: list[float] = field(default_factory=lambda: [0.5, 0.5])
    p2: list[float] = field(default_factory=lambda: [1.0, 0.0])
    material: Material = field(default_factory=Material)
    material_id: str | None = None

    def to_dict(self) -> dict:
        d = {
            "id": self.id,
            "type": "bezier",
            "p0": self.p0,
            "p1": self.p1,
            "p2": self.p2,
        }
        d.update(_material_payload(self.material, self.material_id))
        return d


@dataclass
class Polygon:
    id: str = ""
    vertices: list[list[float]] = field(default_factory=list)
    material: Material = field(default_factory=Material)
    material_id: str | None = None

    def to_dict(self) -> dict:
        d = {
            "id": self.id,
            "type": "polygon",
            "vertices": self.vertices,
        }
        d.update(_material_payload(self.material, self.material_id))
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

    def to_dict(self) -> dict:
        d = {
            "id": self.id,
            "type": "ellipse",
            "center": self.center,
            "semi_a": self.semi_a,
            "semi_b": self.semi_b,
            "rotation": self.rotation,
        }
        d.update(_material_payload(self.material, self.material_id))
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
        return Transform2D(
            translate=d.get("translate", [0.0, 0.0]),
            rotate=d.get("rotate", 0.0),
            scale=d.get("scale", [1.0, 1.0]),
        )


@dataclass
class Group:
    id: str = ""
    transform: Transform2D = field(default_factory=Transform2D)
    shapes: list[Shape] = field(default_factory=list)
    lights: list[Light] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "transform": self.transform.to_dict(),
            "shapes": [s.to_dict() for s in self.shapes],
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
    return Material.from_dict(d["material"]), None


def _parse_shape(d: dict, materials: dict[str, Material]) -> Shape:
    shape_id = _require_entity_id(d, "shape")
    material, material_id = _parse_shape_material(d, materials)
    shape_type = d.get("type", "")
    if shape_type == "circle":
        return Circle(
            id=shape_id,
            center=d["center"],
            radius=d["radius"],
            material=material,
            material_id=material_id,
        )
    if shape_type == "segment":
        return Segment(id=shape_id, a=d["a"], b=d["b"], material=material, material_id=material_id)
    if shape_type == "arc":
        return Arc(
            id=shape_id,
            center=d["center"],
            radius=d["radius"],
            angle_start=d.get("angle_start", 0.0),
            sweep=d.get("sweep", math.tau),
            material=material,
            material_id=material_id,
        )
    if shape_type == "bezier":
        return Bezier(
            id=shape_id,
            p0=d["p0"],
            p1=d["p1"],
            p2=d["p2"],
            material=material,
            material_id=material_id,
        )
    if shape_type == "polygon":
        return Polygon(
            id=shape_id,
            vertices=d["vertices"],
            material=material,
            material_id=material_id,
        )
    if shape_type == "ellipse":
        return Ellipse(
            id=shape_id,
            center=d["center"],
            semi_a=d.get("semi_a", 0.2),
            semi_b=d.get("semi_b", 0.1),
            rotation=d.get("rotation", 0.0),
            material=material,
            material_id=material_id,
        )
    raise ValueError(f"unknown shape type: {shape_type}")


def _parse_shapes(arr: list[dict], materials: dict[str, Material]) -> list[Shape]:
    return [_parse_shape(d, materials) for d in arr]


def _parse_light(d: dict) -> Light:
    light_id = _require_entity_id(d, "light")
    light_type = d.get("type", "")
    if light_type == "point":
        return PointLight(
            id=light_id,
            pos=d["pos"],
            intensity=d.get("intensity", 1.0),
            wavelength_min=d.get("wavelength_min", 380.0),
            wavelength_max=d.get("wavelength_max", 780.0),
        )
    if light_type == "segment":
        return SegmentLight(
            id=light_id,
            a=d["a"],
            b=d["b"],
            intensity=d.get("intensity", 1.0),
            wavelength_min=d.get("wavelength_min", 380.0),
            wavelength_max=d.get("wavelength_max", 780.0),
        )
    if light_type == "beam":
        return BeamLight(
            id=light_id,
            origin=d["origin"],
            direction=d["direction"],
            angular_width=d.get("angular_width", 0.1),
            intensity=d.get("intensity", 1.0),
            wavelength_min=d.get("wavelength_min", 380.0),
            wavelength_max=d.get("wavelength_max", 780.0),
        )
    if light_type == "parallel_beam":
        return ParallelBeamLight(
            id=light_id,
            a=d.get("a", [0.0, 0.0]),
            b=d.get("b", [0.0, 0.5]),
            direction=d.get("direction", [1.0, 0.0]),
            angular_width=d.get("angular_width", 0.0),
            intensity=d.get("intensity", 1.0),
            wavelength_min=d.get("wavelength_min", 380.0),
            wavelength_max=d.get("wavelength_max", 780.0),
        )
    if light_type == "spot":
        return SpotLight(
            id=light_id,
            pos=d.get("pos", [0.0, 0.0]),
            direction=d.get("direction", [1.0, 0.0]),
            angular_width=d.get("angular_width", 0.5),
            falloff=d.get("falloff", 2.0),
            intensity=d.get("intensity", 1.0),
            wavelength_min=d.get("wavelength_min", 380.0),
            wavelength_max=d.get("wavelength_max", 780.0),
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

    def _to_dict_unchecked(self) -> dict:
        d: dict = {}
        if self.materials:
            d["materials"] = {name: mat.to_dict() for name, mat in self.materials.items()}
        d["shapes"] = [s.to_dict() for s in self.shapes]
        d["lights"] = [light.to_dict() for light in self.lights]
        if self.groups:
            d["groups"] = [g.to_dict() for g in self.groups]
        return d

    def to_dict(self) -> dict:
        """Scene content as a dict (no version — used inside Shot)."""
        return self._normalized_copy(sync_material_bindings=True)._to_dict_unchecked()

    def to_wire_dict(self) -> dict:
        """Scene content for transient renderer wire JSON."""
        return self._normalized_copy(sync_material_bindings=False)._to_dict_unchecked()

    @staticmethod
    def _from_dict(d: dict) -> Scene:
        """Parse scene content from a dict (materials/shapes/lights/groups)."""
        scene = Scene()
        for name, mat_d in d.get("materials", {}).items():
            if not name:
                raise ValueError("material ids must be non-empty")
            scene.materials[name] = Material.from_dict(mat_d)
        scene.shapes = _parse_shapes(d.get("shapes", []), scene.materials)
        scene.lights = _parse_lights(d.get("lights", []))
        for gd in d.get("groups", []):
            group = Group(id=_require_entity_id(gd, "group"))
            if "transform" in gd:
                group.transform = Transform2D.from_dict(gd["transform"])
            group.shapes = _parse_shapes(gd.get("shapes", []), scene.materials)
            group.lights = _parse_lights(gd.get("lights", []))
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
        """Full v5 format dict."""
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
        """Parse shot from JSON."""
        d = json.loads(s)
        version = d.get("version")
        if version != SHOT_JSON_VERSION:
            raise ValueError(f"unsupported shot version: {version} (expected {SHOT_JSON_VERSION})")
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
