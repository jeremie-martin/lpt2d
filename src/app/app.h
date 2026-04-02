#pragma once

#include "scene.h"

#include <string>

struct AppConfig {
    int width = 1280;
    int height = 720;
    std::string initial_scene;
};

class App {
public:
    int run(const AppConfig& config);
};
