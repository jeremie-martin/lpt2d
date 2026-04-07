#include "editor.h"

#include "geometry.h"

#include <cmath>
#include <variant>

namespace {

void expand_bounds(Bounds& combined, bool& initialized, const Bounds& b) {
    if (!initialized) {
        combined = b;
        initialized = true;
        return;
    }
    combined.min.x = std::min(combined.min.x, b.min.x);
    combined.min.y = std::min(combined.min.y, b.min.y);
    combined.max.x = std::max(combined.max.x, b.max.x);
    combined.max.y = std::max(combined.max.y, b.max.y);
}

} // namespace

Shape* resolve_shape(Scene& scene, const SelectionRef& id) {
    if (id.type != SelectionRef::Shape || id.id.empty()) return nullptr;
    if (!id.group_id.empty()) {
        if (Group* g = find_group(scene, id.group_id))
            return find_shape_in(g->shapes, id.id);
        return nullptr;
    }
    return find_shape_in(scene.shapes, id.id);
}

const Shape* resolve_shape(const Scene& scene, const SelectionRef& id) {
    return resolve_shape(const_cast<Scene&>(scene), id);
}

Light* resolve_light(Scene& scene, const SelectionRef& id) {
    if (id.type != SelectionRef::Light || id.id.empty()) return nullptr;
    if (!id.group_id.empty()) {
        if (Group* g = find_group(scene, id.group_id))
            return find_light_in(g->lights, id.id);
        return nullptr;
    }
    return find_light_in(scene.lights, id.id);
}

const Light* resolve_light(const Scene& scene, const SelectionRef& id) {
    return resolve_light(const_cast<Scene&>(scene), id);
}

// ─── Object centroid ───────────────────────────────────────────────────

Vec2 object_centroid(const Scene& scene, const SelectionRef& id) {
    if (const Shape* shape = resolve_shape(scene, id))
        return shape_centroid(*shape);
    if (const Light* light = resolve_light(scene, id))
        return light_centroid(*light);
    if (id.type == SelectionRef::Group) {
        if (const Group* g = find_group(scene, id.id))
            return g->transform.translate;
    }
    return {0, 0};
}

Vec2 EditorState::selection_centroid() const {
    if (interaction.selection.empty()) return {0, 0};
    Vec2 sum{0, 0};
    for (auto& id : interaction.selection) sum = sum + object_centroid(shot.scene, id);
    return sum * (1.0f / interaction.selection.size());
}

std::optional<Bounds> object_bounds(const Scene& scene, const SelectionRef& id) {
    if (const Shape* shape = resolve_shape(scene, id))
        return shape_bounds(*shape);
    if (const Light* light = resolve_light(scene, id))
        return light_bounds(*light);
    if (id.type == SelectionRef::Group) {
        if (const Group* group = find_group(scene, id.id)) {
            bool initialized = false;
            Bounds combined{};
            for (const auto& shape : group->shapes)
                expand_bounds(combined, initialized, shape_bounds(transform_shape(shape, group->transform)));
            for (const auto& light : group->lights)
                expand_bounds(combined, initialized, light_bounds(transform_light(light, group->transform)));
            if (initialized) return combined;
        }
    }
    return std::nullopt;
}

Bounds EditorState::selection_bounds() const {
    if (interaction.selection.empty()) return {{0, 0}, {0, 0}};
    bool initialized = false;
    Bounds combined{};
    for (auto& id : interaction.selection) {
        if (auto b = object_bounds(shot.scene, id))
            expand_bounds(combined, initialized, *b);
    }
    return initialized ? combined : Bounds{{0, 0}, {0, 0}};
}

// ─── Hit testing ───────────────────────────────────────────────────────

static float point_seg_dist(Vec2 p, Vec2 a, Vec2 b) {
    Vec2 ab = b - a;
    float len2 = ab.length_sq();
    if (len2 < 1e-10f) return (p - a).length();
    float t = std::clamp((p - a).dot(ab) / len2, 0.0f, 1.0f);
    return (p - (a + ab * t)).length();
}

