#include "scene.h"

#include <algorithm>
#include <set>
#include <utility>

namespace {

template <typename Fn>
void for_each_shape(Scene& scene, Fn&& fn) {
    for (auto& shape : scene.shapes) fn(shape);
    for (auto& group : scene.groups)
        for (auto& shape : group.shapes)
            fn(shape);
}

template <typename Fn>
void for_each_shape(const Scene& scene, Fn&& fn) {
    for (const auto& shape : scene.shapes) fn(shape);
    for (const auto& group : scene.groups)
        for (const auto& shape : group.shapes)
            fn(shape);
}

template <typename Fn>
void for_each_light(Scene& scene, Fn&& fn) {
    for (auto& light : scene.lights) fn(light);
    for (auto& group : scene.groups)
        for (auto& light : group.lights)
            fn(light);
}

template <typename Fn>
void for_each_light(const Scene& scene, Fn&& fn) {
    for (const auto& light : scene.lights) fn(light);
    for (const auto& group : scene.groups)
        for (const auto& light : group.lights)
            fn(light);
}

template <typename Variant>
bool entity_has_id(const Variant& entity, std::string_view id) {
    return std::visit([&](const auto& value) {
        return value.id == id;
    }, entity);
}

std::set<std::string> collect_entity_ids(const Scene& scene) {
    std::set<std::string> ids;
    for_each_shape(scene, [&](const Shape& shape) {
        std::visit([&](const auto& value) {
            if (!value.id.empty()) ids.insert(value.id);
        }, shape);
    });
    for_each_light(scene, [&](const Light& light) {
        std::visit([&](const auto& value) {
            if (!value.id.empty()) ids.insert(value.id);
        }, light);
    });
    for (const auto& group : scene.groups)
        if (!group.id.empty())
            ids.insert(group.id);
    return ids;
}

template <typename T>
void ensure_entity_id(T& entity, std::string_view prefix, std::set<std::string>& used_ids) {
    if (!entity.id.empty() && !used_ids.contains(entity.id)) {
        used_ids.insert(entity.id);
        return;
    }

    std::string base = prefix.empty() ? "entity" : std::string(prefix);
    int suffix = 0;
    while (true) {
        std::string candidate = base + "_" + std::to_string(suffix++);
        if (!used_ids.contains(candidate)) {
            entity.id = std::move(candidate);
            used_ids.insert(entity.id);
            return;
        }
    }
}

} // namespace

std::string shape_type_name(const Shape& shape) {
    return std::visit(overloaded{
        [](const Circle&) { return std::string{"circle"}; },
        [](const Segment&) { return std::string{"segment"}; },
        [](const Arc&) { return std::string{"arc"}; },
        [](const Bezier&) { return std::string{"bezier"}; },
        [](const Polygon&) { return std::string{"polygon"}; },
        [](const Ellipse&) { return std::string{"ellipse"}; },
    }, shape);
}

std::string light_type_name(const Light& light) {
    return std::visit(overloaded{
        [](const PointLight&) { return std::string{"point_light"}; },
        [](const SegmentLight&) { return std::string{"segment_light"}; },
        [](const BeamLight&) { return std::string{"beam_light"}; },
        [](const ParallelBeamLight&) { return std::string{"parallel_beam_light"}; },
        [](const SpotLight&) { return std::string{"spot_light"}; },
    }, light);
}

std::string next_scene_entity_id(const Scene& scene, std::string_view prefix) {
    std::set<std::string> used_ids = collect_entity_ids(scene);
    std::string base = prefix.empty() ? "entity" : std::string(prefix);
    int suffix = 0;
    while (true) {
        std::string candidate = base + "_" + std::to_string(suffix++);
        if (!used_ids.contains(candidate))
            return candidate;
    }
}

