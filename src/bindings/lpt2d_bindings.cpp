#include <nanobind/nanobind.h>
#include <nanobind/stl/array.h>
#include <nanobind/stl/map.h>
#include <nanobind/stl/optional.h>
#include <nanobind/stl/string.h>
#include <nanobind/stl/variant.h>
#include <nanobind/stl/vector.h>

#include "color.h"
#include "geometry.h"
#include "scene.h"
#include "serialize.h"
#include "session.h"
#include "spectrum.h"

#include <sstream>

namespace nb = nanobind;
using namespace nb::literals;

// ─── Vec2 type caster ────────────────────────────────────────────
// Allows Python lists/tuples of 2 floats to auto-convert to Vec2.

namespace nanobind { namespace detail {
template <> struct type_caster<Vec2> {
    NB_TYPE_CASTER(Vec2, const_name("Vec2"))

    bool from_python(handle src, uint8_t, cleanup_list*) noexcept {
        if (isinstance<nb::tuple>(src) || isinstance<nb::list>(src)) {
            nb::sequence seq = nb::borrow<nb::sequence>(src);
            if (nb::len(seq) != 2) return false;
            try {
                value.x = nb::cast<float>(seq[0]);
                value.y = nb::cast<float>(seq[1]);
                return true;
            } catch (...) { return false; }
        }
        return false;
    }

    static handle from_cpp(Vec2 v, rv_policy, cleanup_list*) noexcept {
        return nb::make_tuple(v.x, v.y).release();
    }
};
}} // namespace nanobind::detail

// ─── Helpers ─────────────────────────────────────────────────────

static ToneMap parse_tonemap_arg(nb::object obj) {
    if (nb::isinstance<nb::str>(obj)) {
        auto s = nb::cast<std::string>(obj);
        if (auto tm = parse_tonemap(s)) return *tm;
        throw nb::value_error(("invalid tonemap: " + s).c_str());
    }
    return nb::cast<ToneMap>(obj);
}

static NormalizeMode parse_normalize_arg(nb::object obj) {
    if (nb::isinstance<nb::str>(obj)) {
        auto s = nb::cast<std::string>(obj);
        if (auto nm = parse_normalize_mode(s)) return *nm;
        throw nb::value_error(("invalid normalize mode: " + s).c_str());
    }
    return nb::cast<NormalizeMode>(obj);
}

static SeedMode parse_seed_mode_arg(nb::object obj) {
    if (nb::isinstance<nb::str>(obj)) {
        auto s = nb::cast<std::string>(obj);
        if (auto mode = parse_seed_mode(s)) return *mode;
        throw nb::value_error(("invalid seed mode: " + s).c_str());
    }
    return nb::cast<SeedMode>(obj);
}

static ProjectorProfile parse_projector_profile_arg(nb::object obj) {
    if (nb::isinstance<nb::str>(obj)) {
        auto s = nb::cast<std::string>(obj);
        if (auto profile = parse_projector_profile(s)) return *profile;
        throw nb::value_error(("invalid projector profile: " + s).c_str());
    }
    return nb::cast<ProjectorProfile>(obj);
}

static ProjectorSource parse_projector_source_arg(nb::object obj) {
    if (nb::isinstance<nb::str>(obj)) {
        auto s = nb::cast<std::string>(obj);
        if (auto source = parse_projector_source(s)) return *source;
        throw nb::value_error(("invalid projector source: " + s).c_str());
    }
    return nb::cast<ProjectorSource>(obj);
}

static PolygonJoinMode parse_polygon_join_mode_arg(nb::object obj) {
    if (nb::isinstance<nb::str>(obj)) {
        auto s = nb::cast<std::string>(obj);
        if (auto mode = parse_polygon_join_mode(s)) return *mode;
        throw nb::value_error(("invalid polygon join mode: " + s).c_str());
    }
    return nb::cast<PolygonJoinMode>(obj);
}

static std::vector<PolygonJoinMode> parse_polygon_join_modes_arg(nb::object obj) {
    if (obj.is_none())
        return {};
    if (!(nb::isinstance<nb::tuple>(obj) || nb::isinstance<nb::list>(obj)))
        throw nb::type_error("join_modes must be a sequence");

    nb::sequence seq = nb::borrow<nb::sequence>(obj);
    std::vector<PolygonJoinMode> join_modes;
    join_modes.reserve((size_t)nb::len(seq));
    for (nb::handle item : seq)
        join_modes.push_back(parse_polygon_join_mode_arg(nb::borrow<nb::object>(item)));
    return join_modes;
}

// ─── Module ──────────────────────────────────────────────────────

