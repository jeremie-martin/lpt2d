#include "app.h"

#include "app_actions.h"
#include "app_panels.h"
#include "editor.h"
#include "geometry.h"
#include "renderer.h"
#include "scene.h"
#include "scenes.h"
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
#include <iostream>
#include <map>
#include <optional>
#include <ratio>
#include <utility>
#include <variant>
#include <vector>

namespace {

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

    Camera display_camera;
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
    panel.current_scene = 0;
    if (!config.initial_scene.empty()) {
        bool found = false;
        for (int i = 0; i < (int)builtins.size(); ++i) {
            if (builtins[i].name == config.initial_scene) { panel.current_scene = i; found = true; break; }
        }
        if (!found)
            std::cerr << "Unknown scene: " << config.initial_scene << ", using " << builtins[0].name << "\n";
    }
    ed.shot = load_builtin_scene(builtins[panel.current_scene]);
    ed.shot.trace.batch = kGuiTraceBatch;
    ed.view.scene_bounds = compute_bounds(ed.shot.scene);
    ed.view.camera.fit(ed.view.scene_bounds, (float)win_w, (float)win_h);

    Bounds initial_view = ed.view.camera.visible_bounds((float)win_w, (float)win_h);
    renderer.upload_scene(ed.shot.scene, initial_view);
    renderer.clear();
    ed.session.undo.push(ed.shot.scene); // initial state

    CompareSnapshot compare_ab;
    FrameMetrics live_metrics{};
    int stats_counter = 30; // trigger immediate compute on first frame
    bool force_live_metrics_refresh = true;
    float frame_ms = 16.0f;

    auto make_default_arc = [](Vec2 center, Vec2 target) {
        Vec2 delta = target - center;
        float angle = delta.length_sq() > 1e-10f
            ? normalize_angle(std::atan2(delta.y, delta.x))
            : 0.0f;
        Arc arc;
        arc.center = center;
        arc.radius = std::max(delta.length(), 0.02f);
        arc.angle_start = normalize_angle(angle - 0.5f * PI);
        arc.sweep = PI;
        arc.binding = mat_glass(1.5f, 20000.0f, 0.3f);
        return arc;
    };

    // Shorthand reload via extracted function
    auto reload = [&](bool mark_dirty = true) {
        reload_scene(ed, renderer, compare_ab, panel.light_analysis_valid,
                     force_live_metrics_refresh, win_w, win_h, mark_dirty);
    };

