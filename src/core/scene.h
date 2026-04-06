#pragma once

#include <cmath>
#include <cstdint>
#include <map>
#include <optional>
#include <span>
#include <string>
#include <string_view>
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
    float emission = 0.0f;     // Emissive intensity (adds energy at hit wavelength)

    bool operator==(const Material&) const = default;
};

// Convenience constructors
inline Material mat_absorber() { return {.albedo = 0.0f}; }
inline Material mat_diffuse(float reflectance) { return {.albedo = reflectance}; }
inline Material mat_mirror(float reflectance, float roughness = 0.0f) {
    // Beam splitter behavior: reflects (reflectance), transmits the rest.
    // metallic=1 makes reflectance flat (angle-independent), ior=1 = no bending.
    return {.roughness = roughness, .metallic = 1.0f, .transmission = 1.0f, .albedo = reflectance};
}
inline Material mat_opaque_mirror(float reflectance, float roughness = 0.0f) {
    // Opaque mirror: reflects (reflectance), absorbs the rest (no transmission).
    return {.roughness = roughness, .metallic = 1.0f, .transmission = 0.0f, .albedo = reflectance};
}
inline Material mat_glass(float ior, float cauchy_b = 0.0f, float absorption = 0.0f) {
    return {.ior = ior, .transmission = 1.0f, .absorption = absorption, .cauchy_b = cauchy_b};
}
inline Material mat_emissive(float emission, Material base = {}) {
    base.emission = emission;
    return base;
}

// --- Material binding ---
//
// A shape's material is either an inline Material value or a string reference
// to a named entry in Scene::materials.  One field, one source of truth.

using MaterialMap = std::map<std::string, Material>;
using MaterialBinding = std::variant<Material, std::string>;

// Resolve a binding to its Material value.
// Inline: returns the Material directly.  Reference: looks up in the map.
inline const Material& resolve_binding(const MaterialBinding& binding,
                                        const MaterialMap& materials) {
    if (auto* mat = std::get_if<Material>(&binding)) return *mat;
    const auto& ref = std::get<std::string>(binding);
    auto it = materials.find(ref);
    if (it != materials.end()) return it->second;
    static const Material default_material;
    return default_material;
}

inline bool is_material_ref(const MaterialBinding& b) {
    return std::holds_alternative<std::string>(b);
}

inline std::string_view material_ref_id(const MaterialBinding& b) {
    if (auto* s = std::get_if<std::string>(&b)) return *s;
    return {};
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
    std::string id;
    Vec2 center;
    float radius;
    MaterialBinding binding;
};

struct Segment {
    std::string id;
    Vec2 a, b;
    MaterialBinding binding;
};

struct Arc {
    std::string id;
    Vec2 center;
    float radius;
    float angle_start = 0.0f; // radians [0, 2π)
    float sweep = TWO_PI;     // radians [0, 2π], CCW from angle_start
    MaterialBinding binding;
};

struct Bezier {
    std::string id;
    Vec2 p0, p1, p2; // p1 is control point
    MaterialBinding binding;
};

inline Vec2 bezier_eval(const Bezier& b, float t) {
    float u = 1.0f - t;
    return b.p0 * (u * u) + b.p1 * (2.0f * u * t) + b.p2 * (t * t);
}

struct Polygon {
    std::string id;
    std::vector<Vec2> vertices; // closed polyline: edge i = vertices[i] → vertices[(i+1) % n]
    MaterialBinding binding;

    Vec2 centroid() const {
        if (vertices.empty()) return {0, 0};
        Vec2 c{0, 0};
        for (auto& v : vertices) c = c + v;
        return c * (1.0f / vertices.size());
    }
};

inline float polygon_signed_area2(const Polygon& p) {
    float area2 = 0.0f;
    int n = (int)p.vertices.size();
    for (int i = 0; i < n; ++i) {
        const Vec2& a = p.vertices[i];
        const Vec2& b = p.vertices[(i + 1) % n];
        area2 += a.x * b.y - b.x * a.y;
    }
    return area2;
}

