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
//
// Decision tree per bounce (Russian roulette):
//
//   F_eff = mix(F_fresnel, albedo, metallic)   [TIR forces F_eff = 1]
//
//   [P = F_eff]           REFLECT  (specular/rough/Lambertian per roughness)
//   [P = 1 - F_eff]       NON-REFLECTED:
//     [P = transmission]     REFRACT  (Snell, Beer-Lambert, Cauchy dispersion)
//     [P = 1-transmission]   SURFACE:
//       [P = (1-metallic)*albedo]  DIFFUSE scatter
//       [else]                     ABSORB (metal absorption + dielectric loss)
//
// Energy is always conserved (probabilities sum to 1).

struct Material {
    float ior = 1.0f;          // Index of refraction (1.0 = no boundary)
    float roughness = 0.0f;    // 0 = specular, 1 = Lambertian (applies to both reflect & refract)
    float metallic = 0.0f;     // 0 = dielectric (Fresnel), 1 = conductor (flat reflectance = albedo)
    float transmission = 0.0f; // Fraction of non-reflected light that refracts (0 = opaque, 1 = glass)
    float absorption = 0.0f;   // Beer-Lambert coefficient inside medium (per unit distance)
    float cauchy_b = 0.0f;     // Cauchy dispersion: ior_eff = ior + cauchy_b / lambda_nm^2
    float albedo = 1.0f;       // Metallic: reflectance F0. Dielectric: diffuse scatter probability.
};

// Convenience constructors
inline Material mat_absorber() { return {.albedo = 0.0f}; }
inline Material mat_diffuse(float reflectance) { return {.albedo = reflectance}; }
inline Material mat_mirror(float reflectance, float roughness = 0.0f) {
    // Beam splitter: reflects (reflectance), transmits the rest (ior=1 = no bending).
    // metallic=1 makes reflectance flat (angle-independent).
    return {.roughness = roughness, .metallic = 1.0f, .transmission = 1.0f, .albedo = reflectance};
}
inline Material mat_glass(float ior, float cauchy_b = 0.0f, float absorption = 0.0f) {
    return {.ior = ior, .transmission = 1.0f, .absorption = absorption, .cauchy_b = cauchy_b};
}

// --- Transform ---

struct Transform2D {
    Vec2 translate{0, 0};
    float rotate = 0;      // radians
    Vec2 scale{1, 1};

    // Apply transform to a point: scale → rotate → translate
    Vec2 apply(Vec2 p) const {
        p = {p.x * scale.x, p.y * scale.y};
        float c = std::cos(rotate), s = std::sin(rotate);
        p = {p.x * c - p.y * s, p.x * s + p.y * c};
        return p + translate;
    }

    // Apply to a direction vector (no translate)
    Vec2 apply_direction(Vec2 d) const {
        d = {d.x * scale.x, d.y * scale.y};
        float c = std::cos(rotate), s = std::sin(rotate);
        return {d.x * c - d.y * s, d.x * s + d.y * c};
    }

    bool is_identity() const {
        return translate.x == 0 && translate.y == 0 && rotate == 0 && scale.x == 1 && scale.y == 1;
    }
};

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

// --- Groups ---

struct Group {
    std::string name;
    Transform2D transform;
    std::vector<Shape> shapes;  // in local coordinates
    std::vector<Light> lights;  // in local coordinates
};

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
    std::vector<Shape> shapes;   // ungrouped shapes (world coords)
    std::vector<Light> lights;   // ungrouped lights (world coords)
    std::vector<Group> groups;
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

// Transform a shape/light from local to world coordinates using a Transform2D
Shape transform_shape(const Shape& s, const Transform2D& t);
Light transform_light(const Light& l, const Transform2D& t);
