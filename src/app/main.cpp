#include "app.h"
#include "scenes.h"

#include <cstdlib>
#include <cstring>
#include <iostream>
#include <string>
#include <vector>

int main(int argc, char** argv) {
    std::string scene_name = "three_spheres";
    int width = 1280, height = 720;
    bool scene_arg_set = false;

    for (int i = 1; i < argc; ++i) {
        if (std::strcmp(argv[i], "--scene") == 0 && i + 1 < argc) {
            scene_name = argv[++i];
            scene_arg_set = true;
        } else if (std::strcmp(argv[i], "--width") == 0 && i + 1 < argc)
            width = std::atoi(argv[++i]);
        else if (std::strcmp(argv[i], "--height") == 0 && i + 1 < argc)
            height = std::atoi(argv[++i]);
        else if (std::strcmp(argv[i], "--help") == 0 || std::strcmp(argv[i], "-h") == 0) {
            std::cerr << "Usage: lpt2d [scene-name-or-path] [--scene <name-or-path>] [--width <int>] [--height <int>]\n"
                      << "\nScenes: ";
            for (const auto& entry : get_builtin_scenes())
                std::cerr << entry.name << " ";
            std::cerr << "\n";
            return 0;
        } else if (argv[i][0] != '-' && !scene_arg_set) {
            scene_name = argv[i];
            scene_arg_set = true;
        } else {
            std::cerr << "Unknown option: " << argv[i] << "\n";
            return 1;
        }
    }

    App app;
    AppConfig config;
    config.width = width;
    config.height = height;
    config.initial_scene = scene_name;
    return app.run(config);
}
