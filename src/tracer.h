#pragma once

#include "scene.h"

#include <random>
#include <vector>

class Tracer {
public:
    struct Config {
        int batch_size = 30000;
        int max_depth = 12;
        float intensity = 1.0f;
    };

    std::vector<LineSegment> trace_batch(const Scene& scene, const Config& cfg);
    int total_rays() const { return total_; }

private:
    std::mt19937 rng_{std::random_device{}()};
    std::uniform_real_distribution<float> unit_dist_{0.0f, 1.0f};
    std::uniform_real_distribution<float> wavelength_dist_{380.0f, 780.0f};
    std::discrete_distribution<int> light_dist_;
    const Scene* prepared_scene_ = nullptr;
    int total_ = 0;

    void prepare(const Scene& scene);
    Ray generate_ray(const Light& light);
    Ray scatter(const Ray& ray, const Hit& hit, float wavelength, bool& alive);
};
