#include "scene.h"

#include <algorithm>
#include <cmath>
#include <limits>

float normalize_angle(float angle) {
    angle = std::fmod(angle, TWO_PI);
    if (angle < 0.0f) angle += TWO_PI;
    return angle;
}

float clamp_arc_sweep(float sweep) {
    return std::clamp(sweep, 0.0f, TWO_PI);
}

float arc_end_angle(const Arc& arc) {
    return normalize_angle(arc.angle_start + clamp_arc_sweep(arc.sweep));
}

float arc_mid_angle(const Arc& arc) {
    return normalize_angle(arc.angle_start + 0.5f * clamp_arc_sweep(arc.sweep));
}

Vec2 arc_point(const Arc& arc, float angle) {
    return arc.center + Vec2{arc.radius * std::cos(angle), arc.radius * std::sin(angle)};
}

Vec2 arc_start_point(const Arc& arc) {
    return arc_point(arc, arc.angle_start);
}

Vec2 arc_end_point(const Arc& arc) {
    return arc_point(arc, arc_end_angle(arc));
}

Vec2 arc_mid_point(const Arc& arc) {
    return arc_point(arc, arc_mid_angle(arc));
}

bool angle_in_arc(float angle, const Arc& arc) {
    float sweep = clamp_arc_sweep(arc.sweep);
    if (sweep >= TWO_PI - INTERSECT_EPS)
        return true;
    float delta = normalize_angle(angle - arc.angle_start);
    return delta <= sweep + INTERSECT_EPS;
}

Bounds arc_bounds(const Arc& arc) {
    if (clamp_arc_sweep(arc.sweep) >= TWO_PI - INTERSECT_EPS) {
        return {arc.center - Vec2{arc.radius, arc.radius},
                arc.center + Vec2{arc.radius, arc.radius}};
    }

    float inf = std::numeric_limits<float>::max();
    Vec2 lo{inf, inf}, hi{-inf, -inf};
    auto expand = [&](Vec2 p) {
        lo.x = std::min(lo.x, p.x);
        lo.y = std::min(lo.y, p.y);
        hi.x = std::max(hi.x, p.x);
        hi.y = std::max(hi.y, p.y);
    };

    expand(arc_start_point(arc));
    expand(arc_end_point(arc));

    constexpr float cardinals[] = {0.0f, 0.5f * PI, PI, 1.5f * PI};
    for (float angle : cardinals) {
        if (angle_in_arc(angle, arc))
            expand(arc_point(arc, angle));
    }

    return {lo, hi};
}

float point_arc_distance(Vec2 p, const Arc& arc) {
    Vec2 d = p - arc.center;
    float dc = d.length();
    if (dc < 1e-10f)
        return arc.radius;

    float angle = std::atan2(d.y, d.x);
    if (angle_in_arc(angle, arc))
        return std::abs(dc - arc.radius);

    return std::min((p - arc_start_point(arc)).length(),
                    (p - arc_end_point(arc)).length());
}