static float shape_distance(Vec2 wp, const Shape& shape) {
    return std::visit(overloaded{
        [&](const Circle& c) -> float {
            float dc = (wp - c.center).length();
            return dc < c.radius ? 0.0f : dc - c.radius;
        },
        [&](const Segment& s) -> float { return point_seg_dist(wp, s.a, s.b); },
        [&](const Arc& a) -> float { return point_arc_distance(wp, a); },
        [&](const Bezier& b) -> float {
            float best = 1e30f;
            for (int j = 0; j <= 20; ++j) {
                float t = j / 20.0f;
                float u = 1.0f - t;
                Vec2 p = b.p0 * (u * u) + b.p1 * (2.0f * u * t) + b.p2 * (t * t);
                best = std::min(best, (wp - p).length());
            }
            return best;
        },
        [&](const Polygon& p) -> float {
            float best = 1e30f;
            int n = (int)p.vertices.size();
            for (int i = 0; i < n; ++i)
                best = std::min(best, point_seg_dist(wp, p.vertices[i], p.vertices[(i + 1) % n]));
            return best;
        },
        [&](const Ellipse& e) -> float {
            // Transform point to local coords
            float cr = std::cos(-e.rotation), sr = std::sin(-e.rotation);
            Vec2 d = wp - e.center;
            Vec2 local{d.x * cr - d.y * sr, d.x * sr + d.y * cr};
            // Find nearest point on ellipse via parametric angle
            float angle = std::atan2(local.y / e.semi_b, local.x / e.semi_a);
            Vec2 closest{e.semi_a * std::cos(angle), e.semi_b * std::sin(angle)};
            return (local - closest).length();
        },
        [&](const Path& path) -> float {
            auto parts = decompose_path(path);
            float best = 1e30f;
            for (auto& curve : parts.curves) {
                for (int j = 0; j <= 20; ++j) {
                    float t = j / 20.0f;
                    Vec2 p = bezier_eval(curve, t);
                    best = std::min(best, (wp - p).length());
                }
            }
            return best;
        },
    }, shape);
}

static float light_distance(Vec2 wp, const Light& light) {
    return std::visit(overloaded{
        [&](const PointLight& l) -> float { return (wp - l.pos).length(); },
        [&](const SegmentLight& l) -> float { return point_seg_dist(wp, l.a, l.b); },
        [&](const ProjectorLight& l) -> float {
            if (l.source == ProjectorSource::Ball && l.source_radius > 0.0f) {
                float d = (wp - l.position).length();
                return std::min(d, std::abs(d - l.source_radius));
            }
            Vec2 dir = l.direction.length_sq() > 1e-6f ? l.direction.normalized() : Vec2{1.0f, 0.0f};
            Vec2 tangent = dir.perp() * l.source_radius;
            Vec2 a = l.position - tangent;
            Vec2 b = l.position + tangent;
            return std::min((wp - l.position).length(), point_seg_dist(wp, a, b));
        },
    }, light);
}

