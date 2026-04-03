#include "editor.h"

#include <cmath>

// ─── Object centroid ───────────────────────────────────────────────────

Vec2 object_centroid(const Scene& scene, ObjectId id) {
    if (id.type == ObjectId::Shape && id.index < (int)scene.shapes.size()) {
        return std::visit(overloaded{
            [](const Circle& c) -> Vec2 { return c.center; },
            [](const Segment& s) -> Vec2 { return (s.a + s.b) * 0.5f; },
            [](const Arc& a) -> Vec2 { return a.center; },
            [](const Bezier& b) -> Vec2 { return (b.p0 + b.p1 + b.p2) * (1.0f / 3.0f); },
        }, scene.shapes[id.index]);
    }
    if (id.type == ObjectId::Light && id.index < (int)scene.lights.size()) {
        return std::visit(overloaded{
            [](const PointLight& l) -> Vec2 { return l.pos; },
            [](const SegmentLight& l) -> Vec2 { return (l.a + l.b) * 0.5f; },
            [](const BeamLight& l) -> Vec2 { return l.origin; },
        }, scene.lights[id.index]);
    }
    if (id.type == ObjectId::Group && id.index < (int)scene.groups.size()) {
        return scene.groups[id.index].transform.translate;
    }
    return {0, 0};
}

Vec2 EditorState::selection_centroid() const {
    if (selection.empty()) return {0, 0};
    Vec2 sum{0, 0};
    for (auto& id : selection) sum = sum + object_centroid(scene, id);
    return sum * (1.0f / selection.size());
}

Bounds EditorState::selection_bounds() const {
    if (selection.empty()) return {{0, 0}, {0, 0}};
    Vec2 lo{1e30f, 1e30f}, hi{-1e30f, -1e30f};
    auto expand = [&](Vec2 p) {
        lo.x = std::min(lo.x, p.x); lo.y = std::min(lo.y, p.y);
        hi.x = std::max(hi.x, p.x); hi.y = std::max(hi.y, p.y);
    };
    for (auto& id : selection) {
        if (id.type == ObjectId::Shape && id.index < (int)scene.shapes.size()) {
            std::visit(overloaded{
                [&](const Circle& c) { expand(c.center - Vec2{c.radius, c.radius}); expand(c.center + Vec2{c.radius, c.radius}); },
                [&](const Segment& s) { expand(s.a); expand(s.b); },
                [&](const Arc& a) { expand(a.center - Vec2{a.radius, a.radius}); expand(a.center + Vec2{a.radius, a.radius}); },
                [&](const Bezier& b) { expand(b.p0); expand(b.p1); expand(b.p2); },
            }, scene.shapes[id.index]);
        }
        if (id.type == ObjectId::Light && id.index < (int)scene.lights.size()) {
            std::visit(overloaded{
                [&](const PointLight& l) { expand(l.pos); },
                [&](const SegmentLight& l) { expand(l.a); expand(l.b); },
                [&](const BeamLight& l) { expand(l.origin); },
            }, scene.lights[id.index]);
        }
        if (id.type == ObjectId::Group && id.index < (int)scene.groups.size()) {
            const auto& group = scene.groups[id.index];
            for (const auto& shape : group.shapes) {
                Shape ws = transform_shape(shape, group.transform);
                std::visit(overloaded{
                    [&](const Circle& c) { expand(c.center - Vec2{c.radius, c.radius}); expand(c.center + Vec2{c.radius, c.radius}); },
                    [&](const Segment& s) { expand(s.a); expand(s.b); },
                    [&](const Arc& a) { expand(a.center - Vec2{a.radius, a.radius}); expand(a.center + Vec2{a.radius, a.radius}); },
                    [&](const Bezier& b) { expand(b.p0); expand(b.p1); expand(b.p2); },
                }, ws);
            }
            for (const auto& light : group.lights) {
                Light wl = transform_light(light, group.transform);
                std::visit(overloaded{
                    [&](const PointLight& l) { expand(l.pos); },
                    [&](const SegmentLight& l) { expand(l.a); expand(l.b); },
                    [&](const BeamLight& l) { expand(l.origin); },
                }, wl);
            }
        }
    }
    return {lo, hi};
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
        [&](const Arc& a) -> float {
            Vec2 d = wp - a.center;
            float dc = d.length();
            float angle = std::atan2(d.y, d.x);
            if (angle < 0) angle += TWO_PI;
            float span = a.angle_end - a.angle_start;
            if (span < 0) span += TWO_PI;
            float rel = angle - a.angle_start;
            if (rel < 0) rel += TWO_PI;
            if (rel <= span) {
                return std::abs(dc - a.radius);
            }
            Vec2 p0 = a.center + Vec2{a.radius * std::cos(a.angle_start), a.radius * std::sin(a.angle_start)};
            Vec2 p1 = a.center + Vec2{a.radius * std::cos(a.angle_end), a.radius * std::sin(a.angle_end)};
            return std::min((wp - p0).length(), (wp - p1).length());
        },
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
    }, shape);
}

