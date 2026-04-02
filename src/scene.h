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

// --- Materials ---

struct Diffuse {
    float reflectance = 0.0f; // 0 = absorb, >0 = probability of diffuse scatter
};

struct Specular {
    float reflectance = 1.0f; // probability of reflection (else pass through)
    float roughness = 0.0f;   // 0 = perfect mirror, >0 = glossy (angular spread)
};

struct Refractive {
    float ior = 1.5f;
    float cauchy_b = 0.0f;    // Cauchy dispersion coefficient (nm^2)
    float absorption = 0.0f;  // Beer-Lambert absorption coefficient (per world unit)
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