    auto sanitize_clipboard_material_bindings = [&]() {
        auto for_each = [&](auto&& fn) {
            for (auto& shape : ed.session.clipboard.shapes) fn(shape);
            for (auto& group : ed.session.clipboard.groups)
                for (auto& shape : group.shapes) fn(shape);
        };
        for_each([&](Shape& shape) {
            auto ref = material_ref_id(shape_binding(shape));
            if (!ref.empty() && !ed.shot.scene.materials.contains(std::string(ref)))
                shape_binding(shape) = Material{};
        });
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

    // ── Main loop ───────────────────────────────────────────────────────

    while (!glfwWindowShouldClose(window)) {
        glfwPollEvents();

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
        Camera active_camera = current_display_camera(ed, compare_ab, win_w, win_h);
        CameraView cv{active_camera, (float)win_w, (float)win_h};
        bool showing_snapshot_a = compare_ab.active && compare_ab.showing_a;

        // Trace
        auto t0 = std::chrono::steady_clock::now();
        if (!showing_snapshot_a && !panel.paused && renderer.num_lights() > 0) {
            TraceConfig trace_cfg = ed.shot.trace.to_trace_config(ed.session.frame_index);
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
            live_metrics = compare_ab.metrics;
        } else if (force_live_metrics_refresh || ++stats_counter >= 30) {
            stats_counter = 0;
            force_live_metrics_refresh = false;
            live_metrics = renderer.compute_display_metrics();
        }

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
                bool is_hov = (ed.interaction.hovered == ref);
                bool hidden = !ed.visibility.is_shape_visible(sid);
                ImU32 col = hidden ? IM_COL32(100, 100, 110, 30)
                                   : (is_sel ? COL_SHAPE_SEL : (is_hov ? COL_SHAPE_HOV : COL_SHAPE));
                float th = hidden ? 1.0f * dpi_scale : (is_sel ? 2.5f : 1.5f) * dpi_scale;

                if (ed.interaction.transform.active() && is_sel) {
                    if (const Shape* snap = find_shape_in(ed.interaction.transform.snapshot.shapes, sid)) {
                        draw_shape_overlay(dl, cv, *snap, COL_GHOST_SHAPE, 1.0f * dpi_scale);
                        draw_shape_overlay(dl, cv, shape, COL_SHAPE_SEL, 2.5f * dpi_scale);
                    } else {
                        draw_shape_overlay(dl, cv, shape, col, th);
                    }
                } else {
                    if (is_sel && !hidden && !ed.interaction.transform.active())
                        draw_shape_overlay(dl, cv, shape, COL_SHAPE_SEL_GLOW, 6.0f * dpi_scale);
                    draw_shape_overlay(dl, cv, shape, col, th);
                }
            }

            for (int i = 0; i < (int)ed.shot.scene.lights.size(); ++i) {
                const auto& light = ed.shot.scene.lights[i];
                const auto& lid = light_id(light);
                SelectionRef ref{SelectionRef::Light, lid, ""};
                bool is_sel = ed.is_selected(ref);
                bool is_hov = (ed.interaction.hovered == ref);
                bool hidden = !ed.visibility.is_light_visible(lid);
                ImU32 col = hidden ? IM_COL32(200, 180, 40, 30)
                                   : (is_sel ? COL_LIGHT_SEL : (is_hov ? COL_LIGHT_HOV : COL_LIGHT));
                float th = hidden ? 1.0f * dpi_scale : (is_sel ? 3.0f : 2.0f) * dpi_scale;

                if (ed.interaction.transform.active() && is_sel) {
                    if (const Light* snap = find_light_in(ed.interaction.transform.snapshot.lights, lid)) {
                        draw_light_overlay(dl, cv, *snap, COL_GHOST_LIGHT, 1.0f * dpi_scale, dpi_scale);
                        draw_light_overlay(dl, cv, light, COL_LIGHT_SEL, 3.0f * dpi_scale, dpi_scale);
                    } else {
                        draw_light_overlay(dl, cv, light, col, th, dpi_scale);
                    }
                } else {
                    draw_light_overlay(dl, cv, light, col, th, dpi_scale);
                }
            }

            // Draw groups
            for (const auto& group : ed.shot.scene.groups) {
                SelectionRef gid{SelectionRef::Group, group.id, ""};
                bool is_sel = ed.is_selected(gid);
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
                float s_th = hidden ? 1.0f * dpi_scale : (is_sel ? 2.5f : 1.5f) * dpi_scale;
                float l_th = hidden ? 1.0f * dpi_scale : (is_sel ? 3.0f : 2.0f) * dpi_scale;

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
                ImVec2 delta = io.MouseDelta;
                ed.view.camera.center.x -= delta.x / ed.view.camera.zoom;
                ed.view.camera.center.y += delta.y / ed.view.camera.zoom;
                renderer.update_viewport(ed.view.camera.visible_bounds((float)win_w, (float)win_h));
                renderer.clear();
            }

            if (io.MouseWheel != 0) {
                if (io.KeyAlt && !ImGui::IsMouseDragging(0)) {
                    ed.shot.look.exposure += io.MouseWheel * 0.5f;
                } else if (!compare_view_locked) {
                    Vec2 world_before = cv.to_world(io.MousePos);
                    float factor = (io.MouseWheel > 0) ? 1.1f : (1.0f / 1.1f);
                    ed.view.camera.zoom *= factor;
                    ed.view.camera.zoom = std::clamp(ed.view.camera.zoom, 1.0f, 100000.0f);
                    CameraView cv2{ed.view.camera, (float)win_w, (float)win_h};
                    Vec2 world_after = cv2.to_world(io.MousePos);
                    ed.view.camera.center = ed.view.camera.center + (world_before - world_after);
                    cv = CameraView{ed.view.camera, (float)win_w, (float)win_h};
                    renderer.update_viewport(ed.view.camera.visible_bounds((float)win_w, (float)win_h));
                    renderer.clear();
                }
            }
        }

