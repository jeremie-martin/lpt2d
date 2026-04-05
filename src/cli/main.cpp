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
              << "  --fast                   Half-precision FBO (RGBA16F) — ~3x faster, slight precision loss\n"
              << "  --histogram              Include 256-bin luminance histogram in stderr JSON\n"
              << "  --stream                 Streaming mode: read JSON shots from stdin, write raw RGB to stdout\n"
              << "\nBuilt-in scenes: ";
    for (const auto& entry : get_builtin_scenes())
        std::cerr << entry.name << " ";
    std::cerr << "\n";
}

static Shot resolve_shot(const std::string& arg) {
    // Try built-in name first
    if (auto s = find_builtin_scene(arg)) return *s;
    // Then try as a file path
    Shot s = load_shot_json(arg);
    if (!s.scene.shapes.empty() || !s.scene.lights.empty() || !s.scene.groups.empty()) return s;
    std::cerr << "Unknown scene: " << arg << "\n";
    std::cerr << "Available: ";
    for (auto& entry : get_builtin_scenes())
        std::cerr << entry.name << " ";
    std::cerr << "\n";
    std::exit(1);
}

// CLI overrides — all optional, applied on top of shot defaults
struct CLIOverrides {
    std::optional<int> width, height;
    std::optional<int64_t> rays;
    std::optional<int> batch, depth;
    std::optional<float> exposure, contrast, gamma, white_point;
    std::optional<ToneMap> tonemap;
    std::optional<NormalizeMode> normalize;
    std::optional<float> normalize_ref, normalize_pct;
    std::optional<float> ambient, opacity, intensity;
    std::optional<std::array<float, 3>> background;
};

static void apply_overrides(Shot& shot, const CLIOverrides& ov) {
    if (ov.width) shot.canvas.width = *ov.width;
    if (ov.height) shot.canvas.height = *ov.height;
    if (ov.rays) shot.trace.rays = *ov.rays;
    if (ov.batch) shot.trace.batch = *ov.batch;
    if (ov.depth) shot.trace.depth = *ov.depth;
    if (ov.intensity) shot.trace.intensity = *ov.intensity;
    if (ov.exposure) shot.look.exposure = *ov.exposure;
    if (ov.contrast) shot.look.contrast = *ov.contrast;
    if (ov.gamma) shot.look.gamma = *ov.gamma;
    if (ov.white_point) shot.look.white_point = *ov.white_point;
    if (ov.tonemap) shot.look.tone_map = *ov.tonemap;
    if (ov.normalize) shot.look.normalize = *ov.normalize;
    if (ov.normalize_ref) shot.look.normalize_ref = *ov.normalize_ref;
    if (ov.normalize_pct) shot.look.normalize_pct = *ov.normalize_pct;
    if (ov.ambient) shot.look.ambient = *ov.ambient;
    if (ov.opacity) shot.look.opacity = *ov.opacity;
    if (ov.background) {
        shot.look.background[0] = (*ov.background)[0];
        shot.look.background[1] = (*ov.background)[1];
        shot.look.background[2] = (*ov.background)[2];
    }
}

static int run_stream(const Shot& session, int64_t default_rays, bool fast, bool histogram = false) {
    HeadlessGL gl;
    if (!gl.init()) return 1;

    int width = session.canvas.width;
    int height = session.canvas.height;
    TraceConfig default_tcfg = session.trace.to_trace_config();
    PostProcess default_pp = session.look;

    Renderer renderer;
    if (!renderer.init(width, height, fast)) return 1;

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

        Shot frame_shot = load_shot_json_string(line);

        // Parse per-frame render overrides
        FrameOverrides fo = parse_frame_overrides(line);

        int64_t rays = fo.rays.value_or(default_rays);
        TraceConfig tcfg = default_tcfg;
        if (fo.batch) tcfg.batch_size = *fo.batch;
        if (fo.depth) tcfg.max_depth = *fo.depth;
        if (fo.intensity) tcfg.intensity = *fo.intensity;

        PostProcess pp = default_pp;
        if (fo.exposure) pp.exposure = *fo.exposure;
        if (fo.contrast) pp.contrast = *fo.contrast;
        if (fo.gamma) pp.gamma = *fo.gamma;
        if (fo.white_point) pp.white_point = *fo.white_point;
        if (fo.tonemap) pp.tone_map = *fo.tonemap;
        if (fo.normalize) pp.normalize = *fo.normalize;
        if (fo.normalize_ref) pp.normalize_ref = *fo.normalize_ref;
        if (fo.normalize_pct) pp.normalize_pct = *fo.normalize_pct;
        if (fo.ambient) pp.ambient = *fo.ambient;
        if (fo.background) {
            pp.background[0] = (*fo.background)[0];
            pp.background[1] = (*fo.background)[1];
            pp.background[2] = (*fo.background)[2];
        }
        if (fo.opacity) pp.opacity = *fo.opacity;

        Bounds bounds;
        if (fo.bounds) {
            bounds = *fo.bounds;
        } else if (frame_shot.scene.shapes.empty() && frame_shot.scene.lights.empty() && frame_shot.scene.groups.empty()) {
            bounds = {{-1, -1}, {1, 1}};
        } else {
            bounds = compute_bounds(frame_shot.scene);
        }
        renderer.upload_scene(frame_shot.scene, bounds);
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

        auto stats_t0 = std::chrono::steady_clock::now();
        auto metrics = renderer.compute_frame_metrics();
        auto stats_t1 = std::chrono::steady_clock::now();
        auto t1 = std::chrono::steady_clock::now();
        auto ms = std::chrono::duration_cast<std::chrono::milliseconds>(t1 - t0).count();
        double ms_exact = std::chrono::duration_cast<std::chrono::microseconds>(t1 - t0).count() / 1000.0;
        double stats_ms = std::chrono::duration_cast<std::chrono::microseconds>(stats_t1 - stats_t0).count() / 1000.0;
        char mbuf[352];
        std::snprintf(mbuf, sizeof(mbuf),
            ", \"time_ms_exact\": %.3f, \"mean\": %.1f, \"pct_black\": %.4f, \"pct_clipped\": %.4f, \"p50\": %.0f, \"p95\": %.0f, \"stats_ms\": %.3f",
            ms_exact, metrics.mean_lum, metrics.pct_black, metrics.pct_clipped, metrics.p50, metrics.p95, stats_ms);
        std::string hbuf;
        if (histogram) {
            hbuf = ", \"histogram\": [";
            for (int i = 0; i < 256; ++i) {
                if (i > 0) hbuf += ',';
                hbuf += std::to_string(metrics.histogram[i]);
            }
            hbuf += ']';
        }
        std::cerr << "frame " << frame << ": {\"rays\": " << rays
                  << ", \"time_ms\": " << ms
                  << ", \"max_hdr\": " << renderer.last_max()
                  << ", \"total_rays\": " << renderer.total_rays()
                  << mbuf << hbuf << "}\n";
        ++frame;
    }

    renderer.shutdown();
    return 0;
}