SelectionRef hit_test(Vec2 wp, const Scene& scene, float threshold, const std::string& editing_group_id) {
    SelectionRef result{};
    float best = threshold;

    if (!editing_group_id.empty()) {
        const Group* group = find_group(scene, editing_group_id);
        if (!group) return result;
        // Inside a group: only hit-test members of the editing group
        for (const auto& shape : group->shapes) {
            Shape ws = transform_shape(shape, group->transform);
            float d = shape_distance(wp, ws);
            if (d < best) { best = d; result = {SelectionRef::Shape, shape_id(shape), editing_group_id}; }
        }
        for (const auto& light : group->lights) {
            Light wl = transform_light(light, group->transform);
            float d = light_distance(wp, wl);
            if (d < best) { best = d; result = {SelectionRef::Light, light_id(light), editing_group_id}; }
        }
        return result;
    }

    // Normal mode: hit-test top-level objects
    for (const auto& shape : scene.shapes) {
        float d = shape_distance(wp, shape);
        if (d < best) { best = d; result = {SelectionRef::Shape, shape_id(shape), ""}; }
    }
    for (const auto& light : scene.lights) {
        float d = light_distance(wp, light);
        if (d < best) { best = d; result = {SelectionRef::Light, light_id(light), ""}; }
    }
    // Test group members (in world space) — return group, not individual member
    for (const auto& group : scene.groups) {
        for (const auto& shape : group.shapes) {
            Shape ws = transform_shape(shape, group.transform);
            float d = shape_distance(wp, ws);
            if (d < best) { best = d; result = {SelectionRef::Group, group.id, ""}; }
        }
        for (const auto& light : group.lights) {
            Light wl = transform_light(light, group.transform);
            float d = light_distance(wp, wl);
            if (d < best) { best = d; result = {SelectionRef::Group, group.id, ""}; }
        }
    }
    return result;
}

bool object_in_rect(const Scene& scene, SelectionRef id, Vec2 rect_min, Vec2 rect_max) {
    auto overlaps = [&](const Bounds& b) {
        return b.max.x >= rect_min.x && b.min.x <= rect_max.x &&
               b.max.y >= rect_min.y && b.min.y <= rect_max.y;
    };
    if (const Shape* shape = resolve_shape(scene, id))
        return overlaps(shape_bounds(*shape));
    if (const Light* light = resolve_light(scene, id))
        return overlaps(light_bounds(*light));
    if (id.type == SelectionRef::Group) {
        if (const Group* group = find_group(scene, id.id)) {
            for (const auto& shape : group->shapes) {
                Shape ws = transform_shape(shape, group->transform);
                if (overlaps(shape_bounds(ws))) return true;
            }
            for (const auto& light : group->lights) {
                Light wl = transform_light(light, group->transform);
                if (overlaps(light_bounds(wl))) return true;
            }
        }
    }
    return false;
}

// ─── Transform application ─────────────────────────────────────────────

static Vec2 rotate_around(Vec2 p, Vec2 pivot, float angle) {
    Vec2 d = p - pivot;
    float c = std::cos(angle), s = std::sin(angle);
    return pivot + Vec2{d.x * c - d.y * s, d.x * s + d.y * c};
}

static Vec2 scale_around(Vec2 p, Vec2 pivot, float factor_x, float factor_y) {
    return pivot + Vec2{(p.x - pivot.x) * factor_x, (p.y - pivot.y) * factor_y};
}

static Vec2 compute_grab_delta(const TransformMode& tm, Vec2 mouse_world) {
    Vec2 delta = mouse_world - tm.mouse_start;
    if (tm.lock_x) delta.y = 0;
    if (tm.lock_y) delta.x = 0;

    // Numeric override
    if (!tm.numeric_buf.empty()) {
        float val = 0;
        try { val = std::stof(tm.numeric_buf); } catch (...) {}
        if (tm.lock_x) delta = {val, 0};
        else if (tm.lock_y) delta = {0, val};
        else delta = {val, val};
    }
    return delta;
}

static float compute_rotate_angle(const TransformMode& tm, Vec2 mouse_world, bool shift_held) {
    Vec2 v0 = tm.mouse_start - tm.pivot;
    Vec2 v1 = mouse_world - tm.pivot;
    float angle = std::atan2(v1.y, v1.x) - std::atan2(v0.y, v0.x);

    if (!tm.numeric_buf.empty()) {
        try { angle = std::stof(tm.numeric_buf) * PI / 180.0f; } catch (...) {}
    } else if (shift_held) {
        float snap = 5.0f * PI / 180.0f;
        angle = std::round(angle / snap) * snap;
    }
    return angle;
}

