#include "serialize.h"

#include "geometry.h"
#include "scene.h"

#include <nlohmann/json.hpp>

#include <stddef.h>
#include <stdint.h>
#include <array>
#include <exception>
#include <fstream>
#include <initializer_list>
#include <iostream>
#include <iterator>
#include <map>
#include <optional>
#include <stdexcept>
#include <string>
#include <string_view>
#include <utility>
#include <variant>
#include <vector>

namespace {

using Json = nlohmann::ordered_json;
constexpr int SHOT_JSON_VERSION = 5;
enum class Schema { Authored };

[[noreturn]] void fail(std::string message) { throw std::runtime_error(std::move(message)); }

void expect_object(const Json& json, std::string_view context) {
    if (!json.is_object()) fail(std::string(context) + " must be an object");
}

void expect_array(const Json& json, std::string_view context) {
    if (!json.is_array()) fail(std::string(context) + " must be an array");
}

void reject_unknown_keys(const Json& json, std::initializer_list<std::string_view> allowed,
                         std::string_view context) {
    expect_object(json, context);
    for (const auto& [key, _] : json.items()) {
        bool ok = false;
        for (std::string_view candidate : allowed)
            if (candidate == key) { ok = true; break; }
        if (!ok) fail("unknown key in " + std::string(context) + ": " + key);
    }
}

const Json& require_key(const Json& json, std::string_view key, std::string_view context) {
    expect_object(json, context);
    auto it = json.find(std::string(key));
    if (it == json.end())
        fail(std::string(context) + " requires key: " + std::string(key));
    return *it;
}

const Json* find_key(const Json& json, std::string_view key) {
    if (!json.is_object()) return nullptr;
    auto it = json.find(std::string(key));
    return it == json.end() ? nullptr : &*it;
}

std::string read_string(const Json& json, std::string_view context) {
    if (!json.is_string()) fail(std::string(context) + " must be a string");
    return json.get<std::string>();
}

float read_float(const Json& json, std::string_view context) {
    if (!json.is_number()) fail(std::string(context) + " must be a number");
    return json.get<float>();
}

int read_int(const Json& json, std::string_view context) {
    if (!json.is_number_integer() && !json.is_number_unsigned())
        fail(std::string(context) + " must be an integer");
    return json.get<int>();
}

int64_t read_int64(const Json& json, std::string_view context) {
    if (!json.is_number_integer() && !json.is_number_unsigned())
        fail(std::string(context) + " must be an integer");
    return json.get<int64_t>();
}

Vec2 read_vec2(const Json& json, std::string_view context) {
    expect_array(json, context);
    if (json.size() != 2) fail(std::string(context) + " must contain exactly 2 numbers");
    return {read_float(json[0], std::string(context) + "[0]"),
            read_float(json[1], std::string(context) + "[1]")};
}

std::array<float, 3> read_rgb(const Json& json, std::string_view context) {
    expect_array(json, context);
    if (json.size() != 3) fail(std::string(context) + " must contain exactly 3 numbers");
    return {read_float(json[0], std::string(context) + "[0]"),
            read_float(json[1], std::string(context) + "[1]"),
            read_float(json[2], std::string(context) + "[2]")};
}

Bounds read_bounds(const Json& json, std::string_view context) {
    expect_array(json, context);
    if (json.size() != 4) fail(std::string(context) + " must contain exactly 4 numbers");
    return {{read_float(json[0], std::string(context) + "[0]"),
             read_float(json[1], std::string(context) + "[1]")},
            {read_float(json[2], std::string(context) + "[2]"),
             read_float(json[3], std::string(context) + "[3]")}};
}

std::string read_required_string(const Json& json, std::string_view key, std::string_view context) {
    return read_string(require_key(json, key, context), std::string(context) + "." + std::string(key));
}

float read_required_float(const Json& json, std::string_view key, std::string_view context) {
    return read_float(require_key(json, key, context), std::string(context) + "." + std::string(key));
}

Json vec2_json(Vec2 value) { return Json::array({value.x, value.y}); }
Json rgb_json(const float value[3]) { return Json::array({value[0], value[1], value[2]}); }
Json bounds_json(const Bounds& value) { return Json::array({value.min.x, value.min.y, value.max.x, value.max.y}); }

ToneMap read_tonemap(const Json& json, std::string_view context) {
    const std::string value = read_string(json, context);
    if (auto parsed = parse_tonemap(value)) return *parsed;
    fail("invalid tonemap: " + value);
}

NormalizeMode read_normalize_mode(const Json& json, std::string_view context) {
    const std::string value = read_string(json, context);
    if (auto parsed = parse_normalize_mode(value)) return *parsed;
    fail("invalid normalize mode: " + value);
}

Material read_material(const Json& json, Schema schema, std::string_view context) {
    reject_unknown_keys(json, {"ior", "roughness", "metallic", "transmission", "absorption",
                               "cauchy_b", "albedo", "emission"}, context);
    Material material;
    if (schema == Schema::Authored || json.contains("ior"))
        material.ior = read_required_float(json, "ior", context);
    if (schema == Schema::Authored || json.contains("roughness"))
        material.roughness = read_required_float(json, "roughness", context);
    if (schema == Schema::Authored || json.contains("metallic"))
        material.metallic = read_required_float(json, "metallic", context);
    if (schema == Schema::Authored || json.contains("transmission"))
        material.transmission = read_required_float(json, "transmission", context);
    if (schema == Schema::Authored || json.contains("absorption"))
        material.absorption = read_required_float(json, "absorption", context);
    if (schema == Schema::Authored || json.contains("cauchy_b"))
        material.cauchy_b = read_required_float(json, "cauchy_b", context);
    if (schema == Schema::Authored || json.contains("albedo"))
        material.albedo = read_required_float(json, "albedo", context);
    if (schema == Schema::Authored || json.contains("emission"))
        material.emission = read_required_float(json, "emission", context);
    return material;
}

Json write_material(const Material& material) {
    Json json = Json::object();
    json["ior"] = material.ior;
    json["roughness"] = material.roughness;
    json["metallic"] = material.metallic;
    json["transmission"] = material.transmission;
    json["absorption"] = material.absorption;
    json["cauchy_b"] = material.cauchy_b;
    json["albedo"] = material.albedo;
    json["emission"] = material.emission;
    return json;
}

std::pair<Material, std::string> read_shape_material(const Json& json,
                                                     const std::map<std::string, Material>& materials,
                                                     Schema schema, std::string_view context) {
    const bool has_material = json.contains("material");
    const bool has_material_id = json.contains("material_id");
    if (has_material == has_material_id)
        fail("shape entries must declare exactly one of material and material_id");
    if (has_material_id) {
        const std::string material_id = read_required_string(json, "material_id", context);
        if (material_id.empty()) fail("material_id must be a non-empty string");
        auto it = materials.find(material_id);
        if (it == materials.end()) fail("unknown material_id: " + material_id);
        return {it->second, material_id};
    }
    return {read_material(require_key(json, "material", context), schema,
                          std::string(context) + ".material"), {}};
}

Shape read_shape(const Json& json, const std::map<std::string, Material>& materials,
                 Schema schema, std::string_view context) {
    const std::string type = read_required_string(json, "type", context);
    const std::string id = read_required_string(json, "id", context);
    if (id.empty()) fail("shape ids must be non-empty");
    auto [material, material_id] = read_shape_material(json, materials, schema, context);
    if (type == "circle") {
        reject_unknown_keys(json, {"id", "type", "center", "radius", "material", "material_id"}, context);
        Circle circle{id, {}, 0.1f, material, material_id};
        if (schema == Schema::Authored || json.contains("center"))
            circle.center = read_vec2(require_key(json, "center", context), std::string(context) + ".center");
        if (schema == Schema::Authored || json.contains("radius"))
            circle.radius = read_required_float(json, "radius", context);
        return circle;
    }
    if (type == "segment") {
        reject_unknown_keys(json, {"id", "type", "a", "b", "material", "material_id"}, context);
        Segment segment{id, {}, {}, material, material_id};
        if (schema == Schema::Authored || json.contains("a"))
            segment.a = read_vec2(require_key(json, "a", context), std::string(context) + ".a");
        if (schema == Schema::Authored || json.contains("b"))
            segment.b = read_vec2(require_key(json, "b", context), std::string(context) + ".b");
        return segment;
    }
    if (type == "arc") {
        reject_unknown_keys(json, {"id", "type", "center", "radius", "angle_start", "sweep",
                                   "material", "material_id"}, context);
        Arc arc{id, {}, 0.1f, 0.0f, TWO_PI, material, material_id};
        if (schema == Schema::Authored || json.contains("center"))
            arc.center = read_vec2(require_key(json, "center", context), std::string(context) + ".center");
        if (schema == Schema::Authored || json.contains("radius"))
            arc.radius = read_required_float(json, "radius", context);
        if (schema == Schema::Authored || json.contains("angle_start"))
            arc.angle_start = normalize_angle(read_required_float(json, "angle_start", context));
        if (schema == Schema::Authored || json.contains("sweep"))
            arc.sweep = clamp_arc_sweep(read_required_float(json, "sweep", context));
        return arc;
    }
    if (type == "bezier") {
        reject_unknown_keys(json, {"id", "type", "p0", "p1", "p2", "material", "material_id"}, context);
        Bezier bezier{id, {}, {0.5f, 0.5f}, {1.0f, 0.0f}, material, material_id};
        if (schema == Schema::Authored || json.contains("p0"))
            bezier.p0 = read_vec2(require_key(json, "p0", context), std::string(context) + ".p0");
        if (schema == Schema::Authored || json.contains("p1"))
            bezier.p1 = read_vec2(require_key(json, "p1", context), std::string(context) + ".p1");
        if (schema == Schema::Authored || json.contains("p2"))
            bezier.p2 = read_vec2(require_key(json, "p2", context), std::string(context) + ".p2");
        return bezier;
    }
    if (type == "polygon") {
        reject_unknown_keys(json, {"id", "type", "vertices", "material", "material_id"}, context);
        Polygon polygon;
        polygon.id = id;
        if (schema == Schema::Authored || json.contains("vertices")) {
            expect_array(require_key(json, "vertices", context), std::string(context) + ".vertices");
            for (size_t i = 0; i < json["vertices"].size(); ++i)
                polygon.vertices.push_back(read_vec2(json["vertices"][i],
                                                     std::string(context) + ".vertices[" + std::to_string(i) + "]"));
        }
        polygon.material = material;
        polygon.material_id = material_id;
        return polygon;
    }
    if (type == "ellipse") {
        reject_unknown_keys(json, {"id", "type", "center", "semi_a", "semi_b", "rotation",
                                   "material", "material_id"}, context);
        Ellipse ellipse{id, {}, 0.2f, 0.1f, 0.0f, material, material_id};
        if (schema == Schema::Authored || json.contains("center"))
            ellipse.center = read_vec2(require_key(json, "center", context), std::string(context) + ".center");
        if (schema == Schema::Authored || json.contains("semi_a"))
            ellipse.semi_a = read_required_float(json, "semi_a", context);
        if (schema == Schema::Authored || json.contains("semi_b"))
            ellipse.semi_b = read_required_float(json, "semi_b", context);
        if (schema == Schema::Authored || json.contains("rotation"))
            ellipse.rotation = read_required_float(json, "rotation", context);
        return ellipse;
    }
    fail("unknown shape type: " + type);
}

Json write_shape(const Shape& shape) {
    return std::visit(overloaded{
        [](const Circle& value) {
            Json json = {{"id", value.id}, {"type", "circle"}, {"center", vec2_json(value.center)},
                         {"radius", value.radius}};
            if (value.material_id.empty()) json["material"] = write_material(value.material);
            else json["material_id"] = value.material_id;
            return json;
        },
        [](const Segment& value) {
            Json json = {{"id", value.id}, {"type", "segment"}, {"a", vec2_json(value.a)},
                         {"b", vec2_json(value.b)}};
            if (value.material_id.empty()) json["material"] = write_material(value.material);
            else json["material_id"] = value.material_id;
            return json;
        },
        [](const Arc& value) {
            Json json = {{"id", value.id}, {"type", "arc"}, {"center", vec2_json(value.center)},
                         {"radius", value.radius}, {"angle_start", value.angle_start},
                         {"sweep", value.sweep}};
            if (value.material_id.empty()) json["material"] = write_material(value.material);
            else json["material_id"] = value.material_id;
            return json;
        },
        [](const Bezier& value) {
            Json json = {{"id", value.id}, {"type", "bezier"}, {"p0", vec2_json(value.p0)},
                         {"p1", vec2_json(value.p1)}, {"p2", vec2_json(value.p2)}};
            if (value.material_id.empty()) json["material"] = write_material(value.material);
            else json["material_id"] = value.material_id;
            return json;
        },
        [](const Polygon& value) {
            Json vertices = Json::array();
            for (Vec2 vertex : value.vertices) vertices.push_back(vec2_json(vertex));
            Json json = {{"id", value.id}, {"type", "polygon"}, {"vertices", std::move(vertices)}};
            if (value.material_id.empty()) json["material"] = write_material(value.material);
            else json["material_id"] = value.material_id;
            return json;
        },
        [](const Ellipse& value) {
            Json json = {{"id", value.id}, {"type", "ellipse"}, {"center", vec2_json(value.center)},
                         {"semi_a", value.semi_a}, {"semi_b", value.semi_b},
                         {"rotation", value.rotation}};
            if (value.material_id.empty()) json["material"] = write_material(value.material);
            else json["material_id"] = value.material_id;
            return json;
        },
    }, shape);
}

Light read_light(const Json& json, Schema schema, std::string_view context) {
    const std::string type = read_required_string(json, "type", context);
    const std::string id = read_required_string(json, "id", context);
    if (id.empty()) fail("light ids must be non-empty");
    if (type == "point") {
        reject_unknown_keys(json, {"id", "type", "pos", "intensity", "wavelength_min", "wavelength_max"}, context);
        PointLight light{id, {}, 1.0f, 380.0f, 780.0f};
        if (schema == Schema::Authored || json.contains("pos"))
            light.pos = read_vec2(require_key(json, "pos", context), std::string(context) + ".pos");
        if (schema == Schema::Authored || json.contains("intensity"))
            light.intensity = read_required_float(json, "intensity", context);
        if (schema == Schema::Authored || json.contains("wavelength_min"))
            light.wavelength_min = read_required_float(json, "wavelength_min", context);
        if (schema == Schema::Authored || json.contains("wavelength_max"))
            light.wavelength_max = read_required_float(json, "wavelength_max", context);
        return light;
    }
    if (type == "segment") {
        reject_unknown_keys(json, {"id", "type", "a", "b", "intensity", "wavelength_min", "wavelength_max"}, context);
        SegmentLight light{id, {}, {}, 1.0f, 380.0f, 780.0f};
        if (schema == Schema::Authored || json.contains("a"))
            light.a = read_vec2(require_key(json, "a", context), std::string(context) + ".a");
        if (schema == Schema::Authored || json.contains("b"))
            light.b = read_vec2(require_key(json, "b", context), std::string(context) + ".b");
        if (schema == Schema::Authored || json.contains("intensity"))
            light.intensity = read_required_float(json, "intensity", context);
        if (schema == Schema::Authored || json.contains("wavelength_min"))
            light.wavelength_min = read_required_float(json, "wavelength_min", context);
        if (schema == Schema::Authored || json.contains("wavelength_max"))
            light.wavelength_max = read_required_float(json, "wavelength_max", context);
        return light;
    }
    if (type == "beam") {
        reject_unknown_keys(json, {"id", "type", "origin", "direction", "angular_width",
                                   "intensity", "wavelength_min", "wavelength_max"}, context);
        BeamLight light{id, {}, {1.0f, 0.0f}, 0.1f, 1.0f, 380.0f, 780.0f};
        if (schema == Schema::Authored || json.contains("origin"))
            light.origin = read_vec2(require_key(json, "origin", context), std::string(context) + ".origin");
        if (schema == Schema::Authored || json.contains("direction"))
            light.direction = read_vec2(require_key(json, "direction", context), std::string(context) + ".direction");
        if (schema == Schema::Authored || json.contains("angular_width"))
            light.angular_width = read_required_float(json, "angular_width", context);
        if (schema == Schema::Authored || json.contains("intensity"))
            light.intensity = read_required_float(json, "intensity", context);
        if (schema == Schema::Authored || json.contains("wavelength_min"))
            light.wavelength_min = read_required_float(json, "wavelength_min", context);
        if (schema == Schema::Authored || json.contains("wavelength_max"))
            light.wavelength_max = read_required_float(json, "wavelength_max", context);
        light.direction = light.direction.length_sq() > 1e-6f ? light.direction.normalized() : Vec2{1, 0};
        return light;
    }
    if (type == "parallel_beam") {
        reject_unknown_keys(json, {"id", "type", "a", "b", "direction", "angular_width",
                                   "intensity", "wavelength_min", "wavelength_max"}, context);
        ParallelBeamLight light{id, {}, {0.0f, 0.5f}, {1.0f, 0.0f}, 0.0f, 1.0f, 380.0f, 780.0f};
        if (schema == Schema::Authored || json.contains("a"))
            light.a = read_vec2(require_key(json, "a", context), std::string(context) + ".a");
        if (schema == Schema::Authored || json.contains("b"))
            light.b = read_vec2(require_key(json, "b", context), std::string(context) + ".b");
        if (schema == Schema::Authored || json.contains("direction"))
            light.direction = read_vec2(require_key(json, "direction", context), std::string(context) + ".direction");
        if (schema == Schema::Authored || json.contains("angular_width"))
            light.angular_width = read_required_float(json, "angular_width", context);
        if (schema == Schema::Authored || json.contains("intensity"))
            light.intensity = read_required_float(json, "intensity", context);
        if (schema == Schema::Authored || json.contains("wavelength_min"))
            light.wavelength_min = read_required_float(json, "wavelength_min", context);
        if (schema == Schema::Authored || json.contains("wavelength_max"))
            light.wavelength_max = read_required_float(json, "wavelength_max", context);
        light.direction = light.direction.length_sq() > 1e-6f ? light.direction.normalized() : Vec2{1, 0};
        return light;
    }
    if (type == "spot") {
        reject_unknown_keys(json, {"id", "type", "pos", "direction", "angular_width", "falloff",
                                   "intensity", "wavelength_min", "wavelength_max"}, context);
        SpotLight light{id, {}, {1.0f, 0.0f}, 0.5f, 2.0f, 1.0f, 380.0f, 780.0f};
        if (schema == Schema::Authored || json.contains("pos"))
            light.pos = read_vec2(require_key(json, "pos", context), std::string(context) + ".pos");
        if (schema == Schema::Authored || json.contains("direction"))
            light.direction = read_vec2(require_key(json, "direction", context), std::string(context) + ".direction");
        if (schema == Schema::Authored || json.contains("angular_width"))
            light.angular_width = read_required_float(json, "angular_width", context);
        if (schema == Schema::Authored || json.contains("falloff"))
            light.falloff = read_required_float(json, "falloff", context);
        if (schema == Schema::Authored || json.contains("intensity"))
            light.intensity = read_required_float(json, "intensity", context);
        if (schema == Schema::Authored || json.contains("wavelength_min"))
            light.wavelength_min = read_required_float(json, "wavelength_min", context);
        if (schema == Schema::Authored || json.contains("wavelength_max"))
            light.wavelength_max = read_required_float(json, "wavelength_max", context);
        light.direction = light.direction.length_sq() > 1e-6f ? light.direction.normalized() : Vec2{1, 0};
        return light;
    }
    fail("unknown light type: " + type);
}

Json write_light(const Light& light) {
    return std::visit(overloaded{
        [](const PointLight& value) { return Json{{"id", value.id}, {"type", "point"}, {"pos", vec2_json(value.pos)},
                                                  {"intensity", value.intensity},
                                                  {"wavelength_min", value.wavelength_min},
                                                  {"wavelength_max", value.wavelength_max}}; },
        [](const SegmentLight& value) { return Json{{"id", value.id}, {"type", "segment"}, {"a", vec2_json(value.a)},
                                                    {"b", vec2_json(value.b)}, {"intensity", value.intensity},
                                                    {"wavelength_min", value.wavelength_min},
                                                    {"wavelength_max", value.wavelength_max}}; },
        [](const BeamLight& value) { return Json{{"id", value.id}, {"type", "beam"}, {"origin", vec2_json(value.origin)},
                                                 {"direction", vec2_json(value.direction)},
                                                 {"angular_width", value.angular_width},
                                                 {"intensity", value.intensity},
                                                 {"wavelength_min", value.wavelength_min},
                                                 {"wavelength_max", value.wavelength_max}}; },
        [](const ParallelBeamLight& value) {
            return Json{{"id", value.id}, {"type", "parallel_beam"}, {"a", vec2_json(value.a)},
                        {"b", vec2_json(value.b)}, {"direction", vec2_json(value.direction)},
                        {"angular_width", value.angular_width}, {"intensity", value.intensity},
                        {"wavelength_min", value.wavelength_min}, {"wavelength_max", value.wavelength_max}};
        },
        [](const SpotLight& value) { return Json{{"id", value.id}, {"type", "spot"}, {"pos", vec2_json(value.pos)},
                                                 {"direction", vec2_json(value.direction)},
                                                 {"angular_width", value.angular_width},
                                                 {"falloff", value.falloff}, {"intensity", value.intensity},
                                                 {"wavelength_min", value.wavelength_min},
                                                 {"wavelength_max", value.wavelength_max}}; },
    }, light);
}

Transform2D read_transform(const Json& json, std::string_view context) {
    reject_unknown_keys(json, {"translate", "rotate", "scale"}, context);
    return {read_vec2(require_key(json, "translate", context), std::string(context) + ".translate"),
            read_required_float(json, "rotate", context),
            read_vec2(require_key(json, "scale", context), std::string(context) + ".scale")};
}

Json write_transform(const Transform2D& transform) {
    return Json{{"translate", vec2_json(transform.translate)}, {"rotate", transform.rotate},
                {"scale", vec2_json(transform.scale)}};
}

Group read_group(const Json& json, const std::map<std::string, Material>& materials,
                 Schema schema, std::string_view context) {
    (void)schema;
    reject_unknown_keys(json, {"id", "transform", "shapes", "lights"}, context);
    Group group;
    group.id = read_required_string(json, "id", context);
    if (group.id.empty()) fail("group ids must be non-empty");
    group.transform = read_transform(require_key(json, "transform", context), std::string(context) + ".transform");
    expect_array(require_key(json, "shapes", context), std::string(context) + ".shapes");
    for (size_t i = 0; i < json["shapes"].size(); ++i)
        group.shapes.push_back(read_shape(json["shapes"][i], materials, schema,
                                          std::string(context) + ".shapes[" + std::to_string(i) + "]"));
    expect_array(require_key(json, "lights", context), std::string(context) + ".lights");
    for (size_t i = 0; i < json["lights"].size(); ++i)
        group.lights.push_back(read_light(json["lights"][i], schema,
                                          std::string(context) + ".lights[" + std::to_string(i) + "]"));
    return group;
}

Json write_group(const Group& group) {
    Json shapes = Json::array();
    for (const Shape& shape : group.shapes) shapes.push_back(write_shape(shape));
    Json lights = Json::array();
    for (const Light& light : group.lights) lights.push_back(write_light(light));
    return Json{{"id", group.id}, {"transform", write_transform(group.transform)},
                {"shapes", std::move(shapes)}, {"lights", std::move(lights)}};
}

Camera2D read_camera(const Json& json, std::string_view context) {
    reject_unknown_keys(json, {"bounds", "center", "width"}, context);
    Camera2D camera;
    const bool has_bounds = json.contains("bounds");
    const bool has_center = json.contains("center");
    const bool has_width = json.contains("width");
    if (has_bounds && (has_center || has_width))
        fail(std::string(context) + " cannot mix bounds with center/width");
    if (has_bounds) {
        camera.bounds = read_bounds(json["bounds"], std::string(context) + ".bounds");
        return camera;
    }
    if (has_center != has_width)
        fail(std::string(context) + " requires both center and width, or neither");
    if (has_center) {
        camera.center = read_vec2(json["center"], std::string(context) + ".center");
        camera.width = read_float(json["width"], std::string(context) + ".width");
    }
    return camera;
}

Json write_camera(const Camera2D& camera) {
    if (camera.empty()) return Json::object();
    if (camera.bounds) return Json{{"bounds", bounds_json(*camera.bounds)}};
    return Json{{"center", vec2_json(*camera.center)}, {"width", *camera.width}};
}

Canvas read_canvas(const Json& json, std::string_view context) {
    reject_unknown_keys(json, {"width", "height"}, context);
    return {read_int(require_key(json, "width", context), std::string(context) + ".width"),
            read_int(require_key(json, "height", context), std::string(context) + ".height")};
}

Json write_canvas(const Canvas& canvas) { return Json{{"width", canvas.width}, {"height", canvas.height}}; }

Look read_look(const Json& json, Schema schema, std::string_view context) {
    reject_unknown_keys(json, {"exposure", "contrast", "gamma", "tonemap", "white_point",
                               "normalize", "normalize_ref", "normalize_pct", "ambient",
                               "background", "opacity", "saturation", "vignette", "vignette_radius"}, context);
    Look look;
    if (schema == Schema::Authored || json.contains("exposure"))
        look.exposure = read_required_float(json, "exposure", context);
    if (schema == Schema::Authored || json.contains("contrast"))
        look.contrast = read_required_float(json, "contrast", context);
    if (schema == Schema::Authored || json.contains("gamma"))
        look.gamma = read_required_float(json, "gamma", context);
    if (schema == Schema::Authored || json.contains("tonemap"))
        look.tone_map = read_tonemap(require_key(json, "tonemap", context), std::string(context) + ".tonemap");
    if (schema == Schema::Authored || json.contains("white_point"))
        look.white_point = read_required_float(json, "white_point", context);
    if (schema == Schema::Authored || json.contains("normalize"))
        look.normalize = read_normalize_mode(require_key(json, "normalize", context),
                                             std::string(context) + ".normalize");
    if (schema == Schema::Authored || json.contains("normalize_ref"))
        look.normalize_ref = read_required_float(json, "normalize_ref", context);
    if (schema == Schema::Authored || json.contains("normalize_pct"))
        look.normalize_pct = read_required_float(json, "normalize_pct", context);
    if (schema == Schema::Authored || json.contains("ambient"))
        look.ambient = read_required_float(json, "ambient", context);
    if (schema == Schema::Authored || json.contains("background")) {
        const auto background = read_rgb(require_key(json, "background", context), std::string(context) + ".background");
        look.background[0] = background[0];
        look.background[1] = background[1];
        look.background[2] = background[2];
    }
    if (schema == Schema::Authored || json.contains("opacity"))
        look.opacity = read_required_float(json, "opacity", context);
    if (schema == Schema::Authored || json.contains("saturation"))
        look.saturation = read_required_float(json, "saturation", context);
    if (schema == Schema::Authored || json.contains("vignette"))
        look.vignette = read_required_float(json, "vignette", context);
    if (schema == Schema::Authored || json.contains("vignette_radius"))
        look.vignette_radius = read_required_float(json, "vignette_radius", context);
    return look;
}

Json write_look(const Look& look) {
    return Json{{"exposure", look.exposure}, {"contrast", look.contrast}, {"gamma", look.gamma},
                {"tonemap", tonemap_to_string(look.tone_map)}, {"white_point", look.white_point},
                {"normalize", normalize_mode_to_string(look.normalize)}, {"normalize_ref", look.normalize_ref},
                {"normalize_pct", look.normalize_pct}, {"ambient", look.ambient},
                {"background", rgb_json(look.background)}, {"opacity", look.opacity},
                {"saturation", look.saturation}, {"vignette", look.vignette},
                {"vignette_radius", look.vignette_radius}};
}

TraceDefaults read_trace(const Json& json, Schema schema, std::string_view context) {
    reject_unknown_keys(json, {"rays", "batch", "depth", "intensity"}, context);
    TraceDefaults trace;
    if (schema == Schema::Authored || json.contains("rays"))
        trace.rays = read_int64(require_key(json, "rays", context), std::string(context) + ".rays");
    if (schema == Schema::Authored || json.contains("batch"))
        trace.batch = read_int(require_key(json, "batch", context), std::string(context) + ".batch");
    if (schema == Schema::Authored || json.contains("depth"))
        trace.depth = read_int(require_key(json, "depth", context), std::string(context) + ".depth");
    if (schema == Schema::Authored || json.contains("intensity"))
        trace.intensity = read_required_float(json, "intensity", context);
    return trace;
}

Json write_trace(const TraceDefaults& trace) {
    return Json{{"rays", trace.rays}, {"batch", trace.batch}, {"depth", trace.depth},
                {"intensity", trace.intensity}};
}

Scene read_scene(const Json& root, Schema schema) {
    Scene scene;
    const Json* materials_json = find_key(root, "materials");
    const Json* shapes_json = find_key(root, "shapes");
    const Json* lights_json = find_key(root, "lights");
    const Json* groups_json = find_key(root, "groups");
    const Json& materials = schema == Schema::Authored ? require_key(root, "materials", "shot")
                                                       : (materials_json ? *materials_json : Json::object());
    expect_object(materials, "materials");
    for (const auto& [name, value] : materials.items()) {
        if (name.empty()) fail("material ids must be non-empty");
        scene.materials[name] = read_material(value, schema, "materials." + name);
    }

    const Json& shapes = schema == Schema::Authored ? require_key(root, "shapes", "shot")
                                                    : (shapes_json ? *shapes_json : Json::array());
    expect_array(shapes, "shapes");
    for (size_t i = 0; i < shapes.size(); ++i)
        scene.shapes.push_back(read_shape(shapes[i], scene.materials, schema,
                                          "shapes[" + std::to_string(i) + "]"));

    const Json& lights = schema == Schema::Authored ? require_key(root, "lights", "shot")
                                                    : (lights_json ? *lights_json : Json::array());
    expect_array(lights, "lights");
    for (size_t i = 0; i < lights.size(); ++i)
        scene.lights.push_back(read_light(lights[i], schema, "lights[" + std::to_string(i) + "]"));

    const Json& groups = schema == Schema::Authored ? require_key(root, "groups", "shot")
                                                    : (groups_json ? *groups_json : Json::array());
    expect_array(groups, "groups");
    for (size_t i = 0; i < groups.size(); ++i)
        scene.groups.push_back(read_group(groups[i], scene.materials, schema,
                                          "groups[" + std::to_string(i) + "]"));

    sync_material_bindings(scene);
    std::string error;
    if (!validate_scene(scene, &error)) fail("Invalid scene: " + error);
    return scene;
}

Json write_scene(const Scene& scene) {
    Json materials = Json::object();
    for (const auto& [name, material] : scene.materials) materials[name] = write_material(material);
    Json shapes = Json::array();
    for (const Shape& shape : scene.shapes) shapes.push_back(write_shape(shape));
    Json lights = Json::array();
    for (const Light& light : scene.lights) lights.push_back(write_light(light));
    Json groups = Json::array();
    for (const Group& group : scene.groups) groups.push_back(write_group(group));
    return Json{{"materials", std::move(materials)}, {"shapes", std::move(shapes)},
                {"lights", std::move(lights)}, {"groups", std::move(groups)}};
}

Json parse_root(std::string_view json_content) {
    Json root = Json::parse(json_content, nullptr, false);
    if (root.is_discarded() || !root.is_object()) fail("Invalid JSON");
    return root;
}

int read_version(const Json& root) {
    const Json* version = find_key(root, "version");
    if (!version || (!version->is_number_integer() && !version->is_number_unsigned()))
        fail("Unsupported shot version");
    const int value = version->get<int>();
    if (value != SHOT_JSON_VERSION)
        fail("Unsupported shot version (expected " + std::to_string(SHOT_JSON_VERSION) + ")");
    return value;
}

Shot read_authored_shot(const Json& root) {
    reject_unknown_keys(root, {"version", "name", "camera", "canvas", "look", "trace",
                               "materials", "shapes", "lights", "groups"}, "shot");
    (void)read_version(root);
    Shot shot;
    shot.name = read_required_string(root, "name", "shot");
    shot.camera = read_camera(require_key(root, "camera", "shot"), "camera");
    shot.canvas = read_canvas(require_key(root, "canvas", "shot"), "canvas");
    shot.look = read_look(require_key(root, "look", "shot"), Schema::Authored, "look");
    shot.trace = read_trace(require_key(root, "trace", "shot"), Schema::Authored, "trace");
    shot.scene = read_scene(root, Schema::Authored);
    return shot;
}

Json write_shot(const Shot& shot) {
    Json json = Json::object();
    json["version"] = SHOT_JSON_VERSION;
    json["name"] = shot.name;
    json["camera"] = write_camera(shot.camera);
    json["canvas"] = write_canvas(shot.canvas);
    json["look"] = write_look(shot.look);
    json["trace"] = write_trace(shot.trace);
    Json scene = write_scene(shot.scene);
    json["materials"] = std::move(scene["materials"]);
    json["shapes"] = std::move(scene["shapes"]);
    json["lights"] = std::move(scene["lights"]);
    json["groups"] = std::move(scene["groups"]);
    return json;
}

template <typename Fn>
std::optional<Shot> parse_shot(std::string_view json_content, std::string* error, Fn&& fn) {
    if (error) error->clear();
    try {
        return fn(parse_root(json_content));
    } catch (const std::exception& ex) {
        if (error) *error = ex.what();
        else std::cerr << ex.what() << "\n";
        return std::nullopt;
    }
}

} // namespace

bool save_shot_json(const Shot& shot, const std::string& path) {
    std::ofstream file(path);
    if (!file) {
        std::cerr << "Failed to open " << path << " for writing\n";
        return false;
    }
    file << write_shot(shot).dump(2) << '\n';
    return true;
}

std::optional<Shot> try_load_shot_json_string(std::string_view json_content, std::string* error) {
    return parse_shot(json_content, error, [](const Json& root) { return read_authored_shot(root); });
}

Shot load_shot_json_string(std::string_view json_content) {
    if (auto shot = try_load_shot_json_string(json_content)) return *shot;
    return {};
}

std::optional<Shot> try_load_shot_json(const std::string& path, std::string* error) {
    if (error) error->clear();
    std::ifstream file(path);
    if (!file) {
        if (error) *error = "Failed to open " + path;
        else std::cerr << "Failed to open " << path << "\n";
        return std::nullopt;
    }
    std::string content((std::istreambuf_iterator<char>(file)), std::istreambuf_iterator<char>());
    return try_load_shot_json_string(content, error);
}

Shot load_shot_json(const std::string& path) {
    if (auto shot = try_load_shot_json(path)) return *shot;
    return {};
}