NB_MODULE(_lpt2d, m) {
    m.doc() = "lpt2d core C++ bindings";

    // Suppress leak warnings at interpreter shutdown — these are false positives
    // caused by Python module cleanup ordering, not actual memory leaks.
    nb::set_leak_warnings(false);

    // ── Enums ────────────────────────────────────────────────────
    nb::enum_<ToneMap>(m, "ToneMap")
        .value("none", ToneMap::None)
        .value("reinhard", ToneMap::Reinhard)
        .value("reinhardx", ToneMap::ReinhardExtended)
        .value("aces", ToneMap::ACES)
        .value("log", ToneMap::Logarithmic);

    nb::enum_<NormalizeMode>(m, "NormalizeMode")
        .value("max", NormalizeMode::Max)
        .value("rays", NormalizeMode::Rays)
        .value("fixed", NormalizeMode::Fixed)
        .value("off", NormalizeMode::Off);

    nb::enum_<SeedMode>(m, "SeedMode")
        .value("deterministic", SeedMode::Deterministic)
        .value("decorrelated", SeedMode::Decorrelated);

    nb::enum_<ProjectorProfile>(m, "ProjectorProfile")
        .value("uniform", ProjectorProfile::Uniform)
        .value("soft", ProjectorProfile::Soft)
        .value("gaussian", ProjectorProfile::Gaussian);

    nb::enum_<ProjectorSource>(m, "ProjectorSource")
        .value("line", ProjectorSource::Line)
        .value("ball", ProjectorSource::Ball);

    nb::enum_<PolygonJoinMode>(m, "PolygonJoinMode")
        .value("auto", PolygonJoinMode::Auto)
        .value("sharp", PolygonJoinMode::Sharp)
        .value("smooth", PolygonJoinMode::Smooth);

    // ── Material ─────────────────────────────────────────────────
    nb::class_<Material>(m, "Material")
        .def("__init__", [](Material* mat,
                            float ior, float roughness, float metallic, float transmission,
                            float absorption, float cauchy_b, float albedo, float emission,
                            float spectral_c0, float spectral_c1, float spectral_c2, float fill) {
            new (mat) Material{ior, roughness, metallic, transmission, absorption, cauchy_b, albedo, emission,
                               spectral_c0, spectral_c1, spectral_c2, fill};
        }, "ior"_a = 1.0f, "roughness"_a = 0.0f, "metallic"_a = 0.0f, "transmission"_a = 0.0f,
           "absorption"_a = 0.0f, "cauchy_b"_a = 0.0f, "albedo"_a = 1.0f, "emission"_a = 0.0f,
           "spectral_c0"_a = 0.0f, "spectral_c1"_a = 0.0f, "spectral_c2"_a = 0.0f, "fill"_a = 0.0f)
        .def_rw("ior", &Material::ior)
        .def_rw("roughness", &Material::roughness)
        .def_rw("metallic", &Material::metallic)
        .def_rw("transmission", &Material::transmission)
        .def_rw("absorption", &Material::absorption)
        .def_rw("cauchy_b", &Material::cauchy_b)
        .def_rw("albedo", &Material::albedo)
        .def_rw("emission", &Material::emission)
        .def_rw("spectral_c0", &Material::spectral_c0)
        .def_rw("spectral_c1", &Material::spectral_c1)
        .def_rw("spectral_c2", &Material::spectral_c2)
        .def_rw("fill", &Material::fill)
        .def("__eq__", &Material::operator==)
        .def("__repr__", [](const Material& mat) {
            std::ostringstream os;
            os << "Material(ior=" << mat.ior << ", roughness=" << mat.roughness
               << ", metallic=" << mat.metallic << ", transmission=" << mat.transmission
               << ", absorption=" << mat.absorption << ", cauchy_b=" << mat.cauchy_b
               << ", albedo=" << mat.albedo << ", emission=" << mat.emission
               << ", spectral_c0=" << mat.spectral_c0
               << ", spectral_c1=" << mat.spectral_c1
               << ", spectral_c2=" << mat.spectral_c2
               << ", fill=" << mat.fill << ")";
            return os.str();
        });

    // Material convenience constructors
    m.def("glass", &mat_glass, "ior"_a = 1.5f, "cauchy_b"_a = 0.0f, "absorption"_a = 0.0f);
    m.def("mirror", &mat_mirror, "reflectance"_a, "roughness"_a = 0.0f);
    m.def("opaque_mirror", &mat_opaque_mirror, "reflectance"_a, "roughness"_a = 0.0f);
    m.def("diffuse", &mat_diffuse, "reflectance"_a);
    m.def("absorber", &mat_absorber);
    m.def("emissive", &mat_emissive, "emission"_a, "base"_a = Material{});

    // ── Color convenience ───────────────────────────────────────
    m.def("named_color", [](const std::string& name) -> nb::tuple {
        auto result = named_color(name);
        if (!result) throw nb::value_error(("unknown color name: " + name).c_str());
        return nb::make_tuple(result->c0, result->c1, result->c2);
    }, "name"_a);
    m.def("spectral_fill_rgb", [](float c0, float c1, float c2) -> nb::tuple {
        Vec3 rgb = spectral_fill_rgb(c0, c1, c2);
        return nb::make_tuple(rgb.r, rgb.g, rgb.b);
    }, "c0"_a, "c1"_a, "c2"_a);
    m.def("rgb_to_spectral", [](float r, float g, float b) -> nb::tuple {
        SpectralCoeffs sc = rgb_to_spectral(r, g, b);
        return nb::make_tuple(sc.c0, sc.c1, sc.c2);
    }, "r"_a, "g"_a, "b"_a);
    m.def("named_color_list", []() -> nb::list {
        nb::list result;
        for (const auto* e = named_colors(); e->name; ++e)
            result.append(nb::make_tuple(e->name, e->r, e->g, e->b));
        return result;
    });

    // ── Shape types ──────────────────────────────────────────────

    // Helper: build MaterialBinding from Python material + material_id kwargs.
    // material_id takes precedence if non-empty.
    auto make_binding = [](nb::object material, std::string material_id) -> MaterialBinding {
        if (!material_id.empty())
            return material_id;
        if (!material.is_none() && nb::isinstance<Material>(material))
            return nb::cast<Material>(material);
        return Material{};
    };

    // Material property helpers — present material/material_id as separate Python properties
    auto mat_getter = [](const auto& s) -> Material {
        if (auto* mat = std::get_if<Material>(&s.binding)) return *mat;
        return Material{};
    };
    auto mat_setter = [](auto& s, const Material& mat) { s.binding = mat; };
    auto mid_getter = [](const auto& s) -> std::string {
        if (auto* str = std::get_if<std::string>(&s.binding)) return *str;
        return {};
    };
    auto mid_setter = [](auto& s, std::string id) {
        if (id.empty()) { if (is_material_ref(s.binding)) s.binding = Material{}; }
        else s.binding = std::move(id);
    };

    nb::class_<Circle>(m, "Circle")
        .def("__init__", [=](Circle* c, std::string id, Vec2 center, float radius,
                             nb::object material, std::string material_id) {
            new (c) Circle{std::move(id), center, radius, make_binding(material, std::move(material_id))};
        }, "id"_a = "", "center"_a = Vec2{}, "radius"_a = 0.1f,
           "material"_a = nb::none(), "material_id"_a = "")
        .def_rw("id", &Circle::id)
        .def_rw("center", &Circle::center)
        .def_rw("radius", &Circle::radius)
        .def_prop_rw("material",
            [=](const Circle& c) { return mat_getter(c); },
            [=](Circle& c, const Material& m) { mat_setter(c, m); })
        .def_prop_rw("material_id",
            [=](const Circle& c) { return mid_getter(c); },
            [=](Circle& c, std::string id) { mid_setter(c, std::move(id)); })
        .def("__repr__", [](const Circle& c) {
            return "Circle(id='" + c.id + "', center=(" + std::to_string(c.center.x) + ", "
                   + std::to_string(c.center.y) + "), radius=" + std::to_string(c.radius) + ")";
        });

    nb::class_<Segment>(m, "Segment")
        .def("__init__", [=](Segment* s, std::string id, Vec2 a, Vec2 b,
                             nb::object material, std::string material_id) {
            new (s) Segment{std::move(id), a, b, make_binding(material, std::move(material_id))};
        }, "id"_a = "", "a"_a = Vec2{}, "b"_a = Vec2{},
           "material"_a = nb::none(), "material_id"_a = "")
        .def_rw("id", &Segment::id)
        .def_rw("a", &Segment::a)
        .def_rw("b", &Segment::b)
        .def_prop_rw("material",
            [=](const Segment& s) { return mat_getter(s); },
            [=](Segment& s, const Material& m) { mat_setter(s, m); })
        .def_prop_rw("material_id",
            [=](const Segment& s) { return mid_getter(s); },
            [=](Segment& s, std::string id) { mid_setter(s, std::move(id)); });

    nb::class_<Arc>(m, "Arc")
        .def("__init__", [=](Arc* a, std::string id, Vec2 center, float radius,
                             float angle_start, float sweep,
                             nb::object material, std::string material_id) {
            new (a) Arc{std::move(id), center, radius, angle_start, sweep,
                        make_binding(material, std::move(material_id))};
        }, "id"_a = "", "center"_a = Vec2{}, "radius"_a = 0.1f,
           "angle_start"_a = 0.0f, "sweep"_a = TWO_PI,
           "material"_a = nb::none(), "material_id"_a = "")
        .def_rw("id", &Arc::id)
        .def_rw("center", &Arc::center)
        .def_rw("radius", &Arc::radius)
        .def_rw("angle_start", &Arc::angle_start)
        .def_rw("sweep", &Arc::sweep)
        .def_prop_rw("material",
            [=](const Arc& a) { return mat_getter(a); },
            [=](Arc& a, const Material& m) { mat_setter(a, m); })
        .def_prop_rw("material_id",
            [=](const Arc& a) { return mid_getter(a); },
            [=](Arc& a, std::string id) { mid_setter(a, std::move(id)); });

    nb::class_<Bezier>(m, "Bezier")
        .def("__init__", [=](Bezier* b, std::string id, Vec2 p0, Vec2 p1, Vec2 p2,
                             nb::object material, std::string material_id) {
            new (b) Bezier{std::move(id), p0, p1, p2, make_binding(material, std::move(material_id))};
        }, "id"_a = "", "p0"_a = Vec2{}, "p1"_a = Vec2{0.5f, 0.5f}, "p2"_a = Vec2{1.0f, 0.0f},
           "material"_a = nb::none(), "material_id"_a = "")
        .def_rw("id", &Bezier::id)
        .def_rw("p0", &Bezier::p0)
        .def_rw("p1", &Bezier::p1)
        .def_rw("p2", &Bezier::p2)
        .def_prop_rw("material",
            [=](const Bezier& b) { return mat_getter(b); },
            [=](Bezier& b, const Material& m) { mat_setter(b, m); })
        .def_prop_rw("material_id",
            [=](const Bezier& b) { return mid_getter(b); },
            [=](Bezier& b, std::string id) { mid_setter(b, std::move(id)); });

    nb::class_<Polygon>(m, "Polygon")
        .def("__init__", [=](Polygon* p, std::string id, std::vector<Vec2> vertices,
                             nb::object material, std::string material_id, float corner_radius,
                             std::vector<float> corner_radii, float smooth_angle, nb::object join_modes_obj) {
            new (p) Polygon{};
            p->id = std::move(id);
            p->vertices = std::move(vertices);
            p->binding = make_binding(material, std::move(material_id));
            p->corner_radius = corner_radius;
            p->corner_radii = std::move(corner_radii);
            p->smooth_angle = smooth_angle;
            p->join_modes = parse_polygon_join_modes_arg(join_modes_obj);
        }, "id"_a = "", "vertices"_a = std::vector<Vec2>{},
           "material"_a = nb::none(), "material_id"_a = "", "corner_radius"_a = 0.0f,
           "corner_radii"_a = std::vector<float>{}, "smooth_angle"_a = 0.0f, "join_modes"_a = nb::none())
        .def_rw("id", &Polygon::id)
        .def_rw("vertices", &Polygon::vertices)
        .def_rw("corner_radius", &Polygon::corner_radius)
        .def_rw("corner_radii", &Polygon::corner_radii)
        .def_prop_rw("join_modes",
            [](const Polygon& p) { return p.join_modes; },
            [](Polygon& p, nb::object obj) { p.join_modes = parse_polygon_join_modes_arg(obj); })
        .def_rw("smooth_angle", &Polygon::smooth_angle)
        .def_prop_rw("material",
            [=](const Polygon& p) { return mat_getter(p); },
            [=](Polygon& p, const Material& m) { mat_setter(p, m); })
        .def_prop_rw("material_id",
            [=](const Polygon& p) { return mid_getter(p); },
            [=](Polygon& p, std::string id) { mid_setter(p, std::move(id)); });

    m.def("_polygon_fill_boundary", &polygon_fill_boundary,
          "polygon"_a, "arc_segments"_a = 8);
    m.def("_triangulate_simple_polygon", &triangulate_simple_polygon,
          "vertices"_a);

    nb::class_<Ellipse>(m, "Ellipse")
        .def("__init__", [=](Ellipse* e, std::string id, Vec2 center,
                             float semi_a, float semi_b, float rotation,
                             nb::object material, std::string material_id) {
            new (e) Ellipse{std::move(id), center, semi_a, semi_b, rotation,
                            make_binding(material, std::move(material_id))};
        }, "id"_a = "", "center"_a = Vec2{}, "semi_a"_a = 0.2f, "semi_b"_a = 0.1f,
           "rotation"_a = 0.0f, "material"_a = nb::none(), "material_id"_a = "")
        .def_rw("id", &Ellipse::id)
        .def_rw("center", &Ellipse::center)
        .def_rw("semi_a", &Ellipse::semi_a)
        .def_rw("semi_b", &Ellipse::semi_b)
        .def_rw("rotation", &Ellipse::rotation)
        .def_prop_rw("material",
            [=](const Ellipse& e) { return mat_getter(e); },
            [=](Ellipse& e, const Material& m) { mat_setter(e, m); })
        .def_prop_rw("material_id",
            [=](const Ellipse& e) { return mid_getter(e); },
            [=](Ellipse& e, std::string id) { mid_setter(e, std::move(id)); });

    nb::class_<Path>(m, "Path")
        .def("__init__", [=](Path* p, std::string id, std::vector<Vec2> points,
                             nb::object material, std::string material_id, bool closed) {
            new (p) Path{std::move(id), std::move(points),
                         make_binding(material, std::move(material_id)), closed};
        }, "id"_a = "", "points"_a = std::vector<Vec2>{},
           "material"_a = nb::none(), "material_id"_a = "", "closed"_a = false)
        .def_rw("id", &Path::id)
        .def_rw("points", &Path::points)
        .def_rw("closed", &Path::closed)
        .def_prop_rw("material",
            [=](const Path& p) { return mat_getter(p); },
            [=](Path& p, const Material& m) { mat_setter(p, m); })
        .def_prop_rw("material_id",
            [=](const Path& p) { return mid_getter(p); },
            [=](Path& p, std::string id) { mid_setter(p, std::move(id)); });

    // ── Light types ──────────────────────────────────────────────
    nb::class_<PointLight>(m, "PointLight")
        .def("__init__", [](PointLight* l, std::string id, Vec2 position, float intensity,
                            float wl_min, float wl_max) {
            new (l) PointLight{std::move(id), position, intensity, wl_min, wl_max};
        }, "id"_a = "", "position"_a = Vec2{}, "intensity"_a = 1.0f,
           "wavelength_min"_a = 380.0f, "wavelength_max"_a = 780.0f)
        .def_rw("id", &PointLight::id)
        .def_rw("position", &PointLight::position)
        .def_rw("intensity", &PointLight::intensity)
        .def_rw("wavelength_min", &PointLight::wavelength_min)
        .def_rw("wavelength_max", &PointLight::wavelength_max);

    nb::class_<SegmentLight>(m, "SegmentLight")
        .def("__init__", [](SegmentLight* l, std::string id, Vec2 a, Vec2 b,
                            float intensity, float wl_min, float wl_max) {
            new (l) SegmentLight{std::move(id), a, b, intensity, wl_min, wl_max};
        }, "id"_a = "", "a"_a = Vec2{}, "b"_a = Vec2{},
           "intensity"_a = 1.0f, "wavelength_min"_a = 380.0f, "wavelength_max"_a = 780.0f)
        .def_rw("id", &SegmentLight::id)
        .def_rw("a", &SegmentLight::a)
        .def_rw("b", &SegmentLight::b)
        .def_rw("intensity", &SegmentLight::intensity)
        .def_rw("wavelength_min", &SegmentLight::wavelength_min)
        .def_rw("wavelength_max", &SegmentLight::wavelength_max);

    nb::class_<ProjectorLight>(m, "ProjectorLight")
        .def("__init__", [](ProjectorLight* l, std::string id, Vec2 position, Vec2 direction,
                            float source_radius, float spread, nb::object profile_obj,
                            nb::object source_obj, float softness, float intensity,
                            float wl_min, float wl_max) {
            new (l) ProjectorLight{std::move(id), position, direction, source_radius, spread,
                                   parse_projector_profile_arg(profile_obj),
                                   parse_projector_source_arg(source_obj),
                                   softness, intensity, wl_min, wl_max};
        }, "id"_a = "", "position"_a = Vec2{}, "direction"_a = Vec2{1.0f, 0.0f},
           "source_radius"_a = 0.03f, "spread"_a = 0.1f, "profile"_a = nb::cast("uniform"),
           "source"_a = nb::cast("line"), "softness"_a = 0.0f, "intensity"_a = 1.0f,
           "wavelength_min"_a = 380.0f, "wavelength_max"_a = 780.0f)
        .def_rw("id", &ProjectorLight::id)
        .def_rw("position", &ProjectorLight::position)
        .def_rw("direction", &ProjectorLight::direction)
        .def_rw("source_radius", &ProjectorLight::source_radius)
        .def_rw("spread", &ProjectorLight::spread)
        .def_prop_rw("profile",
            [](const ProjectorLight& l) { return projector_profile_to_string(l.profile); },
            [](ProjectorLight& l, nb::object obj) { l.profile = parse_projector_profile_arg(obj); })
        .def_prop_rw("source",
            [](const ProjectorLight& l) { return projector_source_to_string(l.source); },
            [](ProjectorLight& l, nb::object obj) { l.source = parse_projector_source_arg(obj); })
        .def_rw("softness", &ProjectorLight::softness)
        .def_rw("intensity", &ProjectorLight::intensity)
        .def_rw("wavelength_min", &ProjectorLight::wavelength_min)
        .def_rw("wavelength_max", &ProjectorLight::wavelength_max);

    // ── Transform2D & Group ──────────────────────────────────────
    nb::class_<Transform2D>(m, "Transform2D")
        .def("__init__", [](Transform2D* t, Vec2 translate, float rotate, Vec2 scale) {
            new (t) Transform2D{translate, rotate, scale};
        }, "translate"_a = Vec2{}, "rotate"_a = 0.0f, "scale"_a = Vec2{1.0f, 1.0f})
        .def_rw("translate", &Transform2D::translate)
        .def_rw("rotate", &Transform2D::rotate)
        .def_rw("scale", &Transform2D::scale);

    nb::class_<Group>(m, "Group")
        .def("__init__", [](Group* g, std::string id, Transform2D transform,
                            std::vector<Shape> shapes, std::vector<Light> lights) {
            new (g) Group{std::move(id), transform, std::move(shapes), std::move(lights)};
        }, "id"_a = "", "transform"_a = Transform2D{},
           "shapes"_a = std::vector<Shape>{}, "lights"_a = std::vector<Light>{})
        .def_rw("id", &Group::id)
        .def_rw("transform", &Group::transform)
        .def_rw("shapes", &Group::shapes)
        .def_rw("lights", &Group::lights);

    // ── Scene ────────────────────────────────────────────────────
    nb::class_<Scene>(m, "Scene")
        .def("__init__", [](Scene* s, std::vector<Shape> shapes, std::vector<Light> lights,
                            std::vector<Group> groups, std::map<std::string, Material> materials) {
            new (s) Scene{std::move(shapes), std::move(lights), std::move(groups), std::move(materials)};
        }, "shapes"_a = std::vector<Shape>{}, "lights"_a = std::vector<Light>{},
           "groups"_a = std::vector<Group>{}, "materials"_a = std::map<std::string, Material>{})
        .def_rw("shapes", &Scene::shapes)
        .def_rw("lights", &Scene::lights)
        .def_rw("groups", &Scene::groups)
        .def_rw("materials", &Scene::materials);

    // ── Camera2D ─────────────────────────────────────────────────
    nb::class_<Bounds>(m, "Bounds")
        .def("__init__", [](Bounds* b, Vec2 min, Vec2 max) {
            new (b) Bounds{min, max};
        }, "min"_a = Vec2{}, "max"_a = Vec2{})
        .def_rw("min", &Bounds::min)
        .def_rw("max", &Bounds::max);

    nb::class_<Camera2D>(m, "Camera2D")
        .def("__init__", [](Camera2D* c, nb::object bounds_obj,
                            std::optional<Vec2> center, std::optional<float> width) {
            std::optional<Bounds> bounds;
            if (!bounds_obj.is_none()) {
                // Accept Bounds object or [xmin, ymin, xmax, ymax] list
                if (nb::isinstance<Bounds>(bounds_obj)) {
                    bounds = nb::cast<Bounds>(bounds_obj);
                } else {
                    nb::list lst = nb::cast<nb::list>(bounds_obj);
                    if (nb::len(lst) != 4) throw nb::value_error("bounds must have 4 elements");
                    bounds = Bounds{{nb::cast<float>(lst[0]), nb::cast<float>(lst[1])},
                                   {nb::cast<float>(lst[2]), nb::cast<float>(lst[3])}};
                }
            }
            new (c) Camera2D{bounds, center, width};
        }, "bounds"_a = nb::none(), "center"_a = nb::none(), "width"_a = nb::none())
        .def_rw("bounds", &Camera2D::bounds)
        .def_rw("center", &Camera2D::center)
        .def_rw("width", &Camera2D::width)
        .def("empty", &Camera2D::empty);

    // ── Canvas ───────────────────────────────────────────────────
    nb::class_<Canvas>(m, "Canvas")
        .def("__init__", [](Canvas* c, int width, int height) {
            new (c) Canvas{width, height};
        }, "width"_a = 1920, "height"_a = 1080)
        .def_rw("width", &Canvas::width)
        .def_rw("height", &Canvas::height)
        .def_prop_ro("aspect", &Canvas::aspect);

    // ── Look ─────────────────────────────────────────────────────
    nb::class_<Look>(m, "Look")
        .def("__init__", [](Look* l, float exposure, float contrast, float gamma,
                            nb::object tonemap_obj, float white_point,
                            nb::object normalize_obj,
                            float normalize_ref, float normalize_pct,
                            float ambient, std::array<float, 3> background,
                            float opacity, float saturation,
                            float vignette, float vignette_radius,
                            float temperature, float highlights, float shadows,
                            float hue_shift, float grain, int grain_seed,
                            float chromatic_aberration) {
            new (l) Look{exposure, contrast, gamma,
                         parse_tonemap_arg(tonemap_obj), white_point,
                         parse_normalize_arg(normalize_obj),
                         normalize_ref, normalize_pct,
                         ambient, {background[0], background[1], background[2]},
                         opacity, saturation, vignette, vignette_radius,
                         temperature, highlights, shadows, hue_shift,
                         grain, grain_seed, chromatic_aberration};
        }, "exposure"_a = -5.0f, "contrast"_a = 1.0f, "gamma"_a = 2.0f,
           "tonemap"_a = nb::cast("reinhardx"), "white_point"_a = 0.5f,
           "normalize"_a = nb::cast("rays"),
           "normalize_ref"_a = 0.0f, "normalize_pct"_a = 1.0f,
           "ambient"_a = 0.0f, "background"_a = std::array<float, 3>{0, 0, 0},
           "opacity"_a = 1.0f, "saturation"_a = 1.0f,
           "vignette"_a = 0.0f, "vignette_radius"_a = 0.7f,
           "temperature"_a = 0.0f, "highlights"_a = 0.0f, "shadows"_a = 0.0f,
           "hue_shift"_a = 0.0f, "grain"_a = 0.0f, "grain_seed"_a = 0,
           "chromatic_aberration"_a = 0.0f)
        .def_rw("exposure", &Look::exposure)
        .def_rw("contrast", &Look::contrast)
        .def_rw("gamma", &Look::gamma)
        .def_prop_rw("tonemap",
            [](const Look& l) { return tonemap_to_string(l.tonemap); },
            [](Look& l, nb::object obj) { l.tonemap = parse_tonemap_arg(obj); })
        .def_rw("white_point", &Look::white_point)
        .def_prop_rw("normalize",
            [](const Look& l) { return normalize_mode_to_string(l.normalize); },
            [](Look& l, nb::object obj) { l.normalize = parse_normalize_arg(obj); })
        .def_rw("normalize_ref", &Look::normalize_ref)
        .def_rw("normalize_pct", &Look::normalize_pct)
        .def_rw("ambient", &Look::ambient)
        .def_prop_rw("background",
            [](const Look& l) { return std::array<float, 3>{l.background[0], l.background[1], l.background[2]}; },
            [](Look& l, std::array<float, 3> bg) { l.background[0] = bg[0]; l.background[1] = bg[1]; l.background[2] = bg[2]; })
        .def_rw("opacity", &Look::opacity)
        .def_rw("saturation", &Look::saturation)
        .def_rw("vignette", &Look::vignette)
        .def_rw("vignette_radius", &Look::vignette_radius)
        .def_rw("temperature", &Look::temperature)
        .def_rw("highlights", &Look::highlights)
        .def_rw("shadows", &Look::shadows)
        .def_rw("hue_shift", &Look::hue_shift)
        .def_rw("grain", &Look::grain)
        .def_rw("grain_seed", &Look::grain_seed)
        .def_rw("chromatic_aberration", &Look::chromatic_aberration)
        .def("to_post_process", &Look::to_post_process);

    // ── TraceDefaults ────────────────────────────────────────────
    nb::class_<TraceDefaults>(m, "TraceDefaults")
        .def("__init__", [](TraceDefaults* t, int64_t rays, int batch, int depth, float intensity,
                            nb::object seed_mode_obj) {
            new (t) TraceDefaults{rays, batch, depth, intensity, parse_seed_mode_arg(seed_mode_obj)};
        }, "rays"_a = 10'000'000, "batch"_a = 200'000, "depth"_a = 12, "intensity"_a = 1.0f,
           "seed_mode"_a = nb::cast("deterministic"))
        .def_rw("rays", &TraceDefaults::rays)
        .def_rw("batch", &TraceDefaults::batch)
        .def_rw("depth", &TraceDefaults::depth)
        .def_rw("intensity", &TraceDefaults::intensity)
        .def_prop_rw("seed_mode",
            [](const TraceDefaults& t) { return seed_mode_to_string(t.seed_mode); },
            [](TraceDefaults& t, nb::object obj) { t.seed_mode = parse_seed_mode_arg(obj); })
        .def("to_trace_config", &TraceDefaults::to_trace_config, "frame"_a = 0);

    // ── TraceConfig (runtime) ────────────────────────────────────
    nb::class_<TraceConfig>(m, "TraceConfig")
        .def(nb::init<>())
        .def_rw("batch_size", &TraceConfig::batch_size)
        .def_rw("depth", &TraceConfig::depth)
        .def_rw("intensity", &TraceConfig::intensity)
        .def_prop_rw("seed_mode",
            [](const TraceConfig& cfg) { return seed_mode_to_string(cfg.seed_mode); },
            [](TraceConfig& cfg, nb::object obj) { cfg.seed_mode = parse_seed_mode_arg(obj); })
        .def_rw("frame", &TraceConfig::frame);

    // ── PostProcess (runtime) ────────────────────────────────────
    nb::class_<PostProcess>(m, "PostProcess")
        .def(nb::init<>())
        .def_rw("exposure", &PostProcess::exposure)
        .def_rw("contrast", &PostProcess::contrast)
        .def_rw("gamma", &PostProcess::gamma)
        .def_rw("white_point", &PostProcess::white_point)
        .def_rw("normalize_ref", &PostProcess::normalize_ref)
        .def_rw("normalize_pct", &PostProcess::normalize_pct)
        .def_rw("ambient", &PostProcess::ambient)
        .def_rw("opacity", &PostProcess::opacity)
        .def_rw("saturation", &PostProcess::saturation)
        .def_rw("vignette", &PostProcess::vignette)
        .def_rw("vignette_radius", &PostProcess::vignette_radius)
        .def_rw("temperature", &PostProcess::temperature)
        .def_rw("highlights", &PostProcess::highlights)
        .def_rw("shadows", &PostProcess::shadows)
        .def_rw("hue_shift", &PostProcess::hue_shift)
        .def_rw("grain", &PostProcess::grain)
        .def_rw("grain_seed", &PostProcess::grain_seed)
        .def_rw("chromatic_aberration", &PostProcess::chromatic_aberration)
        .def_prop_rw("tonemap",
            [](const PostProcess& pp) { return tonemap_to_string(pp.tonemap); },
            [](PostProcess& pp, nb::object obj) { pp.tonemap = parse_tonemap_arg(obj); })
        .def_prop_rw("normalize",
            [](const PostProcess& pp) { return normalize_mode_to_string(pp.normalize); },
            [](PostProcess& pp, nb::object obj) { pp.normalize = parse_normalize_arg(obj); })
        .def_prop_rw("background",
            [](const PostProcess& pp) { return std::array<float, 3>{pp.background[0], pp.background[1], pp.background[2]}; },
            [](PostProcess& pp, std::array<float, 3> bg) { pp.background[0] = bg[0]; pp.background[1] = bg[1]; pp.background[2] = bg[2]; });

    // ── Shot ─────────────────────────────────────────────────────
    nb::class_<Shot>(m, "Shot")
        .def("__init__", [](Shot* s, std::string name, Scene scene, Camera2D camera,
                            Canvas canvas, Look look, TraceDefaults trace) {
            new (s) Shot{std::move(scene), camera, canvas, look, trace, std::move(name)};
        }, "name"_a = "", "scene"_a = Scene{}, "camera"_a = Camera2D{},
           "canvas"_a = Canvas{}, "look"_a = Look{}, "trace"_a = TraceDefaults{})
        .def_rw("name", &Shot::name)
        .def_rw("scene", &Shot::scene)
        .def_rw("camera", &Shot::camera)
        .def_rw("canvas", &Shot::canvas)
        .def_rw("look", &Shot::look)
        .def_rw("trace", &Shot::trace);

    // ── File I/O ─────────────────────────────────────────────────
    m.def("load_shot", [](const std::string& path) -> Shot {
        std::string error;
        auto shot = try_load_shot_json(path, &error);
        if (!shot) throw std::runtime_error(error.empty() ? "Failed to load shot" : error);
        return *shot;
    }, "path"_a);

    m.def("load_shot_json_string", [](const std::string& json_content) -> Shot {
        std::string error;
        auto shot = try_load_shot_json_string(json_content, &error);
        if (!shot) throw std::runtime_error(error.empty() ? "Failed to parse shot JSON" : error);
        return *shot;
    }, "json_content"_a);

    m.def("save_shot", [](const Shot& shot, const std::string& path) {
        if (!save_shot_json(shot, path))
            throw std::runtime_error("Failed to save shot to " + path);
    }, "shot"_a, "path"_a);

    // ── Material resolution ─────────────────────────────────────
    m.def("resolve_material", [](const Shape& shape, const Scene& scene) -> Material {
        return resolve_shape_material(shape, scene.materials);
    }, "shape"_a, "scene"_a);

    // ── Geometry utilities ───────────────────────────────────────
    m.def("compute_bounds", &compute_bounds, "scene"_a, "padding"_a = 0.05f);
    m.def("validate_scene", [](const Scene& scene) {
        std::string error;
        if (!validate_scene(scene, &error))
            throw std::runtime_error(error);
    }, "scene"_a);
    m.def("normalize_scene", [](Scene& scene) {
        std::string error;
        if (!normalize_scene(scene, &error))
            throw std::runtime_error(error);
    }, "scene"_a);
    m.def("ray_intersect", [](const Scene& scene, Vec2 origin, Vec2 direction) -> nb::object {
        Ray ray{origin, direction.normalized()};
        auto hit = intersect_scene(ray, scene);
        if (!hit) return nb::none();
        return nb::make_tuple(
            hit->t,
            nb::make_tuple(hit->point.x, hit->point.y),
            nb::make_tuple(hit->normal.x, hit->normal.y),
            hit->shape_id
        );
    }, "scene"_a, "origin"_a, "direction"_a);

    // ── FrameMetrics ─────────────────────────────────────────────
    nb::class_<FrameMetrics>(m, "FrameMetrics")
        .def_ro("mean_lum", &FrameMetrics::mean_lum)
        .def_ro("pct_black", &FrameMetrics::pct_black)
        .def_ro("pct_clipped", &FrameMetrics::pct_clipped)
        .def_ro("p50", &FrameMetrics::p50)
        .def_ro("p95", &FrameMetrics::p95)
        .def_prop_ro("histogram", [](const FrameMetrics& fm) {
            std::vector<int> h(fm.histogram.begin(), fm.histogram.end());
            return h;
        });

    // ── RenderResult ─────────────────────────────────────────────
    nb::class_<RenderResult>(m, "RenderResult")
        .def_prop_ro("pixels", [](const RenderResult& r) {
            return nb::bytes(reinterpret_cast<const char*>(r.pixels.data()), r.pixels.size());
        })
        .def_ro("width", &RenderResult::width)
        .def_ro("height", &RenderResult::height)
        .def_ro("total_rays", &RenderResult::total_rays)
        .def_ro("max_hdr", &RenderResult::max_hdr)
        .def_ro("metrics", &RenderResult::metrics)
        .def_ro("time_ms", &RenderResult::time_ms);

    // ── RenderSession ────────────────────────────────────────────
    nb::class_<RenderSession>(m, "RenderSession")
        .def(nb::init<int, int, bool>(), "width"_a, "height"_a, "half_float"_a = false)
        .def("close", &RenderSession::close)
        .def("render_shot", &RenderSession::render_shot, "shot"_a, "frame"_a = 0)
        .def("render_frame", &RenderSession::render_frame,
             "scene"_a, "bounds"_a, "trace_cfg"_a, "pp"_a, "total_rays"_a)
        .def("resize", &RenderSession::resize, "width"_a, "height"_a)
        .def_prop_ro("width", &RenderSession::width)
        .def_prop_ro("height", &RenderSession::height);
}
