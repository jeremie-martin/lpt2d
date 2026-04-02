#include "app.h"
#include "export.h"
#include "headless.h"
#include "renderer.h"
#include "scenes.h"
#include "tracer.h"

#include <cstring>
#include <iostream>
#include <string>
#include <vector>

static void print_usage() {
    std::cerr << "Usage: lpt2d [options]\n"
              << "  --headless           Run without window\n"
              << "  --scene <name>       Scene name (three_spheres, prism, diamond, lens)\n"
              << "  --output <path>      Output PNG path (headless only, default: output.png)\n"
              << "  --width <int>        Width (default: 1280)\n"
              << "  --height <int>       Height (default: 720)\n"
              << "  --batches <int>      Number of batches (headless, default: 300)\n"
              << "  --batch <int>        Rays per batch (default: 30000)\n"
              << "  --depth <int>        Max ray depth (default: 12)\n";
}

static std::vector<App::SceneFactory> get_scenes() {
    return {
        {"three_spheres", scene_three_spheres},
        {"prism", scene_prism},
        {"diamond", scene_diamond},
        {"lens", scene_lens},
    };
}

static Scene find_scene(const std::vector<App::SceneFactory>& scenes, const std::string& name) {
    for (const auto& [n, f] : scenes) {
        if (n == name)
            return f();
    }
    std::cerr << "Unknown scene: " << name << "\n";
    std::cerr << "Available: ";
    for (const auto& [n, _] : scenes)
        std::cerr << n << " ";
    std::cerr << "\n";
    std::exit(1);
}

int main(int argc, char** argv) {
    bool headless = false;
    std::string scene_name = "three_spheres";
    std::string output = "output.png";
    int width = 1280, height = 720;
    int batches = 300;
    Tracer::Config tcfg;
    PostProcess pp;
    pp.tone_map = ToneMap::ACES;

    for (int i = 1; i < argc; ++i) {
        if (std::strcmp(argv[i], "--headless") == 0)
            headless = true;
        else if (std::strcmp(argv[i], "--scene") == 0 && i + 1 < argc)
            scene_name = argv[++i];
        else if (std::strcmp(argv[i], "--output") == 0 && i + 1 < argc)
            output = argv[++i];
        else if (std::strcmp(argv[i], "--width") == 0 && i + 1 < argc)
            width = std::atoi(argv[++i]);
        else if (std::strcmp(argv[i], "--height") == 0 && i + 1 < argc)
            height = std::atoi(argv[++i]);
        else if (std::strcmp(argv[i], "--batches") == 0 && i + 1 < argc)
            batches = std::atoi(argv[++i]);
        else if (std::strcmp(argv[i], "--batch") == 0 && i + 1 < argc)
            tcfg.batch_size = std::atoi(argv[++i]);
        else if (std::strcmp(argv[i], "--depth") == 0 && i + 1 < argc)
            tcfg.max_depth = std::atoi(argv[++i]);
        else if (std::strcmp(argv[i], "--exposure") == 0 && i + 1 < argc)
            pp.exposure = std::atof(argv[++i]);
        else if (std::strcmp(argv[i], "--gamma") == 0 && i + 1 < argc)
            pp.gamma = std::atof(argv[++i]);
        else if (std::strcmp(argv[i], "--contrast") == 0 && i + 1 < argc)
            pp.contrast = std::atof(argv[++i]);
        else if (std::strcmp(argv[i], "--tonemap") == 0 && i + 1 < argc) {
            std::string tm = argv[++i];
            if (tm == "none") pp.tone_map = ToneMap::None;
            else if (tm == "reinhard") pp.tone_map = ToneMap::Reinhard;
            else if (tm == "aces") pp.tone_map = ToneMap::ACES;
            else if (tm == "log") pp.tone_map = ToneMap::Logarithmic;
        } else if (std::strcmp(argv[i], "--help") == 0 || std::strcmp(argv[i], "-h") == 0) {
            print_usage();
            return 0;
        } else {
            std::cerr << "Unknown option: " << argv[i] << "\n";
            print_usage();
            return 1;
        }
    }

    auto all_scenes = get_scenes();

    if (headless) {
        HeadlessGL gl;
        if (!gl.init())
            return 1;

        Renderer renderer;
        if (!renderer.init(width, height))
            return 1;

        Scene scene = find_scene(all_scenes, scene_name);
        Bounds bounds = compute_bounds(scene);
        Tracer tracer;

        renderer.clear();

        for (int i = 0; i < batches; ++i) {
            auto segments = tracer.trace_batch(scene, tcfg);

            Vec2 size = bounds.max - bounds.min;
            float scale_x = (float)width / size.x;
            float scale_y = (float)height / size.y;
            float scale = std::min(scale_x, scale_y);
            Vec2 offset = {(width - size.x * scale) * 0.5f, (height - size.y * scale) * 0.5f};

            for (auto& s : segments) {
                s.x0 = (s.x0 - bounds.min.x) * scale + offset.x;
                s.y0 = (s.y0 - bounds.min.y) * scale + offset.y;
                s.x1 = (s.x1 - bounds.min.x) * scale + offset.x;
                s.y1 = (s.y1 - bounds.min.y) * scale + offset.y;
            }

            renderer.draw_lines(segments);
            renderer.flush();

            std::cerr << "\r" << (i + 1) << "/" << batches << " batches (" << tracer.total_rays() << " rays)"
                      << std::flush;
        }
        std::cerr << "\n";

        std::vector<uint8_t> pixels;
        renderer.read_pixels(pixels, pp);

        if (export_png(output, pixels.data(), width, height)) {
            std::cerr << "Saved: " << output << "\n";
        } else {
            std::cerr << "Failed to save: " << output << "\n";
            return 1;
        }

        renderer.shutdown();
        return 0;
    }

    // Windowed mode
    App app;
    AppConfig acfg;
    acfg.width = width;
    acfg.height = height;
    acfg.initial_scene = scene_name;
    return app.run(all_scenes, acfg);
}
