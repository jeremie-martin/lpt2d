#include "export.h"
#include "headless.h"
#include "renderer.h"
#include "scenes.h"

#include <cstring>
#include <iostream>
#include <string>
#include <vector>

static void print_usage(const std::vector<SceneFactory>& scenes) {
    std::cerr << "Usage: lpt2d-cli [options]\n"
              << "  --scene <name>           Scene name (default: three_spheres)\n"
              << "  --output <path>          Output PNG (default: output.png)\n"
              << "  --width <int>            Width (default: 1920)\n"
              << "  --height <int>           Height (default: 1080)\n"
              << "  --rays <int>             Total rays (default: 10000000)\n"
              << "  --batch <int>            Rays per batch (default: 200000)\n"
              << "  --depth <int>            Max ray depth (default: 12)\n"
              << "  --exposure <float>       Exposure in stops (default: 2)\n"
              << "  --contrast <float>       Contrast (default: 1)\n"
              << "  --gamma <float>          Gamma (default: 2.2)\n"
              << "  --tonemap <name>         none|reinhard|aces|log (default: aces)\n"
              << "\nScenes: ";
    for (const auto& [name, _] : scenes)
        std::cerr << name << " ";
    std::cerr << "\n";
}

static Scene find_scene(const std::vector<SceneFactory>& scenes, const std::string& name) {
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
    auto all_scenes = get_all_scenes();

    std::string scene_name = "three_spheres";
    std::string output = "output.png";
    int width = 1920, height = 1080;
    int total_rays = 10'000'000;
    TraceConfig tcfg;
    PostProcess pp;

    for (int i = 1; i < argc; ++i) {
        if (std::strcmp(argv[i], "--scene") == 0 && i + 1 < argc)
            scene_name = argv[++i];
        else if (std::strcmp(argv[i], "--output") == 0 && i + 1 < argc)
            output = argv[++i];
        else if (std::strcmp(argv[i], "--width") == 0 && i + 1 < argc)
            width = std::atoi(argv[++i]);
        else if (std::strcmp(argv[i], "--height") == 0 && i + 1 < argc)
            height = std::atoi(argv[++i]);
        else if (std::strcmp(argv[i], "--rays") == 0 && i + 1 < argc)
            total_rays = std::atoi(argv[++i]);
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
            print_usage(all_scenes);
            return 0;
        } else {
            std::cerr << "Unknown option: " << argv[i] << "\n";
            print_usage(all_scenes);
            return 1;
        }
    }

    HeadlessGL gl;
    if (!gl.init())
        return 1;

    Renderer renderer;
    if (!renderer.init(width, height))
        return 1;

    Scene scene = find_scene(all_scenes, scene_name);
    Bounds bounds = compute_bounds(scene);
    renderer.upload_scene(scene, bounds);
    renderer.clear();

    int num_batches = (total_rays + tcfg.batch_size - 1) / tcfg.batch_size;
    for (int i = 0; i < num_batches; ++i) {
        renderer.trace_and_draw(tcfg);

        int done = (i + 1) * tcfg.batch_size;
        if (done > total_rays) done = total_rays;
        std::cerr << "\r" << done << "/" << total_rays << " rays"
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
