// Emscripten glue: expose the GL-free C++ core to the web renderer.
//
// Rung 1 (fill-only): parse a Shot JSON via the authored core, resolve camera
// bounds + viewport transform, convert Look -> postprocess uniforms, and emit
// fill geometry (circles) with their spectral->RGB fill colors computed by the
// *same* core path the native engine uses (spectral_fill_rgb). The TypeScript
// renderer consumes this plan and never re-implements the physics-laden parts.
//
// No OpenGL/EGL/GLEW is referenced here — only scene/serialize/spectrum.

#include "scene.h"
#include "serialize.h"
#include "spectrum.h"

#include <nlohmann/json.hpp>
#include <emscripten/bind.h>

#include <algorithm>
#include <cmath>
#include <string>

using nlohmann::ordered_json;

// Mirror of image_analysis.cpp::viewport_xform (aspect-fit, min-scale, centered).
// Re-stated here to avoid pulling the analysis TU (and its deps) into the WASM
// build; the math is trivial and version-stable.
static void viewport_xform(const Bounds& b, int w, int h, float& s, float& ox, float& oy) {
    const float sizex = b.max.x - b.min.x;
    const float sizey = b.max.y - b.min.y;
    if (sizex <= 0.0f || sizey <= 0.0f || w <= 0 || h <= 0) {
        s = 1.0f; ox = 0.0f; oy = 0.0f; return;
    }
    const float sx = static_cast<float>(w) / sizex;
    const float sy = static_cast<float>(h) / sizey;
    s = std::min(sx, sy);
    ox = (static_cast<float>(w) - sizex * s) * 0.5f;
    oy = (static_cast<float>(h) - sizey * s) * 0.5f;
}

std::string resolve_scene(const std::string& json_in) {
    ordered_json out;
    std::string err;
    auto shot_opt = try_load_shot_json_string(json_in, &err);
    if (!shot_opt) {
        out["error"] = err.empty() ? "shot parse failed" : err;
        return out.dump();
    }
    const Shot& shot = *shot_opt;

    if (!shot.camera.bounds) {
        out["error"] = "rung1 requires explicit camera.bounds";
        return out.dump();
    }
    const Bounds b = *shot.camera.bounds;
    const int w = shot.canvas.width;
    const int h = shot.canvas.height;

    float s, ox, oy;
    viewport_xform(b, w, h, s, ox, oy);

    const Look& L = shot.look;
    out["width"] = w;
    out["height"] = h;
    out["bounds"] = ordered_json::array({b.min.x, b.min.y, b.max.x, b.max.y});
    out["viewport"] = ordered_json{{"scale", s}, {"ox", ox}, {"oy", oy}};
    out["post"] = ordered_json{
        {"tonemap", static_cast<int>(L.tonemap)},
        {"white_point", L.white_point},
        {"inv_gamma", L.gamma > 0.0f ? 1.0f / L.gamma : 1.0f},
        {"contrast", L.contrast},
        {"ambient", L.ambient},
        {"background", ordered_json::array({L.background[0], L.background[1], L.background[2]})},
        {"opacity", L.opacity},
        {"saturation", L.saturation},
        {"temperature", L.temperature},
        {"highlights", L.highlights},
        {"shadows", L.shadows},
        {"exposure_mult", std::exp2(L.exposure)},
    };

    ordered_json fills = ordered_json::array();
    auto add_circle = [&](const Circle& c) {
        const Material& m = resolve_material_id(c.material_id, shot.scene.materials);
        if (m.fill <= 0.0f) return;
        const Vec3 rgb = spectral_fill_rgb(m.spectral_c0, m.spectral_c1, m.spectral_c2);
        fills.push_back(ordered_json{
            {"cx", c.center.x}, {"cy", c.center.y}, {"r", c.radius},
            {"color", ordered_json::array({rgb.r * m.fill, rgb.g * m.fill, rgb.b * m.fill})},
        });
    };
    for (const auto& shape : shot.scene.shapes) {
        std::visit(overloaded{
            [&](const Circle& c) { add_circle(c); },
            [&](const auto&) {},  // segments/arcs/etc: no fillable interior in rung 1
        }, shape);
    }
    out["fills"] = fills;

    return out.dump();
}

EMSCRIPTEN_BINDINGS(lpt2d_web) {
    emscripten::function("resolve_scene", &resolve_scene);
}
