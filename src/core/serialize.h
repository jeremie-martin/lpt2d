#pragma once

#include "scene.h"

#include <optional>
#include <string>
#include <string_view>

// Save shot to JSON file (current v6 authored format). Returns true on success.
bool save_shot_json(const Shot& shot, const std::string& path);

// Try to load a shot from a JSON file in the current authored format.
std::optional<Shot> try_load_shot_json(const std::string& path, std::string* error = nullptr);

// Try to parse a shot from a JSON string in the current authored format.
std::optional<Shot> try_load_shot_json_string(std::string_view json_content, std::string* error = nullptr);

// Load shot from JSON file. Returns default shot on failure.
Shot load_shot_json(const std::string& path);

// Parse shot from a JSON string. Returns default shot on failure.
Shot load_shot_json_string(std::string_view json_content);
