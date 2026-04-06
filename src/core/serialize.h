#pragma once

#include "scene.h"

#include <array>
#include <optional>
#include <string>
#include <string_view>

// Save shot to JSON file (current v5 authored format). Returns true on success.
bool save_shot_json(const Shot& shot, const std::string& path);

// Try to load a shot from a JSON file in the current authored format.
std::optional<Shot> try_load_shot_json(const std::string& path, std::string* error = nullptr);

// Try to parse a shot from a JSON string in the current authored format.
std::optional<Shot> try_load_shot_json_string(std::string_view json_content, std::string* error = nullptr);

// Try to parse a stream frame JSON string. Supports either a full explicit
// authored shot or the sparse stream wire format used by the Python renderer.
std::optional<Shot> try_load_stream_frame_json_string(std::string_view json_content, std::string* error = nullptr);

// Load shot from JSON file. Returns default shot on failure.
Shot load_shot_json(const std::string& path);

// Parse shot from a JSON string. Returns default shot on failure.
Shot load_shot_json_string(std::string_view json_content);

// Sparse render overrides — fields set to std::nullopt use session defaults.
// Used by CLI args, per-frame streaming directives, and GUI session overrides.
struct RenderOverrides {
    // Canvas
    std::optional<int> width, height;

    // Look
    std::optional<float> exposure, contrast, gamma, white_point;
    std::optional<ToneMap> tonemap;
    std::optional<NormalizeMode> normalize;
    std::optional<float> normalize_ref, normalize_pct;
    std::optional<float> ambient, opacity, saturation;
    std::optional<float> vignette, vignette_radius;
    std::optional<std::array<float, 3>> background;

    // Trace
    std::optional<int64_t> rays;
    std::optional<int> batch, depth;
    std::optional<float> intensity;

    // Camera
    std::optional<Bounds> bounds;

    void apply_to(Look& look) const;
    void apply_to(PostProcess& pp) const;
    void apply_to(TraceDefaults& trace) const;
    void apply_to(TraceConfig& tcfg) const;
    void apply_to(Canvas& canvas) const;
    void apply_to(Shot& shot) const;
};

struct StreamFrameDirectives {
    bool has_name = false;
    bool has_camera = false;
    bool has_canvas = false;
    bool has_look = false;
    bool has_trace = false;
    RenderOverrides render;
};

// Extract optional "render" overrides from a shot JSON string.
RenderOverrides parse_frame_overrides(std::string_view json);

// Extract authored-shot block presence plus nested "render" overrides from a
// stream frame JSON string.
StreamFrameDirectives parse_stream_frame_directives(std::string_view json);
