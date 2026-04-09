#include "test_harness.h"
#include "scene.h"
#include "serialize.h"

#include <cstdlib>
#include <filesystem>
#include <string>

// --- Scene validation ---

TEST(validate_empty_scene) {
    Scene scene;
    ASSERT_TRUE(validate_scene(scene));
}

TEST(validate_scene_with_one_shape) {
    Scene scene;
    scene.materials["mat"] = Material{};
    scene.shapes.push_back(Circle{.id = "c1", .center = {0, 0}, .radius = 1.0f, .material_id = "mat"});
    ASSERT_TRUE(validate_scene(scene));
}

TEST(validate_scene_unknown_material_id) {
    Scene scene;
    scene.materials["mat"] = Material{};
    scene.shapes.push_back(Circle{.id = "c1", .center = {0, 0}, .radius = 1.0f, .material_id = "missing"});
    std::string error;
    ASSERT_FALSE(validate_scene(scene, &error));
    ASSERT_TRUE(error.find("missing") != std::string::npos);
}

TEST(validate_scene_duplicate_shape_ids) {
    Scene scene;
    scene.materials["mat"] = Material{};
    scene.shapes.push_back(Circle{.id = "dup", .center = {0, 0}, .radius = 1.0f, .material_id = "mat"});
    scene.shapes.push_back(Circle{.id = "dup", .center = {1, 0}, .radius = 1.0f, .material_id = "mat"});
    std::string error;
    ASSERT_FALSE(validate_scene(scene, &error));
    ASSERT_TRUE(error.find("duplicate") != std::string::npos);
}

TEST(validate_scene_duplicate_id_across_shape_and_light) {
    Scene scene;
    scene.materials["mat"] = Material{};
    scene.shapes.push_back(Circle{.id = "shared", .center = {0, 0}, .radius = 1.0f, .material_id = "mat"});
    scene.lights.push_back(PointLight{.id = "shared", .position = {0, 0}});
    std::string error;
    ASSERT_FALSE(validate_scene(scene, &error));
    ASSERT_TRUE(error.find("duplicate") != std::string::npos);
}

TEST(validate_scene_duplicate_id_across_shape_and_group) {
    Scene scene;
    scene.materials["mat"] = Material{};
    scene.shapes.push_back(Circle{.id = "shared", .center = {0, 0}, .radius = 1.0f, .material_id = "mat"});
    scene.groups.push_back(Group{.id = "shared", .transform = {}, .shapes = {}, .lights = {}});
    std::string error;
    ASSERT_FALSE(validate_scene(scene, &error));
    ASSERT_TRUE(error.find("duplicate") != std::string::npos);
}

TEST(validate_scene_empty_material_id_on_shape) {
    Scene scene;
    scene.materials["mat"] = Material{};
    scene.shapes.push_back(Circle{.id = "c1", .center = {0, 0}, .radius = 1.0f, .material_id = ""});
    std::string error;
    ASSERT_FALSE(validate_scene(scene, &error));
    ASSERT_TRUE(error.find("material_id") != std::string::npos);
}

TEST(validate_scene_polygon_corner_radii_mismatch) {
    Scene scene;
    scene.materials["mat"] = Material{};
    Polygon p;
    p.id = "poly";
    p.vertices = {{0, 0}, {1, 0}, {0, 1}};
    p.material_id = "mat";
    p.corner_radii = {0.1f, 0.2f};  // 2 radii for 3 vertices
    scene.shapes.push_back(p);
    std::string error;
    ASSERT_FALSE(validate_scene(scene, &error));
}

TEST(validate_scene_polygon_join_modes_mismatch) {
    Scene scene;
    scene.materials["mat"] = Material{};
    Polygon p;
    p.id = "poly";
    p.vertices = {{0, 0}, {1, 0}, {0, 1}};
    p.material_id = "mat";
    p.join_modes = {PolygonJoinMode::Sharp};  // 1 mode for 3 vertices
    scene.shapes.push_back(p);
    std::string error;
    ASSERT_FALSE(validate_scene(scene, &error));
}

// --- JSON parsing ---