static float compute_scale_factor(const TransformMode& tm, Vec2 mouse_world, bool shift_held) {
    float d0 = (tm.mouse_start - tm.pivot).length();
    float d1 = (mouse_world - tm.pivot).length();
    float factor = (d0 > 1e-6f) ? d1 / d0 : 1.0f;

    if (!tm.numeric_buf.empty()) {
        try { factor = std::stof(tm.numeric_buf); } catch (...) {}
    } else if (shift_held) {
        factor = std::round(factor * 10.0f) / 10.0f;
    }
    return std::max(factor, 0.01f);
}

void translate_shape(Shape& s, Vec2 delta) {
    std::visit(overloaded{
        [&](Circle& c) { c.center = c.center + delta; },
        [&](Segment& seg) { seg.a = seg.a + delta; seg.b = seg.b + delta; },
        [&](Arc& a) { a.center = a.center + delta; },
        [&](Bezier& b) { b.p0 = b.p0 + delta; b.p1 = b.p1 + delta; b.p2 = b.p2 + delta; },
        [&](Polygon& p) { for (auto& v : p.vertices) v = v + delta; },
        [&](Ellipse& e) { e.center = e.center + delta; },
        [&](Path& p) { for (auto& v : p.points) v = v + delta; },
    }, s);
}

void translate_light(Light& l, Vec2 delta) {
    std::visit(overloaded{
        [&](PointLight& pl) { pl.pos = pl.pos + delta; },
        [&](SegmentLight& sl) { sl.a = sl.a + delta; sl.b = sl.b + delta; },
        [&](ProjectorLight& pl) { pl.position = pl.position + delta; },
    }, l);
}

static void rotate_shape(Shape& s, Vec2 pivot, float angle) {
    std::visit(overloaded{
        [&](Circle& c) { c.center = rotate_around(c.center, pivot, angle); },
        [&](Segment& seg) { seg.a = rotate_around(seg.a, pivot, angle); seg.b = rotate_around(seg.b, pivot, angle); },
        [&](Arc& a) {
            a.center = rotate_around(a.center, pivot, angle);
            a.angle_start = normalize_angle(a.angle_start + angle);
            a.sweep = clamp_arc_sweep(a.sweep);
        },
        [&](Bezier& b) {
            b.p0 = rotate_around(b.p0, pivot, angle);
            b.p1 = rotate_around(b.p1, pivot, angle);
            b.p2 = rotate_around(b.p2, pivot, angle);
        },
        [&](Polygon& p) { for (auto& v : p.vertices) v = rotate_around(v, pivot, angle); },
        [&](Ellipse& e) {
            e.center = rotate_around(e.center, pivot, angle);
            e.rotation += angle;
        },
        [&](Path& p) { for (auto& v : p.points) v = rotate_around(v, pivot, angle); },
    }, s);
}

static void rotate_light(Light& l, Vec2 pivot, float angle) {
    std::visit(overloaded{
        [&](PointLight& pl) { pl.pos = rotate_around(pl.pos, pivot, angle); },
        [&](SegmentLight& sl) { sl.a = rotate_around(sl.a, pivot, angle); sl.b = rotate_around(sl.b, pivot, angle); },
        [&](ProjectorLight& pl) {
            pl.position = rotate_around(pl.position, pivot, angle);
            float c = std::cos(angle), s = std::sin(angle);
            Vec2 d = pl.direction;
            pl.direction = Vec2{d.x * c - d.y * s, d.x * s + d.y * c}.normalized();
        },
    }, l);
}

