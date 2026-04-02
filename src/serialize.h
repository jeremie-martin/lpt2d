#pragma once

#include "scene.h"

#include <string>

// Save scene to JSON file. Returns true on success.
bool save_scene_json(const Scene& scene, const std::string& path);

// Load scene from JSON file. Returns empty scene on failure.
Scene load_scene_json(const std::string& path);
