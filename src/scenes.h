#pragma once

#include "scene.h"

#include <cstdint>
#include <numbers>

inline Scene scene_three_spheres() {
    Scene s;
    s.name = "three_spheres";

    Material glass = mat_glass(1.5f, 20000.0f, 0.5f);
    s.shapes.push_back(Circle{{-0.5f, 0.0f}, 0.2f, glass});
    s.shapes.push_back(Circle{{0.0f, 0.0f}, 0.2f, glass});
    s.shapes.push_back(Circle{{0.5f, 0.0f}, 0.2f, glass});

    add_box_walls(s, 1.2f, 0.8f, mat_mirror(0.95f));

    s.lights.push_back(PointLight{{-0.8f, 0.5f}, 1.0f});
    s.lights.push_back(PointLight{{0.8f, -0.5f}, 1.0f});

    return s;
}

inline Scene scene_prism() {
    Scene s;
    s.name = "prism";

    float size = 0.4f;
    float h = size * std::sqrt(3.0f) / 2.0f;
    Vec2 p0{-0.1f, -h * 0.6f};
    Vec2 p1{-0.1f - size, h * 0.4f};
    Vec2 p2{-0.1f + size, h * 0.4f};
    Material glass = mat_glass(1.5f, 30000.0f, 0.3f);

    // CW winding → perp() gives outward normals
    s.shapes.push_back(Segment{p0, p1, glass});
    s.shapes.push_back(Segment{p1, p2, glass});
    s.shapes.push_back(Segment{p2, p0, glass});

    add_box_walls(s, 1.2f, 0.8f, mat_absorber());

    // Slit to collimate the beam
    float slit_x = -0.7f, slit_gap = 0.04f;
    s.shapes.push_back(Segment{{slit_x, -0.8f}, {slit_x, -slit_gap}, mat_absorber()});
    s.shapes.push_back(Segment{{slit_x, slit_gap}, {slit_x, 0.8f}, mat_absorber()});

    s.lights.push_back(PointLight{{-1.0f, 0.0f}, 1.0f});

    return s;
}

inline Scene scene_diamond() {
    Scene s;
    s.name = "diamond";

    s.shapes.push_back(Circle{{0.0f, 0.0f}, 0.35f, mat_glass(2.42f, 30000.0f, 0.2f)});

    add_box_walls(s, 1.0f, 0.7f, mat_mirror(0.95f));

    s.lights.push_back(PointLight{{-0.7f, 0.4f}, 1.0f});
    s.lights.push_back(PointLight{{0.7f, 0.4f}, 1.0f});
    s.lights.push_back(PointLight{{0.0f, -0.5f}, 0.5f});

    return s;
}

inline Scene scene_lens() {
    Scene s;
    s.name = "lens";

    Material glass = mat_glass(1.5f, 20000.0f, 0.3f);
    s.shapes.push_back(Circle{{-0.35f, 0.0f}, 0.4f, glass});
    s.shapes.push_back(Circle{{0.35f, 0.0f}, 0.4f, glass});

    add_box_walls(s, 1.2f, 0.8f, mat_diffuse(0.1f));

    s.lights.push_back(SegmentLight{{-1.0f, 0.3f}, {-1.0f, -0.3f}, 1.0f});

    return s;
}

// Fiber optic: light bouncing inside a mirrored channel with a glass core
inline Scene scene_fiber() {
    Scene s;
    s.name = "fiber";

    // Outer mirrored walls forming a narrow channel
    float len = 1.5f, gap = 0.12f;
    s.shapes.push_back(Segment{{-len, -gap}, {len, -gap}, mat_mirror(0.98f)});
    s.shapes.push_back(Segment{{-len, gap}, {len, gap}, mat_mirror(0.98f)});

    // Glass core (slight curve via two large circles)
    Material glass = mat_glass(1.5f, 15000.0f, 0.5f);
    s.shapes.push_back(Circle{{0.0f, 0.0f}, 0.06f, glass});
    s.shapes.push_back(Circle{{0.5f, 0.0f}, 0.06f, glass});
    s.shapes.push_back(Circle{{-0.5f, 0.0f}, 0.06f, glass});

    // End caps
    s.shapes.push_back(Segment{{len, -gap}, {len, gap}, mat_absorber()});

    s.lights.push_back(SegmentLight{{-len, gap}, {-len, -gap}, 1.0f});

    return s;
}

