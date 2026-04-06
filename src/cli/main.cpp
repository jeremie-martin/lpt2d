#include "export.h"
#include "scene.h"
#include "scenes.h"
#include "serialize.h"
#include "session.h"

#include <stdint.h>
#include <algorithm>
#include <array>
#include <cstdlib>
#include <cstring>
#include <filesystem>
#include <iostream>
#include <optional>
#include <string>
#include <vector>

static void print_usage() {
    std::cerr << "Usage: lpt2d-cli [options]\n"
              << "  --scene <name-or-path>   Built-in name or path to .json file (default: three_spheres)\n"
              << "  --output <path>          Output PNG (default: output.png)\n"
              << "  --save-shot <path>       Save the resolved v5 shot JSON via the C++ serializer and exit\n"
              << "  --width <int>            Width (overrides shot canvas)\n"
              << "  --height <int>           Height (overrides shot canvas)\n"
              << "  --rays <int>             Total rays (overrides shot trace)\n"
              << "  --batch <int>            Rays per batch (overrides shot trace)\n"
              << "  --depth <int>            Max ray depth (overrides shot trace)\n"
              << "  --exposure <float>       Exposure in stops (overrides shot look)\n"
              << "  --contrast <float>       Contrast (overrides shot look)\n"
              << "  --gamma <float>          Gamma (overrides shot look)\n"
              << "  --tonemap <name>         none|reinhard|reinhardx|aces|log (overrides shot look)\n"
              << "  --white-point <float>    White point for reinhardx/log (overrides shot look)\n"
              << "  --normalize <mode>       max|rays|fixed|off (overrides shot look)\n"
              << "  --normalize-ref <float>  Fixed divisor (for --normalize fixed)\n"
              << "  --normalize-pct <float>  Percentile for max mode (default: 1.0, use 0.99 for P99)\n"
              << "  --ambient <float>        Constant fill light (overrides shot look)\n"
              << "  --background <r,g,b>     Background color, linear RGB 0-1 (overrides shot look)\n"
              << "  --opacity <float>        Global opacity 0-1 (overrides shot look)\n"
              << "  --intensity <float>      Trace intensity multiplier (overrides shot trace)\n"
              << "  --saturation <float>     Color saturation (1=normal, 0=grayscale, >1=boost)\n"
              << "  --vignette <float>       Radial edge darkening 0-1 (overrides shot look)\n"
              << "  --vignette-radius <float> Vignette falloff start (default: 0.7)\n"
              << "  --fast                   Half-precision FBO (RGBA16F) — ~3x faster, slight precision loss\n"
              << "\nBuilt-in scenes: ";
    for (const auto& entry : get_builtin_scenes())
        std::cerr << entry.name << " ";
    std::cerr << "\n";
}

