#include "scene.h"

#include <algorithm>
#include <cmath>
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

static bool angle_in_arc(float angle, float start, float end) {
    while (angle < 0.0f) angle += TWO_PI;
    while (angle >= TWO_PI) angle -= TWO_PI;
    if (start <= end)
        return angle >= start && angle <= end;
    else
        return angle >= start || angle <= end;
}

std::optional<Hit> intersect(const Ray& ray, const Arc& arc) {
    Vec2 oc = ray.origin - arc.center;
    float a = ray.dir.dot(ray.dir);
    float b = 2.0f * oc.dot(ray.dir);
    float c = oc.dot(oc) - arc.radius * arc.radius;
    float disc = b * b - 4.0f * a * c;

    if (disc < 0)
        return std::nullopt;

    float sqrt_disc = std::sqrt(disc);
    float t1 = (-b - sqrt_disc) / (2.0f * a);
    float t2 = (-b + sqrt_disc) / (2.0f * a);

    // Try both roots, take closest valid one within arc angle range
    float roots[] = {t1, t2};
    for (float t : roots) {
        if (t < INTERSECT_EPS) continue;
        Vec2 point = ray.origin + ray.dir * t;
        float angle = std::atan2(point.y - arc.center.y, point.x - arc.center.x);
        if (angle_in_arc(angle, arc.angle_start, arc.angle_end)) {
            Vec2 normal = (point - arc.center).normalized();
            return Hit{t, point, normal, &arc.material};
        }
    }
    return std::nullopt;
}

std::optional<Hit> intersect(const Ray& ray, const Bezier& bez) {
    // Quadratic Bezier: B(t) = (1-t)²p0 + 2t(1-t)p1 + t²p2 = At² + Bt + C
    Vec2 A = bez.p0 - bez.p1 * 2.0f + bez.p2;
    Vec2 B_coeff = (bez.p1 - bez.p0) * 2.0f;
    Vec2 C = bez.p0;

    // Cross-multiply to eliminate ray parameter s:
    // (rd.y*A.x - rd.x*A.y)t² + (rd.y*B.x - rd.x*B.y)t + (rd.y*(C.x-ro.x) - rd.x*(C.y-ro.y)) = 0
    Vec2 ro = ray.origin;
    Vec2 rd = ray.dir;
    float a_coeff = rd.y * A.x - rd.x * A.y;
    float b_coeff = rd.y * B_coeff.x - rd.x * B_coeff.y;
    float c_coeff = rd.y * (C.x - ro.x) - rd.x * (C.y - ro.y);

    float roots[2];
    int n_roots = 0;

    if (std::abs(a_coeff) < INTERSECT_EPS) {
        // Degenerate: linear
        if (std::abs(b_coeff) >= INTERSECT_EPS) {
            roots[0] = -c_coeff / b_coeff;
            n_roots = 1;
        }
    } else {
        float disc = b_coeff * b_coeff - 4.0f * a_coeff * c_coeff;
        if (disc >= 0.0f) {
            float sq = std::sqrt(disc);
            roots[0] = (-b_coeff - sq) / (2.0f * a_coeff);
            roots[1] = (-b_coeff + sq) / (2.0f * a_coeff);
            n_roots = 2;
        }
    }

    std::optional<Hit> best;
    for (int i = 0; i < n_roots; ++i) {
        float t = roots[i];
        if (t < 0.0f || t > 1.0f) continue;
        Vec2 point = A * (t * t) + B_coeff * t + C;
        float s = (point - ro).dot(rd) / rd.dot(rd); // ray parameter
        if (s < INTERSECT_EPS) continue;
        if (best && s >= best->t) continue;

        Vec2 tangent = A * (2.0f * t) + B_coeff;
        Vec2 normal = tangent.perp().normalized();
        if (normal.dot(rd) > 0.0f) normal = -normal;

        best = Hit{s, point, normal, &bez.material};
    }
    return best;
}

std::optional<Hit> intersect_scene(const Ray& ray, const Scene& scene) {
    std::optional<Hit> closest;

    for (const auto& shape : scene.shapes) {
        auto hit = std::visit(overloaded{
                                  [&](const Circle& c) { return intersect(ray, c); },
                                  [&](const Segment& s) { return intersect(ray, s); },
                                  [&](const Arc& a) { return intersect(ray, a); },
                                  [&](const Bezier& b) { return intersect(ray, b); },
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
                       [&](const Arc& a) {
                           // Include arc endpoints
                           expand(a.center + Vec2{a.radius * std::cos(a.angle_start),
                                                  a.radius * std::sin(a.angle_start)});
                           expand(a.center + Vec2{a.radius * std::cos(a.angle_end),
                                                  a.radius * std::sin(a.angle_end)});
                           // Include extrema at cardinal directions if within arc range
                           constexpr float cardinals[] = {0.0f, 1.5707963f, 3.1415927f, 4.7123890f};
                           constexpr float dx[] = {1.0f, 0.0f, -1.0f, 0.0f};
                           constexpr float dy[] = {0.0f, 1.0f, 0.0f, -1.0f};
                           for (int i = 0; i < 4; ++i) {
                               if (angle_in_arc(cardinals[i], a.angle_start, a.angle_end))
                                   expand(a.center + Vec2{a.radius * dx[i], a.radius * dy[i]});
                           }
                       },
                       [&](const Bezier& b) {
                           // Convex hull of control points contains the curve
                           expand(b.p0);
                           expand(b.p1);
                           expand(b.p2);
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
                       [&](const BeamLight& l) {
                           expand(l.origin);
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