void sync_material_bindings(Scene& scene) {
    for_each_shape(scene, [&](Shape& shape) {
        std::visit([&](auto& value) {
            if (value.material_id.empty()) return;
            if (auto it = scene.materials.find(value.material_id); it != scene.materials.end())
                value.material = it->second;
        }, shape);
    });
}

bool validate_scene(const Scene& scene, std::string* error) {
    std::set<std::string> used_ids;
    auto fail = [&](std::string message) {
        if (error) *error = std::move(message);
        return false;
    };

    for (const auto& [material_id, _] : scene.materials)
        if (material_id.empty())
            return fail("material ids must be non-empty");

    for_each_shape(scene, [&](const Shape& shape) {
        std::visit([&](const auto& value) {
            if (error && !error->empty()) return;
            if (value.id.empty()) {
                if (error) *error = "shape ids must be non-empty";
                return;
            }
            if (!used_ids.insert(value.id).second) {
                if (error) *error = "duplicate entity id: " + value.id;
                return;
            }
            if (!value.material_id.empty() && !scene.materials.contains(value.material_id))
                if (error) *error = "unknown material_id: " + value.material_id;
        }, shape);
    });
    if (error && !error->empty()) return false;

    for_each_light(scene, [&](const Light& light) {
        std::visit([&](const auto& value) {
            if (error && !error->empty()) return;
            if (value.id.empty()) {
                if (error) *error = "light ids must be non-empty";
                return;
            }
            if (!used_ids.insert(value.id).second)
                if (error) *error = "duplicate entity id: " + value.id;
        }, light);
    });
    if (error && !error->empty()) return false;

    for (const auto& group : scene.groups) {
        if (group.id.empty())
            return fail("group ids must be non-empty");
        if (!used_ids.insert(group.id).second)
            return fail("duplicate entity id: " + group.id);
    }

    return true;
}

void ensure_scene_entity_ids(Scene& scene) {
    std::set<std::string> used_ids;
    for_each_shape(scene, [&](Shape& shape) {
        std::visit([&](auto& value) {
            ensure_entity_id(value, shape_type_name(shape), used_ids);
        }, shape);
    });
    for_each_light(scene, [&](Light& light) {
        std::visit([&](auto& value) {
            ensure_entity_id(value, light_type_name(light), used_ids);
        }, light);
    });
    for (auto& group : scene.groups)
        ensure_entity_id(group, "group", used_ids);
}

Shape* find_shape_in(std::vector<Shape>& shapes, std::string_view id) {
    if (id.empty()) return nullptr;
    for (auto& shape : shapes)
        if (entity_has_id(shape, id))
            return &shape;
    return nullptr;
}

const Shape* find_shape_in(const std::vector<Shape>& shapes, std::string_view id) {
    return find_shape_in(const_cast<std::vector<Shape>&>(shapes), id);
}

Light* find_light_in(std::vector<Light>& lights, std::string_view id) {
    if (id.empty()) return nullptr;
    for (auto& light : lights)
        if (entity_has_id(light, id))
            return &light;
    return nullptr;
}

const Light* find_light_in(const std::vector<Light>& lights, std::string_view id) {
    return find_light_in(const_cast<std::vector<Light>&>(lights), id);
}

Shape* find_shape(Scene& scene, std::string_view id) {
    if (id.empty()) return nullptr;
    Shape* result = nullptr;
    for_each_shape(scene, [&](Shape& shape) {
        if (!result && entity_has_id(shape, id))
            result = &shape;
    });
    return result;
}

const Shape* find_shape(const Scene& scene, std::string_view id) {
    return find_shape(const_cast<Scene&>(scene), id);
}

Light* find_light(Scene& scene, std::string_view id) {
    if (id.empty()) return nullptr;
    Light* result = nullptr;
    for_each_light(scene, [&](Light& light) {
        if (!result && entity_has_id(light, id))
            result = &light;
    });
    return result;
}

const Light* find_light(const Scene& scene, std::string_view id) {
    return find_light(const_cast<Scene&>(scene), id);
}

