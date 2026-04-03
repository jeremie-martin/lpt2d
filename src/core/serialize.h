#pragma once

#include "scene.h"

#include <optional>
#include <string>
#include <string_view>

// Save scene to JSON file. Returns true on success.
bool save_scene_json(const Scene& scene, const std::string& path);

// Load scene from JSON file. Returns empty scene on failure.
Scene load_scene_json(const std::string& path);

// Parse scene from a JSON string. Returns empty scene on failure.
Scene load_scene_json_string(std::string_view json_content);

// Per-frame render overrides for --stream mode.
// Fields set to std::nullopt use session defaults.
struct FrameOverrides {
    std::optional<int64_t> rays;
    std::optional<int> batch, depth;
    std::optional<float> exposure, contrast, gamma;
    std::optional<ToneMap> tonemap;
    std::optional<Bounds> bounds; // fixed camera
};

// Extract optional "render" overrides from a scene JSON string.
FrameOverrides parse_frame_overrides(std::string_view json);