inline bool polygon_is_clockwise(const Polygon& p) {
    return polygon_signed_area2(p) <= 0.0f;
}

struct Ellipse {
    std::string id;
    Vec2 center;
    float semi_a;          // semi-axis length along rotated X
    float semi_b;          // semi-axis length along rotated Y
    float rotation = 0.0f; // radians, angle of semi_a axis from +X
    MaterialBinding binding;
};

using Shape = std::variant<Circle, Segment, Arc, Bezier, Polygon, Ellipse>;

// --- Lights ---

struct PointLight {
    std::string id;
    Vec2 pos;
    float intensity = 1.0f;
    float wavelength_min = 380.0f;
    float wavelength_max = 780.0f;
};

struct SegmentLight {
    std::string id;
    Vec2 a, b;
    float intensity = 1.0f;
    float wavelength_min = 380.0f;
    float wavelength_max = 780.0f;
};

struct BeamLight {
    std::string id;
    Vec2 origin;
    Vec2 direction{1.0f, 0.0f}; // normalized
    float angular_width = 0.1f;  // full cone angle in radians
    float intensity = 1.0f;
    float wavelength_min = 380.0f;
    float wavelength_max = 780.0f;
};

struct ParallelBeamLight {
    std::string id;
    Vec2 a, b;                      // segment endpoints (emission aperture)
    Vec2 direction{1.0f, 0.0f};     // normalized beam direction
    float angular_width = 0.0f;     // full cone angle in radians (0 = perfectly collimated)
    float intensity = 1.0f;
    float wavelength_min = 380.0f;
    float wavelength_max = 780.0f;
};

struct SpotLight {
    std::string id;
    Vec2 pos;
    Vec2 direction{1.0f, 0.0f};     // normalized
    float angular_width = 0.5f;     // full cone angle in radians
    float falloff = 2.0f;           // cosine-power exponent (0=uniform, higher=sharper)
    float intensity = 1.0f;
    float wavelength_min = 380.0f;
    float wavelength_max = 780.0f;
};

using Light = std::variant<PointLight, SegmentLight, BeamLight, ParallelBeamLight, SpotLight>;

// --- Groups ---

struct Group {
    std::string id;
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
    std::map<std::string, Material> materials; // named material library
};

std::string shape_type_name(const Shape& shape);
std::string light_type_name(const Light& light);
bool validate_scene(const Scene& scene, std::string* error = nullptr);
void ensure_scene_entity_ids(Scene& scene);
std::string next_scene_entity_id(const Scene& scene, std::string_view prefix);
Shape* find_shape(Scene& scene, std::string_view id);
const Shape* find_shape(const Scene& scene, std::string_view id);
Light* find_light(Scene& scene, std::string_view id);
const Light* find_light(const Scene& scene, std::string_view id);
Group* find_group(Scene& scene, std::string_view id);
const Group* find_group(const Scene& scene, std::string_view id);

// Find shape/light within a specific vector (for group-scoped lookups)
Shape* find_shape_in(std::vector<Shape>& shapes, std::string_view id);
const Shape* find_shape_in(const std::vector<Shape>& shapes, std::string_view id);
Light* find_light_in(std::vector<Light>& lights, std::string_view id);
const Light* find_light_in(const std::vector<Light>& lights, std::string_view id);
Material* find_material(Scene& scene, std::string_view id);
const Material* find_material(const Scene& scene, std::string_view id);
bool bind_material(Shape& shape, const Scene& scene, std::string_view material_id, std::string* error = nullptr);
void detach_material(Shape& shape, const MaterialMap& materials);
int material_usage_count(const Scene& scene, std::string_view material_id);
bool rename_material(Scene& scene, std::string_view old_id, std::string_view new_id, std::string* error = nullptr);
bool delete_material(Scene& scene, std::string_view material_id, std::string* error = nullptr);

