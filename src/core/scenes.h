#pragma once

#include "scene.h"

#include <optional>
#include <string>
#include <vector>

struct BuiltinScene {
    std::string name;
    std::string path;
};

// All built-in scenes discovered from the scenes directory.
const std::vector<BuiltinScene>& get_builtin_scenes();

// Load a scene from its file path.
Scene load_builtin_scene(const BuiltinScene& entry);

// Find and load a built-in scene by name. Returns nullopt if not found.
std::optional<Scene> find_builtin_scene(const std::string& name);
