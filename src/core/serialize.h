#pragma once

#include "scene.h"

#include <array>
#include <optional>
#include <string>
#include <string_view>

// Save shot to JSON file (v5 authored format). Returns true on success.
bool save_shot_json(const Shot& shot, const std::string& path);

// Load shot from JSON file. Returns default shot on failure.
Shot load_shot_json(const std::string& path);

// Parse shot from a JSON string. Returns default shot on failure.
Shot load_shot_json_string(std::string_view json_content);

// Per-frame render overrides for --stream mode.
// Fields set to std::nullopt use session defaults.
struct FrameOverrides {
    std::optional<int64_t> rays;
    std::optional<int> batch, depth;
    std::optional<float> exposure, contrast, gamma, white_point;
    std::optional<ToneMap> tonemap;
    std::optional<Bounds> bounds; // fixed camera
    std::optional<NormalizeMode> normalize;
    std::optional<float> normalize_ref;
    std::optional<float> normalize_pct;
    std::optional<float> ambient;
    std::optional<std::array<float, 3>> background;
    std::optional<float> opacity;
    std::optional<float> intensity;
};

// Extract optional "render" overrides from a shot JSON string.
FrameOverrides parse_frame_overrides(std::string_view json);