static float light_distance(Vec2 wp, const Light& light) {
    return std::visit(overloaded{
        [&](const PointLight& l) -> float { return (wp - l.pos).length(); },
        [&](const SegmentLight& l) -> float { return point_seg_dist(wp, l.a, l.b); },
        [&](const BeamLight& l) -> float { return (wp - l.origin).length(); },
    }, light);
}

ObjectId hit_test(Vec2 wp, const Scene& scene, float threshold, int editing_group) {
    ObjectId result{ObjectId::Shape, -1};
    float best = threshold;

    if (editing_group >= 0 && editing_group < (int)scene.groups.size()) {
        // Inside a group: only hit-test members of the editing group
        const auto& group = scene.groups[editing_group];
        for (int i = 0; i < (int)group.shapes.size(); ++i) {
            Shape ws = transform_shape(group.shapes[i], group.transform);
            float d = shape_distance(wp, ws);
            if (d < best) { best = d; result = {ObjectId::Shape, i, editing_group}; }
        }
        for (int i = 0; i < (int)group.lights.size(); ++i) {
            Light wl = transform_light(group.lights[i], group.transform);
            float d = light_distance(wp, wl);
            if (d < best) { best = d; result = {ObjectId::Light, i, editing_group}; }
        }
        return result;
    }

    // Normal mode: hit-test top-level objects
    for (int i = 0; i < (int)scene.shapes.size(); ++i) {
        float d = shape_distance(wp, scene.shapes[i]);
        if (d < best) { best = d; result = {ObjectId::Shape, i}; }
    }
    for (int i = 0; i < (int)scene.lights.size(); ++i) {
        float d = light_distance(wp, scene.lights[i]);
        if (d < best) { best = d; result = {ObjectId::Light, i}; }
    }
    // Test group members (in world space) — return group, not individual member
    for (int g = 0; g < (int)scene.groups.size(); ++g) {
        const auto& group = scene.groups[g];
        for (const auto& shape : group.shapes) {
            Shape ws = transform_shape(shape, group.transform);
            float d = shape_distance(wp, ws);
            if (d < best) { best = d; result = {ObjectId::Group, g}; }
        }
        for (const auto& light : group.lights) {
            Light wl = transform_light(light, group.transform);
            float d = light_distance(wp, wl);
            if (d < best) { best = d; result = {ObjectId::Group, g}; }
        }
    }
    return result;
}

int hit_test_groups(Vec2 wp, const Scene& scene, float threshold) {
    float best = threshold;
    int result = -1;
    for (int g = 0; g < (int)scene.groups.size(); ++g) {
        const auto& group = scene.groups[g];
        for (const auto& shape : group.shapes) {
            Shape ws = transform_shape(shape, group.transform);
            float d = shape_distance(wp, ws);
            if (d < best) { best = d; result = g; }
        }
        for (const auto& light : group.lights) {
            Light wl = transform_light(light, group.transform);
            float d = light_distance(wp, wl);
            if (d < best) { best = d; result = g; }
        }
    }
    return result;
}

