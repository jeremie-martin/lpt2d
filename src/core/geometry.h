#pragma once

#include <optional>
#include <string>
#include <vector>

#include "scene.h"

// ─── Arc geometry helpers ─────────────────────────────────────────

float normalize_angle(float angle);
float clamp_arc_sweep(float sweep);
float arc_end_angle(const Arc& arc);
float arc_mid_angle(const Arc& arc);
Vec2 arc_point(const Arc& arc, float angle);
Vec2 arc_start_point(const Arc& arc);
Vec2 arc_end_point(const Arc& arc);
Vec2 arc_mid_point(const Arc& arc);
bool angle_in_arc(float angle, const Arc& arc);
Bounds arc_bounds(const Arc& arc);
float point_arc_distance(Vec2 p, const Arc& arc);

// ─── Rounded-polygon decomposition ──────────────────────────────

struct RoundedPolygonParts {
    struct Edge { Vec2 a, b; };
    struct Corner { Vec2 center; float radius; float angle_start; float sweep; };
    std::vector<Edge> edges;
    std::vector<Corner> corners;
};

RoundedPolygonParts decompose_rounded_polygon(const Polygon& poly);
std::vector<Vec2> polygon_fill_boundary(const Polygon& poly, int arc_segments = 8);
std::vector<uint32_t> triangulate_simple_polygon(const std::vector<Vec2>& vertices);

// ─── Path decomposition ────────────────────────────────────────────

struct PathParts {
    std::vector<Bezier> curves; // decomposed Bezier segments (id/binding unused)
};

PathParts decompose_path(const Path& path);
Path fit_path_from_samples(const std::vector<Vec2>& samples, const MaterialBinding& binding, bool closed = false);

// ─── Primitive bounds ─────────────────────────────────────────────

Bounds shape_bounds(const Shape& s);
Bounds light_bounds(const Light& l);

// ─── Scene bounds ─────────────────────────────────────────────────

Bounds compute_bounds(const Scene& scene, float padding = 0.05f);

// ─── Scene diagnostics ───────────────────────────────────────────

std::vector<std::string> diagnose_scene(const Scene& scene);

// ─── Intersection testing ─────────────────────────────────────────

std::optional<Hit> intersect(const Ray& ray, const Circle& circle, const MaterialMap& materials);
std::optional<Hit> intersect(const Ray& ray, const Segment& seg, const MaterialMap& materials);
std::optional<Hit> intersect(const Ray& ray, const Arc& arc, const MaterialMap& materials);
std::optional<Hit> intersect(const Ray& ray, const Bezier& bez, const MaterialMap& materials);
std::optional<Hit> intersect(const Ray& ray, const Polygon& poly, const MaterialMap& materials);
std::optional<Hit> intersect(const Ray& ray, const Ellipse& ellipse, const MaterialMap& materials);
std::optional<Hit> intersect(const Ray& ray, const Path& path, const MaterialMap& materials);
std::optional<Hit> intersect_scene(const Ray& ray, const Scene& scene);

// ─── Transform helpers ───────────────────────────────────────────

Shape transform_shape(const Shape& s, const Transform2D& t);
Light transform_light(const Light& l, const Transform2D& t);

// ─── Centroid ────────────────────────────────────────────────────

Vec2 shape_centroid(const Shape& s);
Vec2 light_centroid(const Light& l);

// ─── Perimeter and emission ──────────────────────────────────────

float shape_perimeter(const Shape& s);
std::vector<Light> emission_light(const Shape& s, const MaterialMap& materials);