// Mirror box: two point lights in a reflective box — creates complex caustics
inline Scene scene_mirror_box() {
    Scene s;
    s.name = "mirror_box";

    add_box_walls(s, 0.9f, 0.6f, mat_mirror(0.95f));

    // A few glass spheres of varying sizes
    s.shapes.push_back(Circle{{-0.3f, 0.15f}, 0.15f, mat_glass(1.8f, 25000.0f, 0.4f)});
    s.shapes.push_back(Circle{{0.3f, -0.1f}, 0.1f, mat_glass(1.5f, 20000.0f, 0.3f)});
    s.shapes.push_back(Circle{{0.0f, -0.25f}, 0.08f, mat_glass(2.0f, 30000.0f, 0.5f)});

    s.lights.push_back(PointLight{{-0.6f, -0.35f}, 1.0f});
    s.lights.push_back(PointLight{{0.6f, 0.35f}, 0.7f});

    return s;
}

// Ring of spheres around a central light
inline Scene scene_ring() {
    Scene s;
    s.name = "ring";

    constexpr float PI = std::numbers::pi_v<float>;
    int n = 8;
    float ring_r = 0.5f;
    float sphere_r = 0.1f;
    Material glass = mat_glass(1.5f, 20000.0f, 0.4f);

    for (int i = 0; i < n; ++i) {
        float angle = 2.0f * PI * i / n;
        Vec2 pos{ring_r * std::cos(angle), ring_r * std::sin(angle)};
        s.shapes.push_back(Circle{pos, sphere_r, glass});
    }

    add_box_walls(s, 1.0f, 1.0f, mat_mirror(0.95f));

    s.lights.push_back(PointLight{{0.0f, 0.0f}, 1.0f});

    return s;
}

// Many refractive spheres in a hex grid — complex multi-body caustics
inline Scene scene_crystal_field() {
    Scene s;
    s.name = "crystal_field";

    float spacing = 0.24f;
    float sphere_r = 0.07f;
    int cols = 7, rows = 5;
    static constexpr float iors[] = {1.3f, 1.5f, 1.8f, 2.0f};

    for (int r = 0; r < rows; ++r) {
        int n_cols = (r % 2 == 0) ? cols : cols - 1;
        float x_off = (r % 2 == 0) ? 0.0f : spacing * 0.5f;
        for (int c = 0; c < n_cols; ++c) {
            float x = (c - (n_cols - 1) * 0.5f) * spacing + x_off;
            float y = (r - (rows - 1) * 0.5f) * spacing * (std::sqrt(3.0f) / 2.0f);
            float ior = iors[(c + r) % 4];
            s.shapes.push_back(Circle{{x, y}, sphere_r, mat_glass(ior, 20000.0f, 0.3f)});
        }
    }

    add_box_walls(s, 1.2f, 0.8f, mat_mirror(0.9f));

    s.lights.push_back(PointLight{{-1.0f, 0.6f}, 1.0f});
    s.lights.push_back(PointLight{{0.8f, -0.6f}, 0.7f});

    return s;
}

// Many semi-transparent mirror segments — light splitting and recombining
inline Scene scene_mirrors() {
    Scene s;
    s.name = "mirrors";

    constexpr float PI = std::numbers::pi_v<float>;

    // Deterministic LCG for reproducible placement
    uint32_t seed = 42u;
    auto rng = [&seed]() -> float {
        seed = seed * 1664525u + 1013904223u;
        return float(seed >> 8) / float(1u << 24);
    };

    int n = 12;
    for (int i = 0; i < n; ++i) {
        float cx = (rng() - 0.5f) * 1.4f;
        float cy = (rng() - 0.5f) * 0.9f;
        float angle = rng() * PI;
        float half_len = 0.06f + rng() * 0.12f;
        Vec2 dir{std::cos(angle) * half_len, std::sin(angle) * half_len};
        Vec2 center{cx, cy};
        float refl = 0.3f + rng() * 0.5f;
        s.shapes.push_back(Segment{center - dir, center + dir, mat_mirror(refl)});
    }

    add_box_walls(s, 1.0f, 0.7f, mat_mirror(0.9f));

    s.lights.push_back(PointLight{{-0.7f, 0.0f}, 1.0f});
    s.lights.push_back(PointLight{{0.5f, 0.4f}, 0.8f});

    return s;
}

// Double slit experiment
inline Scene scene_double_slit() {
    Scene s;
    s.name = "double_slit";

    float wall_x = -0.2f;
    float slit_gap = 0.03f;
    float slit_sep = 0.15f;

    // Wall with two slits
    s.shapes.push_back(Segment{{wall_x, -1.0f}, {wall_x, -slit_sep / 2 - slit_gap}, mat_absorber()});
    s.shapes.push_back(Segment{{wall_x, -slit_sep / 2 + slit_gap}, {wall_x, slit_sep / 2 - slit_gap}, mat_absorber()});
    s.shapes.push_back(Segment{{wall_x, slit_sep / 2 + slit_gap}, {wall_x, 1.0f}, mat_absorber()});

    add_box_walls(s, 1.2f, 0.8f, mat_absorber());

    // Point light far to the left (approximate plane wave)
    s.lights.push_back(PointLight{{-1.0f, 0.0f}, 1.0f});

    return s;
}
