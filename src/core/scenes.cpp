#include "scenes.h"
#include "serialize.h"

#include <algorithm>
#include <filesystem>
#include <iostream>

namespace fs = std::filesystem;

const std::vector<BuiltinScene>& get_builtin_scenes() {
    static const auto list = [] {
        std::vector<BuiltinScene> scenes;
        fs::path dir{LPT2D_SCENES_DIR};
        if (!fs::is_directory(dir)) {
            std::cerr << "Scenes directory not found: " << dir << "\n";
            return scenes;
        }
        for (auto& entry : fs::directory_iterator(dir)) {
            if (entry.path().extension() == ".json") {
                scenes.push_back({entry.path().stem().string(), entry.path().string()});
            }
        }
        std::sort(scenes.begin(), scenes.end(),
            [](const auto& a, const auto& b) { return a.name < b.name; });
        return scenes;
    }();
    return list;
}

Shot load_builtin_scene(const BuiltinScene& entry) {
    return load_shot_json(entry.path);
}

std::optional<Shot> find_builtin_scene(const std::string& name) {
    for (auto& entry : get_builtin_scenes()) {
        if (entry.name == name)
            return load_builtin_scene(entry);
    }
    return std::nullopt;
}