int main(int argc, char** argv) {
    std::string scene_name = "three_spheres";
    std::string output = "output.png";
    bool stream_mode = false;
    bool fast_mode = false;
    bool emit_histogram = false;
    CLIOverrides overrides;

    for (int i = 1; i < argc; ++i) {
        if (std::strcmp(argv[i], "--scene") == 0 && i + 1 < argc)
            scene_name = argv[++i];
        else if (std::strcmp(argv[i], "--output") == 0 && i + 1 < argc)
            output = argv[++i];
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
            overrides.exposure = std::atof(argv[++i]);
        else if (std::strcmp(argv[i], "--gamma") == 0 && i + 1 < argc)
            overrides.gamma = std::atof(argv[++i]);
        else if (std::strcmp(argv[i], "--contrast") == 0 && i + 1 < argc)
            overrides.contrast = std::atof(argv[++i]);
        else if (std::strcmp(argv[i], "--white-point") == 0 && i + 1 < argc)
            overrides.white_point = std::atof(argv[++i]);
        else if (std::strcmp(argv[i], "--tonemap") == 0 && i + 1 < argc) {
            if (auto tm = parse_tonemap(argv[++i])) overrides.tonemap = *tm;
        } else if (std::strcmp(argv[i], "--normalize") == 0 && i + 1 < argc) {
            if (auto nm = parse_normalize_mode(argv[++i])) overrides.normalize = *nm;
        } else if (std::strcmp(argv[i], "--normalize-ref") == 0 && i + 1 < argc) {
            overrides.normalize_ref = std::atof(argv[++i]);
        } else if (std::strcmp(argv[i], "--normalize-pct") == 0 && i + 1 < argc) {
            overrides.normalize_pct = std::clamp(std::atof(argv[++i]), 0.0, 1.0);
        } else if (std::strcmp(argv[i], "--ambient") == 0 && i + 1 < argc) {
            overrides.ambient = std::atof(argv[++i]);
        } else if (std::strcmp(argv[i], "--background") == 0 && i + 1 < argc) {
            char* end = nullptr;
            float r = std::strtof(argv[++i], &end);
            float g = r, b = r;
            if (end && *end == ',') { g = std::strtof(end + 1, &end); }
            if (end && *end == ',') { b = std::strtof(end + 1, &end); }
            overrides.background = {r, g, b};
        } else if (std::strcmp(argv[i], "--opacity") == 0 && i + 1 < argc) {
            overrides.opacity = std::clamp(std::atof(argv[++i]), 0.0, 1.0);
        } else if (std::strcmp(argv[i], "--intensity") == 0 && i + 1 < argc) {
            overrides.intensity = std::atof(argv[++i]);
        } else if (std::strcmp(argv[i], "--fast") == 0) {
            fast_mode = true;
        } else if (std::strcmp(argv[i], "--histogram") == 0) {
            emit_histogram = true;
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

    if (stream_mode) {
        // Stream mode: use default shot (no scene file needed), apply CLI overrides
        Shot session;
        apply_overrides(session, overrides);
        return run_stream(session, session.trace.rays, fast_mode, emit_histogram);
    }
    (void)emit_histogram; // only used in stream mode

    // Load shot (scene file provides defaults for everything)
    Shot shot = resolve_shot(scene_name);
    apply_overrides(shot, overrides);

    HeadlessGL gl;
    if (!gl.init())
        return 1;

    int width = shot.canvas.width;
    int height = shot.canvas.height;

    Renderer renderer;
    if (!renderer.init(width, height, fast_mode))
        return 1;

    // Resolve camera bounds
    Bounds scene_bounds = compute_bounds(shot.scene);
    Bounds bounds = shot.camera.resolve(shot.canvas.aspect(), scene_bounds);
    renderer.upload_scene(shot.scene, bounds);
    renderer.clear();

    TraceConfig tcfg = shot.trace.to_trace_config();
    PostProcess pp = shot.look;
    int64_t total_rays = shot.trace.rays;

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