Bounds shape_bounds(const Shape& s) {
    return std::visit(overloaded{
                          [](const Circle& c) {
                              return Bounds{c.center - Vec2{c.radius, c.radius},
                                            c.center + Vec2{c.radius, c.radius}};
                          },
                          [](const Segment& seg) {
                              return Bounds{
                                  {std::min(seg.a.x, seg.b.x), std::min(seg.a.y, seg.b.y)},
                                  {std::max(seg.a.x, seg.b.x), std::max(seg.a.y, seg.b.y)},
                              };
                          },
                          [](const Arc& arc) { return arc_bounds(arc); },
                          [](const Bezier& bez) {
                              Vec2 lo{
                                  std::min({bez.p0.x, bez.p1.x, bez.p2.x}),
                                  std::min({bez.p0.y, bez.p1.y, bez.p2.y}),
                              };
                              Vec2 hi{
                                  std::max({bez.p0.x, bez.p1.x, bez.p2.x}),
                                  std::max({bez.p0.y, bez.p1.y, bez.p2.y}),
                              };
                              return Bounds{lo, hi};
                          },
                          [](const Polygon& p) {
                              if (p.vertices.empty()) return Bounds{{0, 0}, {0, 0}};
                              float inf = std::numeric_limits<float>::max();
                              Vec2 lo{inf, inf}, hi{-inf, -inf};
                              for (auto& v : p.vertices) {
                                  lo.x = std::min(lo.x, v.x); lo.y = std::min(lo.y, v.y);
                                  hi.x = std::max(hi.x, v.x); hi.y = std::max(hi.y, v.y);
                              }
                              return Bounds{lo, hi};
                          },
                          [](const Ellipse& e) {
                              float cr = std::cos(e.rotation), sr = std::sin(e.rotation);
                              float hx = std::sqrt(e.semi_a * e.semi_a * cr * cr + e.semi_b * e.semi_b * sr * sr);
                              float hy = std::sqrt(e.semi_a * e.semi_a * sr * sr + e.semi_b * e.semi_b * cr * cr);
                              return Bounds{e.center - Vec2{hx, hy}, e.center + Vec2{hx, hy}};
                          },
                      },
                      s);
}