Group* find_group(Scene& scene, std::string_view id) {
    if (id.empty()) return nullptr;
    for (auto& group : scene.groups)
        if (group.id == id)
            return &group;
    return nullptr;
}

const Group* find_group(const Scene& scene, std::string_view id) {
    return find_group(const_cast<Scene&>(scene), id);
}

Material* find_material(Scene& scene, std::string_view id) {
    if (id.empty()) return nullptr;
    if (auto it = scene.materials.find(std::string(id)); it != scene.materials.end())
        return &it->second;
    return nullptr;
}

const Material* find_material(const Scene& scene, std::string_view id) {
    return find_material(const_cast<Scene&>(scene), id);
}

bool bind_material(Shape& shape, const Scene& scene, std::string_view material_id, std::string* error) {
    if (material_id.empty()) {
        if (error) *error = "material ids must be non-empty";
        return false;
    }
    const Material* material = find_material(scene, material_id);
    if (!material) {
        if (error) *error = "unknown material_id: " + std::string(material_id);
        return false;
    }
    std::visit([&](auto& value) {
        value.material_id = std::string(material_id);
        value.material = *material;
    }, shape);
    return true;
}

void detach_material(Shape& shape) {
    std::visit([](auto& value) {
        value.material_id.clear();
    }, shape);
}

int material_usage_count(const Scene& scene, std::string_view material_id) {
    int count = 0;
    if (material_id.empty()) return count;
    for_each_shape(scene, [&](const Shape& shape) {
        std::visit([&](const auto& value) {
            if (value.material_id == material_id)
                ++count;
        }, shape);
    });
    return count;
}

bool rename_material(Scene& scene, std::string_view old_id, std::string_view new_id, std::string* error) {
    auto fail = [&](std::string message) {
        if (error) *error = std::move(message);
        return false;
    };

    if (old_id.empty() || new_id.empty())
        return fail("material ids must be non-empty");
    if (old_id == new_id)
        return find_material(scene, old_id) != nullptr || fail("unknown material_id: " + std::string(old_id));
    if (scene.materials.contains(std::string(new_id)))
        return fail("duplicate material_id: " + std::string(new_id));

    auto it = scene.materials.find(std::string(old_id));
    if (it == scene.materials.end())
        return fail("unknown material_id: " + std::string(old_id));

    Material material = it->second;
    scene.materials.erase(it);
    scene.materials[std::string(new_id)] = material;

    for_each_shape(scene, [&](Shape& shape) {
        std::visit([&](auto& value) {
            if (value.material_id == old_id) {
                value.material_id = std::string(new_id);
                value.material = material;
            }
        }, shape);
    });
    return true;
}

bool delete_material(Scene& scene, std::string_view material_id, std::string* error) {
    auto fail = [&](std::string message) {
        if (error) *error = std::move(message);
        return false;
    };

    if (material_id.empty())
        return fail("material ids must be non-empty");
    auto it = scene.materials.find(std::string(material_id));
    if (it == scene.materials.end())
        return fail("unknown material_id: " + std::string(material_id));

    Material material = it->second;
    scene.materials.erase(it);
    for_each_shape(scene, [&](Shape& shape) {
        std::visit([&](auto& value) {
            if (value.material_id == material_id) {
                value.material = material;
                value.material_id.clear();
            }
        }, shape);
    });
    return true;
}

// ─── Authored source enumeration ──────────────────────────────────

