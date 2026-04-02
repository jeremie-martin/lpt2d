#include "tracer.h"

#include "spectrum.h"

#include <cmath>
#include <numbers>

static constexpr float PI = std::numbers::pi_v<float>;

Ray Tracer::generate_ray(const Light& light) {
    std::uniform_real_distribution<float> angle_dist(0.0f, 2.0f * PI);
    std::uniform_real_distribution<float> unit(0.0f, 1.0f);

    return std::visit(
        overloaded{
            [&](const PointLight& l) -> Ray {
                float a = angle_dist(rng_);
                return {l.pos, Vec2{std::cos(a), std::sin(a)}};
            },
            [&](const SegmentLight& l) -> Ray {
                float t = unit(rng_);
                Vec2 pos = l.a + (l.b - l.a) * t;
                Vec2 dir = (l.b - l.a).perp().normalized();
                float a = (unit(rng_) - 0.5f) * PI;
                float cos_a = std::cos(a), sin_a = std::sin(a);
                Vec2 tangent = (l.b - l.a).normalized();
                return {pos, Vec2{dir.x * cos_a + tangent.x * sin_a, dir.y * cos_a + tangent.y * sin_a}};
            },
        },
        light);
}

Ray Tracer::scatter(const Ray& ray, const Hit& hit, float wavelength, bool& alive) {
    return std::visit(
        overloaded{
            [&](const Diffuse&) -> Ray {
                alive = false;
                return {};
            },
            [&](const Specular&) -> Ray {
                alive = true;
                Vec2 n = hit.normal;
                if (ray.dir.dot(n) > 0)
                    n = -n;
                return {hit.point + n * SCATTER_EPS, ray.dir.reflect(n)};
            },
            [&](const Refractive& mat) -> Ray {
                alive = true;
                Vec2 n = hit.normal;
                float cos_i = ray.dir.dot(n);

                float lambda_um = wavelength / 1000.0f;
                float ior = mat.ior + mat.cauchy_b / (lambda_um * lambda_um * 1e6f);

                float n1, n2;
                if (cos_i > 0) {
                    n1 = ior;
                    n2 = 1.0f;
                    n = -n;
                    cos_i = -cos_i;
                } else {
                    n1 = 1.0f;
                    n2 = ior;
                    cos_i = -cos_i;
                }

                float ratio = n1 / n2;
                float cos_t_sq = 1.0f - ratio * ratio * (1.0f - cos_i * cos_i);

                if (cos_t_sq < 0.0f) {
                    return {hit.point + n * SCATTER_EPS, ray.dir.reflect(n)};
                }

                float cos_t = std::sqrt(cos_t_sq);

                float rs = (n1 * cos_i - n2 * cos_t) / (n1 * cos_i + n2 * cos_t);
                float rp = (n2 * cos_i - n1 * cos_t) / (n1 * cos_t + n2 * cos_i);
                float R = 0.5f * (rs * rs + rp * rp);

                if (unit_dist_(rng_) < R) {
                    return {hit.point + n * SCATTER_EPS, ray.dir.reflect(n)};
                } else {
                    Vec2 refracted = ray.dir * ratio + n * (ratio * cos_i - cos_t);
                    return {hit.point - n * SCATTER_EPS, refracted};
                }
            },
        },
        *hit.material);
}

void Tracer::prepare(const Scene& scene) {
    std::vector<float> weights;
    weights.reserve(scene.lights.size());
    for (const auto& light : scene.lights)
        weights.push_back(std::visit([](const auto& l) { return l.intensity; }, light));
    light_dist_ = std::discrete_distribution<int>(weights.begin(), weights.end());
    prepared_scene_ = &scene;
}

std::vector<LineSegment> Tracer::trace_batch(const Scene& scene, const Config& cfg) {
    if (prepared_scene_ != &scene)
        prepare(scene);

    std::vector<LineSegment> segments;
    segments.reserve(cfg.batch_size * 2);

    for (int i = 0; i < cfg.batch_size; ++i) {
        const auto& light = scene.lights[light_dist_(rng_)];
        Ray ray = generate_ray(light);
        float wavelength = wavelength_dist_(rng_);
        Vec3 color = wavelength_to_rgb(wavelength);

        for (int depth = 0; depth < cfg.max_depth; ++depth) {
            auto hit = intersect_scene(ray, scene);

            if (!hit) {
                Vec2 far = ray.origin + ray.dir * 10.0f;
                segments.push_back({ray.origin, far, color, cfg.intensity});
                break;
            }

            segments.push_back({ray.origin, hit->point, color, cfg.intensity});

            bool alive = false;
            ray = scatter(ray, *hit, wavelength, alive);
            if (!alive)
                break;
        }
    }

    total_ += cfg.batch_size;
    return segments;
}
