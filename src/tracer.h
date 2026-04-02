#pragma once

#include "scene.h"

#include <random>
#include <vector>

struct LineSegment {
    float x0, y0, x1, y1;
    float r, g, b;
    float intensity;
};

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
    int total_ = 0;

    Ray generate_ray(const Light& light);
    float random_wavelength();
    Ray scatter(const Ray& ray, const Hit& hit, float wavelength, bool& alive);
};
