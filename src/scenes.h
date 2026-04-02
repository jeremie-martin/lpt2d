#pragma once

#include "scene.h"

// Built-in scene: three refractive spheres with two rainbow point lights
inline Scene scene_three_spheres() {
    Scene s;
    s.name = "three_spheres";

    // Three glass spheres with strong dispersion for visible rainbow
    Refractive glass{1.5f, 20000.0f};
    s.shapes.push_back(Circle{{-0.5f, 0.0f}, 0.2f, glass});
    s.shapes.push_back(Circle{{0.0f, 0.0f}, 0.2f, glass});
    s.shapes.push_back(Circle{{0.5f, 0.0f}, 0.2f, glass});

    // Bounding box walls (specular)
    float w = 1.2f, h = 0.8f;
    s.shapes.push_back(Segment{{-w, -h}, {w, -h}, Specular{}});  // bottom
    s.shapes.push_back(Segment{{-w, h}, {w, h}, Specular{}});    // top
    s.shapes.push_back(Segment{{-w, -h}, {-w, h}, Specular{}});  // left
    s.shapes.push_back(Segment{{w, -h}, {w, h}, Specular{}});    // right

    // Two point lights
    s.lights.push_back(PointLight{{-0.8f, 0.5f}, 1.0f});
    s.lights.push_back(PointLight{{0.8f, -0.5f}, 1.0f});

    return s;
}

// Built-in scene: single prism for rainbow dispersion
inline Scene scene_prism() {
    Scene s;
    s.name = "prism";

    // Larger triangular prism — CW winding so perp() = (-dy,dx) gives outward normals
    float size = 0.4f;
    float h = size * std::sqrt(3.0f) / 2.0f;
    Vec2 p0{-0.1f, -h * 0.6f};   // bottom
    Vec2 p1{-0.1f - size, h * 0.4f};    // top-left
    Vec2 p2{-0.1f + size, h * 0.4f};     // top-right
    Refractive glass{1.5f, 30000.0f};

    s.shapes.push_back(Segment{p0, p1, glass}); // left edge
    s.shapes.push_back(Segment{p1, p2, glass}); // top edge
    s.shapes.push_back(Segment{p2, p0, glass}); // right edge

    // Walls (absorbing)
    float w = 1.2f, wh = 0.8f;
    s.shapes.push_back(Segment{{-w, -wh}, {w, -wh}, Diffuse{}});
    s.shapes.push_back(Segment{{-w, wh}, {w, wh}, Diffuse{}});
    s.shapes.push_back(Segment{{-w, -wh}, {-w, wh}, Diffuse{}});
    s.shapes.push_back(Segment{{w, -wh}, {w, wh}, Diffuse{}});

    // Slit: two absorbing walls with a narrow gap to collimate the beam
    float slit_x = -0.7f;
    float slit_gap = 0.04f; // narrow slit
    s.shapes.push_back(Segment{{slit_x, -wh}, {slit_x, -slit_gap}, Diffuse{}});
    s.shapes.push_back(Segment{{slit_x, slit_gap}, {slit_x, wh}, Diffuse{}});

    // Point light behind the slit (rays spread from source, slit collimates)
    s.lights.push_back(PointLight{{-1.0f, 0.0f}, 1.0f});

    return s;
}

// Built-in scene: single large refractive sphere (diamond-like)
inline Scene scene_diamond() {
    Scene s;
    s.name = "diamond";

    s.shapes.push_back(Circle{{0.0f, 0.0f}, 0.35f, Refractive{2.42f, 30000.0f}});

    float w = 1.0f, h = 0.7f;
    s.shapes.push_back(Segment{{-w, -h}, {w, -h}, Specular{}});
    s.shapes.push_back(Segment{{-w, h}, {w, h}, Specular{}});
    s.shapes.push_back(Segment{{-w, -h}, {-w, h}, Specular{}});
    s.shapes.push_back(Segment{{w, -h}, {w, h}, Specular{}});

    s.lights.push_back(PointLight{{-0.7f, 0.4f}, 1.0f});
    s.lights.push_back(PointLight{{0.7f, 0.4f}, 1.0f});
    s.lights.push_back(PointLight{{0.0f, -0.5f}, 0.5f});

    return s;
}

// Built-in scene: converging lens
inline Scene scene_lens() {
    Scene s;
    s.name = "lens";

    float offset = 0.35f;
    float radius = 0.4f;
    Refractive glass{1.5f, 20000.0f};
    s.shapes.push_back(Circle{{-offset, 0.0f}, radius, glass});
    s.shapes.push_back(Circle{{offset, 0.0f}, radius, glass});

    float w = 1.2f, h = 0.8f;
    s.shapes.push_back(Segment{{-w, -h}, {w, -h}, Diffuse{}});
    s.shapes.push_back(Segment{{-w, h}, {w, h}, Diffuse{}});
    s.shapes.push_back(Segment{{-w, -h}, {-w, h}, Diffuse{}});
    s.shapes.push_back(Segment{{w, -h}, {w, h}, Diffuse{}});

    // Area light pointing RIGHT (swap so perp points right)
    s.lights.push_back(SegmentLight{{-1.0f, 0.3f}, {-1.0f, -0.3f}, 1.0f});

    return s;
}