static void scale_shape(Shape& s, Vec2 pivot, float fx, float fy) {
    float uniform = std::sqrt(fx * fy); // for radii
    std::visit(overloaded{
        [&](Circle& c) {
            c.center = scale_around(c.center, pivot, fx, fy);
            c.radius = std::max(c.radius * uniform, 0.01f);
        },
        [&](Segment& seg) {
            seg.a = scale_around(seg.a, pivot, fx, fy);
            seg.b = scale_around(seg.b, pivot, fx, fy);
        },
        [&](Arc& a) {
            a.center = scale_around(a.center, pivot, fx, fy);
            a.radius = std::max(a.radius * uniform, 0.01f);
        },
        [&](Bezier& b) {
            b.p0 = scale_around(b.p0, pivot, fx, fy);
            b.p1 = scale_around(b.p1, pivot, fx, fy);
            b.p2 = scale_around(b.p2, pivot, fx, fy);
        },
        [&](Polygon& p) { for (auto& v : p.vertices) v = scale_around(v, pivot, fx, fy); },
        [&](Ellipse& e) {
            e.center = scale_around(e.center, pivot, fx, fy);
            e.semi_a = std::max(e.semi_a * uniform, 0.01f);
            e.semi_b = std::max(e.semi_b * uniform, 0.01f);
        },
        [&](Path& p) { for (auto& v : p.points) v = scale_around(v, pivot, fx, fy); },
    }, s);
}

static void scale_light(Light& l, Vec2 pivot, float fx, float fy) {
    std::visit(overloaded{
        [&](PointLight& pl) { pl.pos = scale_around(pl.pos, pivot, fx, fy); },
        [&](SegmentLight& sl) { sl.a = scale_around(sl.a, pivot, fx, fy); sl.b = scale_around(sl.b, pivot, fx, fy); },
        [&](ProjectorLight& pl) {
            float uniform = std::sqrt(fx * fy);
            pl.position = scale_around(pl.position, pivot, fx, fy);
            pl.source_radius *= uniform;
            pl.spread *= uniform;
            sanitize_projector_light(pl);
        },
    }, l);
}

void translate_group(Group& g, Vec2 delta) {
    g.transform.translate = g.transform.translate + delta;
}

void apply_transform_group(Group& dst, const Group& src, const TransformMode& tm, Vec2 mouse_world, bool shift_held) {
    dst = src;
    switch (tm.type) {
    case TransformMode::Grab:
        dst.transform.translate = src.transform.translate + compute_grab_delta(tm, mouse_world);
        break;
    case TransformMode::Rotate: {
        float angle = compute_rotate_angle(tm, mouse_world, shift_held);
        dst.transform.rotate = src.transform.rotate + angle;
        dst.transform.translate = rotate_around(src.transform.translate, tm.pivot, angle);
        break;
    }
    case TransformMode::Scale: {
        float f = compute_scale_factor(tm, mouse_world, shift_held);
        float fx = tm.lock_x ? f : (tm.lock_y ? 1.0f : f);
        float fy = tm.lock_y ? f : (tm.lock_x ? 1.0f : f);
        dst.transform.scale = {src.transform.scale.x * fx, src.transform.scale.y * fy};
        dst.transform.translate = scale_around(src.transform.translate, tm.pivot, fx, fy);
        break;
    }
    default: break;
    }
}

void apply_transform_shape(Shape& dst, const Shape& src, const TransformMode& tm, Vec2 mouse_world, bool shift_held) {
    dst = src;
    switch (tm.type) {
    case TransformMode::Grab:
        translate_shape(dst, compute_grab_delta(tm, mouse_world));
        break;
    case TransformMode::Rotate:
        rotate_shape(dst, tm.pivot, compute_rotate_angle(tm, mouse_world, shift_held));
        break;
    case TransformMode::Scale: {
        float f = compute_scale_factor(tm, mouse_world, shift_held);
        float fx = tm.lock_x ? f : (tm.lock_y ? 1.0f : f);
        float fy = tm.lock_y ? f : (tm.lock_x ? 1.0f : f);
        scale_shape(dst, tm.pivot, fx, fy);
        break;
    }
    default: break;
    }
}

void apply_transform_light(Light& dst, const Light& src, const TransformMode& tm, Vec2 mouse_world, bool shift_held) {
    dst = src;
    switch (tm.type) {
    case TransformMode::Grab:
        translate_light(dst, compute_grab_delta(tm, mouse_world));
        break;
    case TransformMode::Rotate:
        rotate_light(dst, tm.pivot, compute_rotate_angle(tm, mouse_world, shift_held));
        break;
    case TransformMode::Scale: {
        float f = compute_scale_factor(tm, mouse_world, shift_held);
        float fx = tm.lock_x ? f : (tm.lock_y ? 1.0f : f);
        float fy = tm.lock_y ? f : (tm.lock_x ? 1.0f : f);
        scale_light(dst, tm.pivot, fx, fy);
        break;
    }
    default: break;
    }
}