std::vector<AuthoredSource> collect_authored_sources(const Scene& scene) {
    std::vector<AuthoredSource> sources;

    // Scene-level lights
    for (int i = 0; i < (int)scene.lights.size(); ++i) {
        sources.push_back({
            AuthoredSource::SceneLight,
            light_display_name(scene.lights[i], i),
            light_id(scene.lights[i]),
            {},
        });
    }

    // Group lights
    for (int gi = 0; gi < (int)scene.groups.size(); ++gi) {
        const auto& group = scene.groups[gi];
        for (int li = 0; li < (int)group.lights.size(); ++li) {
            sources.push_back({
                AuthoredSource::GroupLight,
                group.id + "/" + light_display_name(group.lights[li], li),
                light_id(group.lights[li]),
                group.id,
            });
        }
    }

    // Emissive shapes (top-level)
    for (int i = 0; i < (int)scene.shapes.size(); ++i) {
        if (shape_material(scene.shapes[i]).emission <= 0.0f) continue;
        sources.push_back({
            AuthoredSource::ShapeEmission,
            shape_display_name(scene.shapes[i], i),
            shape_id(scene.shapes[i]),
            {},
        });
    }

    // Emissive shapes (in groups)
    for (int gi = 0; gi < (int)scene.groups.size(); ++gi) {
        const auto& group = scene.groups[gi];
        for (int si = 0; si < (int)group.shapes.size(); ++si) {
            if (shape_material(group.shapes[si]).emission <= 0.0f) continue;
            sources.push_back({
                AuthoredSource::ShapeEmission,
                group.id + "/" + shape_display_name(group.shapes[si], si),
                shape_id(group.shapes[si]),
                group.id,
            });
        }
    }

    return sources;
}

Scene scene_with_solo_source(const Scene& scene, const AuthoredSource& source) {
    Scene isolated = scene;

    // Zero all emission
    for (auto& shape : isolated.shapes)
        shape_material(shape).emission = 0.0f;
    for (auto& group : isolated.groups)
        for (auto& shape : group.shapes)
            shape_material(shape).emission = 0.0f;

    // Remove all lights
    isolated.lights.clear();
    for (auto& group : isolated.groups)
        group.lights.clear();

    // Restore only the target source
    switch (source.kind) {
    case AuthoredSource::SceneLight: {
        const Light* l = find_light(scene, source.entity_id);
        if (l) isolated.lights.push_back(*l);
        break;
    }
    case AuthoredSource::GroupLight: {
        Group* g = find_group(isolated, source.group_id);
        const Group* orig_g = find_group(scene, source.group_id);
        if (g && orig_g) {
            const Light* l = nullptr;
            for (const auto& light : orig_g->lights)
                if (light_id(light) == source.entity_id) { l = &light; break; }
            if (l) g->lights.push_back(*l);
        }
        break;
    }
    case AuthoredSource::ShapeEmission: {
        if (source.group_id.empty()) {
            Shape* s = find_shape(isolated, source.entity_id);
            const Shape* orig = find_shape(scene, source.entity_id);
            if (s && orig)
                shape_material(*s).emission = shape_material(*orig).emission;
        } else {
            Group* g = find_group(isolated, source.group_id);
            const Group* orig_g = find_group(scene, source.group_id);
            if (g && orig_g) {
                for (auto& shape : g->shapes) {
                    if (shape_id(shape) == source.entity_id) {
                        for (const auto& orig_shape : orig_g->shapes) {
                            if (shape_id(orig_shape) == source.entity_id) {
                                shape_material(shape).emission = shape_material(orig_shape).emission;
                                break;
                            }
                        }
                        break;
                    }
                }
            }
        }
        break;
    }
    }

    return isolated;
}

bool normalize_scene(Scene& scene, std::string* error) {
    ensure_scene_entity_ids(scene);
    sync_material_bindings(scene);
    return validate_scene(scene, error);
}

// ─── Common variant field accessors ───────────────────────────────

