#include "export.h"
#include "headless.h"
#include "renderer.h"
#include "scenes.h"
#include "serialize.h"

#include <cstdlib>
#include <cstring>
#include <iostream>
#include <string>

static void print_usage() {
    std::cerr << "Usage: lpt2d-cli [options]\n"
              << "  --scene <name-or-path>   Built-in name or path to .json file (default: three_spheres)\n"
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
              << "\nBuilt-in scenes: ";
    for (const auto& entry : get_builtin_scenes())
        std::cerr << entry.name << " ";
    std::cerr << "\n";
}

static Scene resolve_scene(const std::string& arg) {
    // Try built-in name first
    if (auto s = find_builtin_scene(arg)) return *s;
    // Then try as a file path
    Scene s = load_scene_json(arg);
    if (!s.shapes.empty() || !s.lights.empty()) return s;
    std::cerr << "Unknown scene: " << arg << "\n";
    std::cerr << "Available: ";
    for (auto& entry : get_builtin_scenes())
        std::cerr << entry.name << " ";
    std::cerr << "\n";
    std::exit(1);
}

int main(int argc, char** argv) {
    std::string scene_name = "three_spheres";
    std::string output = "output.png";
    int width = 1920, height = 1080;
    int64_t total_rays = 10'000'000;
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
            total_rays = std::strtoll(argv[++i], nullptr, 10);
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

    HeadlessGL gl;
    if (!gl.init())
        return 1;

    Renderer renderer;
    if (!renderer.init(width, height))
        return 1;

    Scene scene = resolve_scene(scene_name);
    Bounds bounds = compute_bounds(scene);
    renderer.upload_scene(scene, bounds);
    renderer.clear();

    int64_t num_batches = (total_rays + tcfg.batch_size - 1) / tcfg.batch_size;

    // Multi-batch: group N compute dispatches per draw call to amortize draw overhead
    const int dispatches_per_draw = 4;
    int64_t i = 0;
    while (i < num_batches) {
        int n = std::min((int64_t)dispatches_per_draw, num_batches - i);
        renderer.trace_and_draw_multi(tcfg, n);
        i += n;

        int64_t done = i * tcfg.batch_size;
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