// ─── Handle generation ─────────────────────────────────────────────────

std::vector<Handle> get_handles(const Scene& scene, const std::vector<SelectionRef>& selection) {
    std::vector<Handle> handles;

    for (auto& id : selection) {
        if (const Shape* shape = resolve_shape(scene, id)) {
            std::visit(overloaded{
                [&](const Circle& c) {
                    handles.push_back({Handle::Position, id, 0, c.center});
                    handles.push_back({Handle::Radius, id, 0, c.center + Vec2{c.radius, 0}});
                },
                [&](const Segment& s) {
                    handles.push_back({Handle::Position, id, 0, s.a});
                    handles.push_back({Handle::Position, id, 1, s.b});
                },
                [&](const Arc& a) {
                    handles.push_back({Handle::Position, id, 0, a.center});
                    handles.push_back({Handle::Radius, id, 0, arc_mid_point(a)});
                    handles.push_back({Handle::Angle, id, 0, arc_start_point(a)});
                    handles.push_back({Handle::Angle, id, 1, arc_end_point(a)});
                },
                [&](const Bezier& b) {
                    handles.push_back({Handle::Position, id, 0, b.p0});
                    handles.push_back({Handle::Position, id, 1, b.p1}); // control point
                    handles.push_back({Handle::Position, id, 2, b.p2});
                },
                [&](const Polygon& p) {
                    for (int i = 0; i < (int)p.vertices.size(); ++i)
                        handles.push_back({Handle::Position, id, i, p.vertices[i]});
                },
                [&](const Ellipse& e) {
                    handles.push_back({Handle::Position, id, 0, e.center});
                    float cr = std::cos(e.rotation), sr = std::sin(e.rotation);
                    handles.push_back({Handle::Radius, id, 0, e.center + Vec2{e.semi_a * cr, e.semi_a * sr}});
                    handles.push_back({Handle::Radius, id, 1, e.center + Vec2{-e.semi_b * sr, e.semi_b * cr}});
                },
                [&](const Path& p) {
                    for (int i = 0; i < (int)p.points.size(); ++i)
                        handles.push_back({Handle::Position, id, i, p.points[i]});
                },
            }, *shape);
        }
        if (const Light* light = resolve_light(scene, id)) {
            std::visit(overloaded{
                [&](const PointLight& l) {
                    handles.push_back({Handle::Position, id, 0, l.pos});
                },
                [&](const SegmentLight& l) {
                    handles.push_back({Handle::Position, id, 0, l.a});
                    handles.push_back({Handle::Position, id, 1, l.b});
                },
                [&](const ProjectorLight& l) {
                    Vec2 dir = l.direction.length_sq() > 1e-6f ? l.direction.normalized() : Vec2{1.0f, 0.0f};
                    Vec2 tangent = dir.perp();
                    handles.push_back({Handle::Position, id, 0, l.position});
                    handles.push_back({Handle::Direction, id, 0, l.position + dir * 0.3f});
                    handles.push_back({Handle::Radius, id, 0, l.position + tangent * std::max(l.source_radius, 0.08f)});
                },
            }, *light);
        }
        if (id.type == SelectionRef::Group) {
            if (const Group* group = find_group(scene, id.id))
                handles.push_back({Handle::Position, id, 0, group->transform.translate});
        }
    }
    return handles;
}

int handle_hit_test(const std::vector<Handle>& handles, Vec2 wp, float threshold) {
    int best_idx = -1;
    float best_dist = threshold;
    for (int i = 0; i < (int)handles.size(); ++i) {
        float d = (wp - handles[i].world_pos).length();
        if (d < best_dist) { best_dist = d; best_idx = i; }
    }
    return best_idx;
}

