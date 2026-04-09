#include "test_harness.h"
#include "geometry.h"
#include "scene.h"

#include <cmath>
#include <map>

namespace {
Arc make_arc(Vec2 center, float radius, float angle_start, float sweep) {
    return {.id = {}, .center = center, .radius = radius,
            .angle_start = angle_start, .sweep = sweep, .material_id = {}};
}
} // namespace

// --- Angle normalization ---

TEST(normalize_angle_zero) {
    ASSERT_NEAR(normalize_angle(0.0f), 0.0f, 1e-6f);
}

TEST(normalize_angle_pi) {
    ASSERT_NEAR(normalize_angle(PI), PI, 1e-6f);
}

TEST(normalize_angle_negative_pi) {
    ASSERT_NEAR(normalize_angle(-PI), PI, 1e-6f);
}

TEST(normalize_angle_two_pi_wraps) {
    ASSERT_NEAR(normalize_angle(TWO_PI), 0.0f, 1e-5f);
}

TEST(normalize_angle_large_positive) {
    float result = normalize_angle(3.0f * TWO_PI + 0.5f);
    ASSERT_NEAR(result, 0.5f, 1e-5f);
}

TEST(normalize_angle_large_negative) {
    float result = normalize_angle(-7.0f);
    ASSERT_TRUE(result >= 0.0f && result < TWO_PI);
}

TEST(normalize_angle_negative_half_pi) {
    ASSERT_NEAR(normalize_angle(-PI / 2.0f), 1.5f * PI, 1e-6f);
}

// --- Arc sweep clamping ---

TEST(clamp_arc_sweep_zero) {
    ASSERT_NEAR(clamp_arc_sweep(0.0f), 0.0f, 1e-6f);
}

TEST(clamp_arc_sweep_pi) {
    ASSERT_NEAR(clamp_arc_sweep(PI), PI, 1e-6f);
}

TEST(clamp_arc_sweep_two_pi) {
    ASSERT_NEAR(clamp_arc_sweep(TWO_PI), TWO_PI, 1e-6f);
}

TEST(clamp_arc_sweep_negative) {
    ASSERT_NEAR(clamp_arc_sweep(-1.0f), 0.0f, 1e-6f);
}

TEST(clamp_arc_sweep_excessive) {
    ASSERT_NEAR(clamp_arc_sweep(10.0f), TWO_PI, 1e-6f);
}

// --- Arc end angle ---

TEST(arc_end_angle_quarter) {
    ASSERT_NEAR(arc_end_angle(make_arc({0, 0}, 1.0f, 0.0f, PI / 2.0f)), PI / 2.0f, 1e-6f);
}

TEST(arc_end_angle_full_circle) {
    ASSERT_NEAR(arc_end_angle(make_arc({0, 0}, 1.0f, 0.0f, TWO_PI)), 0.0f, 1e-5f);
}

TEST(arc_end_angle_crossing_zero) {
    float expected = normalize_angle(5.5f + 2.0f);
    ASSERT_NEAR(arc_end_angle(make_arc({0, 0}, 1.0f, 5.5f, 2.0f)), expected, 1e-6f);
}

// --- Arc mid angle ---

TEST(arc_mid_angle_quarter) {
    ASSERT_NEAR(arc_mid_angle(make_arc({0, 0}, 1.0f, 0.0f, PI)), PI / 2.0f, 1e-6f);
}

// --- Arc points ---

TEST(arc_start_point) {
    Vec2 p = arc_start_point(make_arc({1, 2}, 3.0f, 0.0f, PI));
    ASSERT_NEAR(p.x, 4.0f, 1e-6f);
    ASSERT_NEAR(p.y, 2.0f, 1e-6f);
}

TEST(arc_end_point_quarter) {
    Vec2 p = arc_end_point(make_arc({0, 0}, 1.0f, 0.0f, PI / 2.0f));
    ASSERT_NEAR(p.x, 0.0f, 1e-6f);
    ASSERT_NEAR(p.y, 1.0f, 1e-6f);
}

// --- angle_in_arc ---

TEST(angle_in_arc_full_circle_always_true) {
    Arc arc = make_arc({0, 0}, 1.0f, 0.0f, TWO_PI);
    ASSERT_TRUE(angle_in_arc(0.0f, arc));
    ASSERT_TRUE(angle_in_arc(PI, arc));
    ASSERT_TRUE(angle_in_arc(4.0f, arc));
}

TEST(angle_in_arc_half_inside) {
    ASSERT_TRUE(angle_in_arc(0.5f, make_arc({0, 0}, 1.0f, 0.0f, PI)));
}

TEST(angle_in_arc_half_outside) {
    ASSERT_FALSE(angle_in_arc(4.0f, make_arc({0, 0}, 1.0f, 0.0f, PI)));
}

TEST(angle_in_arc_wrap_around_inside) {
    ASSERT_TRUE(angle_in_arc(0.2f, make_arc({0, 0}, 1.0f, 5.5f, 2.0f)));
}

