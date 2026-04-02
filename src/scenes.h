#pragma once

#include "scene.h"

inline Scene scene_three_spheres() {
    Scene s;
    s.name = "three_spheres";

    Refractive glass{1.5f, 20000.0f};
    s.shapes.push_back(Circle{{-0.5f, 0.0f}, 0.2f, glass});
    s.shapes.push_back(Circle{{0.0f, 0.0f}, 0.2f, glass});
    s.shapes.push_back(Circle{{0.5f, 0.0f}, 0.2f, glass});

    add_box_walls(s, 1.2f, 0.8f, Specular{});

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
    Refractive glass{1.5f, 30000.0f};

    s.shapes.push_back(Segment{p0, p1, glass});
    s.shapes.push_back(Segment{p1, p2, glass});
    s.shapes.push_back(Segment{p2, p0, glass});

    add_box_walls(s, 1.2f, 0.8f, Diffuse{});

    // Slit to collimate the beam
    float slit_x = -0.7f, slit_gap = 0.04f;
    s.shapes.push_back(Segment{{slit_x, -0.8f}, {slit_x, -slit_gap}, Diffuse{}});
    s.shapes.push_back(Segment{{slit_x, slit_gap}, {slit_x, 0.8f}, Diffuse{}});

    s.lights.push_back(PointLight{{-1.0f, 0.0f}, 1.0f});

    return s;
}

inline Scene scene_diamond() {
    Scene s;
    s.name = "diamond";

    s.shapes.push_back(Circle{{0.0f, 0.0f}, 0.35f, Refractive{2.42f, 30000.0f}});

    add_box_walls(s, 1.0f, 0.7f, Specular{});

    s.lights.push_back(PointLight{{-0.7f, 0.4f}, 1.0f});
    s.lights.push_back(PointLight{{0.7f, 0.4f}, 1.0f});
    s.lights.push_back(PointLight{{0.0f, -0.5f}, 0.5f});

    return s;
}

inline Scene scene_lens() {
    Scene s;
    s.name = "lens";

    Refractive glass{1.5f, 20000.0f};
    s.shapes.push_back(Circle{{-0.35f, 0.0f}, 0.4f, glass});
    s.shapes.push_back(Circle{{0.35f, 0.0f}, 0.4f, glass});

    add_box_walls(s, 1.2f, 0.8f, Diffuse{});

    s.lights.push_back(SegmentLight{{-1.0f, 0.3f}, {-1.0f, -0.3f}, 1.0f});

    return s;
}
