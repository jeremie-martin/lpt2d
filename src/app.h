#pragma once

#include "scene.h"

#include <functional>
#include <string>
#include <vector>

struct AppConfig {
    int width = 1280;
    int height = 720;
    std::string initial_scene;
};

class App {
public:
    using SceneFactory = std::pair<std::string, std::function<Scene()>>;

    int run(const std::vector<SceneFactory>& scenes, const AppConfig& config);
};