TEST(angle_in_arc_wrap_around_outside) {
    ASSERT_FALSE(angle_in_arc(3.0f, make_arc({0, 0}, 1.0f, 5.5f, 2.0f)));
}

// --- arc_bounds ---

TEST(arc_bounds_full_circle) {
    Bounds b = arc_bounds(make_arc({1, 2}, 3.0f, 0.0f, TWO_PI));
    ASSERT_NEAR(b.min.x, -2.0f, 1e-6f);
    ASSERT_NEAR(b.min.y, -1.0f, 1e-6f);
    ASSERT_NEAR(b.max.x, 4.0f, 1e-6f);
    ASSERT_NEAR(b.max.y, 5.0f, 1e-6f);
}

TEST(arc_bounds_quarter_first_quadrant) {
    Bounds b = arc_bounds(make_arc({0, 0}, 1.0f, 0.0f, PI / 2.0f));
    ASSERT_NEAR(b.min.x, 0.0f, 1e-5f);
    ASSERT_NEAR(b.min.y, 0.0f, 1e-5f);
    ASSERT_NEAR(b.max.x, 1.0f, 1e-5f);
    ASSERT_NEAR(b.max.y, 1.0f, 1e-5f);
}

TEST(arc_bounds_crossing_negative_x) {
    Bounds b = arc_bounds(make_arc({0, 0}, 1.0f, PI / 2.0f, PI));
    ASSERT_NEAR(b.min.x, -1.0f, 1e-5f);
}

// --- Polygon winding ---

TEST(polygon_signed_area2_ccw_triangle) {
    Polygon p;
    p.vertices = {{0, 0}, {1, 0}, {0, 1}};
    ASSERT_NEAR(polygon_signed_area2(p), 1.0f, 1e-6f);
    ASSERT_FALSE(polygon_is_clockwise(p));
}

TEST(polygon_signed_area2_cw_triangle) {
    Polygon p;
    p.vertices = {{0, 0}, {0, 1}, {1, 0}};
    ASSERT_NEAR(polygon_signed_area2(p), -1.0f, 1e-6f);
    ASSERT_TRUE(polygon_is_clockwise(p));
}

TEST(polygon_signed_area2_unit_square) {
    Polygon p;
    p.vertices = {{0, 0}, {1, 0}, {1, 1}, {0, 1}};
    ASSERT_NEAR(polygon_signed_area2(p), 2.0f, 1e-6f);
}

TEST(polygon_signed_area2_degenerate_collinear) {
    Polygon p;
    p.vertices = {{0, 0}, {1, 0}, {2, 0}};
    ASSERT_NEAR(polygon_signed_area2(p), 0.0f, 1e-6f);
}

// --- polygon_effective_corner_radius ---

TEST(polygon_corner_radius_default_only) {
    Polygon p;
    p.vertices = {{0, 0}, {1, 0}, {0, 1}};
    p.corner_radius = 0.5f;
    ASSERT_NEAR(polygon_effective_corner_radius(p, 0), 0.5f, 1e-6f);
    ASSERT_NEAR(polygon_effective_corner_radius(p, 1), 0.5f, 1e-6f);
    ASSERT_NEAR(polygon_effective_corner_radius(p, 2), 0.5f, 1e-6f);
}

TEST(polygon_corner_radius_per_vertex) {
    Polygon p;
    p.vertices = {{0, 0}, {1, 0}, {0, 1}};
    p.corner_radius = 0.5f;
    p.corner_radii = {0.1f, 0.2f, 0.3f};
    ASSERT_NEAR(polygon_effective_corner_radius(p, 0), 0.1f, 1e-6f);
    ASSERT_NEAR(polygon_effective_corner_radius(p, 1), 0.2f, 1e-6f);
    ASSERT_NEAR(polygon_effective_corner_radius(p, 2), 0.3f, 1e-6f);
}

TEST(polygon_corner_radius_size_mismatch_fallback) {
    Polygon p;
    p.vertices = {{0, 0}, {1, 0}, {0, 1}};
    p.corner_radius = 0.5f;
    p.corner_radii = {0.1f, 0.2f};  // wrong size
    ASSERT_NEAR(polygon_effective_corner_radius(p, 0), 0.5f, 1e-6f);
}

// --- polygon_effective_join_mode ---

TEST(polygon_join_mode_default_auto) {
    Polygon p;
    p.vertices = {{0, 0}, {1, 0}, {0, 1}};
    ASSERT_EQ(polygon_effective_join_mode(p, 0), PolygonJoinMode::Auto);
}