// Prepare a scene for serialization: assign IDs, validate.
// Returns false and sets *error if validation fails.
bool normalize_scene(Scene& scene, std::string* error = nullptr);

// Common variant field accessors
const std::string& shape_id(const Shape& s);
std::string& shape_id(Shape& s);
const std::string& light_id(const Light& l);
std::string& light_id(Light& l);
const MaterialBinding& shape_binding(const Shape& s);
MaterialBinding& shape_binding(Shape& s);
const Material& resolve_shape_material(const Shape& s, const MaterialMap& materials);
std::string shape_display_name(const Shape& s, int fallback_index);
std::string light_display_name(const Light& l, int fallback_index);

// ─── Authored source enumeration ──────────────────────────────────

struct AuthoredSource {
    enum Kind { SceneLight, GroupLight, ShapeEmission } kind;
    std::string label;
    std::string entity_id;
    std::string group_id; // empty for top-level
};

std::vector<AuthoredSource> collect_authored_sources(const Scene& scene);
Scene scene_with_solo_source(const Scene& scene, const AuthoredSource& source);

// Scene bounds (AABB with padding)
struct Bounds {
    Vec2 min, max;
};

// --- Rendering types ---

struct LineSegment {
    Vec2 p0, p1;
    Vec3 color;
    float intensity;
};

enum class ToneMap { None, Reinhard, ReinhardExtended, ACES, Logarithmic };

inline std::optional<ToneMap> parse_tonemap(const std::string& s) {
    if (s == "none") return ToneMap::None;
    if (s == "reinhard") return ToneMap::Reinhard;
    if (s == "reinhardx") return ToneMap::ReinhardExtended;
    if (s == "aces") return ToneMap::ACES;
    if (s == "log") return ToneMap::Logarithmic;
    return std::nullopt;
}

inline const char* tonemap_to_string(ToneMap tm) {
    switch (tm) {
        case ToneMap::None: return "none";
        case ToneMap::Reinhard: return "reinhard";
        case ToneMap::ReinhardExtended: return "reinhardx";
        case ToneMap::ACES: return "aces";
        case ToneMap::Logarithmic: return "log";
    }
    return "none";
}

enum class NormalizeMode : int {
    Max = 0,   // per-frame max pixel (or percentile)
    Rays = 1,  // total accumulated rays — stable across ray counts (default)
    Fixed = 2, // user-specified divisor (normalize_ref)
    Off = 3,   // no normalization (divisor = 1.0)
};

inline std::optional<NormalizeMode> parse_normalize_mode(const std::string& s) {
    if (s == "max") return NormalizeMode::Max;
    if (s == "rays") return NormalizeMode::Rays;
    if (s == "fixed") return NormalizeMode::Fixed;
    if (s == "off") return NormalizeMode::Off;
    return std::nullopt;
}

inline const char* normalize_mode_to_string(NormalizeMode nm) {
    switch (nm) {
        case NormalizeMode::Max: return "max";
        case NormalizeMode::Rays: return "rays";
        case NormalizeMode::Fixed: return "fixed";
        case NormalizeMode::Off: return "off";
    }
    return "rays";
}

enum class SeedMode : int {
    Deterministic = 0,
    Decorrelated = 1,
};

inline std::optional<SeedMode> parse_seed_mode(const std::string& s) {
    if (s == "deterministic") return SeedMode::Deterministic;
    if (s == "decorrelated") return SeedMode::Decorrelated;
    return std::nullopt;
}

inline const char* seed_mode_to_string(SeedMode mode) {
    switch (mode) {
        case SeedMode::Deterministic: return "deterministic";
        case SeedMode::Decorrelated: return "decorrelated";
    }
    return "deterministic";
}

struct TraceConfig {
    int batch_size = 200000;
    int max_depth = 12;
    float intensity = 1.0f;
    SeedMode seed_mode = SeedMode::Deterministic;
    int frame_index = 0;
};

