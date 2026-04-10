#include "app.h"

#include "app_actions.h"
#include "app_panels.h"
#include "editor.h"
#include "geometry.h"
#include "renderer.h"
#include "scene.h"
#include "scenes.h"
#include "serialize.h"
#include "ui.h"

#include <GL/glew.h>
#include <GLFW/glfw3.h>
#include <imgui.h>
#include <imgui_impl_glfw.h>
#include <imgui_impl_opengl3.h>

#include <stdint.h>
#include <algorithm>
#include <array>
#include <chrono>
#include <cmath>
#include <cstdio>
#include <deque>
#include <filesystem>
#include <iostream>
#include <map>
#include <optional>
#include <ratio>
#include <utility>
#include <variant>
#include <vector>

namespace {

struct InitialShot {
    Shot shot;
    int builtin_index = -1;
    std::string save_path;
};

struct AlignmentGuide {
    float axis = 0.0f;
    float span_min = 0.0f;
    float span_max = 0.0f;
};

VignetteFrame make_camera_vignette_frame(const Bounds& display_bounds,
                                         const Bounds& camera_bounds, int tex_w, int tex_h) {
    VignetteFrame frame{};
    if (tex_w <= 0 || tex_h <= 0)
        return frame;

    EditorCamera display_camera;
    display_camera.fit(display_bounds, (float)tex_w, (float)tex_h);
    CameraView display_view{display_camera, (float)tex_w, (float)tex_h};
    ImVec2 top_left = display_view.to_screen({camera_bounds.min.x, camera_bounds.max.y});
    ImVec2 bottom_right = display_view.to_screen({camera_bounds.max.x, camera_bounds.min.y});

    float left = top_left.x / (float)tex_w;
    float top = top_left.y / (float)tex_h;
    float right = bottom_right.x / (float)tex_w;
    float bottom = bottom_right.y / (float)tex_h;
    float size_x = std::max(right - left, 1e-6f);
    float size_y = std::max(bottom - top, 1e-6f);

    frame.center[0] = (left + right) * 0.5f;
    frame.center[1] = (top + bottom) * 0.5f;
    frame.inv_size[0] = 1.0f / size_x;
    frame.inv_size[1] = 1.0f / size_y;
    frame.x_scale = ((float)tex_w / (float)tex_h) * (size_x / size_y);
    return frame;
}

std::optional<InitialShot> try_load_initial_shot(const std::string& scene_arg,
                                                 const std::vector<BuiltinScene>& builtins) {
    namespace fs = std::filesystem;

    if (scene_arg.empty())
        return std::nullopt;

    for (int i = 0; i < (int)builtins.size(); ++i) {
        if (builtins[i].name == scene_arg) {
            return InitialShot{
                .shot = load_builtin_scene(builtins[i]),
                .builtin_index = i,
                .save_path = {},
            };
        }
    }

    const fs::path candidate{scene_arg};
    const bool looks_like_path = candidate.has_extension()
        || scene_arg.find('/') != std::string::npos
        || scene_arg.find('\\') != std::string::npos;
    if (looks_like_path || fs::exists(candidate)) {
        std::string error;
        if (auto loaded = try_load_shot_json(scene_arg, &error)) {
            return InitialShot{
                .shot = std::move(*loaded),
                .builtin_index = -1,
                .save_path = scene_arg,
            };
        }
        std::cerr << (error.empty() ? "Failed to load scene: " + scene_arg : error) << "\n";
        return std::nullopt;
    }

    return std::nullopt;
}

} // namespace

// ─── App::run ───────────────────────────────────────────────────────────