static constexpr const char* MINIMAL_SHOT_JSON = R"({
    "version": 11,
    "name": "test",
    "camera": {},
    "canvas": {"width": 100, "height": 100},
    "look": {
        "exposure": -5.0, "contrast": 1.0, "gamma": 2.0,
        "tonemap": "reinhardx", "white_point": 0.5,
        "normalize": "rays", "normalize_ref": 0.0, "normalize_pct": 1.0,
        "ambient": 0.0, "background": [0.0, 0.0, 0.0], "opacity": 1.0,
        "saturation": 1.0, "vignette": 0.0, "vignette_radius": 0.7,
        "temperature": 0.0, "highlights": 0.0, "shadows": 0.0,
        "hue_shift": 0.0, "grain": 0.0, "grain_seed": 0,
        "chromatic_aberration": 0.0
    },
    "trace": {
        "rays": 1000000, "batch": 100000, "depth": 12,
        "intensity": 1.0, "seed_mode": "deterministic"
    },
    "materials": {
        "default": {
            "ior": 1.0, "roughness": 0.0, "metallic": 0.0,
            "transmission": 0.0, "absorption": 0.0, "cauchy_b": 0.0,
            "albedo": 1.0, "emission": 0.0,
            "spectral_c0": 0.0, "spectral_c1": 0.0, "spectral_c2": 0.0,
            "fill": 0.0
        }
    },
    "shapes": [],
    "lights": [],
    "groups": []
})";

TEST(json_parse_minimal_shot) {
    std::string error;
    auto shot = try_load_shot_json_string(MINIMAL_SHOT_JSON, &error);
    REQUIRE_TRUE(shot.has_value());
    ASSERT_EQ(shot->name, std::string("test"));
    ASSERT_EQ(shot->canvas.width, 100);
    ASSERT_EQ(shot->canvas.height, 100);
}

TEST(json_parse_minimal_shot_look_fields) {
    std::string error;
    auto shot = try_load_shot_json_string(MINIMAL_SHOT_JSON, &error);
    REQUIRE_TRUE(shot.has_value());
    ASSERT_NEAR(shot->look.exposure, -5.0f, 1e-6f);
    ASSERT_EQ(shot->look.tonemap, ToneMap::ReinhardExtended);
    ASSERT_EQ(shot->look.normalize, NormalizeMode::Rays);
    ASSERT_NEAR(shot->look.gamma, 2.0f, 1e-6f);
}

TEST(json_parse_minimal_shot_trace_fields) {
    std::string error;
    auto shot = try_load_shot_json_string(MINIMAL_SHOT_JSON, &error);
    REQUIRE_TRUE(shot.has_value());
    ASSERT_EQ(shot->trace.rays, 1000000LL);
    ASSERT_EQ(shot->trace.batch, 100000);
    ASSERT_EQ(shot->trace.depth, 12);
    ASSERT_EQ(shot->trace.seed_mode, SeedMode::Deterministic);
}

TEST(json_parse_malformed) {
    std::string error;
    auto shot = try_load_shot_json_string("{not valid json", &error);
    ASSERT_FALSE(shot.has_value());
    ASSERT_FALSE(error.empty());
}

TEST(json_parse_wrong_version) {
    std::string error;
    auto shot = try_load_shot_json_string(R"({"version": 99})", &error);
    ASSERT_FALSE(shot.has_value());
    ASSERT_FALSE(error.empty());
}

TEST(json_parse_missing_version) {
    std::string error;
    auto shot = try_load_shot_json_string(R"({"name": "test"})", &error);
    ASSERT_FALSE(shot.has_value());
    ASSERT_FALSE(error.empty());
}