bool object_in_rect(const Scene& scene, ObjectId id, Vec2 rect_min, Vec2 rect_max) {
    auto in_rect = [&](Vec2 p) {
        return p.x >= rect_min.x && p.x <= rect_max.x && p.y >= rect_min.y && p.y <= rect_max.y;
    };
    if (id.type == ObjectId::Shape && id.index < (int)scene.shapes.size()) {
        return std::visit(overloaded{
            [&](const Circle& c) -> bool { return in_rect(c.center); },
            [&](const Segment& s) -> bool { return in_rect(s.a) || in_rect(s.b); },
            [&](const Arc& a) -> bool { return in_rect(a.center); },
            [&](const Bezier& b) -> bool { return in_rect(b.p0) || in_rect(b.p1) || in_rect(b.p2); },
        }, scene.shapes[id.index]);
    }
    if (id.type == ObjectId::Light && id.index < (int)scene.lights.size()) {
        return std::visit(overloaded{
            [&](const PointLight& l) -> bool { return in_rect(l.pos); },
            [&](const SegmentLight& l) -> bool { return in_rect(l.a) || in_rect(l.b); },
            [&](const BeamLight& l) -> bool { return in_rect(l.origin); },
        }, scene.lights[id.index]);
    }
    if (id.type == ObjectId::Group && id.index < (int)scene.groups.size()) {
        const auto& group = scene.groups[id.index];
        for (const auto& shape : group.shapes) {
            Shape ws = transform_shape(shape, group.transform);
            bool hit = std::visit(overloaded{
                [&](const Circle& c) -> bool { return in_rect(c.center); },
                [&](const Segment& s) -> bool { return in_rect(s.a) || in_rect(s.b); },
                [&](const Arc& a) -> bool { return in_rect(a.center); },
                [&](const Bezier& b) -> bool { return in_rect(b.p0) || in_rect(b.p1) || in_rect(b.p2); },
            }, ws);
            if (hit) return true;
        }
        for (const auto& light : group.lights) {
            Light wl = transform_light(light, group.transform);
            bool hit = std::visit(overloaded{
                [&](const PointLight& l) -> bool { return in_rect(l.pos); },
                [&](const SegmentLight& l) -> bool { return in_rect(l.a) || in_rect(l.b); },
                [&](const BeamLight& l) -> bool { return in_rect(l.origin); },
            }, wl);
            if (hit) return true;
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
    }, s);
}

void translate_light(Light& l, Vec2 delta) {
    std::visit(overloaded{
        [&](PointLight& pl) { pl.pos = pl.pos + delta; },
        [&](SegmentLight& sl) { sl.a = sl.a + delta; sl.b = sl.b + delta; },
        [&](BeamLight& bl) { bl.origin = bl.origin + delta; },
    }, l);
}

static void rotate_shape(Shape& s, Vec2 pivot, float angle) {
    std::visit(overloaded{
        [&](Circle& c) { c.center = rotate_around(c.center, pivot, angle); },
        [&](Segment& seg) { seg.a = rotate_around(seg.a, pivot, angle); seg.b = rotate_around(seg.b, pivot, angle); },
        [&](Arc& a) {
            a.center = rotate_around(a.center, pivot, angle);
            a.angle_start = std::fmod(std::fmod(a.angle_start + angle, TWO_PI) + TWO_PI, TWO_PI);
            a.angle_end = std::fmod(std::fmod(a.angle_end + angle, TWO_PI) + TWO_PI, TWO_PI);
        },
        [&](Bezier& b) {
            b.p0 = rotate_around(b.p0, pivot, angle);
            b.p1 = rotate_around(b.p1, pivot, angle);
            b.p2 = rotate_around(b.p2, pivot, angle);
        },
    }, s);
}

