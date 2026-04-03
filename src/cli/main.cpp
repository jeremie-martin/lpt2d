#include "export.h"
#include "headless.h"
#include "renderer.h"
#include "scenes.h"
#include "serialize.h"

#include <algorithm>
#include <chrono>
#include <cstdio>
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
              << "  --tonemap <name>         none|reinhard|reinhardx|aces|log (default: aces)\n"
              << "  --white-point <float>    White point for reinhardx/log (default: 1)\n"
              << "  --normalize <mode>       max|rays|fixed|off (default: max)\n"
              << "  --normalize-ref <float>  Fixed divisor (for --normalize fixed)\n"
              << "  --normalize-pct <float>  Percentile for max mode (default: 1.0, use 0.99 for P99)\n"
              << "  --stream                 Streaming mode: read JSON scenes from stdin, write raw RGB to stdout\n"
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
    if (!s.shapes.empty() || !s.lights.empty() || !s.groups.empty()) return s;
    std::cerr << "Unknown scene: " << arg << "\n";
    std::cerr << "Available: ";
    for (auto& entry : get_builtin_scenes())
        std::cerr << entry.name << " ";
    std::cerr << "\n";
    std::exit(1);
}

static int run_stream(int width, int height, int64_t default_rays,
                      TraceConfig default_tcfg, PostProcess default_pp) {
    HeadlessGL gl;
    if (!gl.init()) return 1;

    Renderer renderer;
    if (!renderer.init(width, height)) return 1;

    const size_t frame_bytes = (size_t)width * height * 3;
    std::vector<uint8_t> pixels;
    std::vector<uint8_t> black(frame_bytes, 0);

    // Ensure stdout is fully buffered for binary output
    std::setvbuf(stdout, nullptr, _IOFBF, frame_bytes);

    std::string line;
    int frame = 0;
    while (std::getline(std::cin, line)) {
        auto t0 = std::chrono::steady_clock::now();

        if (line.empty()) {
            std::cerr << "frame " << frame << ": empty line, emitting black frame\n";
            std::fwrite(black.data(), 1, frame_bytes, stdout);
            std::fflush(stdout);
            ++frame;
            continue;
        }

        Scene scene = load_scene_json_string(line);

        // Parse per-frame render overrides
        FrameOverrides fo = parse_frame_overrides(line);

        int64_t rays = fo.rays.value_or(default_rays);
        TraceConfig tcfg = default_tcfg;
        if (fo.batch) tcfg.batch_size = *fo.batch;
        if (fo.depth) tcfg.max_depth = *fo.depth;

        PostProcess pp = default_pp;
        if (fo.exposure) pp.exposure = *fo.exposure;
        if (fo.contrast) pp.contrast = *fo.contrast;
        if (fo.gamma) pp.gamma = *fo.gamma;
        if (fo.white_point) pp.white_point = *fo.white_point;
        if (fo.tonemap) pp.tone_map = *fo.tonemap;
        if (fo.normalize.has_value()) pp.normalize = *fo.normalize;
        if (fo.normalize_ref.has_value()) pp.normalize_ref = *fo.normalize_ref;
        if (fo.normalize_pct.has_value()) pp.normalize_pct = *fo.normalize_pct;

        Bounds bounds;
        if (fo.bounds) {
            bounds = *fo.bounds;
        } else if (scene.shapes.empty() && scene.lights.empty() && scene.groups.empty()) {
            bounds = {{-1, -1}, {1, 1}};
        } else {
            bounds = compute_bounds(scene);
        }
        renderer.upload_scene(scene, bounds);
        renderer.clear();

        // Trace rays in batched dispatches (skip if no lights)
        if (renderer.num_lights() > 0) {
            int64_t num_batches = (rays + tcfg.batch_size - 1) / tcfg.batch_size;
            const int dispatches_per_draw = 4;
            int64_t b = 0;
            while (b < num_batches) {
                int n = std::min((int64_t)dispatches_per_draw, num_batches - b);
                renderer.trace_and_draw_multi(tcfg, n);
                b += n;
            }
        }

        // Read pixels and write raw RGB to stdout
        renderer.read_pixels(pixels, pp);
        std::fwrite(pixels.data(), 1, frame_bytes, stdout);
        std::fflush(stdout);

        auto t1 = std::chrono::steady_clock::now();
        auto ms = std::chrono::duration_cast<std::chrono::milliseconds>(t1 - t0).count();
        std::cerr << "frame " << frame << ": {\"rays\": " << rays
                  << ", \"time_ms\": " << ms
                  << ", \"max_hdr\": " << renderer.last_max()
                  << ", \"total_rays\": " << renderer.total_rays() << "}\n";
        ++frame;
    }

    renderer.shutdown();
    return 0;
}

int main(int argc, char** argv) {
    std::string scene_name = "three_spheres";
    std::string output = "output.png";
    int width = 1920, height = 1080;
    int64_t total_rays = 10'000'000;
    TraceConfig tcfg;
    PostProcess pp;
    bool stream_mode = false;

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
        else if (std::strcmp(argv[i], "--white-point") == 0 && i + 1 < argc)
            pp.white_point = std::atof(argv[++i]);
        else if (std::strcmp(argv[i], "--tonemap") == 0 && i + 1 < argc) {
            std::string tm = argv[++i];
            if (tm == "none") pp.tone_map = ToneMap::None;
            else if (tm == "reinhard") pp.tone_map = ToneMap::Reinhard;
            else if (tm == "reinhardx" || tm == "reinhard_ext" || tm == "reinhard_extended")
                pp.tone_map = ToneMap::ReinhardExtended;
            else if (tm == "aces") pp.tone_map = ToneMap::ACES;
            else if (tm == "log") pp.tone_map = ToneMap::Logarithmic;
        } else if (std::strcmp(argv[i], "--normalize") == 0 && i + 1 < argc) {
            std::string m = argv[++i];
            if (m == "max") pp.normalize = NormalizeMode::Max;
            else if (m == "rays") pp.normalize = NormalizeMode::Rays;
            else if (m == "fixed") pp.normalize = NormalizeMode::Fixed;
            else if (m == "off") pp.normalize = NormalizeMode::Off;
        } else if (std::strcmp(argv[i], "--normalize-ref") == 0 && i + 1 < argc) {
            pp.normalize_ref = std::atof(argv[++i]);
        } else if (std::strcmp(argv[i], "--normalize-pct") == 0 && i + 1 < argc) {
            pp.normalize_pct = std::clamp(std::atof(argv[++i]), 0.0, 1.0);
        } else if (std::strcmp(argv[i], "--stream") == 0) {
            stream_mode = true;
        } else if (std::strcmp(argv[i], "--help") == 0 || std::strcmp(argv[i], "-h") == 0) {
            print_usage();
            return 0;
        } else {
            std::cerr << "Unknown option: " << argv[i] << "\n";
            print_usage();
            return 1;
        }
    }

    if (stream_mode)
        return run_stream(width, height, total_rays, tcfg, pp);

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