int App::run(const AppConfig& config) {
    if (!glfwInit()) { std::cerr << "GLFW init failed\n"; return 1; }

    glfwWindowHint(GLFW_CONTEXT_VERSION_MAJOR, 4);
    glfwWindowHint(GLFW_CONTEXT_VERSION_MINOR, 3);
    glfwWindowHint(GLFW_OPENGL_PROFILE, GLFW_OPENGL_CORE_PROFILE);

    GLFWwindow* window = glfwCreateWindow(config.width, config.height,
        "lpt2d \xe2\x80\x94 2D Light Path Tracer", nullptr, nullptr);
    if (!window) { glfwTerminate(); return 1; }
    glfwMakeContextCurrent(window);
    glfwSwapInterval(1);

    // DPI
    float dpi_scale;
    { float xs, ys; glfwGetWindowContentScale(window, &xs, &ys); dpi_scale = std::max(xs, 1.0f); }

    int fb_w, fb_h, win_w, win_h;
    glfwGetFramebufferSize(window, &fb_w, &fb_h);
    glfwGetWindowSize(window, &win_w, &win_h);

    Renderer renderer;
    if (!renderer.init(fb_w, fb_h)) { glfwTerminate(); return 1; }

    // ImGui
    IMGUI_CHECKVERSION();
    ImGui::CreateContext();
    ImGuiIO& io = ImGui::GetIO();
    io.IniFilename = "imgui.ini";
    ImGui_ImplGlfw_InitForOpenGL(window, true);
    ImGui_ImplOpenGL3_Init("#version 430");

    // Font
    float font_size = 15.0f * dpi_scale;
    if (!io.Fonts->AddFontFromFileTTF(LPT2D_FONT_PATH, font_size)) {
        ImFontConfig cfg;
        cfg.SizePixels = font_size;
        io.Fonts->AddFontDefault(&cfg);
    }
    apply_style(dpi_scale);

    // ── Editor state ──
    EditorState ed;
    const auto& builtins = get_builtin_scenes();

    PanelState panel;
    panel.current_scene = -1;
    if (auto initial = try_load_initial_shot(config.initial_scene, builtins)) {
        panel.current_scene = initial->builtin_index;
        ed.shot = std::move(initial->shot);
        ed.session.save_path = std::move(initial->save_path);
    } else if (!config.initial_scene.empty()) {
        if (!builtins.empty())
            std::cerr << "Unknown scene: " << config.initial_scene << ", using " << builtins[0].name << "\n";
        else
            std::cerr << "Unknown scene: " << config.initial_scene << "\n";
    }
    if (panel.current_scene < 0) {
        if (ed.shot.name.empty()) {
            if (builtins.empty()) {
                std::cerr << "No built-in scenes available\n";
                glfwDestroyWindow(window);
                glfwTerminate();
                return 1;
            }
            panel.current_scene = 0;
            ed.shot = load_builtin_scene(builtins[panel.current_scene]);
        }
    }
    ed.shot.trace.batch = kGuiTraceBatch;
    ed.view.scene_bounds = compute_bounds(ed.shot.scene);
    ed.view.camera.fit(ed.view.scene_bounds, (float)win_w, (float)win_h);

    Bounds initial_view = ed.view.camera.visible_bounds((float)win_w, (float)win_h);
    renderer.upload_scene(ed.shot.scene, initial_view);
    renderer.upload_fills(ed.shot.scene, initial_view);
    renderer.clear();
    ed.session.undo.push(ed.shot.scene); // initial state

    CompareSnapshot compare_ab;
    FrameAnalysis live_metrics{};
    float frame_ms = 16.0f;

    auto add_scene_material = [](Scene& scene, const Material& material, std::string_view base = "Material") {
        std::string material_id = next_scene_material_id(scene, base);
        scene.materials[material_id] = material;
        return material_id;
    };

    auto make_default_arc = [](Vec2 center, Vec2 target, std::string material_id = {}) {
        Vec2 delta = target - center;
        float angle = delta.length_sq() > 1e-10f
            ? normalize_angle(std::atan2(delta.y, delta.x))
            : 0.0f;
        Arc arc;
        arc.center = center;
        arc.radius = std::max(delta.length(), 0.02f);
        arc.angle_start = normalize_angle(angle - 0.5f * PI);
        arc.sweep = PI;
        arc.material_id = std::move(material_id);
        return arc;
    };

    // Shorthand reload via extracted function
    auto reload = [&](bool mark_dirty = true) {
        reload_scene(ed, renderer, compare_ab, panel.light_analysis_valid,
                     win_w, win_h, mark_dirty);
    };

    auto materialize_clipboard_for_paste = [&]() {
        Clipboard pasted = ed.session.clipboard;
        std::map<std::string, std::string> rebound_ids;
        auto for_each = [&](auto&& fn) {
            for (auto& shape : pasted.shapes) fn(shape);
            for (auto& group : pasted.groups)
                for (auto& shape : group.shapes) fn(shape);
        };
        for_each([&](Shape& shape) {
            std::string& material_id = shape_material_id(shape);
            if (material_id.empty()) {
                material_id = add_scene_material(ed.shot.scene, Material{});
                return;
            }
            if (auto rebound = rebound_ids.find(material_id); rebound != rebound_ids.end()) {
                material_id = rebound->second;
                return;
            }
            auto clipboard_material = ed.session.clipboard.materials.find(material_id);
            if (clipboard_material == ed.session.clipboard.materials.end()) {
                if (!ed.shot.scene.materials.contains(material_id)) {
                    std::string fallback_id = add_scene_material(ed.shot.scene, Material{}, material_id);
                    rebound_ids[material_id] = fallback_id;
                    material_id = fallback_id;
                }
                return;
            }
            auto live_material = ed.shot.scene.materials.find(material_id);
            if (live_material == ed.shot.scene.materials.end()) {
                ed.shot.scene.materials[material_id] = clipboard_material->second;
                return;
            }
            if (live_material->second == clipboard_material->second)
                return;
            std::string rebound_id = add_scene_material(ed.shot.scene, clipboard_material->second, material_id);
            rebound_ids[material_id] = rebound_id;
            material_id = rebound_id;
        });
        return pasted;
    };

    auto paste_clipboard_at = [&](Vec2 world_pos) {
        ed.session.undo.push(ed.shot.scene);
        Clipboard pasted = materialize_clipboard_for_paste();
        Vec2 offset = world_pos - pasted.centroid;
        ed.clear_selection();
        for (auto s : pasted.shapes) {
            translate_shape(s, offset);
            ed.shot.scene.shapes.push_back(s);
            ed.select({SelectionRef::Shape, shape_id(s), ""}, true);
        }
        for (auto l : pasted.lights) {
            translate_light(l, offset);
            ed.shot.scene.lights.push_back(l);
            ed.select({SelectionRef::Light, light_id(l), ""}, true);
        }
        for (auto g : pasted.groups) {
            translate_group(g, offset);
            ed.shot.scene.groups.push_back(g);
            ed.select({SelectionRef::Group, g.id, ""}, true);
        }
        reload();
    };

    auto fit_bounds_rect = [](const Bounds& bounds, float width, float height) -> std::array<float, 4> {
        Vec2 size = bounds.max - bounds.min;
        size.x = std::max(size.x, 0.01f);
        size.y = std::max(size.y, 0.01f);
        float scale = std::min(width / size.x, height / size.y);
        return {
            (width - size.x * scale) * 0.5f,
            (height - size.y * scale) * 0.5f,
            size.x * scale,
            size.y * scale,
        };
    };

    // ── Drag-and-drop file loading ─────────────────────────────────────

    struct DropState { std::string pending_path; };
    DropState drop_state;
    glfwSetWindowUserPointer(window, &drop_state);
    glfwSetDropCallback(window, [](GLFWwindow* w, int count, const char** paths) {
        if (count > 0)
            static_cast<DropState*>(glfwGetWindowUserPointer(w))->pending_path = paths[0];
    });

    // ── Main loop ───────────────────────────────────────────────────────

    while (!glfwWindowShouldClose(window)) {
        glfwPollEvents();

        // Handle file drop
        if (!drop_state.pending_path.empty()) {
            std::string error;
            if (try_load_scene(ed, renderer, compare_ab, panel.light_analysis_valid,
                               win_w, win_h,
                               drop_state.pending_path, &error)) {
                panel.current_scene = -1;
            } else {
                std::cerr << "Drop load failed: " << error << "\n";
            }
            drop_state.pending_path.clear();
        }

        // Handle resize
        int new_fb_w, new_fb_h;
        glfwGetFramebufferSize(window, &new_fb_w, &new_fb_h);
        glfwGetWindowSize(window, &win_w, &win_h);
        if (new_fb_w != fb_w || new_fb_h != fb_h) {
            fb_w = new_fb_w;
            fb_h = new_fb_h;
            if (fb_w > 0 && fb_h > 0) {
                renderer.resize(fb_w, fb_h);
                reload();
            }
        }
        if (fb_w <= 0 || fb_h <= 0) { glfwWaitEvents(); continue; }

        // Validate selection
        ed.validate_selection();

        // Camera view for this frame
        EditorCamera active_camera = current_display_camera(ed, compare_ab, win_w, win_h);
        CameraView cv{active_camera, (float)win_w, (float)win_h};
        bool showing_snapshot_a = compare_ab.active && compare_ab.showing_a;

        // Trace
        auto t0 = std::chrono::steady_clock::now();
        if (!showing_snapshot_a && !panel.paused && renderer.num_lights() > 0) {
            TraceConfig trace_cfg = ed.shot.trace.to_trace_config(ed.session.frame);
            renderer.trace_and_draw(trace_cfg);
            glFinish();
        }
        if (!showing_snapshot_a) {
            PostProcess pp = ed.shot.look.to_post_process();
            if (pp.vignette > 0.0f && !ed.shot.camera.empty()) {
                Bounds display_view = current_display_view(ed, compare_ab, win_w, win_h);
                Bounds vignette_camera = ed.shot.camera.resolve(ed.shot.canvas.aspect(), ed.view.scene_bounds);
                VignetteFrame vignette_frame = make_camera_vignette_frame(
                    display_view, vignette_camera, renderer.width(), renderer.height());
                renderer.update_display(pp, 0.0f, &vignette_frame);
            } else {
                renderer.update_display(pp, ed.shot.canvas.aspect());
            }
        }

        if (showing_snapshot_a && compare_ab.metrics_valid) {
            live_metrics = compare_ab.analysis;
        } else if (panel.show_stats_panel && panel.live_analysis) {
            // Opt-in by panel visibility. Closing the Stats window (or
            // unchecking "Live" inside it) stops dispatching the GPU
            // analyser entirely — zero cost while the user is doing
            // something else.
            live_metrics = renderer.run_frame_analysis();
        }
        // else: leave `live_metrics` at the last computed value. This
        // is the "freeze" behaviour the Stats window's Live checkbox
        // promises — the user can pause analysis to inspect a
        // particular frame without the histogram / overlay / deltas
        // resetting to zero.

        // ImGui frame
        ImGui_ImplOpenGL3_NewFrame();
        ImGui_ImplGlfw_NewFrame();
        ImGui::NewFrame();

        glBindFramebuffer(GL_FRAMEBUFFER, 0);
        glViewport(0, 0, fb_w, fb_h);
        glClearColor(0, 0, 0, 1);
        glClear(GL_COLOR_BUFFER_BIT);

        // ── Viewport ────────────────────────────────────────────────────

        ImGui::SetNextWindowPos({0, 0});
        ImGui::SetNextWindowSize(ImVec2((float)win_w, (float)win_h));
        ImGui::PushStyleVar(ImGuiStyleVar_WindowPadding, {0, 0});
        ImGui::Begin("##viewport", nullptr,
            ImGuiWindowFlags_NoTitleBar | ImGuiWindowFlags_NoResize |
            ImGuiWindowFlags_NoMove | ImGuiWindowFlags_NoScrollbar |
            ImGuiWindowFlags_NoBringToFrontOnFocus | ImGuiWindowFlags_NoSavedSettings |
            ImGuiWindowFlags_NoBackground);

        // Display rendered image (FBO always matches camera view)
        if (showing_snapshot_a && compare_ab.texture) {
            auto src = fit_bounds_rect(compare_ab.view_bounds,
                                       (float)compare_ab.texture_width,
                                       (float)compare_ab.texture_height);
            auto dst = fit_bounds_rect(compare_ab.view_bounds, (float)win_w, (float)win_h);
            ImGui::SetCursorPos(ImVec2(dst[0], dst[1]));
            ImVec2 uv0(src[0] / (float)compare_ab.texture_width,
                       1.0f - src[1] / (float)compare_ab.texture_height);
            ImVec2 uv1((src[0] + src[2]) / (float)compare_ab.texture_width,
                       1.0f - (src[1] + src[3]) / (float)compare_ab.texture_height);
            ImGui::Image((ImTextureID)(intptr_t)compare_ab.texture,
                         ImVec2(dst[2], dst[3]), uv0, uv1);
            ImGui::SetCursorPos(ImVec2(0, 0));
        } else {
            ImGui::Image((ImTextureID)(intptr_t)renderer.display_texture(),
                         ImVec2((float)win_w, (float)win_h), ImVec2(0, 1), ImVec2(1, 0));
        }

        bool vp_hovered = ImGui::IsWindowHovered();

        // ── Grid overlay ───────────────────────────────────────────────
        float grid_spacing = 0;
        if (ed.view.show_grid) {
            ImDrawList* gdl = ImGui::GetWindowDrawList();
            grid_spacing = adaptive_grid_spacing(cv.cam.zoom);
            draw_grid(gdl, cv, grid_spacing);
        }

        // ── Wireframe overlay ───────────────────────────────────────────

        if (panel.show_wireframe && !showing_snapshot_a) {
            ImDrawList* dl = ImGui::GetWindowDrawList();

            for (int i = 0; i < (int)ed.shot.scene.shapes.size(); ++i) {
                const auto& shape = ed.shot.scene.shapes[i];
                const auto& sid = shape_id(shape);
                SelectionRef ref{SelectionRef::Shape, sid, ""};
                bool is_sel = ed.is_selected(ref);
                bool is_active = ed.is_active(ref);
                bool is_hov = (ed.interaction.hovered == ref);
                bool hidden = !ed.visibility.is_shape_visible(sid);
                ImU32 col = hidden ? IM_COL32(100, 100, 110, 30)
                                   : (is_sel ? COL_SHAPE_SEL : (is_hov ? COL_SHAPE_HOV : COL_SHAPE));
                float th = hidden ? 1.0f * dpi_scale
                                  : (is_active ? 3.0f : (is_sel ? 2.0f : 1.5f)) * dpi_scale;

                if (ed.interaction.transform.active() && is_sel) {
                    if (const Shape* snap = find_shape_in(ed.interaction.transform.snapshot.shapes, sid)) {
                        draw_shape_overlay(dl, cv, *snap, COL_GHOST_SHAPE, 1.0f * dpi_scale);
                        draw_shape_overlay(dl, cv, shape, COL_SHAPE_SEL, 2.5f * dpi_scale);
                    } else {
                        draw_shape_overlay(dl, cv, shape, col, th);
                    }
                } else {
                    if (is_active && !hidden && !ed.interaction.transform.active())
                        draw_shape_overlay(dl, cv, shape, COL_SHAPE_SEL_GLOW, 6.0f * dpi_scale);
                    draw_shape_overlay(dl, cv, shape, col, th);
                }
            }

            for (int i = 0; i < (int)ed.shot.scene.lights.size(); ++i) {
                const auto& light = ed.shot.scene.lights[i];
                const auto& lid = light_id(light);
                SelectionRef ref{SelectionRef::Light, lid, ""};
                bool is_sel = ed.is_selected(ref);
                bool is_active = ed.is_active(ref);
                bool is_hov = (ed.interaction.hovered == ref);
                bool hidden = !ed.visibility.is_light_visible(lid);
                ImU32 col = hidden ? IM_COL32(200, 180, 40, 30)
                                   : (is_sel ? COL_LIGHT_SEL : (is_hov ? COL_LIGHT_HOV : COL_LIGHT));
                float th = hidden ? 1.0f * dpi_scale
                                  : (is_active ? 4.0f : (is_sel ? 3.0f : 2.0f)) * dpi_scale;

                if (ed.interaction.transform.active() && is_sel) {
                    if (const Light* snap = find_light_in(ed.interaction.transform.snapshot.lights, lid)) {
                        draw_light_overlay(dl, cv, *snap, COL_GHOST_LIGHT, 1.0f * dpi_scale, dpi_scale);
                        draw_light_overlay(dl, cv, light, COL_LIGHT_SEL, 3.0f * dpi_scale, dpi_scale);
                    } else {
                        draw_light_overlay(dl, cv, light, col, th, dpi_scale);
                    }
                } else {
                    if (is_active && !hidden)
                        draw_light_overlay(dl, cv, light, COL_LIGHT_SEL, 5.0f * dpi_scale, dpi_scale);
                    draw_light_overlay(dl, cv, light, col, th, dpi_scale);
                }
            }

            // Draw groups
            for (const auto& group : ed.shot.scene.groups) {
                SelectionRef gid{SelectionRef::Group, group.id, ""};
                bool is_sel = ed.is_selected(gid);
                bool is_active = ed.is_active(gid);
                bool is_hov = (ed.interaction.hovered == gid);
                bool hidden = !ed.visibility.is_group_visible(group.id);

                if (ed.interaction.transform.active() && is_sel) {
                    if (const Group* snap_group = find_group(ed.interaction.transform.snapshot, group.id)) {
                        for (const auto& s : snap_group->shapes) {
                            Shape ws = transform_shape(s, snap_group->transform);
                            draw_shape_overlay(dl, cv, ws, COL_GHOST_SHAPE, 1.0f * dpi_scale);
                        }
                        for (const auto& l : snap_group->lights) {
                            Light wl = transform_light(l, snap_group->transform);
                            draw_light_overlay(dl, cv, wl, COL_GHOST_LIGHT, 1.0f * dpi_scale, dpi_scale);
                        }
                    }
                }

                ImU32 shape_col = hidden ? IM_COL32(100, 100, 110, 30)
                                        : (is_sel ? COL_SHAPE_SEL : (is_hov ? COL_SHAPE_HOV : COL_SHAPE));
                ImU32 light_col = hidden ? IM_COL32(200, 180, 40, 30)
                                        : (is_sel ? COL_LIGHT_SEL : (is_hov ? COL_LIGHT_HOV : COL_LIGHT));
                float s_th = hidden ? 1.0f * dpi_scale
                                    : (is_active ? 3.0f : (is_sel ? 2.5f : 1.5f)) * dpi_scale;
                float l_th = hidden ? 1.0f * dpi_scale
                                    : (is_active ? 4.0f : (is_sel ? 3.0f : 2.0f)) * dpi_scale;

                for (const auto& s : group.shapes) {
                    Shape ws = transform_shape(s, group.transform);
                    draw_shape_overlay(dl, cv, ws, shape_col, s_th);
                }
                for (const auto& l : group.lights) {
                    Light wl = transform_light(l, group.transform);
                    draw_light_overlay(dl, cv, wl, light_col, l_th, dpi_scale);
                }

                if (is_sel) {
                    Bounds gb = ed.selection_bounds();
                    ImVec2 mn = cv.to_screen(gb.min);
                    ImVec2 mx = cv.to_screen(gb.max);
                    if (mn.y > mx.y) std::swap(mn.y, mx.y);
                    dl->AddRect(mn, mx, IM_COL32(80, 140, 235, 80), 0, 0, 1.0f * dpi_scale);
                }
            }

            // Handles for selected objects
            if (!ed.interaction.selection.empty() && ed.interaction.tool == EditTool::Select && !ed.interaction.transform.active()) {
                auto handles = get_handles(ed.shot.scene, ed.interaction.selection);
                Vec2 mw = cv.to_world(io.MousePos);
                int hov_h = vp_hovered ? handle_hit_test(handles, mw, 8.0f / cv.cam.zoom) : -1;
                draw_handles(dl, cv, ed.shot.scene, handles, hov_h);
            }

            // Alignment guides while dragging top-level objects
            if (ed.interaction.dragging && ed.interaction.editing_group_id.empty() && !ed.interaction.selection.empty()) {
                Bounds sel = ed.selection_bounds();
                float sel_xs[3] = {sel.min.x, (sel.min.x + sel.max.x) * 0.5f, sel.max.x};
                float sel_ys[3] = {sel.min.y, (sel.min.y + sel.max.y) * 0.5f, sel.max.y};
                float guide_thresh = 8.0f / cv.cam.zoom;

                struct BestGuide {
                    bool found = false;
                    float diff = 1e30f;
                    AlignmentGuide guide{};
                };
                BestGuide best_v, best_h;

                auto consider_vertical = [&](float sx, float cx, float y0, float y1) {
                    float diff = std::abs(sx - cx);
                    if (diff <= guide_thresh && diff < best_v.diff) {
                        best_v.found = true;
                        best_v.diff = diff;
                        best_v.guide = AlignmentGuide{cx, y0, y1};
                    }
                };
                auto consider_horizontal = [&](float sy, float cy, float x0, float x1) {
                    float diff = std::abs(sy - cy);
                    if (diff <= guide_thresh && diff < best_h.diff) {
                        best_h.found = true;
                        best_h.diff = diff;
                        best_h.guide = AlignmentGuide{cy, x0, x1};
                    }
                };
                auto compare_against = [&](const Bounds& b) {
                    float cand_xs[3] = {b.min.x, (b.min.x + b.max.x) * 0.5f, b.max.x};
                    float cand_ys[3] = {b.min.y, (b.min.y + b.max.y) * 0.5f, b.max.y};
                    for (float sx : sel_xs)
                        for (float cx : cand_xs)
                            consider_vertical(
                                sx, cx, std::min(sel.min.y, b.min.y), std::max(sel.max.y, b.max.y));
                    for (float sy : sel_ys)
                        for (float cy : cand_ys)
                            consider_horizontal(
                                sy, cy, std::min(sel.min.x, b.min.x), std::max(sel.max.x, b.max.x));
                };

                for (const auto& s : ed.shot.scene.shapes) {
                    SelectionRef ref{SelectionRef::Shape, shape_id(s), ""};
                    if (ed.is_selected(ref) || !ed.visibility.is_shape_visible(shape_id(s))) continue;
                    if (auto b = object_bounds(ed.shot.scene, ref)) compare_against(*b);
                }
                for (const auto& l : ed.shot.scene.lights) {
                    SelectionRef ref{SelectionRef::Light, light_id(l), ""};
                    if (ed.is_selected(ref) || !ed.visibility.is_light_visible(light_id(l))) continue;
                    if (auto b = object_bounds(ed.shot.scene, ref)) compare_against(*b);
                }
                for (const auto& g : ed.shot.scene.groups) {
                    SelectionRef ref{SelectionRef::Group, g.id, ""};
                    if (ed.is_selected(ref) || !ed.visibility.is_group_visible(g.id)) continue;
                    if (auto b = object_bounds(ed.shot.scene, ref)) compare_against(*b);
                }

                if (best_v.found) {
                    ImVec2 a = cv.to_screen({best_v.guide.axis, best_v.guide.span_min});
                    ImVec2 b = cv.to_screen({best_v.guide.axis, best_v.guide.span_max});
                    dl->AddLine(a, b, COL_ALIGN_GUIDE, 1.5f * dpi_scale);
                }
                if (best_h.found) {
                    ImVec2 a = cv.to_screen({best_h.guide.span_min, best_h.guide.axis});
                    ImVec2 b = cv.to_screen({best_h.guide.span_max, best_h.guide.axis});
                    dl->AddLine(a, b, COL_ALIGN_GUIDE, 1.5f * dpi_scale);
                }
            }

            // Creation preview
            if (ed.interaction.creating) {
                Vec2 mw = cv.to_world(io.MousePos);
                if (ed.interaction.tool == EditTool::Circle) {
                    float r = (mw - ed.interaction.create_start).length() * cv.cam.zoom;
                    dl->AddCircle(cv.to_screen(ed.interaction.create_start), r, COL_PREVIEW, 64, 1.5f * dpi_scale);
                } else if (ed.interaction.tool == EditTool::Arc) {
                    Vec2 delta = mw - ed.interaction.create_start;
                    if (delta.length_sq() > 1e-10f) {
                        Arc preview = make_default_arc(ed.interaction.create_start, mw);
                        draw_shape_overlay(dl, cv, preview, COL_PREVIEW, 1.5f * dpi_scale);
                    }
                } else if (ed.interaction.tool == EditTool::Polygon) {
                    ImVec2 a = cv.to_screen(ed.interaction.create_start);
                    ImVec2 b = io.MousePos;
                    dl->AddRect(ImVec2(std::min(a.x,b.x), std::min(a.y,b.y)),
                                ImVec2(std::max(a.x,b.x), std::max(a.y,b.y)), COL_PREVIEW, 0.0f, 0, 1.5f * dpi_scale);
                } else if (ed.interaction.tool == EditTool::Ellipse) {
                    ImVec2 a = cv.to_screen(ed.interaction.create_start);
                    ImVec2 b = io.MousePos;
                    dl->AddRect(ImVec2(std::min(a.x,b.x), std::min(a.y,b.y)),
                                ImVec2(std::max(a.x,b.x), std::max(a.y,b.y)), COL_PREVIEW, 0.0f, 0, 1.5f * dpi_scale);
                } else if (ed.interaction.tool == EditTool::Segment || ed.interaction.tool == EditTool::SegmentLight || ed.interaction.tool == EditTool::Bezier) {
                    dl->AddLine(cv.to_screen(ed.interaction.create_start), io.MousePos, COL_PREVIEW, 1.5f * dpi_scale);
                }
            }

            // Path multi-click preview
            if (!ed.interaction.path_create_points.empty()) {
                auto& pts = ed.interaction.path_create_points;
                for (size_t i = 0; i + 1 < pts.size(); ++i)
                    dl->AddLine(cv.to_screen(pts[i]), cv.to_screen(pts[i + 1]), COL_PREVIEW, 1.5f * dpi_scale);
                dl->AddLine(cv.to_screen(pts.back()), io.MousePos, COL_PREVIEW, 1.5f * dpi_scale);
                for (auto& pt : pts) {
                    ImVec2 sp = cv.to_screen(pt);
                    float r = 3.0f * dpi_scale;
                    dl->AddCircleFilled(sp, r, COL_PREVIEW);
                }
            }

            // Box selection preview
            if (ed.interaction.box_selecting) {
                ImVec2 cur = io.MousePos;
                ImVec2 mn(std::min(ed.interaction.box_start.x, cur.x), std::min(ed.interaction.box_start.y, cur.y));
                ImVec2 mx(std::max(ed.interaction.box_start.x, cur.x), std::max(ed.interaction.box_start.y, cur.y));
                dl->AddRectFilled(mn, mx, COL_BOX_SEL_FILL);
                dl->AddRect(mn, mx, COL_BOX_SEL_BORDER, 0, 0, 1.0f * dpi_scale);
            }

            // Transform pivot
            if (ed.interaction.transform.active() && ed.interaction.transform.type != TransformMode::Grab) {
                ImVec2 pivot_screen = cv.to_screen(ed.interaction.transform.pivot);
                float r = 6.0f * dpi_scale;
                dl->AddLine(ImVec2(pivot_screen.x - r, pivot_screen.y), ImVec2(pivot_screen.x + r, pivot_screen.y), COL_PIVOT, 2.0f * dpi_scale);
                dl->AddLine(ImVec2(pivot_screen.x, pivot_screen.y - r), ImVec2(pivot_screen.x, pivot_screen.y + r), COL_PIVOT, 2.0f * dpi_scale);
            }

            // Transform status text
            if (ed.interaction.transform.active()) {
                Vec2 mw = cv.to_world(io.MousePos);
                char status[128];
                switch (ed.interaction.transform.type) {
                case TransformMode::Grab: {
                    Vec2 delta = mw - ed.interaction.transform.mouse_start;
                    if (ed.interaction.transform.lock_x) delta.y = 0;
                    if (ed.interaction.transform.lock_y) delta.x = 0;
                    std::snprintf(status, sizeof(status), "Grab: dx=%.3f dy=%.3f%s",
                        delta.x, delta.y,
                        ed.interaction.transform.lock_x ? " [X]" : (ed.interaction.transform.lock_y ? " [Y]" : ""));
                    break;
                }
                case TransformMode::Rotate: {
                    Vec2 v0 = ed.interaction.transform.mouse_start - ed.interaction.transform.pivot;
                    Vec2 v1 = mw - ed.interaction.transform.pivot;
                    float angle = std::atan2(v1.y, v1.x) - std::atan2(v0.y, v0.x);
                    std::snprintf(status, sizeof(status), "Rotate: %.1f deg", angle * 180.0f / PI);
                    break;
                }
                case TransformMode::Scale: {
                    float d0 = (ed.interaction.transform.mouse_start - ed.interaction.transform.pivot).length();
                    float d1 = (mw - ed.interaction.transform.pivot).length();
                    float factor = (d0 > 1e-6f) ? d1 / d0 : 1.0f;
                    std::snprintf(status, sizeof(status), "Scale: %.2fx%s", factor,
                        ed.interaction.transform.lock_x ? " [X]" : (ed.interaction.transform.lock_y ? " [Y]" : ""));
                    break;
                }
                default: status[0] = 0;
                }
                if (status[0]) {
                    ImVec2 text_pos((float)win_w * 0.5f - 100, (float)win_h - 30 * dpi_scale);
                    dl->AddText(text_pos, IM_COL32(255, 255, 255, 220), status);
                }
            }
        }

        // ── Light circle overlay ─────────────────────────────────────────
        // Draws each measured LightCircle (from the C++ GPU analyser,
        // via run_frame_analysis) on top of the viewport. Uses a thin
        // green/red outline for pass/fail against a subset of the
        // crystal_field check.py thresholds so the user can iterate on
        // whether the measurement is catching what they see.
        if (panel.show_circle_overlay && !live_metrics.circles.empty()) {
            ImDrawList* dl = ImGui::GetWindowDrawList();
            const float rw = (float)renderer.width();
            const float rh = (float)renderer.height();
            const float sx_scale = (rw > 0) ? (float)win_w / rw : 1.0f;
            const float sy_scale = (rh > 0) ? (float)win_h / rh : 1.0f;
            const float r_scale = 0.5f * (sx_scale + sy_scale);
            // Thresholds mirrored from examples/python/families/crystal_field/check.py
            // (they are the GUI's own hard-coded preview — the Python filter
            // is the source of truth).
            constexpr float kMinMovingRadiusPx = 3.0f;
            constexpr float kMaxMovingRadiusPx = 80.0f;
            constexpr float kMinSharpness = 0.010f;
            constexpr int   kMinBrightPixels = 20;

            for (const auto& c : live_metrics.circles) {
                if (c.radius_px <= 0.0f) continue;
                const float sx = c.pixel_x * sx_scale;
                const float sy = c.pixel_y * sy_scale;
                const ImVec2 center(sx, sy);
                const float r_screen = c.radius_px * r_scale;
                const float fwhm_screen = c.radius_half_max_px * r_scale;

                const bool is_moving = c.id.rfind("light_", 0) == 0;
                const bool ok = (!is_moving) ||
                    (c.radius_px >= kMinMovingRadiusPx &&
                     c.radius_px <= kMaxMovingRadiusPx &&
                     c.sharpness >= kMinSharpness &&
                     c.n_bright_pixels >= kMinBrightPixels);
                const ImU32 col = ok ? IM_COL32(60, 220, 100, 220)
                                     : IM_COL32(230, 80, 80, 220);
                const ImU32 col_fwhm = ok ? IM_COL32(60, 220, 100, 110)
                                          : IM_COL32(230, 80, 80, 110);
                dl->AddCircle(center, r_screen, col, 0, 1.5f * dpi_scale);
                if (fwhm_screen > 0.0f)
                    dl->AddCircle(center, fwhm_screen, col_fwhm, 0, 1.0f * dpi_scale);
                dl->AddCircleFilled(center, 2.0f * dpi_scale, col);
                char label[64];
                std::snprintf(label, sizeof(label), "%s r%.0f",
                              c.id.c_str(), c.radius_px);
                dl->AddText(ImVec2(sx + r_screen + 4 * dpi_scale, sy - 7 * dpi_scale),
                            col, label);
            }
        }

        // ── Measurement overlay ──────────────────────────────────────────
        if (!showing_snapshot_a && ed.interaction.tool == EditTool::Measure && ed.interaction.measure_active) {
            ImDrawList* dl = ImGui::GetWindowDrawList();
            ImU32 meas_col = IM_COL32(0, 255, 180, 200);
            Vec2 mend = cv.to_world(io.MousePos);
            if (ed.view.snap_to_grid && ed.view.show_grid && grid_spacing > 0)
                mend = snap_to_grid_pos(mend, grid_spacing);
            ImVec2 s0 = cv.to_screen(ed.interaction.measure_start);
            ImVec2 s1 = cv.to_screen(mend);
            dl->AddLine(s0, s1, meas_col, 1.5f * dpi_scale);
            dl->AddCircleFilled(s0, 3.0f * dpi_scale, meas_col);
            dl->AddCircleFilled(s1, 3.0f * dpi_scale, meas_col);
            Vec2 delta = mend - ed.interaction.measure_start;
            float dist = delta.length();
            float angle_deg = std::atan2(delta.y, delta.x) * 180.0f / PI;
            char mtext[128];
            std::snprintf(mtext, sizeof(mtext), "d=%.4f  a=%.1f deg  dx=%.4f  dy=%.4f",
                          dist, angle_deg, delta.x, delta.y);
            ImVec2 mid = {(s0.x + s1.x) * 0.5f, std::min(s0.y, s1.y) - 20.0f * dpi_scale};
            dl->AddText(mid, meas_col, mtext);
        }

        // ── Camera frame overlay ───────────────────────────────────────
        struct CamHandlePt { CameraHandle id; Vec2 pos; };
        Bounds cam_frame{};
        CamHandlePt cam_handle_pts[8] = {};
        int n_cam_handles = 0;
        bool cam_active = !showing_snapshot_a && ed.view.show_camera_frame && !ed.shot.camera.empty();

        if (cam_active) {
            cam_frame = ed.shot.camera.resolve(ed.shot.canvas.aspect(), ed.view.scene_bounds);
            Vec2 mn = cam_frame.min, mx = cam_frame.max, mid = (mn + mx) * 0.5f;
            cam_handle_pts[0] = {CameraHandle::TopLeft,     {mn.x, mx.y}};
            cam_handle_pts[1] = {CameraHandle::TopRight,    mx};
            cam_handle_pts[2] = {CameraHandle::BottomLeft,  mn};
            cam_handle_pts[3] = {CameraHandle::BottomRight, {mx.x, mn.y}};
            cam_handle_pts[4] = {CameraHandle::Top,         {mid.x, mx.y}};
            cam_handle_pts[5] = {CameraHandle::Bottom,      {mid.x, mn.y}};
            cam_handle_pts[6] = {CameraHandle::Left,        {mn.x, mid.y}};
            cam_handle_pts[7] = {CameraHandle::Right,       {mx.x, mid.y}};
            n_cam_handles = 8;

            ImDrawList* dl = ImGui::GetWindowDrawList();
            ImVec2 scr_max = cv.to_screen(cam_frame.max);
            ImVec2 scr_min = cv.to_screen(cam_frame.min);
            float sl = scr_min.x, sr = scr_max.x;
            float st = scr_max.y, sb = scr_min.y;

            if (ed.view.dim_outside_camera) {
                float vr = (float)win_w, vb = (float)win_h;
                dl->AddRectFilled(ImVec2(0, 0), ImVec2(vr, st), COL_CAMERA_DIM);
                dl->AddRectFilled(ImVec2(0, sb), ImVec2(vr, vb), COL_CAMERA_DIM);
                dl->AddRectFilled(ImVec2(0, st), ImVec2(sl, sb), COL_CAMERA_DIM);
                dl->AddRectFilled(ImVec2(sr, st), ImVec2(vr, sb), COL_CAMERA_DIM);
            }

            dl->AddRect(ImVec2(sl, st), ImVec2(sr, sb), COL_CAMERA_FRAME, 0, 0, 1.5f * dpi_scale);

            if (ed.interaction.selection.empty() && ed.interaction.tool == EditTool::Select && !ed.interaction.transform.active()) {
                float hs = 4.0f * dpi_scale;
                for (int h = 0; h < n_cam_handles; ++h) {
                    ImVec2 sp = cv.to_screen(cam_handle_pts[h].pos);
                    ImU32 col = (ed.interaction.cam_handle_hovered == cam_handle_pts[h].id) ? COL_HANDLE_HOV : COL_CAMERA_HANDLE;
                    dl->AddRectFilled(ImVec2(sp.x - hs, sp.y - hs), ImVec2(sp.x + hs, sp.y + hs), col);
                }
            }
        }

        ImGui::End();
        ImGui::PopStyleVar();

        // ── Mouse interaction ───────────────────────────────────────────

        Vec2 mw_raw = cv.to_world(io.MousePos);
        bool snapping = ed.view.snap_to_grid && ed.view.show_grid && grid_spacing > 0;
        Vec2 mw = snapping ? snap_to_grid_pos(mw_raw, grid_spacing) : mw_raw;
        float hit_thresh = 8.0f / cv.cam.zoom;

        // Camera handle interaction (hover + start drag)
        if (!showing_snapshot_a && vp_hovered && ed.interaction.selection.empty() && ed.interaction.tool == EditTool::Select
            && !ed.interaction.transform.active() && cam_active
            && ed.interaction.cam_handle_dragging == CameraHandle::None) {

            ed.interaction.cam_handle_hovered = CameraHandle::None;
            for (int h = 0; h < n_cam_handles; ++h) {
                if ((mw - cam_handle_pts[h].pos).length() < hit_thresh) {
                    ed.interaction.cam_handle_hovered = cam_handle_pts[h].id;
                    break;
                }
            }

            if (ed.interaction.cam_handle_hovered != CameraHandle::None && ImGui::IsMouseClicked(0)) {
                ed.interaction.cam_handle_dragging = ed.interaction.cam_handle_hovered;
                ed.interaction.cam_drag_start_bounds = cam_frame;
            }
        } else if (ed.interaction.cam_handle_dragging == CameraHandle::None) {
            ed.interaction.cam_handle_hovered = CameraHandle::None;
        }

        // Camera handle drag (continues even outside viewport)
        if (!showing_snapshot_a && ed.interaction.cam_handle_dragging != CameraHandle::None) {
            if (ImGui::IsMouseDragging(0)) {
                Bounds b = ed.interaction.cam_drag_start_bounds;
                Vec2 drag_origin = cv.to_world(io.MouseClickedPos[0]);
                Vec2 drag_offset = mw - drag_origin;

                switch (ed.interaction.cam_handle_dragging) {
                case CameraHandle::Move:        b.min = b.min + drag_offset;
                                                b.max = b.max + drag_offset; break;
                case CameraHandle::TopLeft:     b.min.x = mw.x; b.max.y = mw.y; break;
                case CameraHandle::Top:         b.max.y = mw.y; break;
                case CameraHandle::TopRight:    b.max.x = mw.x; b.max.y = mw.y; break;
                case CameraHandle::Right:       b.max.x = mw.x; break;
                case CameraHandle::BottomRight: b.max.x = mw.x; b.min.y = mw.y; break;
                case CameraHandle::Bottom:      b.min.y = mw.y; break;
                case CameraHandle::BottomLeft:  b.min.x = mw.x; b.min.y = mw.y; break;
                case CameraHandle::Left:        b.min.x = mw.x; break;
                default: break;
                }

                if (b.min.x > b.max.x) std::swap(b.min.x, b.max.x);
                if (b.min.y > b.max.y) std::swap(b.min.y, b.max.y);

                ed.shot.camera.bounds = b;
                ed.shot.camera.center.reset();
                ed.shot.camera.width.reset();
                ed.session.dirty = true;
            }
            if (ImGui::IsMouseReleased(0)) {
                ed.interaction.cam_handle_dragging = CameraHandle::None;
            }
        }

        // Hover detection (Select tool only, skip during camera drag)
        if (!showing_snapshot_a && vp_hovered && ed.interaction.tool == EditTool::Select && !ed.interaction.dragging && !ed.interaction.creating && !ed.interaction.box_selecting && !ed.interaction.transform.active()
            && ed.interaction.cam_handle_dragging == CameraHandle::None) {
            SelectionRef hit = hit_test(mw_raw, ed.shot.scene, hit_thresh, ed.interaction.editing_group_id);
            ed.interaction.hovered = hit;
        } else if (!vp_hovered) {
            ed.interaction.hovered = {};
        } else if (showing_snapshot_a) {
            ed.interaction.hovered = {};
        }

        // --- Viewport navigation: pan & zoom ---

        if (vp_hovered) {
            bool compare_view_locked = compare_ab.active;
            bool middle_drag = ImGui::IsMouseDragging(2);
            bool alt_drag = io.KeyAlt && ImGui::IsMouseDragging(0);

            if (!compare_view_locked && (middle_drag || alt_drag)) {
                ed.view.showing_authored_camera = false;
                ImVec2 delta = io.MouseDelta;
                ed.view.camera.center.x -= delta.x / ed.view.camera.zoom;
                ed.view.camera.center.y += delta.y / ed.view.camera.zoom;
                auto view_bounds = ed.view.camera.visible_bounds((float)win_w, (float)win_h);
                renderer.update_viewport(view_bounds);
                renderer.redraw_fills(view_bounds);
                renderer.clear();
            }

            if (io.MouseWheel != 0) {
                if (io.KeyAlt && !ImGui::IsMouseDragging(0)) {
                    ed.shot.look.exposure += io.MouseWheel * 0.5f;
                } else if (io.KeyShift && !ImGui::IsMouseDragging(0)) {
                    // Shift+Scroll: adjust intensity of hovered or selected light
                    auto adjust_light_intensity = [&](Light& light) {
                        float& intensity = std::visit([](auto& l) -> float& { return l.intensity; }, light);
                        float factor = (io.MouseWheel > 0) ? 1.1f : (1.0f / 1.1f);
                        intensity = std::max(intensity * factor, 0.001f);
                    };
                    SelectionRef target = ed.interaction.hovered;
                    if (target.type != SelectionRef::Light || target.id.empty()) {
                        // Fall back to active selection if not hovering a light
                        if (const auto* active = ed.active_selection();
                            active && active->type == SelectionRef::Light)
                            target = *active;
                    }
                    if (target.type == SelectionRef::Light && !target.id.empty()) {
                        if (Light* light = resolve_light(ed.shot.scene, target)) {
                            ed.session.undo.push(ed.shot.scene);
                            adjust_light_intensity(*light);
                            reload();
                        }
                    }
                } else if (!compare_view_locked) {
                    ed.view.showing_authored_camera = false;
                    Vec2 world_before = cv.to_world(io.MousePos);
                    float factor = (io.MouseWheel > 0) ? 1.1f : (1.0f / 1.1f);
                    ed.view.camera.zoom *= factor;
                    ed.view.camera.zoom = std::clamp(ed.view.camera.zoom, 1.0f, 100000.0f);
                    CameraView cv2{ed.view.camera, (float)win_w, (float)win_h};
                    Vec2 world_after = cv2.to_world(io.MousePos);
                    ed.view.camera.center = ed.view.camera.center + (world_before - world_after);
                    cv = CameraView{ed.view.camera, (float)win_w, (float)win_h};
                    auto zoom_bounds = ed.view.camera.visible_bounds((float)win_w, (float)win_h);
                    renderer.update_viewport(zoom_bounds);
                    renderer.redraw_fills(zoom_bounds);
                    renderer.clear();
                }
            }
        }

        // --- Tool interactions ---

        bool panning = (io.KeyAlt && ImGui::IsMouseDown(0)) || ImGui::IsMouseDown(2);

        auto finalize_path_creation = [&]() {
            if (ed.interaction.path_create_points.size() < 2) {
                ed.interaction.path_create_points.clear();
                ed.interaction.tool = EditTool::Select;
                return;
            }
            ed.session.undo.push(ed.shot.scene);
            Path path = fit_path_from_samples(ed.interaction.path_create_points,
                                              add_scene_material(ed.shot.scene, mat_glass(1.5f, 20000.0f, 0.3f)));
            path.id = next_scene_entity_id(ed.shot.scene, "path");
            ed.shot.scene.shapes.push_back(path);
            ed.select_only({SelectionRef::Shape, path.id, ""});
            ed.interaction.path_create_points.clear();
            ed.interaction.tool = EditTool::Select;
            reload();
        };

        if (!showing_snapshot_a && vp_hovered && !panning && !ed.interaction.transform.active()
            && ed.interaction.cam_handle_dragging == CameraHandle::None) {
            // Double-click: enter group editing mode
            if (ImGui::IsMouseDoubleClicked(0) && ed.interaction.tool == EditTool::Select) {
                if (ed.interaction.editing_group_id.empty()) {
                    SelectionRef hit = hit_test(mw_raw, ed.shot.scene, hit_thresh, "");
                    if (hit.type == SelectionRef::Group && !hit.id.empty()) {
                        ed.interaction.editing_group_id = hit.id;
                        ed.clear_selection();
                        SelectionRef member = hit_test(mw_raw, ed.shot.scene, hit_thresh, ed.interaction.editing_group_id);
                        if (!member.id.empty()) ed.select(member, true);
                        reload();
                    }
                }
            }

            if (ImGui::IsMouseClicked(0)) {
                if (ed.interaction.tool == EditTool::Select) {
                    auto handles = get_handles(ed.shot.scene, ed.interaction.selection);
                    int h_idx = handle_hit_test(handles, mw_raw, hit_thresh);
                    if (h_idx >= 0) {
                        ed.session.undo.push(ed.shot.scene);
                        ed.interaction.handle_dragging = true;
                        ed.interaction.active_handle = handles[h_idx];
                    } else {
                        SelectionRef hit = hit_test(mw_raw, ed.shot.scene, hit_thresh, ed.interaction.editing_group_id);

                        if (!hit.id.empty()) {
                            if (io.KeyShift) {
                                ed.click_select(hit, true);
                            } else {
                                ed.click_select(hit, false);
                                ed.session.undo.push(ed.shot.scene);
                                ed.interaction.dragging = true;
                                ed.interaction.drag_offsets.clear();
                                for (auto& sid : ed.interaction.selection) {
                                    if (const Shape* shape = resolve_shape(ed.shot.scene, sid)) {
                                        std::visit(overloaded{
                                            [&](const Circle& ci) { ed.interaction.drag_offsets.push_back({ci.center - mw_raw, {}}); },
                                            [&](const Segment& s) { ed.interaction.drag_offsets.push_back({s.a - mw_raw, s.b - mw_raw}); },
                                            [&](const Arc& a) { ed.interaction.drag_offsets.push_back({a.center - mw_raw, {}}); },
                                            [&](const Bezier& b) { ed.interaction.drag_offsets.push_back({b.p0 - mw_raw, b.p2 - mw_raw}); },
                                            [&](const Polygon& p) { ed.interaction.drag_offsets.push_back({p.centroid() - mw_raw, {}}); },
                                            [&](const Ellipse& e) { ed.interaction.drag_offsets.push_back({e.center - mw_raw, {}}); },
                                            [&](const Path& p) {
                                                Vec2 c = shape_centroid(Shape{p});
                                                ed.interaction.drag_offsets.push_back({c - mw_raw, {}});
                                            },
                                        }, *shape);
                                    } else if (const Light* light = resolve_light(ed.shot.scene, sid)) {
                                        std::visit(overloaded{
                                            [&](const PointLight& l) { ed.interaction.drag_offsets.push_back({l.position - mw_raw, {}}); },
                                            [&](const SegmentLight& l) { ed.interaction.drag_offsets.push_back({l.a - mw_raw, l.b - mw_raw}); },
                                            [&](const ProjectorLight& l) { ed.interaction.drag_offsets.push_back({l.position - mw_raw, {}}); },
                                        }, *light);
                                    } else if (sid.type == SelectionRef::Group) {
                                        if (const Group* g = find_group(ed.shot.scene, sid.id))
                                            ed.interaction.drag_offsets.push_back({g->transform.translate - mw_raw, {}});
                                    }
                                }
                            }
                        } else {
                            ed.interaction.box_active_before = ed.interaction.active_selection;
                            if (!io.KeyShift)
                                ed.clear_selection();
                            ed.interaction.box_selecting = true;
                            ed.interaction.box_start = io.MousePos;
                        }
                    }
                } else if (ed.interaction.tool == EditTool::Erase) {
                    SelectionRef hit = hit_test(mw_raw, ed.shot.scene, hit_thresh, ed.interaction.editing_group_id);
                    if (!hit.id.empty()) {
                        ed.select_only(hit);
                        delete_selected(ed, renderer, compare_ab, panel.light_analysis_valid,
                                        win_w, win_h);
                    }
                } else if (ed.interaction.tool == EditTool::PointLight) {
                    ed.session.undo.push(ed.shot.scene);
                    PointLight light;
                    light.id = next_scene_entity_id(ed.shot.scene, "point_light");
                    light.position = mw;
                    light.intensity = 1.0f;
                    ed.shot.scene.lights.push_back(light);
                    ed.select_only({SelectionRef::Light, light.id, ""});
                    ed.interaction.tool = EditTool::Select;
                    reload();
                } else if (ed.interaction.tool == EditTool::ProjectorLight) {
                    ed.session.undo.push(ed.shot.scene);
                    ProjectorLight light;
                    light.id = next_scene_entity_id(ed.shot.scene, "projector_light");
                    light.position = mw;
                    light.direction = {1.0f, 0.0f};
                    light.intensity = 1.0f;
                    ed.shot.scene.lights.push_back(light);
                    ed.select_only({SelectionRef::Light, light.id, ""});
                    ed.interaction.tool = EditTool::Select;
                    reload();
                } else if (ed.interaction.tool == EditTool::Path) {
                    if (ImGui::IsMouseDoubleClicked(0) && ed.interaction.path_create_points.size() >= 2) {
                        finalize_path_creation();
                    } else if (!ImGui::IsMouseDoubleClicked(0)) {
                        ed.interaction.path_create_points.push_back(mw);
                    }
                } else if (ed.interaction.tool == EditTool::Measure) {
                    if (!ed.interaction.measure_active) {
                        ed.interaction.measure_start = mw;
                        ed.interaction.measure_active = true;
                    } else {
                        ed.interaction.measure_active = false;
                    }
                } else {
                    ed.interaction.creating = true;
                    ed.interaction.create_start = mw;
                }
            }

            // ── Right-click: context menu ─────────────────────────────────
            if (ImGui::IsMouseClicked(1)
                && !ed.interaction.dragging && !ed.interaction.handle_dragging
                && !ed.interaction.box_selecting && !ed.interaction.creating) {
                // Check for polygon vertex handle first
                bool vertex_hit = false;
                {
                    auto handles = get_handles(ed.shot.scene, ed.interaction.selection);
                    int h_idx = handle_hit_test(handles, mw_raw, hit_thresh);
                    if (h_idx >= 0 && handles[h_idx].kind == Handle::Position) {
                        const Handle& h = handles[h_idx];
                        if (const Shape* shape = resolve_shape(ed.shot.scene, h.obj)) {
                            if (std::get_if<Polygon>(shape)) {
                                panel.context_menu = {ContextMenuTarget::PolygonVertex, h.obj, h.param_index, mw_raw, false};
                                vertex_hit = true;
                            }
                        }
                    }
                }
                if (!vertex_hit) {
                    SelectionRef hit = hit_test(mw_raw, ed.shot.scene, hit_thresh, ed.interaction.editing_group_id);
                    if (!hit.id.empty()) {
                        if (!ed.is_selected(hit)) ed.select_only(hit);
                        else ed.set_active(hit);

                        ContextMenuTarget::Kind kind = ContextMenuTarget::Shape;
                        if (hit.type == SelectionRef::Light)
                            kind = ContextMenuTarget::Light;
                        else if (hit.type == SelectionRef::Group)
                            kind = ContextMenuTarget::Group;
                        else if (const Shape* s = resolve_shape(ed.shot.scene, hit)) {
                            if (std::get_if<Polygon>(s))
                                kind = ContextMenuTarget::Polygon;
                        }
                        panel.context_menu = {kind, hit, -1, mw_raw};
                    } else {
                        ed.clear_selection();
                        panel.context_menu = {ContextMenuTarget::EmptySpace, {}, -1, mw_raw};
                    }
                }
                ImGui::OpenPopup("ContextMenu##popup");
            }

        }

        // Handle drag (specific parameter modification)
        if (ImGui::IsMouseDragging(0) && ed.interaction.handle_dragging) {
            apply_handle_drag(ed.shot.scene, ed.interaction.active_handle, mw);
            reload();
        }

        // Drag to move selected objects
        if (ImGui::IsMouseDragging(0) && ed.interaction.dragging && !ed.interaction.handle_dragging && !ed.interaction.box_selecting &&
            ed.interaction.drag_offsets.size() == ed.interaction.selection.size()) {
            for (int i = 0; i < (int)ed.interaction.selection.size(); ++i) {
                auto& sid = ed.interaction.selection[i];
                auto& off = ed.interaction.drag_offsets[i];
                if (Shape* shape = resolve_shape(ed.shot.scene, sid)) {
                    std::visit(overloaded{
                        [&](Circle& c) { c.center = mw + off.a; },
                        [&](Segment& s) { s.a = mw + off.a; s.b = mw + off.b; },
                        [&](Arc& a) { a.center = mw + off.a; },
                        [&](Bezier& b) {
                            Vec2 delta = (mw + off.a) - b.p0;
                            b.p0 = b.p0 + delta; b.p1 = b.p1 + delta; b.p2 = b.p2 + delta;
                        },
                        [&](Polygon& p) {
                            if (p.vertices.empty()) return;
                            Vec2 delta = (mw + off.a) - p.centroid();
                            for (auto& v : p.vertices) v = v + delta;
                        },
                        [&](Ellipse& e) { e.center = mw + off.a; },
                        [&](Path& p) {
                            if (p.points.empty()) return;
                            Vec2 c = shape_centroid(Shape{p});
                            Vec2 delta = (mw + off.a) - c;
                            for (auto& v : p.points) v = v + delta;
                        },
                    }, *shape);
                } else if (Light* light = resolve_light(ed.shot.scene, sid)) {
                    std::visit(overloaded{
                        [&](PointLight& l) { l.position = mw + off.a; },
                        [&](SegmentLight& l) { l.a = mw + off.a; l.b = mw + off.b; },
                        [&](ProjectorLight& l) { l.position = mw + off.a; },
                    }, *light);
                } else if (sid.type == SelectionRef::Group) {
                    if (Group* g = find_group(ed.shot.scene, sid.id))
                        g->transform.translate = mw + off.a;
                }
            }
            reload();
        }

        if (ImGui::IsMouseReleased(0)) {
            // Complete creation
            if (ed.interaction.creating) {
                Vec2 end = cv.to_world(io.MousePos);
                float dist = (end - ed.interaction.create_start).length();

                ed.session.undo.push(ed.shot.scene);
                bool created = false;

                if (ed.interaction.tool == EditTool::Circle) {
                    float r = std::max(dist, 0.02f);
                    Circle circle;
                    circle.id = next_scene_entity_id(ed.shot.scene, "circle");
                    circle.center = ed.interaction.create_start;
                    circle.radius = r;
                    circle.material_id = add_scene_material(ed.shot.scene, mat_glass(1.5f, 20000.0f, 0.3f));
                    ed.shot.scene.shapes.push_back(circle);
                    ed.select_only({SelectionRef::Shape, circle.id, ""});
                    created = true;
                } else if (ed.interaction.tool == EditTool::Segment && dist > 0.01f) {
                    Segment segment;
                    segment.id = next_scene_entity_id(ed.shot.scene, "segment");
                    segment.a = ed.interaction.create_start;
                    segment.b = end;
                    segment.material_id = add_scene_material(ed.shot.scene, mat_mirror(0.95f));
                    ed.shot.scene.shapes.push_back(segment);
                    ed.select_only({SelectionRef::Shape, segment.id, ""});
                    created = true;
                } else if (ed.interaction.tool == EditTool::Arc) {
                    Arc arc = make_default_arc(
                        ed.interaction.create_start,
                        end,
                        add_scene_material(ed.shot.scene, mat_glass(1.5f, 20000.0f, 0.3f)));
                    arc.id = next_scene_entity_id(ed.shot.scene, "arc");
                    ed.shot.scene.shapes.push_back(arc);
                    ed.select_only({SelectionRef::Shape, arc.id, ""});
                    created = true;
                } else if (ed.interaction.tool == EditTool::Bezier && dist > 0.01f) {
                    Vec2 mid = (ed.interaction.create_start + end) * 0.5f;
                    Bezier bezier;
                    bezier.id = next_scene_entity_id(ed.shot.scene, "bezier");
                    bezier.p0 = ed.interaction.create_start;
                    bezier.p1 = mid;
                    bezier.p2 = end;
                    bezier.material_id = add_scene_material(ed.shot.scene, mat_glass(1.5f, 20000.0f, 0.3f));
                    ed.shot.scene.shapes.push_back(bezier);
                    ed.select_only({SelectionRef::Shape, bezier.id, ""});
                    created = true;
                } else if (ed.interaction.tool == EditTool::Polygon && dist > 0.01f) {
                    Vec2 a = ed.interaction.create_start, b = end;
                    Polygon p;
                    p.id = next_scene_entity_id(ed.shot.scene, "polygon");
                    p.vertices = {{a.x, a.y}, {b.x, a.y}, {b.x, b.y}, {a.x, b.y}};
                    if (!polygon_is_clockwise(p))
                        std::reverse(p.vertices.begin(), p.vertices.end());
                    p.material_id = add_scene_material(ed.shot.scene, mat_glass(1.5f, 20000.0f, 0.3f));
                    ed.shot.scene.shapes.push_back(p);
                    ed.select_only({SelectionRef::Shape, p.id, ""});
                    created = true;
                } else if (ed.interaction.tool == EditTool::Ellipse && dist > 0.01f) {
                    Vec2 center = (ed.interaction.create_start + end) * 0.5f;
                    float sa = std::max(std::abs(end.x - ed.interaction.create_start.x) * 0.5f, 0.02f);
                    float sb = std::max(std::abs(end.y - ed.interaction.create_start.y) * 0.5f, 0.02f);
                    Ellipse ellipse;
                    ellipse.id = next_scene_entity_id(ed.shot.scene, "ellipse");
                    ellipse.center = center;
                    ellipse.semi_a = sa;
                    ellipse.semi_b = sb;
                    ellipse.rotation = 0.0f;
                    ellipse.material_id = add_scene_material(ed.shot.scene, mat_glass(1.5f, 20000.0f, 0.3f));
                    ed.shot.scene.shapes.push_back(ellipse);
                    ed.select_only({SelectionRef::Shape, ellipse.id, ""});
                    created = true;
                } else if (ed.interaction.tool == EditTool::SegmentLight && dist > 0.01f) {
                    SegmentLight light;
                    light.id = next_scene_entity_id(ed.shot.scene, "segment_light");
                    light.a = ed.interaction.create_start;
                    light.b = end;
                    light.intensity = 1.0f;
                    ed.shot.scene.lights.push_back(light);
                    ed.select_only({SelectionRef::Light, light.id, ""});
                    created = true;
                }

                if (created) reload();
                else { ed.session.undo.snapshots.pop_back(); ed.session.undo.current--; }
                ed.interaction.creating = false;
                if (is_add_tool(ed.interaction.tool))
                    ed.interaction.tool = EditTool::Select;
            }

            // Complete box selection
            if (ed.interaction.box_selecting) {
                ImVec2 cur = io.MousePos;
                Vec2 wmin = cv.to_world(ImVec2(std::min(ed.interaction.box_start.x, cur.x), std::max(ed.interaction.box_start.y, cur.y)));
                Vec2 wmax = cv.to_world(ImVec2(std::max(ed.interaction.box_start.x, cur.x), std::min(ed.interaction.box_start.y, cur.y)));
                std::vector<SelectionRef> selected = io.KeyShift ? ed.interaction.selection : std::vector<SelectionRef>{};
                auto contains_ref = [&](const SelectionRef& ref) {
                    return std::find(selected.begin(), selected.end(), ref) != selected.end();
                };
                for (const auto& s : ed.shot.scene.shapes) {
                    SelectionRef ref{SelectionRef::Shape, shape_id(s), ""};
                    if (object_in_rect(ed.shot.scene, ref, wmin, wmax) && !contains_ref(ref))
                        selected.push_back(ref);
                }
                for (const auto& l : ed.shot.scene.lights) {
                    SelectionRef ref{SelectionRef::Light, light_id(l), ""};
                    if (object_in_rect(ed.shot.scene, ref, wmin, wmax) && !contains_ref(ref))
                        selected.push_back(ref);
                }
                for (const auto& g : ed.shot.scene.groups) {
                    SelectionRef ref{SelectionRef::Group, g.id, ""};
                    if (object_in_rect(ed.shot.scene, ref, wmin, wmax) && !contains_ref(ref))
                        selected.push_back(ref);
                }
                std::optional<SelectionRef> active = std::nullopt;
                if (ed.interaction.box_active_before
                    && std::find(selected.begin(), selected.end(), *ed.interaction.box_active_before) != selected.end()) {
                    active = ed.interaction.box_active_before;
                }
                ed.replace_selection(std::move(selected), active);
                ed.interaction.box_selecting = false;
                ed.interaction.box_active_before.reset();
            }

            ed.interaction.dragging = false;
            ed.interaction.handle_dragging = false;
            ed.interaction.drag_offsets.clear();
        }

        // ── Controls panel ──────────────────────────────────────────────

        // Re-show the panel when a dialog popup is requested while hidden,
        // so Ctrl+O and Ctrl+Shift+S work in fullscreen mode.
        if (!panel.show_controls_panel && (panel.open_load_popup || panel.open_save_as_popup))
            panel.show_controls_panel = true;

        if (panel.show_controls_panel)
            draw_controls_panel(ed, renderer, compare_ab, panel, live_metrics,
                                io, dpi_scale,
                                frame_ms, win_w, win_h, fb_w, fb_h);

        // Floating Stats window — top-level, independent of the
        // Controls tab bar so it stays visible while editing. Position
        // and size are remembered across runs via imgui.ini.
        draw_stats_window(panel, live_metrics, compare_ab, dpi_scale);

        // Shared add-menu items (used by A-key popup and right-click context menu)
        auto draw_add_menu_items = [&]() {
            auto add_item = [&](const char* name, EditTool tool) {
                if (ImGui::MenuItem(name)) {
                    ed.interaction.creating = false;
                    ed.interaction.path_create_points.clear();
                    ed.interaction.tool = tool;
                }
            };
            ImGui::TextDisabled("Shapes");
            add_item("Circle", EditTool::Circle);
            add_item("Segment", EditTool::Segment);
            add_item("Arc", EditTool::Arc);
            add_item("Bezier", EditTool::Bezier);
            add_item("Polygon", EditTool::Polygon);
            add_item("Ellipse", EditTool::Ellipse);
            add_item("Path", EditTool::Path);
            ImGui::Separator();
            ImGui::TextDisabled("Lights");
            add_item("Point Light", EditTool::PointLight);
            add_item("Segment Light", EditTool::SegmentLight);
            add_item("Projector", EditTool::ProjectorLight);
        };

        // ── Add popup at cursor (A) ──────────────────────────────────

        if (panel.open_add_popup) {
            ImGui::OpenPopup("AddAtCursor##popup");
            panel.open_add_popup = false;
        }
        if (ImGui::BeginPopup("AddAtCursor##popup")) {
            draw_add_menu_items();
            ImGui::EndPopup();
        }

        // ── Right-click context menu ────────────────────────────────────

        if (ImGui::BeginPopup("ContextMenu##popup")) {
            auto& ctx = panel.context_menu;

            switch (ctx.kind) {
            case ContextMenuTarget::EmptySpace: {
                if (ImGui::BeginMenu("Add")) {
                    draw_add_menu_items();
                    ImGui::EndMenu();
                }
                if (ImGui::MenuItem("Paste", "Ctrl+V", false, !ed.session.clipboard.empty())) {
                    paste_clipboard_at(ctx.world_pos);
                }
                ImGui::Separator();
                if (ImGui::MenuItem("Fit to Scene", "Home")) {
                    ed.view.camera.fit(ed.view.scene_bounds, (float)win_w, (float)win_h);
                    auto bounds = ed.view.camera.visible_bounds((float)win_w, (float)win_h);
                    renderer.update_viewport(bounds);
                    renderer.redraw_fills(bounds);
                    renderer.clear();
                }
                if (ImGui::MenuItem("Select All", "Ctrl+A")) {
                    ed.select_all();
                }
                break;
            }

            case ContextMenuTarget::Shape:
            case ContextMenuTarget::Polygon: {
                // Material submenu
                if (ImGui::BeginMenu("Material")) {
                    const Shape* ctx_shape = resolve_shape(ed.shot.scene, ctx.ref);
                    const std::string current = ctx_shape ? shape_material_id(*ctx_shape) : "";
                    for (auto& [name, mat] : ed.shot.scene.materials) {
                        bool is_current = (name == current);
                        if (ImGui::MenuItem(name.c_str(), nullptr, is_current)) {
                            if (!is_current) {
                                ed.session.undo.push(ed.shot.scene);
                                for (auto& sid : ed.interaction.selection) {
                                    if (Shape* s = resolve_shape(ed.shot.scene, sid))
                                        bind_material(*s, ed.shot.scene, name);
                                }
                                reload();
                            }
                        }
                    }
                    ImGui::EndMenu();
                }
                if (ImGui::MenuItem("Duplicate", "Ctrl+D")) {
                    duplicate_selected(ed, renderer, compare_ab, panel.light_analysis_valid,
                                       win_w, win_h);
                }
                if (ImGui::MenuItem("Delete", "Del")) {
                    delete_selected(ed, renderer, compare_ab, panel.light_analysis_valid,
                                    win_w, win_h);
                }
                if (ImGui::MenuItem("Group", "Ctrl+G")) {
                    group_selected(ed, renderer, compare_ab, panel.light_analysis_valid,
                                   win_w, win_h);
                }
                if (ImGui::MenuItem("Hide", "H")) {
                    for (auto& sid : ed.interaction.selection) {
                        if (sid.type == SelectionRef::Shape)
                            ed.visibility.toggle_shape(sid.id);
                    }
                    reload();
                }
                // Polygon-specific items
                if (ctx.kind == ContextMenuTarget::Polygon) {
                    ImGui::Separator();
                    if (Shape* shape = resolve_shape(ed.shot.scene, ctx.ref)) {
                        if (auto* poly = std::get_if<Polygon>(shape)) {
                            if (ImGui::MenuItem("All Smooth")) {
                                ed.session.undo.push(ed.shot.scene);
                                poly->join_modes.assign(poly->vertices.size(), PolygonJoinMode::Smooth);
                                reload();
                            }
                            if (ImGui::MenuItem("All Sharp")) {
                                ed.session.undo.push(ed.shot.scene);
                                poly->join_modes.assign(poly->vertices.size(), PolygonJoinMode::Sharp);
                                reload();
                            }
                            if (ImGui::MenuItem("All Auto")) {
                                ed.session.undo.push(ed.shot.scene);
                                poly->join_modes.clear();
                                reload();
                            }
                        }
                    }
                }
                break;
            }

            case ContextMenuTarget::PolygonVertex: {
                if (Shape* shape = resolve_shape(ed.shot.scene, ctx.ref)) {
                    if (auto* poly = std::get_if<Polygon>(shape)) {
                        int vi = ctx.vertex_index;
                        if (vi >= 0 && vi < (int)poly->vertices.size()) {
                            auto push_undo_once = [&]() {
                                if (!ctx.undo_pushed) { ed.session.undo.push(ed.shot.scene); ctx.undo_pushed = true; }
                            };
                            // Join Mode submenu
                            PolygonJoinMode current_mode = polygon_effective_join_mode(*poly, vi);
                            if (ImGui::BeginMenu("Join Mode")) {
                                auto set_join = [&](PolygonJoinMode mode) {
                                    push_undo_once();
                                    if (!polygon_uses_per_vertex_join_modes(*poly)) {
                                        poly->join_modes.resize(poly->vertices.size(), PolygonJoinMode::Auto);
                                        for (int i = 0; i < (int)poly->vertices.size(); ++i)
                                            poly->join_modes[i] = polygon_effective_join_mode(*poly, i);
                                    }
                                    poly->join_modes[vi] = mode;
                                    reload();
                                };
                                if (ImGui::MenuItem("Auto", nullptr, current_mode == PolygonJoinMode::Auto))
                                    set_join(PolygonJoinMode::Auto);
                                if (ImGui::MenuItem("Sharp", nullptr, current_mode == PolygonJoinMode::Sharp))
                                    set_join(PolygonJoinMode::Sharp);
                                if (ImGui::MenuItem("Smooth", nullptr, current_mode == PolygonJoinMode::Smooth))
                                    set_join(PolygonJoinMode::Smooth);
                                ImGui::EndMenu();
                            }
                            // Corner Radius inline editor
                            float radius = polygon_effective_corner_radius(*poly, vi);
                            ImGui::SetNextItemWidth(120);
                            if (ImGui::DragFloat("Corner Radius", &radius, 0.001f, 0.0f, 10.0f, "%.3f")) {
                                push_undo_once();
                                if (!polygon_uses_per_vertex_corner_radii(*poly)) {
                                    poly->corner_radii.resize(poly->vertices.size());
                                    for (int i = 0; i < (int)poly->vertices.size(); ++i)
                                        poly->corner_radii[i] = polygon_effective_corner_radius(*poly, i);
                                    poly->corner_radius = 0.0f;
                                }
                                poly->corner_radii[vi] = radius;
                                reload();
                            }
                        }
                    }
                }
                break;
            }

            case ContextMenuTarget::Light: {
                if (ImGui::MenuItem("Duplicate", "Ctrl+D")) {
                    duplicate_selected(ed, renderer, compare_ab, panel.light_analysis_valid,
                                       win_w, win_h);
                }
                if (ImGui::MenuItem("Delete", "Del")) {
                    delete_selected(ed, renderer, compare_ab, panel.light_analysis_valid,
                                    win_w, win_h);
                }
                if (ImGui::MenuItem("Solo")) {
                    if (ed.visibility.solo_light_id == ctx.ref.id
                        && ed.visibility.solo_light_group_id == ctx.ref.group_id) {
                        ed.visibility.clear_solo();
                    } else {
                        ed.visibility.solo_light_id = ctx.ref.id;
                        ed.visibility.solo_light_group_id = ctx.ref.group_id;
                    }
                    reload();
                }
                if (ImGui::MenuItem("Hide", "H")) {
                    ed.visibility.toggle_light(ctx.ref.id);
                    reload();
                }
                break;
            }

            case ContextMenuTarget::Group: {
                if (ImGui::MenuItem("Enter Group")) {
                    ed.interaction.editing_group_id = ctx.ref.id;
                    ed.clear_selection();
                    reload();
                }
                if (ImGui::MenuItem("Ungroup", "Ctrl+Shift+G")) {
                    ungroup_selected(ed, renderer, compare_ab, panel.light_analysis_valid,
                                     win_w, win_h);
                }
                if (ImGui::MenuItem("Duplicate", "Ctrl+D")) {
                    duplicate_selected(ed, renderer, compare_ab, panel.light_analysis_valid,
                                       win_w, win_h);
                }
                if (ImGui::MenuItem("Delete", "Del")) {
                    delete_selected(ed, renderer, compare_ab, panel.light_analysis_valid,
                                    win_w, win_h);
                }
                if (ImGui::MenuItem("Hide", "H")) {
                    ed.visibility.toggle_group(ctx.ref.id);
                    reload();
                }
                break;
            }

            default: break;
            }

            ImGui::EndPopup();
        } else {
            panel.context_menu.kind = ContextMenuTarget::None;
        }

        // ── Shortcut reference overlay (?) ──────────────────────────────

        if (panel.show_shortcuts_help) {
            ImGui::SetNextWindowPos(ImVec2((float)win_w * 0.5f, (float)win_h * 0.5f),
                                    ImGuiCond_Appearing, ImVec2(0.5f, 0.5f));
            ImGui::SetNextWindowSize(ImVec2(420 * dpi_scale, 0), ImGuiCond_Appearing);
            if (ImGui::Begin("Keyboard Shortcuts", &panel.show_shortcuts_help,
                             ImGuiWindowFlags_NoCollapse | ImGuiWindowFlags_NoSavedSettings)) {
                auto section = [](const char* title) {
                    ImGui::Spacing();
                    ImGui::TextDisabled("%s", title);
                    ImGui::Separator();
                };
                auto row = [](const char* key, const char* desc) {
                    ImGui::Text("%-18s %s", key, desc);
                };
                section("Navigation");
                row("Middle / Alt+Drag", "Pan");
                row("Scroll", "Zoom");
                row("F", "Fit to selection");
                row("Home", "Fit to scene");
                row("0", "Toggle authored camera");
                row("Tab", "Toggle panel");
                row("1 / 2", "Edit / Look tab");

                section("Selection & Edit");
                row("Click", "Select");
                row("Shift+Click", "Add/remove");
                row("G / R / S", "Grab / Rotate / Scale");
                row("X / Y", "Axis constraint (in G/R/S)");
                row("Delete / Backspace", "Delete selected");
                row("Ctrl+D", "Duplicate + Grab");
                row("Ctrl+G / Ctrl+Sh+G", "Group / Ungroup");
                row("H / Alt+H", "Hide / Show all");

                section("Tools");
                row("Q", "Select tool");
                row("A", "Add menu at cursor");
                row("Right-click", "Context menu");
                row("X", "Erase tool");
                row("M", "Measure tool");

                section("Materials & Look");
                row("N / Shift+N", "Cycle material fwd / back");
                row("J", "Cycle join mode (polygon)");
                row("V", "Toggle wireframe");
                row("Shift+1-6", "Look presets");
                row("[ / ]", "Exposure nudge");
                row("Shift+Scroll", "Light intensity");
                row("Space", "Pause / unpause");

                section("Comparison");
                row("`  (backtick)", "Toggle A/B snapshot");

                section("File");
                row("Ctrl+S", "Save");
                row("Ctrl+Shift+S", "Save As");
                row("Ctrl+O", "Load");
                row("Ctrl+Z / Ctrl+Sh+Z", "Undo / Redo");

                ImGui::Spacing();
                ImGui::TextDisabled("Press ? to close");
            }
            ImGui::End();
        }

        // ── Keyboard shortcuts ──────────────────────────────────────────

        if (!io.WantCaptureKeyboard) {
            // --- Modal transform input ---
            if (ed.interaction.transform.active()) {
                // Axis constraints
                if (ImGui::IsKeyPressed(ImGuiKey_X)) {
                    ed.interaction.transform.lock_x = !ed.interaction.transform.lock_x;
                    ed.interaction.transform.lock_y = false;
                }
                if (ImGui::IsKeyPressed(ImGuiKey_Y)) {
                    ed.interaction.transform.lock_y = !ed.interaction.transform.lock_y;
                    ed.interaction.transform.lock_x = false;
                }

                // Numeric input (row keys + numpad)
                for (int k = ImGuiKey_0; k <= ImGuiKey_9; ++k) {
                    if (ImGui::IsKeyPressed((ImGuiKey)k))
                        ed.interaction.transform.numeric_buf += ('0' + (k - ImGuiKey_0));
                }
                for (int k = ImGuiKey_Keypad0; k <= ImGuiKey_Keypad9; ++k) {
                    if (ImGui::IsKeyPressed((ImGuiKey)k))
                        ed.interaction.transform.numeric_buf += ('0' + (k - ImGuiKey_Keypad0));
                }
                if (ImGui::IsKeyPressed(ImGuiKey_Period) || ImGui::IsKeyPressed(ImGuiKey_KeypadDecimal))
                    ed.interaction.transform.numeric_buf += '.';
                if (ImGui::IsKeyPressed(ImGuiKey_Minus) || ImGui::IsKeyPressed(ImGuiKey_KeypadSubtract))
                    ed.interaction.transform.numeric_buf += '-';
                if (ImGui::IsKeyPressed(ImGuiKey_Backspace) && !ed.interaction.transform.numeric_buf.empty())
                    ed.interaction.transform.numeric_buf.pop_back();

                // Live-apply transform every frame
                for (auto& sid : ed.interaction.selection) {
                    if (Shape* live = resolve_shape(ed.shot.scene, sid)) {
                        if (const Shape* snap = resolve_shape(ed.interaction.transform.snapshot, sid))
                            apply_transform_shape(*live, *snap, ed.interaction.transform, mw, io.KeyShift);
                    } else if (Light* live = resolve_light(ed.shot.scene, sid)) {
                        if (const Light* snap = resolve_light(ed.interaction.transform.snapshot, sid))
                            apply_transform_light(*live, *snap, ed.interaction.transform, mw, io.KeyShift);
                    } else if (sid.type == SelectionRef::Group) {
                        Group* live_g = find_group(ed.shot.scene, sid.id);
                        const Group* snap_g = find_group(ed.interaction.transform.snapshot, sid.id);
                        if (live_g && snap_g)
                            apply_transform_group(*live_g, *snap_g, ed.interaction.transform, mw, io.KeyShift);
                    }
                }
                reload();

                // Confirm
                if (ImGui::IsKeyPressed(ImGuiKey_Enter) || ImGui::IsMouseClicked(0)) {
                    ed.interaction.transform.type = TransformMode::None;
                    ed.interaction.transform.snapshot = {};
                }

                // Cancel
                if (ImGui::IsKeyPressed(ImGuiKey_Escape) || ImGui::IsMouseClicked(1)) {
                    ed.shot.scene = ed.interaction.transform.snapshot;
                    ed.interaction.transform.type = TransformMode::None;
                    ed.interaction.transform.snapshot = {};
                    reload();
                }
            } else {
                // --- Global shortcuts ---

                // Undo/Redo
                if (io.KeyCtrl && io.KeyShift && ImGui::IsKeyPressed(ImGuiKey_Z)) {
                    if (ed.session.undo.redo(ed.shot.scene)) {
                        panel.material_panel.synced_target.reset();
                        ed.validate_selection();
                        reload();
                    }
                } else if (io.KeyCtrl && ImGui::IsKeyPressed(ImGuiKey_Z)) {
                    if (ed.session.undo.undo(ed.shot.scene)) {
                        panel.material_panel.synced_target.reset();
                        ed.validate_selection();
                        reload();
                    }
                }

                // Exposure nudge: [ / ]
                if (ImGui::IsKeyPressed(ImGuiKey_LeftBracket)) ed.shot.look.exposure -= 0.5f;
                if (ImGui::IsKeyPressed(ImGuiKey_RightBracket)) ed.shot.look.exposure += 0.5f;

                // Panel toggle: Tab
                if (ImGui::IsKeyPressed(ImGuiKey_Tab))
                    panel.show_controls_panel = !panel.show_controls_panel;

                // Panel tab switching: 1 / 2 (only when panel is visible)
                if (panel.show_controls_panel && !io.KeyShift && !io.KeyCtrl && !io.KeyAlt) {
                    if (ImGui::IsKeyPressed(ImGuiKey_1) || ImGui::IsKeyPressed(ImGuiKey_Keypad1)) { panel.active_tab = 0; panel.tab_switch_requested = true; }
                    if (ImGui::IsKeyPressed(ImGuiKey_2) || ImGui::IsKeyPressed(ImGuiKey_Keypad2)) { panel.active_tab = 1; panel.tab_switch_requested = true; }
                }

                // Look presets: Shift+1 through Shift+6
                if (io.KeyShift && !io.KeyCtrl && !io.KeyAlt) {
                    for (int k = ImGuiKey_1; k <= ImGuiKey_6; ++k)
                        if (ImGui::IsKeyPressed((ImGuiKey)k))
                            apply_look_preset(ed.shot.look, k - ImGuiKey_1);
                    for (int k = ImGuiKey_Keypad1; k <= ImGuiKey_Keypad6; ++k)
                        if (ImGui::IsKeyPressed((ImGuiKey)k))
                            apply_look_preset(ed.shot.look, k - ImGuiKey_Keypad1);
                }

                // A/B look toggle: ` (grave accent)
                if (ImGui::IsKeyPressed(ImGuiKey_GraveAccent) && compare_ab.active) {
                    compare_ab.showing_a = !compare_ab.showing_a;
                    if (!compare_ab.showing_a)
                        reload(false);
                }

                // Save/Load
                if (io.KeyCtrl && io.KeyShift && ImGui::IsKeyPressed(ImGuiKey_S)) {
                    panel.open_save_as_popup = true;
                } else if (io.KeyCtrl && ImGui::IsKeyPressed(ImGuiKey_S)) {
                    do_save(ed);
                }
                if (io.KeyCtrl && ImGui::IsKeyPressed(ImGuiKey_O)) {
                    panel.open_load_popup = true;
                }

                // Add menu at cursor: A
                if (!io.KeyShift && !io.KeyCtrl && !io.KeyAlt && ImGui::IsKeyPressed(ImGuiKey_A)) {
                    panel.open_add_popup = true;
                }

                // Shortcut reference: ? (character-based for layout independence)
                // Stats window toggle: ! (since plain 'S' is taken by the
                // Scale transform tool during selection). Reopen the Stats
                // floating panel after it's been closed with its X button.
                for (int ci = 0; ci < io.InputQueueCharacters.Size; ++ci) {
                    const auto ch = io.InputQueueCharacters[ci];
                    if (ch == '?') {
                        panel.show_shortcuts_help = !panel.show_shortcuts_help;
                    } else if (ch == '!') {
                        panel.show_stats_panel = !panel.show_stats_panel;
                    }
                }

                // Select all
                if (io.KeyCtrl && ImGui::IsKeyPressed(ImGuiKey_A)) {
                    ed.select_all();
                }

                // Group / Ungroup
                if (io.KeyCtrl && io.KeyShift && ImGui::IsKeyPressed(ImGuiKey_G)) {
                    ungroup_selected(ed, renderer, compare_ab, panel.light_analysis_valid,
                                     win_w, win_h);
                } else if (io.KeyCtrl && ImGui::IsKeyPressed(ImGuiKey_G)) {
                    group_selected(ed, renderer, compare_ab, panel.light_analysis_valid,
                                   win_w, win_h);
                }

                // Copy/Paste/Cut/Duplicate
                if (io.KeyCtrl && ImGui::IsKeyPressed(ImGuiKey_C)) {
                    copy_to_clipboard(ed);
                }

                if (io.KeyCtrl && ImGui::IsKeyPressed(ImGuiKey_V) && !ed.session.clipboard.empty()) {
                    paste_clipboard_at(mw);
                }

                if (io.KeyCtrl && ImGui::IsKeyPressed(ImGuiKey_X)) {
                    copy_to_clipboard(ed);
                    delete_selected(ed, renderer, compare_ab, panel.light_analysis_valid,
                                    win_w, win_h);
                }

                if (io.KeyCtrl && ImGui::IsKeyPressed(ImGuiKey_D) && !ed.interaction.selection.empty()) {
                    duplicate_selected(ed, renderer, compare_ab, panel.light_analysis_valid,
                                       win_w, win_h);
                    ed.interaction.transform.type = TransformMode::Grab;
                    ed.interaction.transform.pivot = ed.selection_centroid();
                    ed.interaction.transform.mouse_start = mw;
                    ed.interaction.transform.lock_x = ed.interaction.transform.lock_y = false;
                    ed.interaction.transform.numeric_buf.clear();
                    ed.interaction.transform.snapshot = ed.shot.scene;
                }

                // Transform shortcuts (G/R/S)
                if (!ed.interaction.selection.empty()) {
                    auto start_transform = [&](TransformMode::Type type) {
                        ed.interaction.transform.type = type;
                        ed.interaction.transform.pivot = ed.selection_centroid();
                        ed.interaction.transform.mouse_start = mw;
                        ed.interaction.transform.lock_x = ed.interaction.transform.lock_y = false;
                        ed.interaction.transform.numeric_buf.clear();
                        ed.interaction.transform.snapshot = ed.shot.scene;
                        ed.session.undo.push(ed.shot.scene);
                    };

                    if (ImGui::IsKeyPressed(ImGuiKey_G)) start_transform(TransformMode::Grab);
                    if (ImGui::IsKeyPressed(ImGuiKey_R)) start_transform(TransformMode::Rotate);
                    if (ImGui::IsKeyPressed(ImGuiKey_S) && !io.KeyCtrl) start_transform(TransformMode::Scale);
                }

                // Tool switching
                if (!io.KeyCtrl && !io.KeyAlt) {
                    auto switch_tool = [&](EditTool t) {
                        if (ed.interaction.tool == EditTool::Measure && t != EditTool::Measure)
                            ed.interaction.measure_active = false;
                        if (t != EditTool::Path)
                            ed.interaction.path_create_points.clear();
                        ed.interaction.creating = false;
                        ed.interaction.tool = t;
                    };
                    if (ImGui::IsKeyPressed(ImGuiKey_Q)) switch_tool(EditTool::Select);
                    if (ImGui::IsKeyPressed(ImGuiKey_X) && !ed.interaction.transform.active()) switch_tool(EditTool::Erase);
                    if (ImGui::IsKeyPressed(ImGuiKey_M)) switch_tool(EditTool::Measure);

                    // Wireframe toggle: V
                    if (ImGui::IsKeyPressed(ImGuiKey_V))
                        panel.show_wireframe = !panel.show_wireframe;

                    // Material cycling: N / Shift+N
                    if (ImGui::IsKeyPressed(ImGuiKey_N) && !ed.interaction.selection.empty()) {
                        auto& mats = ed.shot.scene.materials;
                        if (!mats.empty()) {
                            // Find the first selected shape's material
                            for (auto& sid : ed.interaction.selection) {
                                if (Shape* shape = resolve_shape(ed.shot.scene, sid)) {
                                    const std::string& cur = shape_material_id(*shape);
                                    auto it = mats.find(cur);
                                    if (io.KeyShift) {
                                        if (it == mats.end() || it == mats.begin())
                                            it = std::prev(mats.end());
                                        else
                                            --it;
                                    } else {
                                        if (it == mats.end())
                                            it = mats.begin();
                                        else if (++it == mats.end())
                                            it = mats.begin();
                                    }
                                    ed.session.undo.push(ed.shot.scene);
                                    bind_material(*shape, ed.shot.scene, it->first);
                                    reload();
                                    break;
                                }
                            }
                        }
                    }

                    // Join mode cycle: J (polygon only)
                    // Auto → Sharp → Smooth → Auto (mixed resets to Auto)
                    if (ImGui::IsKeyPressed(ImGuiKey_J) && !ed.interaction.selection.empty()) {
                        for (auto& sid : ed.interaction.selection) {
                            if (Shape* shape = resolve_shape(ed.shot.scene, sid)) {
                                if (auto* poly = std::get_if<Polygon>(shape)) {
                                    if (poly->vertices.empty()) break;
                                    ed.session.undo.push(ed.shot.scene);
                                    if (poly->join_modes.empty()) {
                                        poly->join_modes.assign(poly->vertices.size(), PolygonJoinMode::Sharp);
                                    } else if (std::all_of(poly->join_modes.begin(), poly->join_modes.end(),
                                                   [](PolygonJoinMode m) { return m == PolygonJoinMode::Sharp; })) {
                                        poly->join_modes.assign(poly->vertices.size(), PolygonJoinMode::Smooth);
                                    } else {
                                        poly->join_modes.clear();
                                    }
                                    reload();
                                    break;
                                }
                            }
                        }
                    }
                }

                // Visibility: H = toggle selected, Alt+H = show all
                if (ImGui::IsKeyPressed(ImGuiKey_H)) {
                    if (io.KeyAlt) {
                        ed.visibility.show_all();
                    } else {
                        for (auto& sid : ed.interaction.selection) {
                            if (sid.type == SelectionRef::Shape) ed.visibility.toggle_shape(sid.id);
                            else if (sid.type == SelectionRef::Light) ed.visibility.toggle_light(sid.id);
                            else if (sid.type == SelectionRef::Group) ed.visibility.toggle_group(sid.id);
                        }
                    }
                    reload();
                }

                // Authored camera toggle: 0
                if (!compare_ab.active && !io.KeyShift && !io.KeyCtrl && !io.KeyAlt
                    && (ImGui::IsKeyPressed(ImGuiKey_0) || ImGui::IsKeyPressed(ImGuiKey_Keypad0)) && !ed.shot.camera.empty()) {
                    if (ed.view.showing_authored_camera) {
                        // Restore free camera
                        if (ed.view.saved_free_camera)
                            ed.view.camera = *ed.view.saved_free_camera;
                        ed.view.showing_authored_camera = false;
                    } else {
                        // Snap to authored camera
                        ed.view.saved_free_camera = ed.view.camera;
                        Bounds cam_bounds = ed.shot.camera.resolve(ed.shot.canvas.aspect(), ed.view.scene_bounds);
                        ed.view.camera.fit(cam_bounds, (float)win_w, (float)win_h);
                        ed.view.showing_authored_camera = true;
                    }
                    auto bounds = ed.view.camera.visible_bounds((float)win_w, (float)win_h);
                    renderer.update_viewport(bounds);
                    renderer.redraw_fills(bounds);
                    renderer.clear();
                }

                // Fit to view
                if (!compare_ab.active && ImGui::IsKeyPressed(ImGuiKey_F)) {
                    ed.view.showing_authored_camera = false;
                    if (!ed.interaction.selection.empty()) {
                        Bounds sb = ed.selection_bounds();
                        Vec2 sz = sb.max - sb.min;
                        Vec2 scene_sz = ed.view.scene_bounds.max - ed.view.scene_bounds.min;
                        float min_pad = std::max(scene_sz.x, scene_sz.y) * 0.2f;
                        float pad = std::max(std::max(sz.x, sz.y) * 0.2f, min_pad);
                        sb.min = sb.min - Vec2{pad, pad};
                        sb.max = sb.max + Vec2{pad, pad};
                        ed.view.camera.fit(sb, (float)win_w, (float)win_h);
                    } else {
                        ed.view.camera.fit(ed.view.scene_bounds, (float)win_w, (float)win_h);
                    }
                    {
                        auto fit_bounds = ed.view.camera.visible_bounds((float)win_w, (float)win_h);
                        renderer.update_viewport(fit_bounds);
                        renderer.redraw_fills(fit_bounds);
                        renderer.clear();
                    }
                }
                if (!compare_ab.active && ImGui::IsKeyPressed(ImGuiKey_Home)) {
                    ed.view.showing_authored_camera = false;
                    ed.view.camera.fit(ed.view.scene_bounds, (float)win_w, (float)win_h);
                    {
                        auto home_bounds = ed.view.camera.visible_bounds((float)win_w, (float)win_h);
                        renderer.update_viewport(home_bounds);
                        renderer.redraw_fills(home_bounds);
                        renderer.clear();
                    }
                }

                // Space: pause
                if (ImGui::IsKeyPressed(ImGuiKey_Space)) panel.paused = !panel.paused;

                // Enter finalizes path creation
                if (ImGui::IsKeyPressed(ImGuiKey_Enter) && !ed.interaction.path_create_points.empty()) {
                    finalize_path_creation();
                }

                // Escape cascade
                if (ImGui::IsKeyPressed(ImGuiKey_Escape)) {
                    if (!ed.interaction.path_create_points.empty()) {
                        ed.interaction.path_create_points.clear();
                        ed.interaction.tool = EditTool::Select;
                    } else if (ed.interaction.tool == EditTool::Path) {
                        ed.interaction.tool = EditTool::Select;
                    } else if (ed.interaction.tool == EditTool::Measure && ed.interaction.measure_active) {
                        ed.interaction.measure_active = false;
                    } else if (ed.interaction.creating) {
                        ed.interaction.creating = false;
                        if (is_add_tool(ed.interaction.tool))
                            ed.interaction.tool = EditTool::Select;
                    } else if (is_add_tool(ed.interaction.tool)) {
                        ed.interaction.tool = EditTool::Select;
                    } else if (!ed.interaction.editing_group_id.empty()) {
                        ed.interaction.editing_group_id.clear();
                        ed.clear_selection();
                    } else if (!ed.interaction.selection.empty()) {
                        ed.clear_selection();
                    } else {
                        ed.interaction.tool = EditTool::Select;
                    }
                }

                // Delete
                if (ImGui::IsKeyPressed(ImGuiKey_Delete) || ImGui::IsKeyPressed(ImGuiKey_Backspace)) {
                    delete_selected(ed, renderer, compare_ab, panel.light_analysis_valid,
                                    win_w, win_h);
                }
            }
        }

        // ── Update window title (only when changed) ────────────────────

        {
            static std::string last_title;
            char title[256];
            std::snprintf(title, sizeof(title), "lpt2d \xe2\x80\x94 %s%s",
                ed.shot.name.empty() ? "untitled" : ed.shot.name.c_str(),
                ed.session.dirty ? " *" : "");
            if (last_title != title) { glfwSetWindowTitle(window, title); last_title = title; }
        }

        // ── Render ──────────────────────────────────────────────────────

        ImGui::Render();
        ImGui_ImplOpenGL3_RenderDrawData(ImGui::GetDrawData());
        glfwSwapBuffers(window);

        auto t1 = std::chrono::steady_clock::now();
        frame_ms = std::chrono::duration<float, std::milli>(t1 - t0).count();
    }

    ImGui_ImplOpenGL3_Shutdown();
    ImGui_ImplGlfw_Shutdown();
    ImGui::DestroyContext();
    destroy_compare_snapshot(compare_ab);
    renderer.shutdown();
    glfwDestroyWindow(window);
    glfwTerminate();
    return 0;
}
