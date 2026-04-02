#include "scene.h"

#include <algorithm>
#include <limits>

std::optional<Hit> intersect(const Ray& ray, const Circle& circle) {
    Vec2 oc = ray.origin - circle.center;
    float a = ray.dir.dot(ray.dir);
    float b = 2.0f * oc.dot(ray.dir);
    float c = oc.dot(oc) - circle.radius * circle.radius;
    float disc = b * b - 4.0f * a * c;

    if (disc < 0)
        return std::nullopt;

    float sqrt_disc = std::sqrt(disc);
    float t1 = (-b - sqrt_disc) / (2.0f * a);
    float t2 = (-b + sqrt_disc) / (2.0f * a);

    float t = (t1 > INTERSECT_EPS) ? t1 : ((t2 > INTERSECT_EPS) ? t2 : -1.0f);
    if (t < 0)
        return std::nullopt;

    Vec2 point = ray.origin + ray.dir * t;
    Vec2 normal = (point - circle.center).normalized();

    return Hit{t, point, normal, &circle.material};
}

std::optional<Hit> intersect(const Ray& ray, const Segment& seg) {
    Vec2 d = seg.b - seg.a;
    Vec2 e = ray.dir;
    Vec2 f = ray.origin - seg.a;

    float denom = e.x * d.y - e.y * d.x;
    if (std::abs(denom) < INTERSECT_EPS)
        return std::nullopt;

    float t = (d.x * f.y - d.y * f.x) / denom;
    float s = (e.x * f.y - e.y * f.x) / denom;

    if (t < INTERSECT_EPS || s < 0.0f || s > 1.0f)
        return std::nullopt;

    Vec2 point = ray.origin + ray.dir * t;
    Vec2 normal = d.perp().normalized();

    return Hit{t, point, normal, &seg.material};
}

std::optional<Hit> intersect_scene(const Ray& ray, const Scene& scene) {
    std::optional<Hit> closest;

    for (const auto& shape : scene.shapes) {
        auto hit = std::visit(overloaded{
                                  [&](const Circle& c) { return intersect(ray, c); },
                                  [&](const Segment& s) { return intersect(ray, s); },
                              },
                              shape);

        if (hit && (!closest || hit->t < closest->t)) {
            closest = hit;
        }
    }

    return closest;
}

Bounds compute_bounds(const Scene& scene, float padding) {
    float inf = std::numeric_limits<float>::max();
    Vec2 lo{inf, inf}, hi{-inf, -inf};

    auto expand = [&](Vec2 p) {
        lo.x = std::min(lo.x, p.x);
        lo.y = std::min(lo.y, p.y);
        hi.x = std::max(hi.x, p.x);
        hi.y = std::max(hi.y, p.y);
    };

    for (const auto& shape : scene.shapes) {
        std::visit(overloaded{
                       [&](const Circle& c) {
                           expand(c.center - Vec2{c.radius, c.radius});
                           expand(c.center + Vec2{c.radius, c.radius});
                       },
                       [&](const Segment& s) {
                           expand(s.a);
                           expand(s.b);
                       },
                   },
                   shape);
    }

    for (const auto& light : scene.lights) {
        std::visit(overloaded{
                       [&](const PointLight& l) { expand(l.pos); },
                       [&](const SegmentLight& l) {
                           expand(l.a);
                           expand(l.b);
                       },
                   },
                   light);
    }

    Vec2 size = hi - lo;
    float pad = std::max(size.x, size.y) * padding;
    return {lo - Vec2{pad, pad}, hi + Vec2{pad, pad}};
}

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
    scene.shapes.push_back(Segment{{-half_w, -half_h}, {half_w, -half_h}, mat});  // bottom → normal up
    scene.shapes.push_back(Segment{{half_w, half_h}, {-half_w, half_h}, mat});    // top → normal down
    scene.shapes.push_back(Segment{{-half_w, half_h}, {-half_w, -half_h}, mat});  // left → normal right
    scene.shapes.push_back(Segment{{half_w, -half_h}, {half_w, half_h}, mat});    // right → normal left
}
