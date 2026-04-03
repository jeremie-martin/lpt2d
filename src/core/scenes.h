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

// Load a shot from its file path.
Shot load_builtin_scene(const BuiltinScene& entry);

// Find and load a built-in shot by name. Returns nullopt if not found.
std::optional<Shot> find_builtin_scene(const std::string& name);