Bounds light_bounds(const Light& l) {
    return std::visit(overloaded{
                          [](const PointLight& light) {
                              return Bounds{light.pos, light.pos};
                          },
                          [](const SegmentLight& light) {
                              return Bounds{
                                  {std::min(light.a.x, light.b.x), std::min(light.a.y, light.b.y)},
                                  {std::max(light.a.x, light.b.x), std::max(light.a.y, light.b.y)},
                              };
                          },
                          [](const BeamLight& light) {
                              return Bounds{light.origin, light.origin};
                          },
                          [](const ParallelBeamLight& light) {
                              return Bounds{
                                  {std::min(light.a.x, light.b.x), std::min(light.a.y, light.b.y)},
                                  {std::max(light.a.x, light.b.x), std::max(light.a.y, light.b.y)},
                              };
                          },
                          [](const SpotLight& light) {
                              return Bounds{light.pos, light.pos};
                          },
                      },
                      l);
}

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
        if (angle_in_arc(angle, arc)) {
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

std::optional<Hit> intersect(const Ray& ray, const Polygon& poly) {
    std::optional<Hit> best;
    int n = (int)poly.vertices.size();
    bool clockwise = polygon_is_clockwise(poly);
    for (int i = 0; i < n; ++i) {
        Vec2 a = poly.vertices[i];
        Vec2 b = poly.vertices[(i + 1) % n];
        Segment edge{clockwise ? a : b, clockwise ? b : a, poly.material};
        auto hit = intersect(ray, edge);
        if (hit && (!best || hit->t < best->t)) {
            best = hit;
            best->material = &poly.material; // re-point to polygon (edge Segment is stack-local)
        }
    }
    return best;
}

std::optional<Hit> intersect(const Ray& ray, const Ellipse& ellipse) {
    // cos/sin computed once; inverse rotation uses (cr, -sr)
    float cr = std::cos(ellipse.rotation), sr = std::sin(ellipse.rotation);
    Vec2 oc = ray.origin - ellipse.center;
    Vec2 lo{oc.x * cr + oc.y * sr, -oc.x * sr + oc.y * cr};
    Vec2 ld{ray.dir.x * cr + ray.dir.y * sr, -ray.dir.x * sr + ray.dir.y * cr};

    float a2 = ellipse.semi_a * ellipse.semi_a;
    float b2 = ellipse.semi_b * ellipse.semi_b;

    float A = ld.x * ld.x / a2 + ld.y * ld.y / b2;
    float B = 2.0f * (lo.x * ld.x / a2 + lo.y * ld.y / b2);
    float C = lo.x * lo.x / a2 + lo.y * lo.y / b2 - 1.0f;
    float disc = B * B - 4.0f * A * C;

    if (disc < 0)
        return std::nullopt;

    float sqrt_disc = std::sqrt(disc);
    float t1 = (-B - sqrt_disc) / (2.0f * A);
    float t2 = (-B + sqrt_disc) / (2.0f * A);

    float t = (t1 > INTERSECT_EPS) ? t1 : ((t2 > INTERSECT_EPS) ? t2 : -1.0f);
    if (t < 0)
        return std::nullopt;

    // Hit point in local coords
    Vec2 lp = lo + ld * t;

    // Normal: gradient of ellipse equation in local coords
    Vec2 ln{2.0f * lp.x / a2, 2.0f * lp.y / b2};
    float len = ln.length();
    if (len > 0) ln = ln / len;

    // Rotate normal back to world coords (forward rotation: cr, sr)
    Vec2 normal{ln.x * cr - ln.y * sr, ln.x * sr + ln.y * cr};

    Vec2 point = ray.origin + ray.dir * t;
    return Hit{t, point, normal, &ellipse.material};
}

std::optional<Hit> intersect_scene(const Ray& ray, const Scene& scene) {
    std::optional<Hit> closest;

    for (const auto& shape : scene.shapes) {
        auto hit = std::visit(overloaded{
                                  [&](const Circle& c) { return intersect(ray, c); },
                                  [&](const Segment& s) { return intersect(ray, s); },
                                  [&](const Arc& a) { return intersect(ray, a); },
                                  [&](const Bezier& b) { return intersect(ray, b); },
                                  [&](const Polygon& p) { return intersect(ray, p); },
                                  [&](const Ellipse& e) { return intersect(ray, e); },
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
        Bounds b = shape_bounds(shape);
        expand(b.min);
        expand(b.max);
    }

    for (const auto& light : scene.lights) {
        Bounds b = light_bounds(light);
        expand(b.min);
        expand(b.max);
    }

    // Groups: expand with world-space transformed shapes/lights
    for (const auto& group : scene.groups) {
        for (const auto& shape : group.shapes) {
            Shape ws = transform_shape(shape, group.transform);
            Bounds b = shape_bounds(ws);
            expand(b.min);
            expand(b.max);
        }
        for (const auto& light : group.lights) {
            Light wl = transform_light(light, group.transform);
            Bounds b = light_bounds(wl);
            expand(b.min);
            expand(b.max);
        }
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

// ─── Transform helpers ─────────────────────────────────────────────

Shape transform_shape(const Shape& s, const Transform2D& t) {
    if (t.is_identity()) return s;
    float uniform_scale = std::sqrt(std::abs(t.scale.x * t.scale.y));
    return std::visit(overloaded{
        [&](const Circle& c) -> Shape {
            Circle r = c;
            r.center = t.apply(c.center);
            r.radius = std::max(c.radius * uniform_scale, 0.01f);
            return r;
        },
        [&](const Segment& seg) -> Shape {
            Segment r = seg;
            r.a = t.apply(seg.a);
            r.b = t.apply(seg.b);
            return r;
        },
        [&](const Arc& a) -> Shape {
            Arc r = a;
            r.center = t.apply(a.center);
            r.radius = std::max(a.radius * uniform_scale, 0.01f);
            r.angle_start = normalize_angle(a.angle_start + t.rotate);
            r.sweep = clamp_arc_sweep(a.sweep);
            return r;
        },
        [&](const Bezier& b) -> Shape {
            Bezier r = b;
            r.p0 = t.apply(b.p0);
            r.p1 = t.apply(b.p1);
            r.p2 = t.apply(b.p2);
            return r;
        },
        [&](const Polygon& p) -> Shape {
            Polygon r = p;
            for (auto& v : r.vertices) v = t.apply(v);
            return r;
        },
        [&](const Ellipse& e) -> Shape {
            Ellipse r = e;
            r.center = t.apply(e.center);
            r.rotation = e.rotation + t.rotate;
            r.semi_a = std::max(e.semi_a * uniform_scale, 0.01f);
            r.semi_b = std::max(e.semi_b * uniform_scale, 0.01f);
            return r;
        },
    }, s);
}

Light transform_light(const Light& l, const Transform2D& t) {
    if (t.is_identity()) return l;
    return std::visit(overloaded{
        [&](const PointLight& pl) -> Light {
            PointLight r = pl;
            r.pos = t.apply(pl.pos);
            return r;
        },
        [&](const SegmentLight& sl) -> Light {
            SegmentLight r = sl;
            r.a = t.apply(sl.a);
            r.b = t.apply(sl.b);
            return r;
        },
        [&](const BeamLight& bl) -> Light {
            BeamLight r = bl;
            r.origin = t.apply(bl.origin);
            Vec2 d = t.apply_direction(bl.direction);
            r.direction = d.length_sq() > 1e-6f ? d.normalized() : Vec2{1, 0};
            r.angular_width = std::clamp(bl.angular_width * std::sqrt(std::abs(t.scale.x * t.scale.y)), 0.01f, PI);
            return r;
        },
        [&](const ParallelBeamLight& pl) -> Light {
            ParallelBeamLight r = pl;
            r.a = t.apply(pl.a);
            r.b = t.apply(pl.b);
            Vec2 d = t.apply_direction(pl.direction);
            r.direction = d.length_sq() > 1e-6f ? d.normalized() : Vec2{1, 0};
            // angular_width is collimation quality — doesn't scale with spatial transforms
            return r;
        },
        [&](const SpotLight& sl) -> Light {
            SpotLight r = sl;
            r.pos = t.apply(sl.pos);
            Vec2 d = t.apply_direction(sl.direction);
            r.direction = d.length_sq() > 1e-6f ? d.normalized() : Vec2{1, 0};
            r.angular_width = std::clamp(sl.angular_width * std::sqrt(std::abs(t.scale.x * t.scale.y)), 0.01f, PI);
            return r;
        },
    }, l);
}

void add_box_walls(Scene& scene, float half_w, float half_h, const Material& mat) {
    // CW winding so perp() normals point inward
    scene.shapes.push_back(Segment{{-half_w, -half_h}, {half_w, -half_h}, mat});  // bottom → normal up
    scene.shapes.push_back(Segment{{half_w, half_h}, {-half_w, half_h}, mat});    // top → normal down
    scene.shapes.push_back(Segment{{-half_w, half_h}, {-half_w, -half_h}, mat});  // left → normal right
    scene.shapes.push_back(Segment{{half_w, -half_h}, {half_w, half_h}, mat});    // right → normal left
}

float shape_perimeter(const Shape& s) {
    return std::visit(overloaded{
        [](const Circle& c) { return TWO_PI * c.radius; },
        [](const Segment& seg) { return (seg.b - seg.a).length(); },
        [](const Arc& a) { return a.radius * clamp_arc_sweep(a.sweep); },
        [](const Bezier& b) {
            float len = 0;
            Vec2 prev = b.p0;
            for (int i = 1; i <= 32; ++i) {
                Vec2 cur = bezier_eval(b, (float)i / 32.0f);
                len += (cur - prev).length();
                prev = cur;
            }
            return len;
        },
        [](const Polygon& p) {
            float sum = 0;
            int n = (int)p.vertices.size();
            for (int i = 0; i < n; ++i)
                sum += (p.vertices[(i + 1) % n] - p.vertices[i]).length();
            return sum;
        },
        [](const Ellipse& e) {
            // Ramanujan approximation
            float a = e.semi_a, b = e.semi_b;
            float h = (a - b) * (a - b) / ((a + b) * (a + b));
            return PI * (a + b) * (1.0f + 3.0f * h / (10.0f + std::sqrt(4.0f - 3.0f * h)));
        },
    }, s);
}

static const Material& get_material(const Shape& s) {
    return std::visit([](const auto& shape) -> const Material& { return shape.material; }, s);
}

// Emission sampling constants
static constexpr float EMISSION_SAMPLE_SPACING = 0.02f;
static constexpr int EMISSION_MIN_POINTS = 4;
static constexpr int EMISSION_MAX_POINTS = 128;

static int emission_point_count(float perimeter) {
    int n = std::max(EMISSION_MIN_POINTS, (int)std::round(perimeter / EMISSION_SAMPLE_SPACING));
    return std::min(n, EMISSION_MAX_POINTS);
}

std::vector<Light> emission_light(const Shape& s) {
    const Material& mat = get_material(s);
    if (mat.emission <= 0.0f) return {};

    float perimeter = shape_perimeter(s);
    if (perimeter <= 0.0f) return {};

    std::vector<Light> lights;

    std::visit(overloaded{
        [&](const Circle& c) {
            int N = emission_point_count(perimeter);
            float per_point = mat.emission * perimeter / N;
            for (int i = 0; i < N; ++i) {
                float angle = TWO_PI * i / N;
                Vec2 pos = c.center + Vec2{c.radius * std::cos(angle), c.radius * std::sin(angle)};
                lights.push_back(PointLight{pos, per_point});
            }
        },
        [&](const Segment& seg) {
            // SegmentLight is an isotropic line source, so a glowing segment
            // emits from its full length without depending on endpoint order.
            float total = mat.emission * perimeter;
            lights.push_back(SegmentLight{seg.a, seg.b, total});
        },
        [&](const Arc& a) {
            // Approximate arc as a chain of short isotropic SegmentLights.
            float sweep = clamp_arc_sweep(a.sweep);
            int N = emission_point_count(perimeter);
            float seg_intensity = mat.emission * perimeter / std::max(1, N - 1);
            Vec2 prev = arc_point(a, a.angle_start);
            for (int i = 1; i < N; ++i) {
                float t = (float)i / (N - 1);
                float angle = a.angle_start + sweep * t;
                Vec2 cur = arc_point(a, angle);
                lights.push_back(SegmentLight{prev, cur, seg_intensity});
                prev = cur;
            }
        },
        [&](const Bezier& b) {
            // Approximate bezier as a chain of short isotropic SegmentLights.
            int N = emission_point_count(perimeter);
            float seg_intensity = mat.emission * perimeter / std::max(1, N - 1);
            Vec2 prev = bezier_eval(b, 0.0f);
            for (int i = 1; i < N; ++i) {
                float t = (float)i / (N - 1);
                Vec2 cur = bezier_eval(b, t);
                lights.push_back(SegmentLight{prev, cur, seg_intensity});
                prev = cur;
            }
        },
        [&](const Polygon& p) {
            // One isotropic SegmentLight per edge.
            int n = (int)p.vertices.size();
            if (n < 2) return;
            for (int i = 0; i < n; ++i) {
                Vec2 a = p.vertices[i], b = p.vertices[(i + 1) % n];
                float edge_len = (b - a).length();
                lights.push_back(SegmentLight{a, b, mat.emission * edge_len});
            }
        },
        [&](const Ellipse& e) {
            int N = emission_point_count(perimeter);
            float per_point = mat.emission * perimeter / N;
            float cr = std::cos(e.rotation), sr = std::sin(e.rotation);
            for (int i = 0; i < N; ++i) {
                float angle = TWO_PI * i / N;
                float lx = e.semi_a * std::cos(angle);
                float ly = e.semi_b * std::sin(angle);
                Vec2 pos = e.center + Vec2{lx * cr - ly * sr, lx * sr + ly * cr};
                lights.push_back(PointLight{pos, per_point});
            }
        },
    }, s);

    return lights;
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