static void rotate_light(Light& l, Vec2 pivot, float angle) {
    std::visit(overloaded{
        [&](PointLight& pl) { pl.pos = rotate_around(pl.pos, pivot, angle); },
        [&](SegmentLight& sl) { sl.a = rotate_around(sl.a, pivot, angle); sl.b = rotate_around(sl.b, pivot, angle); },
        [&](BeamLight& bl) {
            bl.origin = rotate_around(bl.origin, pivot, angle);
            float c = std::cos(angle), s = std::sin(angle);
            Vec2 d = bl.direction;
            bl.direction = Vec2{d.x * c - d.y * s, d.x * s + d.y * c}.normalized();
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
    }, s);
}

static void scale_light(Light& l, Vec2 pivot, float fx, float fy) {
    std::visit(overloaded{
        [&](PointLight& pl) { pl.pos = scale_around(pl.pos, pivot, fx, fy); },
        [&](SegmentLight& sl) { sl.a = scale_around(sl.a, pivot, fx, fy); sl.b = scale_around(sl.b, pivot, fx, fy); },
        [&](BeamLight& bl) {
            bl.origin = scale_around(bl.origin, pivot, fx, fy);
            bl.angular_width = std::clamp(bl.angular_width * std::sqrt(fx * fy), 0.01f, PI);
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

std::vector<Handle> get_handles(const Scene& scene, const std::vector<ObjectId>& selection) {
    std::vector<Handle> handles;

    for (auto& id : selection) {
        if (id.type == ObjectId::Shape && id.index < (int)scene.shapes.size()) {
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
                    float mid_angle = a.angle_start + (a.angle_end - a.angle_start) * 0.5f;
                    if (a.angle_end < a.angle_start) mid_angle += PI;
                    handles.push_back({Handle::Radius, id, 0, a.center + Vec2{a.radius * std::cos(mid_angle), a.radius * std::sin(mid_angle)}});
                    handles.push_back({Handle::Angle, id, 0, a.center + Vec2{a.radius * std::cos(a.angle_start), a.radius * std::sin(a.angle_start)}});
                    handles.push_back({Handle::Angle, id, 1, a.center + Vec2{a.radius * std::cos(a.angle_end), a.radius * std::sin(a.angle_end)}});
                },
                [&](const Bezier& b) {
                    handles.push_back({Handle::Position, id, 0, b.p0});
                    handles.push_back({Handle::Position, id, 1, b.p1}); // control point
                    handles.push_back({Handle::Position, id, 2, b.p2});
                },
            }, scene.shapes[id.index]);
        }
        if (id.type == ObjectId::Light && id.index < (int)scene.lights.size()) {
            std::visit(overloaded{
                [&](const PointLight& l) {
                    handles.push_back({Handle::Position, id, 0, l.pos});
                },
                [&](const SegmentLight& l) {
                    handles.push_back({Handle::Position, id, 0, l.a});
                    handles.push_back({Handle::Position, id, 1, l.b});
                },
                [&](const BeamLight& l) {
                    handles.push_back({Handle::Position, id, 0, l.origin});
                    handles.push_back({Handle::Direction, id, 0, l.origin + l.direction.normalized() * 0.3f});
                },
            }, scene.lights[id.index]);
        }
        if (id.type == ObjectId::Group && id.index < (int)scene.groups.size()) {
            const auto& group = scene.groups[id.index];
            handles.push_back({Handle::Position, id, 0, group.transform.translate});
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

    if (obj.type == ObjectId::Shape && obj.index < (int)scene.shapes.size()) {
        auto& shape = scene.shapes[obj.index];
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
                    float angle = std::atan2(wp.y - a.center.y, wp.x - a.center.x);
                    if (angle < 0) angle += TWO_PI;
                    if (handle.param_index == 0) a.angle_start = angle;
                    else a.angle_end = angle;
                }
            },
            [&](Bezier& b) {
                if (handle.param_index == 0) b.p0 = wp;
                else if (handle.param_index == 1) b.p1 = wp;
                else b.p2 = wp;
            },
        }, shape);
    }

    if (obj.type == ObjectId::Light && obj.index < (int)scene.lights.size()) {
        auto& light = scene.lights[obj.index];
        std::visit(overloaded{
            [&](PointLight& l) {
                l.pos = wp;
            },
            [&](SegmentLight& l) {
                if (handle.param_index == 0) l.a = wp;
                else l.b = wp;
            },
            [&](BeamLight& l) {
                if (handle.kind == Handle::Position) {
                    l.origin = wp;
                } else if (handle.kind == Handle::Direction) {
                    Vec2 d = wp - l.origin;
                    if (d.length_sq() > 1e-6f) l.direction = d.normalized();
                }
            },
        }, light);
    }

    if (obj.type == ObjectId::Group && obj.index < (int)scene.groups.size()) {
        auto& group = scene.groups[obj.index];
        if (handle.kind == Handle::Position) {
            group.transform.translate = wp;
        }
    }
}