        // --- Tool interactions ---

        bool panning = (io.KeyAlt && ImGui::IsMouseDown(0)) || ImGui::IsMouseDown(2);

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
                        if (!member.id.empty()) ed.select(member);
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
                                ed.toggle_select(hit);
                            } else if (!ed.is_selected(hit)) {
                                ed.clear_selection();
                                ed.select(hit);
                            }
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
                                    }, *shape);
                                } else if (const Light* light = resolve_light(ed.shot.scene, sid)) {
                                    std::visit(overloaded{
                                        [&](const PointLight& l) { ed.interaction.drag_offsets.push_back({l.pos - mw_raw, {}}); },
                                        [&](const SegmentLight& l) { ed.interaction.drag_offsets.push_back({l.a - mw_raw, l.b - mw_raw}); },
                                        [&](const ProjectorLight& l) { ed.interaction.drag_offsets.push_back({l.position - mw_raw, {}}); },
                                    }, *light);
                                } else if (sid.type == SelectionRef::Group) {
                                    if (const Group* g = find_group(ed.shot.scene, sid.id))
                                        ed.interaction.drag_offsets.push_back({g->transform.translate - mw_raw, {}});
                                }
                            }
                        } else {
                            if (!io.KeyShift) ed.clear_selection();
                            ed.interaction.box_selecting = true;
                            ed.interaction.box_start = io.MousePos;
                        }
                    }
                } else if (ed.interaction.tool == EditTool::Erase) {
                    SelectionRef hit = hit_test(mw_raw, ed.shot.scene, hit_thresh, ed.interaction.editing_group_id);
                    if (!hit.id.empty()) {
                        ed.clear_selection();
                        ed.select(hit);
                        delete_selected(ed, renderer, compare_ab, panel.light_analysis_valid,
                                        force_live_metrics_refresh, win_w, win_h);
                    }
                } else if (ed.interaction.tool == EditTool::PointLight) {
                    ed.session.undo.push(ed.shot.scene);
                    PointLight light;
                    light.id = next_scene_entity_id(ed.shot.scene, "point_light");
                    light.pos = mw;
                    light.intensity = 1.0f;
                    ed.shot.scene.lights.push_back(light);
                    ed.clear_selection();
                    ed.select({SelectionRef::Light, light.id, ""});
                    reload();
                } else if (ed.interaction.tool == EditTool::ProjectorLight) {
                    ed.session.undo.push(ed.shot.scene);
                    ProjectorLight light;
                    light.id = next_scene_entity_id(ed.shot.scene, "projector_light");
                    light.position = mw;
                    light.direction = {1.0f, 0.0f};
                    light.intensity = 1.0f;
                    ed.shot.scene.lights.push_back(light);
                    ed.clear_selection();
                    ed.select({SelectionRef::Light, light.id, ""});
                    reload();
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
                    }, *shape);
                } else if (Light* light = resolve_light(ed.shot.scene, sid)) {
                    std::visit(overloaded{
                        [&](PointLight& l) { l.pos = mw + off.a; },
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
                    circle.binding = mat_glass(1.5f, 20000.0f, 0.3f);
                    ed.shot.scene.shapes.push_back(circle);
                    ed.clear_selection();
                    ed.select({SelectionRef::Shape, circle.id, ""});
                    created = true;
                } else if (ed.interaction.tool == EditTool::Segment && dist > 0.01f) {
                    Segment segment;
                    segment.id = next_scene_entity_id(ed.shot.scene, "segment");
                    segment.a = ed.interaction.create_start;
                    segment.b = end;
                    segment.binding = mat_mirror(0.95f);
                    ed.shot.scene.shapes.push_back(segment);
                    ed.clear_selection();
                    ed.select({SelectionRef::Shape, segment.id, ""});
                    created = true;
                } else if (ed.interaction.tool == EditTool::Arc) {
                    Arc arc = make_default_arc(ed.interaction.create_start, end);
                    arc.id = next_scene_entity_id(ed.shot.scene, "arc");
                    ed.shot.scene.shapes.push_back(arc);
                    ed.clear_selection();
                    ed.select({SelectionRef::Shape, arc.id, ""});
                    created = true;
                } else if (ed.interaction.tool == EditTool::Bezier && dist > 0.01f) {
                    Vec2 mid = (ed.interaction.create_start + end) * 0.5f;
                    Bezier bezier;
                    bezier.id = next_scene_entity_id(ed.shot.scene, "bezier");
                    bezier.p0 = ed.interaction.create_start;
                    bezier.p1 = mid;
                    bezier.p2 = end;
                    bezier.binding = mat_glass(1.5f, 20000.0f, 0.3f);
                    ed.shot.scene.shapes.push_back(bezier);
                    ed.clear_selection();
                    ed.select({SelectionRef::Shape, bezier.id, ""});
                    created = true;
                } else if (ed.interaction.tool == EditTool::Polygon && dist > 0.01f) {
                    Vec2 a = ed.interaction.create_start, b = end;
                    Polygon p;
                    p.id = next_scene_entity_id(ed.shot.scene, "polygon");
                    p.vertices = {{a.x, a.y}, {b.x, a.y}, {b.x, b.y}, {a.x, b.y}};
                    if (!polygon_is_clockwise(p))
                        std::reverse(p.vertices.begin(), p.vertices.end());
                    p.binding = mat_glass(1.5f, 20000.0f, 0.3f);
                    ed.shot.scene.shapes.push_back(p);
                    ed.clear_selection();
                    ed.select({SelectionRef::Shape, p.id, ""});
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
                    ellipse.binding = mat_glass(1.5f, 20000.0f, 0.3f);
                    ed.shot.scene.shapes.push_back(ellipse);
                    ed.clear_selection();
                    ed.select({SelectionRef::Shape, ellipse.id, ""});
                    created = true;
                } else if (ed.interaction.tool == EditTool::SegmentLight && dist > 0.01f) {
                    SegmentLight light;
                    light.id = next_scene_entity_id(ed.shot.scene, "segment_light");
                    light.a = ed.interaction.create_start;
                    light.b = end;
                    light.intensity = 1.0f;
                    ed.shot.scene.lights.push_back(light);
                    ed.clear_selection();
                    ed.select({SelectionRef::Light, light.id, ""});
                    created = true;
                }

                if (created) reload();
                else { ed.session.undo.snapshots.pop_back(); ed.session.undo.current--; }
                ed.interaction.creating = false;
            }

            // Complete box selection
            if (ed.interaction.box_selecting) {
                ImVec2 cur = io.MousePos;
                Vec2 wmin = cv.to_world(ImVec2(std::min(ed.interaction.box_start.x, cur.x), std::max(ed.interaction.box_start.y, cur.y)));
                Vec2 wmax = cv.to_world(ImVec2(std::max(ed.interaction.box_start.x, cur.x), std::min(ed.interaction.box_start.y, cur.y)));

                if (!io.KeyShift) ed.clear_selection();
                for (const auto& s : ed.shot.scene.shapes) {
                    SelectionRef ref{SelectionRef::Shape, shape_id(s), ""};
                    if (object_in_rect(ed.shot.scene, ref, wmin, wmax))
                        ed.select(ref);
                }
                for (const auto& l : ed.shot.scene.lights) {
                    SelectionRef ref{SelectionRef::Light, light_id(l), ""};
                    if (object_in_rect(ed.shot.scene, ref, wmin, wmax))
                        ed.select(ref);
                }
                for (const auto& g : ed.shot.scene.groups) {
                    SelectionRef ref{SelectionRef::Group, g.id, ""};
                    if (object_in_rect(ed.shot.scene, ref, wmin, wmax))
                        ed.select(ref);
                }
                ed.interaction.box_selecting = false;
            }

            ed.interaction.dragging = false;
            ed.interaction.handle_dragging = false;
            ed.interaction.drag_offsets.clear();
        }

        // ── Controls panel ──────────────────────────────────────────────

        draw_controls_panel(ed, renderer, compare_ab, panel, live_metrics,
                            force_live_metrics_refresh, io, dpi_scale,
                            frame_ms, win_w, win_h, fb_w, fb_h);

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

                // Numeric input
                for (int k = ImGuiKey_0; k <= ImGuiKey_9; ++k) {
                    if (ImGui::IsKeyPressed((ImGuiKey)k))
                        ed.interaction.transform.numeric_buf += ('0' + (k - ImGuiKey_0));
                }
                if (ImGui::IsKeyPressed(ImGuiKey_Period))
                    ed.interaction.transform.numeric_buf += '.';
                if (ImGui::IsKeyPressed(ImGuiKey_Minus))
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
                    if (ed.session.undo.redo(ed.shot.scene)) { ed.validate_selection(); reload(); }
                } else if (io.KeyCtrl && ImGui::IsKeyPressed(ImGuiKey_Z)) {
                    if (ed.session.undo.undo(ed.shot.scene)) { ed.validate_selection(); reload(); }
                }

                // Exposure nudge: [ / ]
                if (ImGui::IsKeyPressed(ImGuiKey_LeftBracket)) ed.shot.look.exposure -= 0.5f;
                if (ImGui::IsKeyPressed(ImGuiKey_RightBracket)) ed.shot.look.exposure += 0.5f;

                // A/B look toggle: ` (grave accent)
                if (ImGui::IsKeyPressed(ImGuiKey_GraveAccent) && compare_ab.active) {
                    compare_ab.showing_a = !compare_ab.showing_a;
                    if (!compare_ab.showing_a)
                        reload(false);
                    force_live_metrics_refresh = true;
                }

                // Save/Load
                if (io.KeyCtrl && ImGui::IsKeyPressed(ImGuiKey_S)) { do_save(ed); }
                if (io.KeyCtrl && ImGui::IsKeyPressed(ImGuiKey_O)) {
                    panel.open_load_popup = true;
                }

                // Select all
                if (io.KeyCtrl && ImGui::IsKeyPressed(ImGuiKey_A)) {
                    ed.select_all();
                }

                // Group / Ungroup
                if (io.KeyCtrl && io.KeyShift && ImGui::IsKeyPressed(ImGuiKey_G)) {
                    ungroup_selected(ed, renderer, compare_ab, panel.light_analysis_valid,
                                     force_live_metrics_refresh, win_w, win_h);
                } else if (io.KeyCtrl && ImGui::IsKeyPressed(ImGuiKey_G)) {
                    group_selected(ed, renderer, compare_ab, panel.light_analysis_valid,
                                   force_live_metrics_refresh, win_w, win_h);
                }

                // Copy/Paste/Cut/Duplicate
                if (io.KeyCtrl && ImGui::IsKeyPressed(ImGuiKey_C)) {
                    copy_to_clipboard(ed);
                }

                if (io.KeyCtrl && ImGui::IsKeyPressed(ImGuiKey_V) && !ed.session.clipboard.empty()) {
                    ed.session.undo.push(ed.shot.scene);
                    Vec2 offset = mw - ed.session.clipboard.centroid;
                    sanitize_clipboard_material_bindings();
                    ed.clear_selection();
                    for (auto s : ed.session.clipboard.shapes) {
                        translate_shape(s, offset);
                        ed.shot.scene.shapes.push_back(s);
                        ed.select({SelectionRef::Shape, shape_id(s), ""});
                    }
                    for (auto l : ed.session.clipboard.lights) {
                        translate_light(l, offset);
                        ed.shot.scene.lights.push_back(l);
                        ed.select({SelectionRef::Light, light_id(l), ""});
                    }
                    for (auto g : ed.session.clipboard.groups) {
                        translate_group(g, offset);
                        ed.shot.scene.groups.push_back(g);
                        ed.select({SelectionRef::Group, g.id, ""});
                    }
                    reload();
                }

                if (io.KeyCtrl && ImGui::IsKeyPressed(ImGuiKey_X)) {
                    copy_to_clipboard(ed);
                    delete_selected(ed, renderer, compare_ab, panel.light_analysis_valid,
                                    force_live_metrics_refresh, win_w, win_h);
                }

                if (io.KeyCtrl && ImGui::IsKeyPressed(ImGuiKey_D) && !ed.interaction.selection.empty()) {
                    ed.session.undo.push(ed.shot.scene);
                    std::vector<SelectionRef> new_sel;
                    Vec2 offset{0.05f, 0.05f};
                    for (auto& sid : ed.interaction.selection) {
                        if (const Shape* shape = resolve_shape(ed.shot.scene, sid)) {
                            Shape s = *shape;
                            shape_id(s) = next_scene_entity_id(ed.shot.scene, shape_type_name(s));
                            translate_shape(s, offset);
                            ed.shot.scene.shapes.push_back(s);
                            new_sel.push_back({SelectionRef::Shape, shape_id(s), ""});
                        } else if (const Light* light = resolve_light(ed.shot.scene, sid)) {
                            Light l = *light;
                            light_id(l) = next_scene_entity_id(ed.shot.scene, light_type_name(l));
                            translate_light(l, offset);
                            ed.shot.scene.lights.push_back(l);
                            new_sel.push_back({SelectionRef::Light, light_id(l), ""});
                        } else if (sid.type == SelectionRef::Group) {
                            if (const Group* gp = find_group(ed.shot.scene, sid.id)) {
                                Group g = *gp;
                                g.id = next_scene_entity_id(ed.shot.scene, "group");
                                translate_group(g, offset);
                                ed.shot.scene.groups.push_back(g);
                                new_sel.push_back({SelectionRef::Group, g.id, ""});
                            }
                        }
                    }
                    ed.interaction.selection = new_sel;

                    ed.interaction.transform.type = TransformMode::Grab;
                    ed.interaction.transform.pivot = ed.selection_centroid();
                    ed.interaction.transform.mouse_start = mw;
                    ed.interaction.transform.lock_x = ed.interaction.transform.lock_y = false;
                    ed.interaction.transform.numeric_buf.clear();
                    ed.interaction.transform.snapshot = ed.shot.scene;
                    reload();
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
                        if (ed.interaction.tool == EditTool::Measure) ed.interaction.measure_active = false;
                        ed.interaction.tool = t;
                    };
                    if (ImGui::IsKeyPressed(ImGuiKey_Q)) switch_tool(EditTool::Select);
                    if (ImGui::IsKeyPressed(ImGuiKey_C)) switch_tool(EditTool::Circle);
                    if (ImGui::IsKeyPressed(ImGuiKey_L)) switch_tool(EditTool::Segment);
                    if (ImGui::IsKeyPressed(ImGuiKey_A) && !io.KeyCtrl) switch_tool(EditTool::Arc);
                    if (ImGui::IsKeyPressed(ImGuiKey_B)) switch_tool(EditTool::Bezier);
                    if (ImGui::IsKeyPressed(ImGuiKey_E)) switch_tool(EditTool::Ellipse);
                    if (ImGui::IsKeyPressed(ImGuiKey_X) && !ed.interaction.transform.active()) switch_tool(EditTool::Erase);
                    if (ImGui::IsKeyPressed(ImGuiKey_P)) switch_tool(EditTool::PointLight);
                    if (ImGui::IsKeyPressed(ImGuiKey_T)) switch_tool(EditTool::SegmentLight);
                    if (ImGui::IsKeyPressed(ImGuiKey_W)) switch_tool(EditTool::ProjectorLight);
                    if (ImGui::IsKeyPressed(ImGuiKey_M)) switch_tool(EditTool::Measure);
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

                // Fit to view
                if (!compare_ab.active && ImGui::IsKeyPressed(ImGuiKey_F)) {
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
                    renderer.update_viewport(ed.view.camera.visible_bounds((float)win_w, (float)win_h));
                    renderer.clear();
                }
                if (!compare_ab.active && ImGui::IsKeyPressed(ImGuiKey_Home)) {
                    ed.view.camera.fit(ed.view.scene_bounds, (float)win_w, (float)win_h);
                    renderer.update_viewport(ed.view.camera.visible_bounds((float)win_w, (float)win_h));
                    renderer.clear();
                }

                // Space: pause
                if (ImGui::IsKeyPressed(ImGuiKey_Space)) panel.paused = !panel.paused;

                // Escape cascade
                if (ImGui::IsKeyPressed(ImGuiKey_Escape)) {
                    if (ed.interaction.tool == EditTool::Measure && ed.interaction.measure_active) {
                        ed.interaction.measure_active = false;
                    } else if (ed.interaction.creating) {
                        ed.interaction.creating = false;
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
                                    force_live_metrics_refresh, win_w, win_h);
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