// ─── Handle drag application ───────────────────────────────────────────

void apply_handle_drag(Scene& scene, const Handle& handle, Vec2 wp) {
    auto& obj = handle.obj;

    if (Shape* shape = resolve_shape(scene, obj)) {
        std::visit(overloaded{
            [&](Circle& c) {
                if (handle.kind == Handle::Position) {
                    c.center = wp;
                } else if (handle.kind == Handle::Radius) {
                    c.radius = std::max((wp - c.center).length(), 0.01f);
                }
            },
            [&](Segment& s) {
                if (handle.param_index == 0) s.a = wp;
                else s.b = wp;
            },
            [&](Arc& a) {
                if (handle.kind == Handle::Position) {
                    a.center = wp;
                } else if (handle.kind == Handle::Radius) {
                    a.radius = std::max((wp - a.center).length(), 0.01f);
                } else if (handle.kind == Handle::Angle) {
                    float old_sweep = clamp_arc_sweep(a.sweep);
                    float angle = normalize_angle(std::atan2(wp.y - a.center.y, wp.x - a.center.x));
                    if (old_sweep >= TWO_PI - INTERSECT_EPS) {
                        a.angle_start = angle;
                        a.sweep = TWO_PI;
                    } else if (handle.param_index == 0) {
                        float raw_end_angle = a.angle_start + old_sweep;
                        a.angle_start = angle;
                        a.sweep = clamp_arc_sweep(normalize_angle(raw_end_angle - a.angle_start));
                    } else {
                        a.sweep = clamp_arc_sweep(normalize_angle(angle - a.angle_start));
                    }
                }
            },
            [&](Bezier& b) {
                if (handle.param_index == 0) b.p0 = wp;
                else if (handle.param_index == 1) b.p1 = wp;
                else b.p2 = wp;
            },
            [&](Polygon& p) {
                if (handle.param_index >= 0 && handle.param_index < (int)p.vertices.size())
                    p.vertices[handle.param_index] = wp;
            },
            [&](Ellipse& e) {
                if (handle.kind == Handle::Position) {
                    e.center = wp;
                } else if (handle.kind == Handle::Radius) {
                    Vec2 d = wp - e.center;
                    float cr = std::cos(e.rotation), sr = std::sin(e.rotation);
                    if (handle.param_index == 0)
                        e.semi_a = std::max(d.x * cr + d.y * sr, 0.01f);
                    else
                        e.semi_b = std::max(-d.x * sr + d.y * cr, 0.01f);
                }
            },
            [&](Path& p) {
                if (handle.param_index >= 0 && handle.param_index < (int)p.points.size())
                    p.points[handle.param_index] = wp;
            },
        }, *shape);
    }

    if (Light* light = resolve_light(scene, obj)) {
        std::visit(overloaded{
            [&](PointLight& l) {
                l.pos = wp;
            },
            [&](SegmentLight& l) {
                if (handle.param_index == 0) l.a = wp;
                else l.b = wp;
            },
            [&](ProjectorLight& l) {
                if (handle.kind == Handle::Position) {
                    l.position = wp;
                } else if (handle.kind == Handle::Direction) {
                    Vec2 d = wp - l.position;
                    if (d.length_sq() > 1e-6f) l.direction = d.normalized();
                } else if (handle.kind == Handle::Radius) {
                    Vec2 dir = l.direction.length_sq() > 1e-6f ? l.direction.normalized() : Vec2{1.0f, 0.0f};
                    Vec2 tangent = dir.perp();
                    l.source_radius = std::max(std::abs((wp - l.position).dot(tangent)), 0.0f);
                }
            },
        }, *light);
    }

    if (obj.type == SelectionRef::Group) {
        if (Group* group = find_group(scene, obj.id)) {
            if (handle.kind == Handle::Position) {
                group->transform.translate = wp;
            }
        }
    }
}
