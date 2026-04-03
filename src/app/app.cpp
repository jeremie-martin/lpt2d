#include "app.h"

#include "editor.h"
#include "export.h"
#include "renderer.h"
#include "scenes.h"
#include "serialize.h"
#include "ui.h"

#include <GL/glew.h>
#include <GLFW/glfw3.h>
#include <imgui.h>
#include <imgui_impl_glfw.h>
#include <imgui_impl_opengl3.h>

#include <algorithm>
#include <chrono>
#include <cstdio>
#include <cstring>
#include <iostream>

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

    int current_scene = 0;
    if (!config.initial_scene.empty()) {
        bool found = false;
        for (int i = 0; i < (int)builtins.size(); ++i) {
            if (builtins[i].name == config.initial_scene) { current_scene = i; found = true; break; }
        }
        if (!found)
            std::cerr << "Unknown scene: " << config.initial_scene << ", using " << builtins[0].name << "\n";
    }
    ed.scene = load_builtin_scene(builtins[current_scene]);
    ed.scene_bounds = compute_bounds(ed.scene);
    ed.camera.fit(ed.scene_bounds, (float)win_w, (float)win_h);

    Bounds initial_view = ed.camera.visible_bounds((float)win_w, (float)win_h);
    renderer.upload_scene(ed.scene, initial_view);
    renderer.clear();
    ed.undo.push(ed.scene); // initial state

    TraceConfig tcfg;
    tcfg.batch_size = 50000;
    PostProcess pp;
    // total rays tracked by renderer.total_rays()
    bool paused = false;
    float frame_ms = 16.0f;
    bool show_wireframe = true;
    bool open_load_popup = false;

    // Reload: re-upload scene to GPU, clear accumulation
    // Renderer viewport always tracks the camera's visible bounds.
    auto reload = [&]() {
        if (ed.scene.shapes.empty() && ed.scene.lights.empty() && ed.scene.groups.empty())
            ed.scene_bounds = {{-1, -1}, {1, 1}};
        else
            ed.scene_bounds = compute_bounds(ed.scene);
        Bounds view = ed.camera.visible_bounds((float)win_w, (float)win_h);
        renderer.upload_scene(ed.scene, view);
        renderer.clear();
        ed.dirty = true;
    };

    auto do_save = [&]() {
        std::string path = ed.save_path.empty() ? (ed.scene.name + ".json") : ed.save_path;
        if (save_scene_json(ed.scene, path)) {
            ed.save_path = path;
            ed.dirty = false;
            std::cerr << "Saved: " << path << "\n";
        }
    };

    auto copy_to_clipboard = [&]() {
        ed.clipboard.shapes.clear();
        ed.clipboard.lights.clear();
        ed.clipboard.groups.clear();
        for (auto& sid : ed.selection) {
            if (sid.type == ObjectId::Shape) ed.clipboard.shapes.push_back(ed.scene.shapes[sid.index]);
            else if (sid.type == ObjectId::Light) ed.clipboard.lights.push_back(ed.scene.lights[sid.index]);
            else if (sid.type == ObjectId::Group) ed.clipboard.groups.push_back(ed.scene.groups[sid.index]);
        }
        ed.clipboard.centroid = ed.selection_centroid();
    };

    auto reset_editor = [&]() {
        ed.clear_selection();
        ed.creating = false;
        ed.dragging = false;
        ed.handle_dragging = false;
        ed.undo.clear();
        ed.undo.push(ed.scene);
        // Fit camera before reload so renderer uses correct visible bounds
        ed.scene_bounds = ed.scene.shapes.empty() && ed.scene.lights.empty()
            ? Bounds{{-1, -1}, {1, 1}} : compute_bounds(ed.scene);
        ed.camera.fit(ed.scene_bounds, (float)win_w, (float)win_h);
        reload();
        ed.dirty = false;
    };

    auto delete_selected = [&]() {
        if (ed.selection.empty()) return false;
        ed.undo.push(ed.scene);

        // Sort selection in reverse order so deletion doesn't invalidate indices
        auto sorted = ed.selection;
        std::sort(sorted.begin(), sorted.end(), [](const ObjectId& a, const ObjectId& b) {
            if (a.type != b.type) return a.type > b.type; // groups (2) > lights (1) > shapes (0)
            return a.index > b.index; // higher indices first
        });
        for (auto& id : sorted) {
            if (id.type == ObjectId::Shape && id.index < (int)ed.scene.shapes.size())
                ed.scene.shapes.erase(ed.scene.shapes.begin() + id.index);
            else if (id.type == ObjectId::Light && id.index < (int)ed.scene.lights.size())
                ed.scene.lights.erase(ed.scene.lights.begin() + id.index);
            else if (id.type == ObjectId::Group && id.index < (int)ed.scene.groups.size())
                ed.scene.groups.erase(ed.scene.groups.begin() + id.index);
        }
        ed.clear_selection();
        reload();
        return true;
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
        CameraView cv{ed.camera, (float)win_w, (float)win_h};

        // Trace
        auto t0 = std::chrono::steady_clock::now();
        bool has_lights = !ed.scene.lights.empty();
        if (!has_lights) {
            for (const auto& g : ed.scene.groups) { if (!g.lights.empty()) { has_lights = true; break; } }
        }
        if (!paused && has_lights) {
            renderer.trace_and_draw(tcfg);
            glFinish();
        }
        renderer.update_display(pp);

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
        ImGui::Image((ImTextureID)(intptr_t)renderer.display_texture(),
                     ImVec2((float)win_w, (float)win_h), ImVec2(0, 1), ImVec2(1, 0));

        bool vp_hovered = ImGui::IsWindowHovered();

        // ── Wireframe overlay ───────────────────────────────────────────

        if (show_wireframe) {
            ImDrawList* dl = ImGui::GetWindowDrawList();

            Vec2 mouse_w = cv.to_world(io.MousePos);
            for (int i = 0; i < (int)ed.scene.shapes.size(); ++i) {
                ObjectId id{ObjectId::Shape, i};
                bool is_sel = ed.is_selected(id);
                bool is_hov = (ed.hovered == id);
                ImU32 col = is_sel ? COL_SHAPE_SEL : (is_hov ? COL_SHAPE_HOV : COL_SHAPE);
                float th = (is_sel ? 2.5f : 1.5f) * dpi_scale;

                if (ed.transform.active() && is_sel && i < (int)ed.transform.snapshot.shapes.size()) {
                    // Ghost at original position (dim)
                    draw_shape_overlay(dl, cv, ed.transform.snapshot.shapes[i], IM_COL32(100, 100, 110, 60), 1.0f * dpi_scale);
                    // Preview at transformed position
                    Shape preview = ed.transform.snapshot.shapes[i];
                    apply_transform_shape(preview, ed.transform.snapshot.shapes[i], ed.transform, mouse_w, io.KeyShift);
                    draw_shape_overlay(dl, cv, preview, IM_COL32(120, 180, 255, 220), 2.5f * dpi_scale);
                } else {
                    draw_shape_overlay(dl, cv, ed.scene.shapes[i], col, th);
                }
            }

            for (int i = 0; i < (int)ed.scene.lights.size(); ++i) {
                ObjectId id{ObjectId::Light, i};
                bool is_sel = ed.is_selected(id);
                bool is_hov = (ed.hovered == id);
                ImU32 col = is_sel ? COL_LIGHT_SEL : (is_hov ? COL_LIGHT_HOV : COL_LIGHT);
                float th = (is_sel ? 3.0f : 2.0f) * dpi_scale;

                if (ed.transform.active() && is_sel && i < (int)ed.transform.snapshot.lights.size()) {
                    draw_light_overlay(dl, cv, ed.transform.snapshot.lights[i], IM_COL32(200, 180, 40, 60), 1.0f * dpi_scale, dpi_scale);
                    Light preview = ed.transform.snapshot.lights[i];
                    apply_transform_light(preview, ed.transform.snapshot.lights[i], ed.transform, mouse_w, io.KeyShift);
                    draw_light_overlay(dl, cv, preview, IM_COL32(255, 240, 100, 220), 3.0f * dpi_scale, dpi_scale);
                } else {
                    draw_light_overlay(dl, cv, ed.scene.lights[i], col, th, dpi_scale);
                }
            }

            // Draw groups
            for (int g = 0; g < (int)ed.scene.groups.size(); ++g) {
                ObjectId gid{ObjectId::Group, g};
                bool is_sel = ed.is_selected(gid);
                bool is_hov = (ed.hovered == gid);

                const auto& group = ed.scene.groups[g];
                const Group* draw_group = &group;
                Group preview_group;

                if (ed.transform.active() && is_sel && g < (int)ed.transform.snapshot.groups.size()) {
                    // Ghost at original position
                    const auto& snap_group = ed.transform.snapshot.groups[g];
                    for (const auto& s : snap_group.shapes) {
                        Shape ws = transform_shape(s, snap_group.transform);
                        draw_shape_overlay(dl, cv, ws, IM_COL32(100, 100, 110, 60), 1.0f * dpi_scale);
                    }
                    for (const auto& l : snap_group.lights) {
                        Light wl = transform_light(l, snap_group.transform);
                        draw_light_overlay(dl, cv, wl, IM_COL32(200, 180, 40, 60), 1.0f * dpi_scale, dpi_scale);
                    }
                    // Preview at transformed position
                    apply_transform_group(preview_group, snap_group, ed.transform, mouse_w, io.KeyShift);
                    draw_group = &preview_group;
                }

                ImU32 shape_col = is_sel ? COL_SHAPE_SEL : (is_hov ? COL_SHAPE_HOV : COL_SHAPE);
                ImU32 light_col = is_sel ? COL_LIGHT_SEL : (is_hov ? COL_LIGHT_HOV : COL_LIGHT);
                float s_th = (is_sel ? 2.5f : 1.5f) * dpi_scale;
                float l_th = (is_sel ? 3.0f : 2.0f) * dpi_scale;

                for (const auto& s : draw_group->shapes) {
                    Shape ws = transform_shape(s, draw_group->transform);
                    draw_shape_overlay(dl, cv, ws, shape_col, s_th);
                }
                for (const auto& l : draw_group->lights) {
                    Light wl = transform_light(l, draw_group->transform);
                    draw_light_overlay(dl, cv, wl, light_col, l_th, dpi_scale);
                }

                // Draw group bounding box when selected
                if (is_sel) {
                    Bounds gb = ed.selection_bounds();
                    ImVec2 mn = cv.to_screen(gb.min);
                    ImVec2 mx = cv.to_screen(gb.max);
                    // Fix Y inversion (screen Y is flipped)
                    if (mn.y > mx.y) std::swap(mn.y, mx.y);
                    dl->AddRect(mn, mx, IM_COL32(80, 140, 235, 80), 0, 0, 1.0f * dpi_scale);
                }
            }

            // Handles for selected objects
            if (!ed.selection.empty() && ed.tool == EditTool::Select && !ed.transform.active()) {
                auto handles = get_handles(ed.scene, ed.selection);
                Vec2 mw = cv.to_world(io.MousePos);
                int hov_h = vp_hovered ? handle_hit_test(handles, mw, 8.0f / cv.cam.zoom) : -1;
                draw_handles(dl, cv, ed.scene, handles, hov_h);
            }

            // Creation preview
            if (ed.creating) {
                Vec2 mw = cv.to_world(io.MousePos);
                if (ed.tool == EditTool::Circle || ed.tool == EditTool::Arc) {
                    float r = (mw - ed.create_start).length() * cv.cam.zoom;
                    dl->AddCircle(cv.to_screen(ed.create_start), r, COL_PREVIEW, 64, 1.5f * dpi_scale);
                } else if (ed.tool == EditTool::Segment || ed.tool == EditTool::SegmentLight || ed.tool == EditTool::Bezier) {
                    dl->AddLine(cv.to_screen(ed.create_start), io.MousePos, COL_PREVIEW, 1.5f * dpi_scale);
                }
            }

            // Box selection preview
            if (ed.box_selecting) {
                ImVec2 cur = io.MousePos;
                ImVec2 mn(std::min(ed.box_start.x, cur.x), std::min(ed.box_start.y, cur.y));
                ImVec2 mx(std::max(ed.box_start.x, cur.x), std::max(ed.box_start.y, cur.y));
                dl->AddRectFilled(mn, mx, COL_BOX_SEL_FILL);
                dl->AddRect(mn, mx, COL_BOX_SEL_BORDER, 0, 0, 1.0f * dpi_scale);
            }

            // Transform pivot
            if (ed.transform.active() && ed.transform.type != TransformMode::Grab) {
                ImVec2 pp = cv.to_screen(ed.transform.pivot);
                float r = 6.0f * dpi_scale;
                dl->AddLine(ImVec2(pp.x - r, pp.y), ImVec2(pp.x + r, pp.y), COL_PIVOT, 2.0f * dpi_scale);
                dl->AddLine(ImVec2(pp.x, pp.y - r), ImVec2(pp.x, pp.y + r), COL_PIVOT, 2.0f * dpi_scale);
            }

            // Transform status text
            if (ed.transform.active()) {
                Vec2 mw = cv.to_world(io.MousePos);
                char status[128];
                switch (ed.transform.type) {
                case TransformMode::Grab: {
                    Vec2 delta = mw - ed.transform.mouse_start;
                    if (ed.transform.lock_x) delta.y = 0;
                    if (ed.transform.lock_y) delta.x = 0;
                    std::snprintf(status, sizeof(status), "Grab: dx=%.3f dy=%.3f%s",
                        delta.x, delta.y,
                        ed.transform.lock_x ? " [X]" : (ed.transform.lock_y ? " [Y]" : ""));
                    break;
                }
                case TransformMode::Rotate: {
                    Vec2 v0 = ed.transform.mouse_start - ed.transform.pivot;
                    Vec2 v1 = mw - ed.transform.pivot;
                    float angle = std::atan2(v1.y, v1.x) - std::atan2(v0.y, v0.x);
                    std::snprintf(status, sizeof(status), "Rotate: %.1f deg", angle * 180.0f / PI);
                    break;
                }
                case TransformMode::Scale: {
                    float d0 = (ed.transform.mouse_start - ed.transform.pivot).length();
                    float d1 = (mw - ed.transform.pivot).length();
                    float factor = (d0 > 1e-6f) ? d1 / d0 : 1.0f;
                    std::snprintf(status, sizeof(status), "Scale: %.2fx%s", factor,
                        ed.transform.lock_x ? " [X]" : (ed.transform.lock_y ? " [Y]" : ""));
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

        ImGui::End();
        ImGui::PopStyleVar();

        // ── Mouse interaction ───────────────────────────────────────────

        Vec2 mw = cv.to_world(io.MousePos);
        float hit_thresh = 8.0f / cv.cam.zoom;

        // Hover detection (Select tool only)
        if (vp_hovered && ed.tool == EditTool::Select && !ed.dragging && !ed.creating && !ed.box_selecting && !ed.transform.active()) {
            ObjectId hit = hit_test(mw, ed.scene, hit_thresh);
            ed.hovered = hit;
        } else if (!vp_hovered) {
            ed.hovered = {ObjectId::Shape, -1};
        }

        // --- Viewport navigation: pan & zoom ---

        // Pan: middle mouse drag or Alt+LMB drag
        if (vp_hovered) {
            bool middle_drag = ImGui::IsMouseDragging(2); // middle button
            bool alt_drag = io.KeyAlt && ImGui::IsMouseDragging(0);

            if (middle_drag || alt_drag) {
                ImVec2 delta = io.MouseDelta;
                ed.camera.center.x -= delta.x / ed.camera.zoom;
                ed.camera.center.y += delta.y / ed.camera.zoom;
                renderer.update_viewport(ed.camera.visible_bounds((float)win_w, (float)win_h));
                renderer.clear();
            }

            // Zoom: scroll wheel (cursor-centered)
            if (io.MouseWheel != 0) {
                Vec2 world_before = cv.to_world(io.MousePos);
                float factor = (io.MouseWheel > 0) ? 1.1f : (1.0f / 1.1f);
                ed.camera.zoom *= factor;
                ed.camera.zoom = std::clamp(ed.camera.zoom, 1.0f, 100000.0f);
                // Recompute cv after zoom change
                CameraView cv2{ed.camera, (float)win_w, (float)win_h};
                Vec2 world_after = cv2.to_world(io.MousePos);
                ed.camera.center = ed.camera.center + (world_before - world_after);
                cv = CameraView{ed.camera, (float)win_w, (float)win_h};
                renderer.update_viewport(ed.camera.visible_bounds((float)win_w, (float)win_h));
                renderer.clear();
            }
        }

        // --- Tool interactions ---

        // Skip tool interactions during alt-drag (pan) or middle drag
        bool panning = (io.KeyAlt && ImGui::IsMouseDown(0)) || ImGui::IsMouseDown(2);

        if (vp_hovered && !panning && !ed.transform.active()) {
            if (ImGui::IsMouseClicked(0)) {
                if (ed.tool == EditTool::Select) {
                    // Check handle hit first
                    auto handles = get_handles(ed.scene, ed.selection);
                    int h_idx = handle_hit_test(handles, mw, hit_thresh);

                    if (h_idx >= 0) {
                        // Start handle drag
                        ed.undo.push(ed.scene);
                        ed.handle_dragging = true;
                        ed.active_handle = handles[h_idx];
                    } else {
                        // Hit test objects
                        ObjectId hit = hit_test(mw, ed.scene, hit_thresh);

                        if (hit.index >= 0) {
                            if (io.KeyShift) {
                                ed.toggle_select(hit);
                            } else if (!ed.is_selected(hit)) {
                                ed.clear_selection();
                                ed.select(hit);
                            }
                            // Start drag move
                            ed.undo.push(ed.scene);
                            ed.dragging = true;
                            ed.drag_offsets.clear();
                            for (auto& sid : ed.selection) {
                                if (sid.type == ObjectId::Shape) {
                                    std::visit(overloaded{
                                        [&](const Circle& ci) { ed.drag_offsets.push_back({ci.center - mw, {}}); },
                                        [&](const Segment& s) { ed.drag_offsets.push_back({s.a - mw, s.b - mw}); },
                                        [&](const Arc& a) { ed.drag_offsets.push_back({a.center - mw, {}}); },
                                        [&](const Bezier& b) { ed.drag_offsets.push_back({b.p0 - mw, b.p2 - mw}); },
                                    }, ed.scene.shapes[sid.index]);
                                } else if (sid.type == ObjectId::Light) {
                                    std::visit(overloaded{
                                        [&](const PointLight& l) { ed.drag_offsets.push_back({l.pos - mw, {}}); },
                                        [&](const SegmentLight& l) { ed.drag_offsets.push_back({l.a - mw, l.b - mw}); },
                                        [&](const BeamLight& l) { ed.drag_offsets.push_back({l.origin - mw, {}}); },
                                    }, ed.scene.lights[sid.index]);
                                } else if (sid.type == ObjectId::Group) {
                                    auto& g = ed.scene.groups[sid.index];
                                    ed.drag_offsets.push_back({g.transform.translate - mw, {}});
                                }
                            }
                        } else {
                            if (!io.KeyShift) ed.clear_selection();
                            // Start box select
                            ed.box_selecting = true;
                            ed.box_start = io.MousePos;
                        }
                    }
                } else if (ed.tool == EditTool::Erase) {
                    ObjectId hit = hit_test(mw, ed.scene, hit_thresh);
                    if (hit.index >= 0) {
                        ed.clear_selection();
                        ed.select(hit);
                        delete_selected();
                    }
                } else if (ed.tool == EditTool::PointLight) {
                    ed.undo.push(ed.scene);
                    ed.scene.lights.push_back(PointLight{mw, 1.0f});
                    ed.clear_selection();
                    ed.select({ObjectId::Light, (int)ed.scene.lights.size() - 1});
                    reload();
                } else if (ed.tool == EditTool::BeamLight) {
                    ed.undo.push(ed.scene);
                    ed.scene.lights.push_back(BeamLight{mw, {1.0f, 0.0f}, 0.1f, 1.0f});
                    ed.clear_selection();
                    ed.select({ObjectId::Light, (int)ed.scene.lights.size() - 1});
                    reload();
                } else {
                    ed.creating = true;
                    ed.create_start = mw;
                }
            }
        }

        // Handle drag (specific parameter modification)
        if (ImGui::IsMouseDragging(0) && ed.handle_dragging) {
            apply_handle_drag(ed.scene, ed.active_handle, mw);
            reload();
        }

        // Drag to move selected objects
        if (ImGui::IsMouseDragging(0) && ed.dragging && !ed.handle_dragging && !ed.box_selecting &&
            ed.drag_offsets.size() == ed.selection.size()) {
            for (int i = 0; i < (int)ed.selection.size(); ++i) {
                auto& sid = ed.selection[i];
                auto& off = ed.drag_offsets[i];
                if (sid.type == ObjectId::Shape && sid.index < (int)ed.scene.shapes.size()) {
                    std::visit(overloaded{
                        [&](Circle& c) { c.center = mw + off.a; },
                        [&](Segment& s) { s.a = mw + off.a; s.b = mw + off.b; },
                        [&](Arc& a) { a.center = mw + off.a; },
                        [&](Bezier& b) {
                            Vec2 delta = (mw + off.a) - b.p0;
                            b.p0 = b.p0 + delta; b.p1 = b.p1 + delta; b.p2 = b.p2 + delta;
                        },
                    }, ed.scene.shapes[sid.index]);
                } else if (sid.type == ObjectId::Light && sid.index < (int)ed.scene.lights.size()) {
                    std::visit(overloaded{
                        [&](PointLight& l) { l.pos = mw + off.a; },
                        [&](SegmentLight& l) { l.a = mw + off.a; l.b = mw + off.b; },
                        [&](BeamLight& l) { l.origin = mw + off.a; },
                    }, ed.scene.lights[sid.index]);
                } else if (sid.type == ObjectId::Group && sid.index < (int)ed.scene.groups.size()) {
                    ed.scene.groups[sid.index].transform.translate = mw + off.a;
                }
            }
            reload();
        }

        if (ImGui::IsMouseReleased(0)) {
            // Complete creation
            if (ed.creating) {
                Vec2 end = cv.to_world(io.MousePos);
                float dist = (end - ed.create_start).length();

                ed.undo.push(ed.scene);
                bool created = false;

                if (ed.tool == EditTool::Circle) {
                    float r = std::max(dist, 0.02f);
                    ed.scene.shapes.push_back(Circle{ed.create_start, r, mat_glass(1.5f, 20000.0f, 0.3f)});
                    ed.clear_selection();
                    ed.select({ObjectId::Shape, (int)ed.scene.shapes.size() - 1});
                    created = true;
                } else if (ed.tool == EditTool::Segment && dist > 0.01f) {
                    ed.scene.shapes.push_back(Segment{ed.create_start, end, mat_mirror(0.95f)});
                    ed.clear_selection();
                    ed.select({ObjectId::Shape, (int)ed.scene.shapes.size() - 1});
                    created = true;
                } else if (ed.tool == EditTool::Arc) {
                    float r = std::max(dist, 0.02f);
                    ed.scene.shapes.push_back(Arc{ed.create_start, r, 0.0f, TWO_PI, mat_glass(1.5f, 20000.0f, 0.3f)});
                    ed.clear_selection();
                    ed.select({ObjectId::Shape, (int)ed.scene.shapes.size() - 1});
                    created = true;
                } else if (ed.tool == EditTool::Bezier && dist > 0.01f) {
                    Vec2 mid = (ed.create_start + end) * 0.5f;
                    ed.scene.shapes.push_back(Bezier{ed.create_start, mid, end, mat_glass(1.5f, 20000.0f, 0.3f)});
                    ed.clear_selection();
                    ed.select({ObjectId::Shape, (int)ed.scene.shapes.size() - 1});
                    created = true;
                } else if (ed.tool == EditTool::SegmentLight && dist > 0.01f) {
                    ed.scene.lights.push_back(SegmentLight{ed.create_start, end, 1.0f});
                    ed.clear_selection();
                    ed.select({ObjectId::Light, (int)ed.scene.lights.size() - 1});
                    created = true;
                }

                if (created) reload();
                else { ed.undo.snapshots.pop_back(); ed.undo.current--; } // nothing created, revert push
                ed.creating = false;
            }

            // Complete box selection
            if (ed.box_selecting) {
                ImVec2 cur = io.MousePos;
                Vec2 wmin = cv.to_world(ImVec2(std::min(ed.box_start.x, cur.x), std::max(ed.box_start.y, cur.y)));
                Vec2 wmax = cv.to_world(ImVec2(std::max(ed.box_start.x, cur.x), std::min(ed.box_start.y, cur.y)));

                if (!io.KeyShift) ed.clear_selection();
                for (int i = 0; i < (int)ed.scene.shapes.size(); ++i) {
                    ObjectId id{ObjectId::Shape, i};
                    if (object_in_rect(ed.scene, id, wmin, wmax))
                        ed.select(id);
                }
                for (int i = 0; i < (int)ed.scene.lights.size(); ++i) {
                    ObjectId id{ObjectId::Light, i};
                    if (object_in_rect(ed.scene, id, wmin, wmax))
                        ed.select(id);
                }
                for (int i = 0; i < (int)ed.scene.groups.size(); ++i) {
                    ObjectId id{ObjectId::Group, i};
                    if (object_in_rect(ed.scene, id, wmin, wmax))
                        ed.select(id);
                }
                ed.box_selecting = false;
            }

            ed.dragging = false;
            ed.handle_dragging = false;
            ed.drag_offsets.clear();
        }

        // ── Controls panel ──────────────────────────────────────────────

        float panel_w = 280 * dpi_scale;
        ImGui::SetNextWindowPos(ImVec2((float)win_w - panel_w - 8, 8), ImGuiCond_FirstUseEver);
        ImGui::SetNextWindowSize(ImVec2(panel_w, (float)win_h - 16), ImGuiCond_FirstUseEver);
        ImGui::SetNextWindowSizeConstraints(ImVec2(220 * dpi_scale, 200), ImVec2(500 * dpi_scale, 1e6f));
        ImGui::Begin("Controls");

        // -- Scene --
        if (ImGui::CollapsingHeader("Scene", ImGuiTreeNodeFlags_DefaultOpen)) {
            ImGui::PushID("Scene");
            const char* label = (current_scene >= 0) ? builtins[current_scene].name.c_str() : "Custom";
            if (ImGui::BeginCombo("##scene", label)) {
                for (int i = 0; i < (int)builtins.size(); ++i) {
                    if (ImGui::Selectable(builtins[i].name.c_str(), i == current_scene)) {
                        current_scene = i;
                        ed.scene = load_builtin_scene(builtins[i]);
                        reset_editor();
                    }
                }
                ImGui::EndCombo();
            }
            if (ImGui::Button("New Scene")) {
                current_scene = -1;
                ed.scene = Scene{};
                ed.scene.name = "custom";
                add_box_walls(ed.scene, 1.0f, 0.7f, mat_mirror(0.95f));
                ed.scene.lights.push_back(PointLight{{0.0f, 0.0f}, 1.0f});
                reset_editor();
            }

            // Save/Load
            ImGui::SameLine();
            if (ImGui::Button("Save")) { do_save(); }
            ImGui::SameLine();
            if (ImGui::Button("Load")) {
                ImGui::OpenPopup("Load Scene##popup");
            }

            // Load popup (can be triggered by Ctrl+O shortcut)
            static char load_path_buf[256] = "";
            if (open_load_popup) { ImGui::OpenPopup("Load Scene##popup"); open_load_popup = false; }
            if (ImGui::BeginPopup("Load Scene##popup")) {
                ImGui::Text("File path:");
                ImGui::InputText("##loadpath", load_path_buf, sizeof(load_path_buf));
                if (ImGui::Button("OK") && load_path_buf[0]) {
                    Scene loaded = load_scene_json(load_path_buf);
                    if (!loaded.shapes.empty() || !loaded.lights.empty() || !loaded.groups.empty()) {
                        ed.scene = loaded;
                        ed.save_path = load_path_buf;
                        current_scene = -1;
                        reset_editor();
                    }
                    ImGui::CloseCurrentPopup();
                }
                ImGui::SameLine();
                if (ImGui::Button("Cancel")) ImGui::CloseCurrentPopup();
                ImGui::EndPopup();
            }
            ImGui::PopID();
        }

        // -- Tools --
        if (ImGui::CollapsingHeader("Tools", ImGuiTreeNodeFlags_DefaultOpen)) {
            ImGui::PushID("Tools");
            ImVec4 accent(0.31f, 0.53f, 0.86f, 1.0f);
            ImVec4 accent_h(0.38f, 0.60f, 0.92f, 1.0f);
            auto tbtn = [&](const char* lbl, EditTool t) {
                bool active = (ed.tool == t);
                if (active) {
                    ImGui::PushStyleColor(ImGuiCol_Button, accent);
                    ImGui::PushStyleColor(ImGuiCol_ButtonHovered, accent_h);
                }
                if (ImGui::Button(lbl)) { ed.tool = t; ed.creating = false; }
                if (active) ImGui::PopStyleColor(2);
            };
            tbtn("Select", EditTool::Select); ImGui::SameLine();
            tbtn("Circle", EditTool::Circle); ImGui::SameLine();
            tbtn("Segment", EditTool::Segment);
            tbtn("Arc", EditTool::Arc); ImGui::SameLine();
            tbtn("Bezier", EditTool::Bezier); ImGui::SameLine();
            tbtn("Erase", EditTool::Erase);
            tbtn("Pt Light", EditTool::PointLight); ImGui::SameLine();
            tbtn("Seg Light", EditTool::SegmentLight); ImGui::SameLine();
            tbtn("Beam", EditTool::BeamLight);

            ImGui::Checkbox("Wireframe overlay", &show_wireframe);
            ImGui::PopID();
        }

        // -- Objects --
        if (ImGui::CollapsingHeader("Objects", ImGuiTreeNodeFlags_DefaultOpen)) {
            ImGui::PushID("Objects");
            int n_items = (int)(ed.scene.shapes.size() + ed.scene.lights.size() + ed.scene.groups.size());
            float h = std::clamp(n_items * ImGui::GetTextLineHeightWithSpacing() + 8.0f,
                                 40.0f, 200.0f * dpi_scale);
            ImGui::BeginChild("##objlist", ImVec2(0, h), ImGuiChildFlags_Borders);

            for (int i = 0; i < (int)ed.scene.shapes.size(); ++i) {
                ObjectId id{ObjectId::Shape, i};
                bool is_sel = ed.is_selected(id);
                char lbl[96];
                std::visit(overloaded{
                    [&](const Circle& c) {
                        std::snprintf(lbl, sizeof(lbl), "Circle %d (%s)", i, material_name(c.material));
                    },
                    [&](const Segment& s) {
                        std::snprintf(lbl, sizeof(lbl), "Segment %d (%s)", i, material_name(s.material));
                    },
                    [&](const Arc& a) {
                        std::snprintf(lbl, sizeof(lbl), "Arc %d (%s)", i, material_name(a.material));
                    },
                    [&](const Bezier& b) {
                        std::snprintf(lbl, sizeof(lbl), "Bezier %d (%s)", i, material_name(b.material));
                    },
                }, ed.scene.shapes[i]);
                if (ImGui::Selectable(lbl, is_sel)) {
                    if (io.KeyShift) ed.toggle_select(id);
                    else { ed.clear_selection(); ed.select(id); }
                }
            }

            for (int i = 0; i < (int)ed.scene.lights.size(); ++i) {
                ObjectId id{ObjectId::Light, i};
                bool is_sel = ed.is_selected(id);
                char lbl[96];
                std::visit(overloaded{
                    [&](const PointLight& l) {
                        std::snprintf(lbl, sizeof(lbl), "Point Light %d (I=%.1f)", i, l.intensity);
                    },
                    [&](const SegmentLight& l) {
                        std::snprintf(lbl, sizeof(lbl), "Seg Light %d (I=%.1f)", i, l.intensity);
                    },
                    [&](const BeamLight& l) {
                        std::snprintf(lbl, sizeof(lbl), "Beam Light %d (I=%.1f)", i, l.intensity);
                    },
                }, ed.scene.lights[i]);
                if (ImGui::Selectable(lbl, is_sel)) {
                    if (io.KeyShift) ed.toggle_select(id);
                    else { ed.clear_selection(); ed.select(id); }
                }
            }

            for (int i = 0; i < (int)ed.scene.groups.size(); ++i) {
                ObjectId id{ObjectId::Group, i};
                bool is_sel = ed.is_selected(id);
                char lbl[96];
                const auto& group = ed.scene.groups[i];
                int n_members = (int)(group.shapes.size() + group.lights.size());
                if (group.name.empty())
                    std::snprintf(lbl, sizeof(lbl), "Group %d (%d items)", i, n_members);
                else
                    std::snprintf(lbl, sizeof(lbl), "%s (%d items)", group.name.c_str(), n_members);
                if (ImGui::Selectable(lbl, is_sel)) {
                    if (io.KeyShift) ed.toggle_select(id);
                    else { ed.clear_selection(); ed.select(id); }
                }
            }

            ImGui::EndChild();

            if (!ed.selection.empty()) {
                if (ed.selection.size() > 1)
                    ImGui::Text("%d objects selected", (int)ed.selection.size());
                if (ImGui::Button("Delete Selected")) {
                    delete_selected();
                }
            }
            ImGui::PopID();
        }

        // -- Properties --
        if (ed.selection.size() == 1 &&
            ImGui::CollapsingHeader("Properties", ImGuiTreeNodeFlags_DefaultOpen)) {
            ImGui::PushID("Properties");
            bool changed = false;
            auto& sid = ed.selection[0];

            if (sid.type == ObjectId::Shape && sid.index < (int)ed.scene.shapes.size()) {
                auto& shape = ed.scene.shapes[sid.index];
                std::visit(overloaded{
                    [&](Circle& c) {
                        changed |= ImGui::DragFloat2("Center", &c.center.x, 0.01f);
                        changed |= ImGui::DragFloat("Radius", &c.radius, 0.005f, 0.01f, 5.0f);
                        changed |= edit_material(c.material);
                    },
                    [&](Segment& s) {
                        changed |= ImGui::DragFloat2("Point A", &s.a.x, 0.01f);
                        changed |= ImGui::DragFloat2("Point B", &s.b.x, 0.01f);
                        changed |= edit_material(s.material);
                    },
                    [&](Arc& a) {
                        changed |= ImGui::DragFloat2("Center", &a.center.x, 0.01f);
                        changed |= ImGui::DragFloat("Radius", &a.radius, 0.005f, 0.01f, 5.0f);
                        changed |= ImGui::SliderFloat("Start angle", &a.angle_start, 0.0f, TWO_PI);
                        changed |= ImGui::SliderFloat("End angle", &a.angle_end, 0.0f, TWO_PI);
                        changed |= edit_material(a.material);
                    },
                    [&](Bezier& b) {
                        changed |= ImGui::DragFloat2("P0", &b.p0.x, 0.01f);
                        changed |= ImGui::DragFloat2("P1 (ctrl)", &b.p1.x, 0.01f);
                        changed |= ImGui::DragFloat2("P2", &b.p2.x, 0.01f);
                        changed |= edit_material(b.material);
                    },
                }, shape);
            }

            if (sid.type == ObjectId::Light && sid.index < (int)ed.scene.lights.size()) {
                auto& light = ed.scene.lights[sid.index];
                auto edit_wavelength = [&](float& wl_min, float& wl_max) {
                    changed |= ImGui::SliderFloat("Lambda min", &wl_min, 380.0f, 780.0f, "%.0f nm");
                    changed |= ImGui::SliderFloat("Lambda max", &wl_max, 380.0f, 780.0f, "%.0f nm");
                    if (wl_min > wl_max) wl_max = wl_min;
                };
                std::visit(overloaded{
                    [&](PointLight& l) {
                        changed |= ImGui::DragFloat2("Position", &l.pos.x, 0.01f);
                        changed |= ImGui::SliderFloat("Intensity", &l.intensity, 0.01f, 5.0f);
                        edit_wavelength(l.wavelength_min, l.wavelength_max);
                    },
                    [&](SegmentLight& l) {
                        changed |= ImGui::DragFloat2("Point A", &l.a.x, 0.01f);
                        changed |= ImGui::DragFloat2("Point B", &l.b.x, 0.01f);
                        changed |= ImGui::SliderFloat("Intensity", &l.intensity, 0.01f, 5.0f);
                        edit_wavelength(l.wavelength_min, l.wavelength_max);
                    },
                    [&](BeamLight& l) {
                        changed |= ImGui::DragFloat2("Origin", &l.origin.x, 0.01f);
                        changed |= ImGui::DragFloat2("Direction", &l.direction.x, 0.01f);
                        if (l.direction.length_sq() > 1e-6f) l.direction = l.direction.normalized();
                        else l.direction = {1.0f, 0.0f};
                        changed |= ImGui::SliderFloat("Ang. width", &l.angular_width, 0.01f, PI);
                        changed |= ImGui::SliderFloat("Intensity", &l.intensity, 0.01f, 5.0f);
                        edit_wavelength(l.wavelength_min, l.wavelength_max);
                    },
                }, light);
            }

            if (sid.type == ObjectId::Group && sid.index < (int)ed.scene.groups.size()) {
                auto& group = ed.scene.groups[sid.index];
                static char name_buf[64];
                strncpy(name_buf, group.name.c_str(), sizeof(name_buf) - 1);
                name_buf[sizeof(name_buf) - 1] = '\0';
                if (ImGui::InputText("Name", name_buf, sizeof(name_buf))) {
                    group.name = name_buf;
                    changed = true;
                }
                ImGui::Separator();
                ImGui::Text("Transform");
                changed |= ImGui::DragFloat2("Translate", &group.transform.translate.x, 0.01f);
                float deg = group.transform.rotate * 180.0f / PI;
                if (ImGui::DragFloat("Rotate", &deg, 0.5f, -360.0f, 360.0f, "%.1f deg")) {
                    group.transform.rotate = deg * PI / 180.0f;
                    changed = true;
                }
                changed |= ImGui::DragFloat2("Scale", &group.transform.scale.x, 0.01f, 0.01f, 100.0f);
                ImGui::Separator();
                int n_shapes = (int)group.shapes.size();
                int n_lights = (int)group.lights.size();
                ImGui::Text("%d shapes, %d lights", n_shapes, n_lights);
            }

            if (changed) {
                if (!ed.prop_editing) {
                    ed.undo.push(ed.scene);
                    ed.prop_editing = true;
                }
                reload();
            }
            if (!ImGui::IsAnyItemActive() && ed.prop_editing) {
                ed.prop_editing = false;
            }
            ImGui::PopID();
        }

        // -- Tracer --
        if (ImGui::CollapsingHeader("Tracer", ImGuiTreeNodeFlags_DefaultOpen)) {
            ImGui::PushID("Tracer");
            ImGui::SliderInt("Batch", &tcfg.batch_size, 1000, 1000000, "%d",
                             ImGuiSliderFlags_Logarithmic);
            ImGui::SliderInt("Max depth", &tcfg.max_depth, 1, 30);
            ImGui::SliderFloat("Intensity", &tcfg.intensity, 0.001f, 10.0f, "%.3f",
                               ImGuiSliderFlags_Logarithmic);
            ImGui::Checkbox("Paused", &paused);
            ImGui::PopID();
        }

        // -- Display --
        if (ImGui::CollapsingHeader("Display", ImGuiTreeNodeFlags_DefaultOpen)) {
            ImGui::PushID("Display");
            ImGui::SliderFloat("Exposure", &pp.exposure, -5.0f, 5.0f);
            ImGui::SliderFloat("Contrast", &pp.contrast, 0.1f, 3.0f);
            ImGui::SliderFloat("Gamma", &pp.gamma, 0.5f, 4.0f);
            ImGui::SliderFloat("White point", &pp.white_point, 0.1f, 10.0f);
            const char* tone_names[] = {"None", "Reinhard", "Reinhard Ext", "ACES", "Logarithmic"};
            int tm = (int)pp.tone_map;
            if (ImGui::Combo("Tone map", &tm, tone_names, 5))
                pp.tone_map = (ToneMap)tm;
            const char* norm_names[] = {"Auto (Max)", "Ray Count", "Fixed Ref", "Off"};
            int nm = (int)pp.normalize;
            if (ImGui::Combo("Normalize", &nm, norm_names, 4))
                pp.normalize = (NormalizeMode)nm;
            if (pp.normalize == NormalizeMode::Max) {
                ImGui::SliderFloat("Percentile", &pp.normalize_pct, 0.9f, 1.0f, "%.3f");
            }
            if (pp.normalize == NormalizeMode::Fixed) {
                ImGui::SliderFloat("Ref value", &pp.normalize_ref, 1.0f, 1000000.0f,
                                   "%.0f", ImGuiSliderFlags_Logarithmic);
                if (ImGui::Button("Capture Ref")) {
                    pp.normalize_ref = renderer.compute_current_max();
                }
            }
            ImGui::Separator();
            ImGui::SliderFloat("Ambient", &pp.ambient, 0.0f, 0.5f, "%.3f");
            ImGui::ColorEdit3("Background", pp.background,
                              ImGuiColorEditFlags_Float | ImGuiColorEditFlags_HDR);
            ImGui::SliderFloat("Opacity", &pp.opacity, 0.0f, 1.0f);
            ImGui::PopID();
        }

        // -- Output --
        if (ImGui::CollapsingHeader("Output", ImGuiTreeNodeFlags_DefaultOpen)) {
            ImGui::PushID("Output");
            char ray_str[32];
            int64_t tr = renderer.total_rays();
            if (tr >= 1'000'000)
                std::snprintf(ray_str, sizeof(ray_str), "%.1fM", tr / 1e6);
            else if (tr >= 1'000)
                std::snprintf(ray_str, sizeof(ray_str), "%.1fK", tr / 1e3);
            else
                std::snprintf(ray_str, sizeof(ray_str), "%lld", (long long)tr);
            ImGui::Text("Rays: %s", ray_str);
            if (pp.normalize == NormalizeMode::Max)
                ImGui::Text("Max HDR: %.2f", renderer.last_max());
            else
                ImGui::TextDisabled("Max HDR: —");
            ImGui::Text("%.1f FPS (%.1f ms)", 1000.0f / frame_ms, frame_ms);
            ImGui::Text("Zoom: %.0f%%", ed.camera.zoom / std::min((float)win_w / std::max(ed.scene_bounds.max.x - ed.scene_bounds.min.x, 0.01f), (float)win_h / std::max(ed.scene_bounds.max.y - ed.scene_bounds.min.y, 0.01f)) * 100.0f);

            if (ImGui::Button("Clear")) {
                renderer.clear();
            }
            ImGui::SameLine();
            if (ImGui::Button("Export PNG")) {
                std::vector<uint8_t> pixels;
                renderer.read_pixels(pixels, pp);
                std::string filename = ed.scene.name + ".png";
                if (export_png(filename, pixels.data(), fb_w, fb_h))
                    std::cerr << "Exported: " << filename << "\n";
            }
            ImGui::PopID();
        }

        ImGui::End(); // Controls

        // ── Keyboard shortcuts ──────────────────────────────────────────

        if (!io.WantCaptureKeyboard) {
            // --- Modal transform input ---
            if (ed.transform.active()) {
                // Axis constraints
                if (ImGui::IsKeyPressed(ImGuiKey_X)) {
                    ed.transform.lock_x = !ed.transform.lock_x;
                    ed.transform.lock_y = false;
                }
                if (ImGui::IsKeyPressed(ImGuiKey_Y)) {
                    ed.transform.lock_y = !ed.transform.lock_y;
                    ed.transform.lock_x = false;
                }

                // Numeric input
                for (int k = ImGuiKey_0; k <= ImGuiKey_9; ++k) {
                    if (ImGui::IsKeyPressed((ImGuiKey)k))
                        ed.transform.numeric_buf += ('0' + (k - ImGuiKey_0));
                }
                if (ImGui::IsKeyPressed(ImGuiKey_Period))
                    ed.transform.numeric_buf += '.';
                if (ImGui::IsKeyPressed(ImGuiKey_Minus))
                    ed.transform.numeric_buf += '-';
                if (ImGui::IsKeyPressed(ImGuiKey_Backspace) && !ed.transform.numeric_buf.empty())
                    ed.transform.numeric_buf.pop_back();

                // Confirm
                if (ImGui::IsKeyPressed(ImGuiKey_Enter) || ImGui::IsMouseClicked(0)) {
                    // Apply transform to scene
                    for (auto& sid : ed.selection) {
                        if (sid.type == ObjectId::Shape && sid.index < (int)ed.transform.snapshot.shapes.size()) {
                            apply_transform_shape(ed.scene.shapes[sid.index],
                                ed.transform.snapshot.shapes[sid.index], ed.transform, mw, io.KeyShift);
                        } else if (sid.type == ObjectId::Light && sid.index < (int)ed.transform.snapshot.lights.size()) {
                            apply_transform_light(ed.scene.lights[sid.index],
                                ed.transform.snapshot.lights[sid.index], ed.transform, mw, io.KeyShift);
                        } else if (sid.type == ObjectId::Group && sid.index < (int)ed.transform.snapshot.groups.size()) {
                            apply_transform_group(ed.scene.groups[sid.index],
                                ed.transform.snapshot.groups[sid.index], ed.transform, mw, io.KeyShift);
                        }
                    }
                    ed.transform.type = TransformMode::None;
                    ed.transform.snapshot = {};
                    reload();
                }

                // Cancel
                if (ImGui::IsKeyPressed(ImGuiKey_Escape) || ImGui::IsMouseClicked(1)) {
                    ed.scene = ed.transform.snapshot;
                    ed.transform.type = TransformMode::None;
                    ed.transform.snapshot = {};
                    reload();
                }
            } else {
                // --- Global shortcuts ---

                // Undo/Redo
                if (io.KeyCtrl && io.KeyShift && ImGui::IsKeyPressed(ImGuiKey_Z)) {
                    if (ed.undo.redo(ed.scene)) { ed.validate_selection(); reload(); }
                } else if (io.KeyCtrl && ImGui::IsKeyPressed(ImGuiKey_Z)) {
                    if (ed.undo.undo(ed.scene)) { ed.validate_selection(); reload(); }
                }

                // Save/Load
                if (io.KeyCtrl && ImGui::IsKeyPressed(ImGuiKey_S)) { do_save(); }
                if (io.KeyCtrl && ImGui::IsKeyPressed(ImGuiKey_O)) {
                    open_load_popup = true;
                }

                // Select all
                if (io.KeyCtrl && ImGui::IsKeyPressed(ImGuiKey_A)) {
                    ed.select_all();
                }

                // Group / Ungroup
                if (io.KeyCtrl && io.KeyShift && ImGui::IsKeyPressed(ImGuiKey_G)) {
                    // Ungroup selected groups
                    bool any_ungrouped = false;
                    for (auto& sid : ed.selection) {
                        if (sid.type == ObjectId::Group && sid.index < (int)ed.scene.groups.size()) {
                            any_ungrouped = true;
                            break;
                        }
                    }
                    if (any_ungrouped) {
                        ed.undo.push(ed.scene);
                        std::vector<ObjectId> new_sel;
                        // Collect group indices to remove (reverse order)
                        std::vector<int> to_remove;
                        for (auto& sid : ed.selection) {
                            if (sid.type != ObjectId::Group) continue;
                            if (sid.index >= (int)ed.scene.groups.size()) continue;
                            auto& group = ed.scene.groups[sid.index];
                            // Bake transform into shapes/lights and add to scene
                            for (auto& s : group.shapes) {
                                Shape ws = transform_shape(s, group.transform);
                                ed.scene.shapes.push_back(ws);
                                new_sel.push_back({ObjectId::Shape, (int)ed.scene.shapes.size() - 1});
                            }
                            for (auto& l : group.lights) {
                                Light wl = transform_light(l, group.transform);
                                ed.scene.lights.push_back(wl);
                                new_sel.push_back({ObjectId::Light, (int)ed.scene.lights.size() - 1});
                            }
                            to_remove.push_back(sid.index);
                        }
                        // Remove groups in reverse order
                        std::sort(to_remove.rbegin(), to_remove.rend());
                        for (int idx : to_remove)
                            ed.scene.groups.erase(ed.scene.groups.begin() + idx);
                        ed.selection = new_sel;
                        ed.validate_selection();
                        reload();
                    }
                } else if (io.KeyCtrl && ImGui::IsKeyPressed(ImGuiKey_G)) {
                    // Group selected ungrouped shapes/lights
                    // Only group if 2+ ungrouped objects selected and no groups in selection
                    int n_ungrouped = 0;
                    bool has_groups = false;
                    for (auto& sid : ed.selection) {
                        if (sid.type == ObjectId::Group) has_groups = true;
                        else n_ungrouped++;
                    }
                    if (n_ungrouped >= 2 && !has_groups) {
                        ed.undo.push(ed.scene);
                        // Compute centroid
                        Vec2 centroid = ed.selection_centroid();
                        Group group;
                        static int group_counter = 0;
                        group.name = "Group " + std::to_string(group_counter++);
                        group.transform.translate = centroid;

                        // Collect shapes/lights, converting to local coords
                        std::vector<int> shape_indices, light_indices;
                        for (auto& sid : ed.selection) {
                            if (sid.type == ObjectId::Shape && sid.index < (int)ed.scene.shapes.size()) {
                                Shape s = ed.scene.shapes[sid.index];
                                translate_shape(s, Vec2{0, 0} - centroid);
                                group.shapes.push_back(s);
                                shape_indices.push_back(sid.index);
                            } else if (sid.type == ObjectId::Light && sid.index < (int)ed.scene.lights.size()) {
                                Light l = ed.scene.lights[sid.index];
                                translate_light(l, Vec2{0, 0} - centroid);
                                group.lights.push_back(l);
                                light_indices.push_back(sid.index);
                            }
                        }

                        // Remove originals (reverse order to preserve indices)
                        std::sort(shape_indices.rbegin(), shape_indices.rend());
                        std::sort(light_indices.rbegin(), light_indices.rend());
                        for (int idx : light_indices)
                            ed.scene.lights.erase(ed.scene.lights.begin() + idx);
                        for (int idx : shape_indices)
                            ed.scene.shapes.erase(ed.scene.shapes.begin() + idx);

                        ed.scene.groups.push_back(std::move(group));
                        ed.clear_selection();
                        ed.select({ObjectId::Group, (int)ed.scene.groups.size() - 1});
                        reload();
                    }
                }

                // Copy/Paste/Cut/Duplicate
                if (io.KeyCtrl && ImGui::IsKeyPressed(ImGuiKey_C)) {
                    copy_to_clipboard();
                }

                if (io.KeyCtrl && ImGui::IsKeyPressed(ImGuiKey_V) && !ed.clipboard.empty()) {
                    ed.undo.push(ed.scene);
                    Vec2 offset = mw - ed.clipboard.centroid;
                    ed.clear_selection();
                    for (auto s : ed.clipboard.shapes) {
                        translate_shape(s, offset);
                        ed.scene.shapes.push_back(s);
                        ed.select({ObjectId::Shape, (int)ed.scene.shapes.size() - 1});
                    }
                    for (auto l : ed.clipboard.lights) {
                        translate_light(l, offset);
                        ed.scene.lights.push_back(l);
                        ed.select({ObjectId::Light, (int)ed.scene.lights.size() - 1});
                    }
                    for (auto g : ed.clipboard.groups) {
                        translate_group(g, offset);
                        ed.scene.groups.push_back(g);
                        ed.select({ObjectId::Group, (int)ed.scene.groups.size() - 1});
                    }
                    reload();
                }

                if (io.KeyCtrl && ImGui::IsKeyPressed(ImGuiKey_X)) {
                    copy_to_clipboard();
                    delete_selected();
                }

                if (io.KeyCtrl && ImGui::IsKeyPressed(ImGuiKey_D) && !ed.selection.empty()) {
                    // Duplicate: copy in place with small offset, then enter grab
                    ed.undo.push(ed.scene);
                    std::vector<ObjectId> new_sel;
                    Vec2 offset{0.05f, 0.05f};
                    for (auto& sid : ed.selection) {
                        if (sid.type == ObjectId::Shape) {
                            Shape s = ed.scene.shapes[sid.index];
                            translate_shape(s, offset);
                            ed.scene.shapes.push_back(s);
                            new_sel.push_back({ObjectId::Shape, (int)ed.scene.shapes.size() - 1});
                        } else if (sid.type == ObjectId::Light) {
                            Light l = ed.scene.lights[sid.index];
                            translate_light(l, offset);
                            ed.scene.lights.push_back(l);
                            new_sel.push_back({ObjectId::Light, (int)ed.scene.lights.size() - 1});
                        } else if (sid.type == ObjectId::Group) {
                            Group g = ed.scene.groups[sid.index];
                            translate_group(g, offset);
                            ed.scene.groups.push_back(g);
                            new_sel.push_back({ObjectId::Group, (int)ed.scene.groups.size() - 1});
                        }
                    }
                    ed.selection = new_sel;

                    // Enter grab mode
                    ed.transform.type = TransformMode::Grab;
                    ed.transform.pivot = ed.selection_centroid();
                    ed.transform.mouse_start = mw;
                    ed.transform.lock_x = ed.transform.lock_y = false;
                    ed.transform.numeric_buf.clear();
                    ed.transform.snapshot = ed.scene;
                    reload();
                }

                // Transform shortcuts (G/R/S)
                if (!ed.selection.empty()) {
                    auto start_transform = [&](TransformMode::Type type) {
                        ed.transform.type = type;
                        ed.transform.pivot = ed.selection_centroid();
                        ed.transform.mouse_start = mw;
                        ed.transform.lock_x = ed.transform.lock_y = false;
                        ed.transform.numeric_buf.clear();
                        ed.transform.snapshot = ed.scene;
                        ed.undo.push(ed.scene);
                    };

                    if (ImGui::IsKeyPressed(ImGuiKey_G)) start_transform(TransformMode::Grab);
                    if (ImGui::IsKeyPressed(ImGuiKey_R)) start_transform(TransformMode::Rotate);
                    if (ImGui::IsKeyPressed(ImGuiKey_S) && !io.KeyCtrl) start_transform(TransformMode::Scale);
                }

                // Tool switching
                if (!io.KeyCtrl && !io.KeyAlt) {
                    if (ImGui::IsKeyPressed(ImGuiKey_Q)) ed.tool = EditTool::Select;
                    if (ImGui::IsKeyPressed(ImGuiKey_C)) ed.tool = EditTool::Circle;
                    if (ImGui::IsKeyPressed(ImGuiKey_L)) ed.tool = EditTool::Segment;
                    if (ImGui::IsKeyPressed(ImGuiKey_A) && !io.KeyCtrl) ed.tool = EditTool::Arc;
                    if (ImGui::IsKeyPressed(ImGuiKey_B)) ed.tool = EditTool::Bezier;
                    if (ImGui::IsKeyPressed(ImGuiKey_X) && !ed.transform.active()) ed.tool = EditTool::Erase;
                    if (ImGui::IsKeyPressed(ImGuiKey_P)) ed.tool = EditTool::PointLight;
                    if (ImGui::IsKeyPressed(ImGuiKey_T)) ed.tool = EditTool::SegmentLight;
                    if (ImGui::IsKeyPressed(ImGuiKey_W)) ed.tool = EditTool::BeamLight;
                }

                // Fit to view
                if (ImGui::IsKeyPressed(ImGuiKey_F)) {
                    if (!ed.selection.empty()) {
                        Bounds sb = ed.selection_bounds();
                        Vec2 sz = sb.max - sb.min;
                        // Minimum padding: 20% of selection size, but at least 20% of scene size
                        // so that zero-extent selections (point lights) get a useful view
                        Vec2 scene_sz = ed.scene_bounds.max - ed.scene_bounds.min;
                        float min_pad = std::max(scene_sz.x, scene_sz.y) * 0.2f;
                        float pad = std::max(std::max(sz.x, sz.y) * 0.2f, min_pad);
                        sb.min = sb.min - Vec2{pad, pad};
                        sb.max = sb.max + Vec2{pad, pad};
                        ed.camera.fit(sb, (float)win_w, (float)win_h);
                    } else {
                        ed.camera.fit(ed.scene_bounds, (float)win_w, (float)win_h);
                    }
                    renderer.update_viewport(ed.camera.visible_bounds((float)win_w, (float)win_h));
                    renderer.clear();
                }
                if (ImGui::IsKeyPressed(ImGuiKey_Home)) {
                    ed.camera.fit(ed.scene_bounds, (float)win_w, (float)win_h);
                    renderer.update_viewport(ed.camera.visible_bounds((float)win_w, (float)win_h));
                    renderer.clear();
                }

                // Space: pause
                if (ImGui::IsKeyPressed(ImGuiKey_Space)) paused = !paused;

                // Escape cascade
                if (ImGui::IsKeyPressed(ImGuiKey_Escape)) {
                    if (ed.creating) {
                        ed.creating = false;
                    } else if (!ed.selection.empty()) {
                        ed.clear_selection();
                    } else {
                        ed.tool = EditTool::Select;
                    }
                }

                // Delete
                if (ImGui::IsKeyPressed(ImGuiKey_Delete) || ImGui::IsKeyPressed(ImGuiKey_Backspace)) {
                    delete_selected();
                }
            }
        }

        // ── Update window title (only when changed) ────────────────────

        {
            static std::string last_title;
            char title[256];
            std::snprintf(title, sizeof(title), "lpt2d \xe2\x80\x94 %s%s",
                ed.scene.name.empty() ? "untitled" : ed.scene.name.c_str(),
                ed.dirty ? " *" : "");
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
    renderer.shutdown();
    glfwDestroyWindow(window);
    glfwTerminate();
    return 0;
}
