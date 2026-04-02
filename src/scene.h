#pragma once

#include <cmath>
#include <optional>
#include <string>
#include <variant>
#include <vector>

// --- Math ---

struct Vec2 {
    float x = 0, y = 0;

    Vec2 operator+(Vec2 v) const { return {x + v.x, y + v.y}; }
    Vec2 operator-(Vec2 v) const { return {x - v.x, y - v.y}; }
    Vec2 operator*(float s) const { return {x * s, y * s}; }
    Vec2 operator/(float s) const { return {x / s, y / s}; }
    Vec2 operator-() const { return {-x, -y}; }

    float dot(Vec2 v) const { return x * v.x + y * v.y; }
    float length() const { return std::sqrt(x * x + y * y); }
    float length_sq() const { return x * x + y * y; }
    Vec2 normalized() const {
        float l = length();
        return l > 0 ? Vec2{x / l, y / l} : Vec2{0, 0};
    }
    Vec2 perp() const { return {-y, x}; }
};

inline Vec2 operator*(float s, Vec2 v) { return {s * v.x, s * v.y}; }

struct Vec3 {
    float r = 0, g = 0, b = 0;
    Vec3 operator*(float s) const { return {r * s, g * s, b * s}; }
};

// --- Materials ---

struct Diffuse {};

struct Specular {};

struct Refractive {
    float ior = 1.5f;
    float cauchy_b = 0.0f; // Cauchy dispersion coefficient (nm^2)
};

using Material = std::variant<Diffuse, Specular, Refractive>;

// --- Geometry ---

struct Circle {
    Vec2 center;
    float radius;
    Material material;
};

struct Segment {
    Vec2 a, b;
    Material material;
};

using Shape = std::variant<Circle, Segment>;

// --- Lights ---

struct PointLight {
    Vec2 pos;
    float intensity = 1.0f;
};

struct SegmentLight {
    Vec2 a, b;
    float intensity = 1.0f;
};

using Light = std::variant<PointLight, SegmentLight>;

// --- Ray tracing ---

struct Ray {
    Vec2 origin, dir; // dir should be normalized
};

struct Hit {
    float t;
    Vec2 point;
    Vec2 normal;
    const Material* material;
};

// --- Scene ---

struct Scene {
    std::vector<Shape> shapes;
    std::vector<Light> lights;
    std::string name;
};

// Intersection testing
std::optional<Hit> intersect(const Ray& ray, const Circle& circle);
std::optional<Hit> intersect(const Ray& ray, const Segment& seg);
std::optional<Hit> intersect_scene(const Ray& ray, const Scene& scene);

// Scene bounds (AABB with padding)
struct Bounds {
    Vec2 min, max;
};
Bounds compute_bounds(const Scene& scene, float padding = 0.05f);

// Variant helper
template <class... Ts>
struct overloaded : Ts... {
    using Ts::operator()...;
};