TEST(json_parse_unknown_key_rejected) {
    // The parser uses reject_unknown_keys, so an extra top-level key should fail
    std::string json = R"({
        "version": 11, "name": "test", "camera": {}, "bogus_key": 42,
        "canvas": {"width": 100, "height": 100},
        "look": {"exposure": -5.0, "contrast": 1.0, "gamma": 2.0,
            "tonemap": "reinhardx", "white_point": 0.5,
            "normalize": "rays", "normalize_ref": 0.0, "normalize_pct": 1.0,
            "ambient": 0.0, "background": [0.0, 0.0, 0.0], "opacity": 1.0,
            "saturation": 1.0, "vignette": 0.0, "vignette_radius": 0.7,
            "temperature": 0.0, "highlights": 0.0, "shadows": 0.0,
            "hue_shift": 0.0, "grain": 0.0, "grain_seed": 0,
            "chromatic_aberration": 0.0},
        "trace": {"rays": 1000000, "batch": 100000, "depth": 12,
            "intensity": 1.0, "seed_mode": "deterministic"},
        "materials": {}, "shapes": [], "lights": [], "groups": []
    })";
    std::string error;
    auto shot = try_load_shot_json_string(json, &error);
    ASSERT_FALSE(shot.has_value());
    ASSERT_TRUE(error.find("unknown") != std::string::npos);
}

TEST(json_parse_shot_with_circle) {
    std::string json = R"({
        "version": 11, "name": "with_circle",
        "camera": {"bounds": [-1, -1, 1, 1]},
        "canvas": {"width": 200, "height": 200},
        "look": {"exposure": -5.0, "contrast": 1.0, "gamma": 2.0,
            "tonemap": "reinhardx", "white_point": 0.5,
            "normalize": "rays", "normalize_ref": 0.0, "normalize_pct": 1.0,
            "ambient": 0.0, "background": [0.0, 0.0, 0.0], "opacity": 1.0,
            "saturation": 1.0, "vignette": 0.0, "vignette_radius": 0.7,
            "temperature": 0.0, "highlights": 0.0, "shadows": 0.0,
            "hue_shift": 0.0, "grain": 0.0, "grain_seed": 0,
            "chromatic_aberration": 0.0},
        "trace": {"rays": 1000000, "batch": 100000, "depth": 12,
            "intensity": 1.0, "seed_mode": "deterministic"},
        "materials": {"glass": {
            "ior": 1.5, "roughness": 0.0, "metallic": 0.0,
            "transmission": 1.0, "absorption": 0.0, "cauchy_b": 0.0,
            "albedo": 1.0, "emission": 0.0,
            "spectral_c0": 0.0, "spectral_c1": 0.0, "spectral_c2": 0.0,
            "fill": 0.0}},
        "shapes": [{"type": "circle", "id": "c1",
                     "center": [0.5, -0.3], "radius": 0.25,
                     "material_id": "glass"}],
        "lights": [], "groups": []
    })";
    std::string error;
    auto shot = try_load_shot_json_string(json, &error);
    REQUIRE_TRUE(shot.has_value());
    ASSERT_EQ(shot->name, std::string("with_circle"));
    ASSERT_EQ(shot->scene.shapes.size(), size_t(1));
    auto* circle = std::get_if<Circle>(&shot->scene.shapes[0]);
    REQUIRE_TRUE(circle != nullptr);
    ASSERT_NEAR(circle->center.x, 0.5f, 1e-6f);
    ASSERT_NEAR(circle->center.y, -0.3f, 1e-6f);
    ASSERT_NEAR(circle->radius, 0.25f, 1e-6f);
    ASSERT_EQ(circle->material_id, std::string("glass"));
}

TEST(json_roundtrip_default_shot) {
    Shot original;
    original.name = "roundtrip_test";
    original.canvas = {320, 240};

    auto path = std::filesystem::temp_directory_path() / "lpt2d_test_roundtrip_XXXXXX.json";
    std::string path_str = path.string();
    REQUIRE_TRUE(save_shot_json(original, path_str));

    std::string error;
    auto reloaded = try_load_shot_json(path_str, &error);
    std::filesystem::remove(path_str);
    REQUIRE_TRUE(reloaded.has_value());
    ASSERT_EQ(reloaded->name, std::string("roundtrip_test"));
    ASSERT_EQ(reloaded->canvas.width, 320);
    ASSERT_EQ(reloaded->canvas.height, 240);
    ASSERT_NEAR(reloaded->look.exposure, original.look.exposure, 1e-6f);
    ASSERT_EQ(reloaded->look.tonemap, original.look.tonemap);
}