struct PostProcess {
    float exposure = -5.0f;
    float contrast = 1.0f;
    float gamma = 2.0f;
    ToneMap tone_map = ToneMap::ReinhardExtended;
    float white_point = 0.5f;
    NormalizeMode normalize = NormalizeMode::Rays;
    float normalize_ref = 0.0f; // divisor for Fixed mode
    float normalize_pct = 1.0f; // percentile for Max mode (1.0=max, 0.99=P99)
    float ambient = 0.0f;       // constant fill light (added after exposure, before tonemap)
    float background[3] = {0, 0, 0}; // background color (linear RGB, applied to unlit pixels)
    float opacity = 1.0f;       // global opacity (applied after tonemap, for fade-to-black)
    float saturation = 1.0f;    // color saturation (1=normal, 0=grayscale, >1=boosted)
    float vignette = 0.0f;      // radial edge darkening strength [0,1]
    float vignette_radius = 0.7f; // falloff start (smaller=more aggressive, default 0.7)
    float temperature = 0.0f;   // warm/cool color shift (-1=cool, 0=neutral, 1=warm)
    float highlights = 0.0f;    // highlight adjustment (-1=compress, 0=neutral, 1=boost)
    float shadows = 0.0f;       // shadow adjustment (-1=crush, 0=neutral, 1=lift)
    float hue_shift = 0.0f;     // hue rotation in degrees (-180 to 180)
    float grain = 0.0f;         // film grain strength (0=off)
    int grain_seed = 0;         // grain noise seed (vary per frame for animation)
    float chromatic_aberration = 0.0f; // per-channel UV offset strength (0=off)
};

// --- Shot: the authored document ---

struct Camera2D {
    std::optional<Bounds> bounds;   // explicit [xmin, ymin, xmax, ymax]
    std::optional<Vec2> center;     // center point (requires width)
    std::optional<float> width;     // world width (height derived from aspect)

    // Resolve to concrete bounds. Uses fallback (e.g. scene bounds) if unset.
    Bounds resolve(float aspect, const Bounds& fallback) const;
    bool empty() const { return !bounds && !center && !width; }
};

struct Canvas {
    int width = 1920;
    int height = 1080;
    float aspect() const { return (float)width / height; }
};

// Look: authored display intent (what the user saves).
// PostProcess: runtime GPU uniform state (what the shader consumes).
// Identical fields, distinct types — use to_post_process() to convert.
struct Look {
    float exposure = -5.0f;
    float contrast = 1.0f;
    float gamma = 2.0f;
    ToneMap tone_map = ToneMap::ReinhardExtended;
    float white_point = 0.5f;
    NormalizeMode normalize = NormalizeMode::Rays;
    float normalize_ref = 0.0f;
    float normalize_pct = 1.0f;
    float ambient = 0.0f;
    float background[3] = {0, 0, 0};
    float opacity = 1.0f;
    float saturation = 1.0f;
    float vignette = 0.0f;
    float vignette_radius = 0.7f;
    float temperature = 0.0f;
    float highlights = 0.0f;
    float shadows = 0.0f;
    float hue_shift = 0.0f;
    float grain = 0.0f;
    int grain_seed = 0;
    float chromatic_aberration = 0.0f;

    PostProcess to_post_process() const {
        return {exposure, contrast, gamma, tone_map, white_point, normalize,
                normalize_ref, normalize_pct, ambient,
                {background[0], background[1], background[2]},
                opacity, saturation, vignette, vignette_radius,
                temperature, highlights, shadows, hue_shift,
                grain, grain_seed, chromatic_aberration};
    }
};

struct TraceDefaults {
    int64_t rays = 10'000'000;
    int batch = 200'000;
    int depth = 12;
    float intensity = 1.0f;
    SeedMode seed_mode = SeedMode::Deterministic;

    TraceConfig to_trace_config(int frame_index = 0) const;
};

struct Shot {
    Scene scene;
    Camera2D camera;
    Canvas canvas;
    Look look;
    TraceDefaults trace;
    std::string name;
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
