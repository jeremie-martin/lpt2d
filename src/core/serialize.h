#pragma once

#include "scene.h"

#include <string>
#include <string_view>

// Save scene to JSON file. Returns true on success.
bool save_scene_json(const Scene& scene, const std::string& path);

// Load scene from JSON file. Returns empty scene on failure.
Scene load_scene_json(const std::string& path);

// Parse scene from a JSON string. Returns empty scene on failure.
Scene load_scene_json_string(std::string_view json_content);