TEST(polygon_join_mode_per_vertex) {
    Polygon p;
    p.vertices = {{0, 0}, {1, 0}, {0, 1}};
    p.join_modes = {PolygonJoinMode::Sharp, PolygonJoinMode::Smooth, PolygonJoinMode::Auto};
    ASSERT_EQ(polygon_effective_join_mode(p, 0), PolygonJoinMode::Sharp);
    ASSERT_EQ(polygon_effective_join_mode(p, 1), PolygonJoinMode::Smooth);
    ASSERT_EQ(polygon_effective_join_mode(p, 2), PolygonJoinMode::Auto);
}

TEST(polygon_join_mode_size_mismatch) {
    Polygon p;
    p.vertices = {{0, 0}, {1, 0}, {0, 1}};
    p.join_modes = {PolygonJoinMode::Sharp};  // wrong size
    ASSERT_EQ(polygon_effective_join_mode(p, 0), PolygonJoinMode::Auto);
}

// --- Intersection: Circle ---

TEST(intersect_circle_direct_hit) {
    MaterialMap materials = {{"mat", Material{}}};
    Circle circle{.id = "c", .center = {0, 0}, .radius = 1.0f, .material_id = "mat"};
    Ray ray{{-2, 0}, {1, 0}};  // from left, heading right

    auto hit = intersect(ray, circle, materials);
    ASSERT_TRUE(hit.has_value());
    ASSERT_NEAR(hit->t, 1.0f, 1e-4f);          // hits at x=-1
    ASSERT_NEAR(hit->point.x, -1.0f, 1e-4f);
    ASSERT_NEAR(hit->point.y, 0.0f, 1e-4f);
    ASSERT_NEAR(hit->normal.x, -1.0f, 1e-4f);  // outward normal
    ASSERT_NEAR(hit->normal.y, 0.0f, 1e-4f);
}

TEST(intersect_circle_miss) {
    MaterialMap materials = {{"mat", Material{}}};
    Circle circle{.id = "c", .center = {0, 0}, .radius = 1.0f, .material_id = "mat"};
    Ray ray{{-2, 2}, {1, 0}};  // passes above

    auto hit = intersect(ray, circle, materials);
    ASSERT_FALSE(hit.has_value());
}

TEST(intersect_circle_from_inside) {
    MaterialMap materials = {{"mat", Material{}}};
    Circle circle{.id = "c", .center = {0, 0}, .radius = 1.0f, .material_id = "mat"};
    Ray ray{{0, 0}, {1, 0}};  // from center, heading right

    auto hit = intersect(ray, circle, materials);
    ASSERT_TRUE(hit.has_value());
    ASSERT_NEAR(hit->point.x, 1.0f, 1e-4f);  // far side
}

// --- Intersection: Segment ---

TEST(intersect_segment_perpendicular) {
    MaterialMap materials = {{"mat", Material{}}};
    Segment seg{.id = "s", .a = {0, -1}, .b = {0, 1}, .material_id = "mat"};
    Ray ray{{-1, 0}, {1, 0}};

    auto hit = intersect(ray, seg, materials);
    ASSERT_TRUE(hit.has_value());
    ASSERT_NEAR(hit->t, 1.0f, 1e-4f);
    ASSERT_NEAR(hit->point.x, 0.0f, 1e-4f);
    ASSERT_NEAR(hit->point.y, 0.0f, 1e-4f);
}

TEST(intersect_segment_parallel_miss) {
    MaterialMap materials = {{"mat", Material{}}};
    Segment seg{.id = "s", .a = {0, 0}, .b = {1, 0}, .material_id = "mat"};
    Ray ray{{0, 1}, {1, 0}};  // parallel, above

    auto hit = intersect(ray, seg, materials);
    ASSERT_FALSE(hit.has_value());
}

TEST(intersect_segment_backward_miss) {
    MaterialMap materials = {{"mat", Material{}}};
    Segment seg{.id = "s", .a = {0, -1}, .b = {0, 1}, .material_id = "mat"};
    Ray ray{{1, 0}, {1, 0}};  // pointing away

    auto hit = intersect(ray, seg, materials);
    ASSERT_FALSE(hit.has_value());
}

// --- Intersection: Arc ---

TEST(intersect_arc_hit_within_sweep) {
    MaterialMap materials = {{"mat", Material{}}};
    Arc arc{.id = "a", .center = {0, 0}, .radius = 1.0f,
            .angle_start = PI / 2.0f, .sweep = PI, .material_id = "mat"};
    Ray ray{{-2, 0}, {1, 0}};

    auto hit = intersect(ray, arc, materials);
    ASSERT_TRUE(hit.has_value());
    ASSERT_NEAR(hit->point.x, -1.0f, 1e-4f);
}

TEST(intersect_arc_miss_outside_sweep) {
    MaterialMap materials = {{"mat", Material{}}};
    Arc arc{.id = "a", .center = {0, 0}, .radius = 1.0f,
            .angle_start = PI / 4.0f, .sweep = PI / 2.0f, .material_id = "mat"};
    Ray ray{{-2, 0}, {1, 0}};

    auto hit = intersect(ray, arc, materials);
    ASSERT_FALSE(hit.has_value());
}