static Shot resolve_shot(const std::string& arg) {
    namespace fs = std::filesystem;

    // Try built-in name first
    if (auto s = find_builtin_scene(arg)) return *s;

    const fs::path candidate{arg};
    const bool looks_like_path = candidate.has_extension()
        || arg.find('/') != std::string::npos
        || arg.find('\\') != std::string::npos;
    if (looks_like_path || fs::exists(candidate)) {
        std::string error;
        if (auto s = try_load_shot_json(arg, &error)) return *s;
        if (!error.empty())
            std::cerr << error << "\n";
        std::exit(1);
    }

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
    std::string save_shot_path;
    bool fast_mode = false;

    // Deferred overrides: parse flags first, apply to shot after loading.
    // Using lambdas to capture the override actions.
    struct {
        std::optional<int> width, height;
        std::optional<int64_t> rays;
        std::optional<int> batch, depth;
        std::optional<float> exposure, contrast, gamma, white_point;
        std::optional<ToneMap> tonemap;
        std::optional<NormalizeMode> normalize;
        std::optional<float> normalize_ref, normalize_pct;
        std::optional<float> ambient, opacity, saturation, intensity;
        std::optional<float> vignette, vignette_radius;
        std::optional<std::array<float, 3>> background;

        void apply_to(Shot& shot) const {
            if (width) shot.canvas.width = *width;
            if (height) shot.canvas.height = *height;
            if (rays) shot.trace.rays = *rays;
            if (batch) shot.trace.batch = *batch;
            if (depth) shot.trace.depth = *depth;
            if (intensity) shot.trace.intensity = *intensity;
            if (exposure) shot.look.exposure = *exposure;
            if (contrast) shot.look.contrast = *contrast;
            if (gamma) shot.look.gamma = *gamma;
            if (white_point) shot.look.white_point = *white_point;
            if (tonemap) shot.look.tone_map = *tonemap;
            if (normalize) shot.look.normalize = *normalize;
            if (normalize_ref) shot.look.normalize_ref = *normalize_ref;
            if (normalize_pct) shot.look.normalize_pct = *normalize_pct;
            if (ambient) shot.look.ambient = *ambient;
            if (opacity) shot.look.opacity = *opacity;
            if (saturation) shot.look.saturation = *saturation;
            if (vignette) shot.look.vignette = *vignette;
            if (vignette_radius) shot.look.vignette_radius = *vignette_radius;
            if (background) {
                shot.look.background[0] = (*background)[0];
                shot.look.background[1] = (*background)[1];
                shot.look.background[2] = (*background)[2];
            }
        }
    } overrides;

    for (int i = 1; i < argc; ++i) {
        if (std::strcmp(argv[i], "--scene") == 0 && i + 1 < argc)
            scene_name = argv[++i];
        else if (std::strcmp(argv[i], "--output") == 0 && i + 1 < argc)
            output = argv[++i];
        else if (std::strcmp(argv[i], "--save-shot") == 0 && i + 1 < argc)
            save_shot_path = argv[++i];
        else if (std::strcmp(argv[i], "--width") == 0 && i + 1 < argc)
            overrides.width = std::atoi(argv[++i]);
        else if (std::strcmp(argv[i], "--height") == 0 && i + 1 < argc)
            overrides.height = std::atoi(argv[++i]);
        else if (std::strcmp(argv[i], "--rays") == 0 && i + 1 < argc)
            overrides.rays = std::strtoll(argv[++i], nullptr, 10);
        else if (std::strcmp(argv[i], "--batch") == 0 && i + 1 < argc)
            overrides.batch = std::atoi(argv[++i]);
        else if (std::strcmp(argv[i], "--depth") == 0 && i + 1 < argc)
            overrides.depth = std::atoi(argv[++i]);
        else if (std::strcmp(argv[i], "--exposure") == 0 && i + 1 < argc)
            overrides.exposure = (float)std::atof(argv[++i]);
        else if (std::strcmp(argv[i], "--gamma") == 0 && i + 1 < argc)
            overrides.gamma = (float)std::atof(argv[++i]);
        else if (std::strcmp(argv[i], "--contrast") == 0 && i + 1 < argc)
            overrides.contrast = (float)std::atof(argv[++i]);
        else if (std::strcmp(argv[i], "--white-point") == 0 && i + 1 < argc)
            overrides.white_point = (float)std::atof(argv[++i]);
        else if (std::strcmp(argv[i], "--tonemap") == 0 && i + 1 < argc) {
            const char* value = argv[++i];
            if (auto tm = parse_tonemap(value)) overrides.tonemap = *tm;
            else {
                std::cerr << "Invalid tonemap: " << value << "\n";
                return 1;
            }
        } else if (std::strcmp(argv[i], "--normalize") == 0 && i + 1 < argc) {
            const char* value = argv[++i];
            if (auto nm = parse_normalize_mode(value)) overrides.normalize = *nm;
            else {
                std::cerr << "Invalid normalize mode: " << value << "\n";
                return 1;
            }
        } else if (std::strcmp(argv[i], "--normalize-ref") == 0 && i + 1 < argc) {
            overrides.normalize_ref = (float)std::atof(argv[++i]);
        } else if (std::strcmp(argv[i], "--normalize-pct") == 0 && i + 1 < argc) {
            overrides.normalize_pct = (float)std::clamp(std::atof(argv[++i]), 0.0, 1.0);
        } else if (std::strcmp(argv[i], "--ambient") == 0 && i + 1 < argc) {
            overrides.ambient = (float)std::atof(argv[++i]);
        } else if (std::strcmp(argv[i], "--background") == 0 && i + 1 < argc) {
            char* end = nullptr;
            float r = std::strtof(argv[++i], &end);
            float g = r, b = r;
            if (end && *end == ',') { g = std::strtof(end + 1, &end); }
            if (end && *end == ',') { b = std::strtof(end + 1, &end); }
            overrides.background = {r, g, b};
        } else if (std::strcmp(argv[i], "--opacity") == 0 && i + 1 < argc) {
            overrides.opacity = (float)std::clamp(std::atof(argv[++i]), 0.0, 1.0);
        } else if (std::strcmp(argv[i], "--intensity") == 0 && i + 1 < argc) {
            overrides.intensity = (float)std::atof(argv[++i]);
        } else if (std::strcmp(argv[i], "--saturation") == 0 && i + 1 < argc) {
            overrides.saturation = (float)std::max(std::atof(argv[++i]), 0.0);
        } else if (std::strcmp(argv[i], "--vignette") == 0 && i + 1 < argc) {
            overrides.vignette = (float)std::clamp(std::atof(argv[++i]), 0.0, 1.0);
        } else if (std::strcmp(argv[i], "--vignette-radius") == 0 && i + 1 < argc) {
            overrides.vignette_radius = (float)std::atof(argv[++i]);
        } else if (std::strcmp(argv[i], "--fast") == 0) {
            fast_mode = true;
        } else if (std::strcmp(argv[i], "--help") == 0 || std::strcmp(argv[i], "-h") == 0) {
            print_usage();
            return 0;
        } else {
            std::cerr << "Unknown option: " << argv[i] << "\n";
            print_usage();
            return 1;
        }
    }

    // Load shot and apply CLI overrides
    Shot shot = resolve_shot(scene_name);
    overrides.apply_to(shot);

    if (!save_shot_path.empty()) {
        normalize_scene(shot.scene);
        if (!save_shot_json(shot, save_shot_path)) {
            std::cerr << "Failed to save shot: " << save_shot_path << "\n";
            return 1;
        }
        std::cerr << "Saved shot: " << save_shot_path << "\n";
        return 0;
    }

    // Render using RenderSession
    RenderSession session(shot.canvas.width, shot.canvas.height, fast_mode);
    auto result = session.render_shot(shot);

    std::cerr << shot.trace.rays << "/" << shot.trace.rays << " rays\n";

    if (export_png(output, result.pixels.data(), result.width, result.height)) {
        std::cerr << "Saved: " << output << "\n";
    } else {
        std::cerr << "Failed to save: " << output << "\n";
        return 1;
    }

    return 0;
}
