#pragma once

#include <cmath>
#include <optional>
#include <span>
#include <string>
#include <variant>
#include <vector>

// --- Constants ---

inline constexpr float PI = 3.14159265358979f;
inline constexpr float TWO_PI = 2.0f * PI;
inline constexpr float INTERSECT_EPS = 1e-5f;
inline constexpr float SCATTER_EPS = 1e-4f;

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
    Vec2 reflect(Vec2 n) const { return *this - n * (2.0f * dot(n)); }
};

inline Vec2 operator*(float s, Vec2 v) { return {s * v.x, s * v.y}; }

struct Vec3 {
    float r = 0, g = 0, b = 0;
    Vec3 operator*(float s) const { return {r * s, g * s, b * s}; }
};

// --- Materials (Principled BSDF) ---

struct Material {
    float ior = 1.0f;          // Index of refraction (1.0 = no refraction boundary)
    float roughness = 0.0f;    // 0 = perfect specular, 1 = fully diffuse
    float metallic = 0.0f;     // 0 = dielectric (Fresnel), 1 = conductor (flat reflectance)
    float transmission = 0.0f; // 0 = opaque, 1 = fully transmissive
    float absorption = 0.0f;   // Beer-Lambert coefficient inside medium
    float cauchy_b = 0.0f;     // Cauchy dispersion coefficient (nm^2)
    float albedo = 1.0f;       // Scattering probability [0,1]
};

// Convenience constructors
inline Material mat_absorber() { return {.albedo = 0.0f}; }
inline Material mat_diffuse(float reflectance) { return {.albedo = reflectance}; }
inline Material mat_mirror(float reflectance, float roughness = 0.0f) {
    // transmission=1 so non-reflected rays pass through (ior=1 refraction = no bending)
    return {.roughness = roughness, .metallic = 1.0f, .transmission = 1.0f, .albedo = reflectance};
}
inline Material mat_glass(float ior, float cauchy_b = 0.0f, float absorption = 0.0f) {
    return {.ior = ior, .transmission = 1.0f, .absorption = absorption, .cauchy_b = cauchy_b};
}

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

struct Arc {
    Vec2 center;
    float radius;
    float angle_start = 0.0f;                   // radians [0, 2π]
    float angle_end = TWO_PI;  // radians [0, 2π]
    Material material;
};

struct Bezier {
    Vec2 p0, p1, p2; // p1 is control point
    Material material;
};

using Shape = std::variant<Circle, Segment, Arc, Bezier>;

// --- Lights ---

struct PointLight {
    Vec2 pos;
    float intensity = 1.0f;
    float wavelength_min = 380.0f;
    float wavelength_max = 780.0f;
};

struct SegmentLight {
    Vec2 a, b;
    float intensity = 1.0f;
    float wavelength_min = 380.0f;
    float wavelength_max = 780.0f;
};

struct BeamLight {
    Vec2 origin;
    Vec2 direction{1.0f, 0.0f}; // normalized
    float angular_width = 0.1f;  // full cone angle in radians
    float intensity = 1.0f;
    float wavelength_min = 380.0f;
    float wavelength_max = 780.0f;
};

using Light = std::variant<PointLight, SegmentLight, BeamLight>;

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
std::optional<Hit> intersect(const Ray& ray, const Arc& arc);
std::optional<Hit> intersect(const Ray& ray, const Bezier& bez);
std::optional<Hit> intersect_scene(const Ray& ray, const Scene& scene);

// Scene bounds (AABB with padding)
struct Bounds {
    Vec2 min, max;
};
Bounds compute_bounds(const Scene& scene, float padding = 0.05f);

// --- Rendering types ---

struct LineSegment {
    Vec2 p0, p1;
    Vec3 color;
    float intensity;
};

enum class ToneMap { None, Reinhard, ReinhardExtended, ACES, Logarithmic };

struct PostProcess {
    float exposure = 2.0f;   // stops (brighter default)
    float contrast = 1.0f;   // centered at 0.5
    float gamma = 2.2f;      // sRGB
    ToneMap tone_map = ToneMap::ACES;
    float white_point = 1.0f;
};

// --- Utilities ---

// Variant dispatch helper
template <class... Ts>
struct overloaded : Ts... {
    using Ts::operator()...;
};

// Transform line segments from world coords to pixel coords
void world_to_pixel(std::span<LineSegment> segments, const Bounds& bounds, int width, int height);

// Add four axis-aligned walls forming a box
void add_box_walls(Scene& scene, float half_w, float half_h, const Material& mat);