const std::string& shape_id(const Shape& s) {
    return std::visit([](const auto& v) -> const std::string& { return v.id; }, s);
}
std::string& shape_id(Shape& s) {
    return std::visit([](auto& v) -> std::string& { return v.id; }, s);
}
const std::string& light_id(const Light& l) {
    return std::visit([](const auto& v) -> const std::string& { return v.id; }, l);
}
std::string& light_id(Light& l) {
    return std::visit([](auto& v) -> std::string& { return v.id; }, l);
}
const Material& shape_material(const Shape& s) {
    return std::visit([](const auto& v) -> const Material& { return v.material; }, s);
}
Material& shape_material(Shape& s) {
    return std::visit([](auto& v) -> Material& { return v.material; }, s);
}
const std::string& shape_material_id(const Shape& s) {
    return std::visit([](const auto& v) -> const std::string& { return v.material_id; }, s);
}
std::string& shape_material_id(Shape& s) {
    return std::visit([](auto& v) -> std::string& { return v.material_id; }, s);
}

std::string shape_display_name(const Shape& s, int fallback_index) {
    const std::string& id = shape_id(s);
    if (!id.empty()) return id;
    std::string kind = std::visit(overloaded{
        [](const Circle&) { return std::string{"Circle"}; },
        [](const Segment&) { return std::string{"Segment"}; },
        [](const Arc&) { return std::string{"Arc"}; },
        [](const Bezier&) { return std::string{"Bezier"}; },
        [](const Polygon&) { return std::string{"Polygon"}; },
        [](const Ellipse&) { return std::string{"Ellipse"}; },
    }, s);
    return kind + " " + std::to_string(fallback_index);
}

std::string light_display_name(const Light& l, int fallback_index) {
    const std::string& id = light_id(l);
    if (!id.empty()) return id;
    std::string kind = std::visit(overloaded{
        [](const PointLight&) { return std::string{"Point Light"}; },
        [](const SegmentLight&) { return std::string{"Segment Light"}; },
        [](const BeamLight&) { return std::string{"Beam Light"}; },
        [](const ParallelBeamLight&) { return std::string{"Parallel Beam"}; },
        [](const SpotLight&) { return std::string{"Spot Light"}; },
    }, l);
    return kind + " " + std::to_string(fallback_index);
}

// ─── Utilities ────────────────────────────────────────────────────

void world_to_pixel(std::span<LineSegment> segments, const Bounds& bounds, int width, int height) {
    Vec2 size = bounds.max - bounds.min;
    float scale_x = (float)width / size.x;
    float scale_y = (float)height / size.y;
    float scale = std::min(scale_x, scale_y);
    Vec2 offset = {(width - size.x * scale) * 0.5f, (height - size.y * scale) * 0.5f};

    for (auto& s : segments) {
        s.p0 = (s.p0 - bounds.min) * scale + offset;
        s.p1 = (s.p1 - bounds.min) * scale + offset;
    }
}

void add_box_walls(Scene& scene, float half_w, float half_h, const Material& mat) {
    // CW winding so perp() normals point inward
    Segment bottom;
    bottom.a = {-half_w, -half_h};
    bottom.b = {half_w, -half_h};
    bottom.material = mat;
    scene.shapes.push_back(bottom);

    Segment top;
    top.a = {half_w, half_h};
    top.b = {-half_w, half_h};
    top.material = mat;
    scene.shapes.push_back(top);

    Segment left;
    left.a = {-half_w, half_h};
    left.b = {-half_w, -half_h};
    left.material = mat;
    scene.shapes.push_back(left);

    Segment right;
    right.a = {half_w, -half_h};
    right.b = {half_w, half_h};
    right.material = mat;
    scene.shapes.push_back(right);
}

// --- Shot types ---

Bounds Camera2D::resolve(float aspect, const Bounds& fallback) const {
    if (bounds) return *bounds;
    if (center && width) {
        float hw = *width / 2.0f;
        float hh = hw / aspect;
        return {{center->x - hw, center->y - hh}, {center->x + hw, center->y + hh}};
    }
    return fallback;
}

TraceConfig TraceDefaults::to_trace_config() const {
    return {.batch_size = batch, .max_depth = depth, .intensity = intensity};
}
