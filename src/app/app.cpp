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
    ed.shot = load_builtin_scene(builtins[current_scene]);
    ed.shot.trace.batch = 50000; // interactive batch size
    ed.scene_bounds = compute_bounds(ed.shot.scene);
    ed.camera.fit(ed.scene_bounds, (float)win_w, (float)win_h);

    Bounds initial_view = ed.camera.visible_bounds((float)win_w, (float)win_h);
    renderer.upload_scene(ed.shot.scene, initial_view);
    renderer.clear();
    ed.undo.push(ed.shot.scene); // initial state

    bool paused = false;
    float frame_ms = 16.0f;
    bool show_wireframe = true;
    bool open_load_popup = false;
    auto make_default_arc = [](Vec2 center, Vec2 target) {
        Vec2 delta = target - center;
        float angle = delta.length_sq() > 1e-10f
            ? normalize_angle(std::atan2(delta.y, delta.x))
            : 0.0f;
        return Arc{
            center,
            std::max(delta.length(), 0.02f),
            normalize_angle(angle - 0.5f * PI),
            PI,
            mat_glass(1.5f, 20000.0f, 0.3f),
        };
    };

    // Reload: re-upload scene to GPU, clear accumulation
    // Renderer viewport always tracks the camera's visible bounds.
    auto reload = [&]() {
        if (ed.shot.scene.shapes.empty() && ed.shot.scene.lights.empty() && ed.shot.scene.groups.empty())
            ed.scene_bounds = {{-1, -1}, {1, 1}};
        else
            ed.scene_bounds = compute_bounds(ed.shot.scene);
        Bounds view = ed.camera.visible_bounds((float)win_w, (float)win_h);
        renderer.upload_scene(ed.shot.scene, view);
        renderer.clear();
        ed.dirty = true;
    };

    auto do_save = [&]() {
        std::string path = ed.save_path.empty() ? (ed.shot.name + ".json") : ed.save_path;
        if (save_shot_json(ed.shot, path)) {
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
            if (const Shape* shape = resolve_shape(ed.shot.scene, sid)) ed.clipboard.shapes.push_back(*shape);
            else if (const Light* light = resolve_light(ed.shot.scene, sid)) ed.clipboard.lights.push_back(*light);
            else if (sid.type == ObjectId::Group) ed.clipboard.groups.push_back(ed.shot.scene.groups[sid.index]);
        }
        ed.clipboard.centroid = ed.selection_centroid();
    };

    auto reset_editor = [&]() {
        ed.clear_selection();
        ed.creating = false;
        ed.dragging = false;
        ed.handle_dragging = false;
        ed.cam_handle_dragging = CameraHandle::None;
        ed.cam_handle_hovered = CameraHandle::None;
        ed.undo.clear();
        ed.undo.push(ed.shot.scene);
        // reload() updates ed.scene_bounds, then fit camera
        reload();
        ed.camera.fit(ed.scene_bounds, (float)win_w, (float)win_h);
        reload(); // re-upload with fitted camera view
        ed.dirty = false;
    };

    auto delete_selected = [&]() {
        if (ed.selection.empty()) return false;
        ed.undo.push(ed.shot.scene);

        // Sort selection in reverse order so deletion doesn't invalidate indices
        auto sorted = ed.selection;
        std::sort(sorted.begin(), sorted.end(), [](const ObjectId& a, const ObjectId& b) {
            if (a.type != b.type) return a.type > b.type; // groups (2) > lights (1) > shapes (0)
            return a.index > b.index; // higher indices first
        });
        for (auto& id : sorted) {
            if (id.type == ObjectId::Shape && id.index < (int)ed.shot.scene.shapes.size())
                ed.shot.scene.shapes.erase(ed.shot.scene.shapes.begin() + id.index);
            else if (id.type == ObjectId::Light && id.index < (int)ed.shot.scene.lights.size())
                ed.shot.scene.lights.erase(ed.shot.scene.lights.begin() + id.index);
            else if (id.type == ObjectId::Group && id.index < (int)ed.shot.scene.groups.size())
                ed.shot.scene.groups.erase(ed.shot.scene.groups.begin() + id.index);
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
        if (!paused && renderer.num_lights() > 0) {
            renderer.trace_and_draw(ed.shot.trace.to_trace_config());
            glFinish();
        }
        renderer.update_display(ed.shot.look);

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

            for (int i = 0; i < (int)ed.shot.scene.shapes.size(); ++i) {
                ObjectId id{ObjectId::Shape, i};
                bool is_sel = ed.is_selected(id);
                bool is_hov = (ed.hovered == id);
                ImU32 col = is_sel ? COL_SHAPE_SEL : (is_hov ? COL_SHAPE_HOV : COL_SHAPE);
                float th = (is_sel ? 2.5f : 1.5f) * dpi_scale;

                if (ed.transform.active() && is_sel && i < (int)ed.transform.snapshot.shapes.size()) {
                    // Ghost at original position (dim)
                    draw_shape_overlay(dl, cv, ed.transform.snapshot.shapes[i], COL_GHOST_SHAPE, 1.0f * dpi_scale);
                    // Live scene already has the transformed position
                    draw_shape_overlay(dl, cv, ed.shot.scene.shapes[i], COL_SHAPE_SEL, 2.5f * dpi_scale);
                } else {
                    draw_shape_overlay(dl, cv, ed.shot.scene.shapes[i], col, th);
                }
            }

            for (int i = 0; i < (int)ed.shot.scene.lights.size(); ++i) {
                ObjectId id{ObjectId::Light, i};
                bool is_sel = ed.is_selected(id);
                bool is_hov = (ed.hovered == id);
                ImU32 col = is_sel ? COL_LIGHT_SEL : (is_hov ? COL_LIGHT_HOV : COL_LIGHT);
                float th = (is_sel ? 3.0f : 2.0f) * dpi_scale;

                if (ed.transform.active() && is_sel && i < (int)ed.transform.snapshot.lights.size()) {
                    // Ghost at original position (dim)
                    draw_light_overlay(dl, cv, ed.transform.snapshot.lights[i], COL_GHOST_LIGHT, 1.0f * dpi_scale, dpi_scale);
                    // Live scene already has the transformed position
                    draw_light_overlay(dl, cv, ed.shot.scene.lights[i], COL_LIGHT_SEL, 3.0f * dpi_scale, dpi_scale);
                } else {
                    draw_light_overlay(dl, cv, ed.shot.scene.lights[i], col, th, dpi_scale);
                }
            }

            // Draw groups
            for (int g = 0; g < (int)ed.shot.scene.groups.size(); ++g) {
                ObjectId gid{ObjectId::Group, g};
                bool is_sel = ed.is_selected(gid);
                bool is_hov = (ed.hovered == gid);

                const auto& group = ed.shot.scene.groups[g];

                if (ed.transform.active() && is_sel && g < (int)ed.transform.snapshot.groups.size()) {
                    // Ghost at original position (dim)
                    const auto& snap_group = ed.transform.snapshot.groups[g];
                    for (const auto& s : snap_group.shapes) {
                        Shape ws = transform_shape(s, snap_group.transform);
                        draw_shape_overlay(dl, cv, ws, COL_GHOST_SHAPE, 1.0f * dpi_scale);
                    }
                    for (const auto& l : snap_group.lights) {
                        Light wl = transform_light(l, snap_group.transform);
                        draw_light_overlay(dl, cv, wl, COL_GHOST_LIGHT, 1.0f * dpi_scale, dpi_scale);
                    }
                }

                ImU32 shape_col = is_sel ? COL_SHAPE_SEL : (is_hov ? COL_SHAPE_HOV : COL_SHAPE);
                ImU32 light_col = is_sel ? COL_LIGHT_SEL : (is_hov ? COL_LIGHT_HOV : COL_LIGHT);
                float s_th = (is_sel ? 2.5f : 1.5f) * dpi_scale;
                float l_th = (is_sel ? 3.0f : 2.0f) * dpi_scale;

                for (const auto& s : group.shapes) {
                    Shape ws = transform_shape(s, group.transform);
                    draw_shape_overlay(dl, cv, ws, shape_col, s_th);
                }
                for (const auto& l : group.lights) {
                    Light wl = transform_light(l, group.transform);
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
                auto handles = get_handles(ed.shot.scene, ed.selection);
                Vec2 mw = cv.to_world(io.MousePos);
                int hov_h = vp_hovered ? handle_hit_test(handles, mw, 8.0f / cv.cam.zoom) : -1;
                draw_handles(dl, cv, ed.shot.scene, handles, hov_h);
            }

            // Creation preview
            if (ed.creating) {
                Vec2 mw = cv.to_world(io.MousePos);
                if (ed.tool == EditTool::Circle) {
                    float r = (mw - ed.create_start).length() * cv.cam.zoom;
                    dl->AddCircle(cv.to_screen(ed.create_start), r, COL_PREVIEW, 64, 1.5f * dpi_scale);
                } else if (ed.tool == EditTool::Arc) {
                    Vec2 delta = mw - ed.create_start;
                    if (delta.length_sq() > 1e-10f) {
                        Arc preview = make_default_arc(ed.create_start, mw);
                        draw_shape_overlay(dl, cv, preview, COL_PREVIEW, 1.5f * dpi_scale);
                    }
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
                ImVec2 pivot_screen = cv.to_screen(ed.transform.pivot);
                float r = 6.0f * dpi_scale;
                dl->AddLine(ImVec2(pivot_screen.x - r, pivot_screen.y), ImVec2(pivot_screen.x + r, pivot_screen.y), COL_PIVOT, 2.0f * dpi_scale);
                dl->AddLine(ImVec2(pivot_screen.x, pivot_screen.y - r), ImVec2(pivot_screen.x, pivot_screen.y + r), COL_PIVOT, 2.0f * dpi_scale);
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

        // ── Camera frame overlay ───────────────────────────────────────
        // Resolve camera bounds once per frame for both drawing and interaction
        struct CamHandlePt { CameraHandle id; Vec2 pos; };
        Bounds cam_frame{};
        CamHandlePt cam_handle_pts[8] = {};
        int n_cam_handles = 0;
        bool cam_active = ed.show_camera_frame && !ed.shot.camera.empty();

        if (cam_active) {
            cam_frame = ed.shot.camera.resolve(ed.shot.canvas.aspect(), ed.scene_bounds);
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

            if (ed.dim_outside_camera) {
                float vr = (float)win_w, vb = (float)win_h;
                dl->AddRectFilled(ImVec2(0, 0), ImVec2(vr, st), COL_CAMERA_DIM);
                dl->AddRectFilled(ImVec2(0, sb), ImVec2(vr, vb), COL_CAMERA_DIM);
                dl->AddRectFilled(ImVec2(0, st), ImVec2(sl, sb), COL_CAMERA_DIM);
                dl->AddRectFilled(ImVec2(sr, st), ImVec2(vr, sb), COL_CAMERA_DIM);
            }

            dl->AddRect(ImVec2(sl, st), ImVec2(sr, sb), COL_CAMERA_FRAME, 0, 0, 1.5f * dpi_scale);

            if (ed.selection.empty() && ed.tool == EditTool::Select && !ed.transform.active()) {
                float hs = 4.0f * dpi_scale;
                for (int h = 0; h < n_cam_handles; ++h) {
                    ImVec2 sp = cv.to_screen(cam_handle_pts[h].pos);
                    ImU32 col = (ed.cam_handle_hovered == cam_handle_pts[h].id) ? COL_HANDLE_HOV : COL_CAMERA_HANDLE;
                    dl->AddRectFilled(ImVec2(sp.x - hs, sp.y - hs), ImVec2(sp.x + hs, sp.y + hs), col);
                }
            }
        }

        ImGui::End();
        ImGui::PopStyleVar();

        // ── Mouse interaction ───────────────────────────────────────────

        Vec2 mw = cv.to_world(io.MousePos);
        float hit_thresh = 8.0f / cv.cam.zoom;

        // Camera handle interaction (hover + start drag)
        if (vp_hovered && ed.selection.empty() && ed.tool == EditTool::Select
            && !ed.transform.active() && cam_active
            && ed.cam_handle_dragging == CameraHandle::None) {

            ed.cam_handle_hovered = CameraHandle::None;
            for (int h = 0; h < n_cam_handles; ++h) {
                if ((mw - cam_handle_pts[h].pos).length() < hit_thresh) {
                    ed.cam_handle_hovered = cam_handle_pts[h].id;
                    break;
                }
            }

            if (ed.cam_handle_hovered != CameraHandle::None && ImGui::IsMouseClicked(0)) {
                ed.cam_handle_dragging = ed.cam_handle_hovered;
                ed.cam_drag_start_bounds = cam_frame;
            }
        } else if (ed.cam_handle_dragging == CameraHandle::None) {
            ed.cam_handle_hovered = CameraHandle::None;
        }

        // Camera handle drag (continues even outside viewport)
        if (ed.cam_handle_dragging != CameraHandle::None) {
            if (ImGui::IsMouseDragging(0)) {
                Bounds b = ed.cam_drag_start_bounds;
                Vec2 drag_origin = cv.to_world(io.MouseClickedPos[0]);
                Vec2 drag_offset = mw - drag_origin;

                switch (ed.cam_handle_dragging) {
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

                // Normalize if dragged past opposite edge
                if (b.min.x > b.max.x) std::swap(b.min.x, b.max.x);
                if (b.min.y > b.max.y) std::swap(b.min.y, b.max.y);

                ed.shot.camera.bounds = b;
                ed.shot.camera.center.reset();
                ed.shot.camera.width.reset();
                ed.dirty = true;
            }
            if (ImGui::IsMouseReleased(0)) {
                ed.cam_handle_dragging = CameraHandle::None;
            }
        }

        // Hover detection (Select tool only, skip during camera drag)
        if (vp_hovered && ed.tool == EditTool::Select && !ed.dragging && !ed.creating && !ed.box_selecting && !ed.transform.active()
            && ed.cam_handle_dragging == CameraHandle::None) {
            ObjectId hit = hit_test(mw, ed.shot.scene, hit_thresh, ed.editing_group);
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

        if (vp_hovered && !panning && !ed.transform.active()
            && ed.cam_handle_dragging == CameraHandle::None) {
            // Double-click: enter group editing mode
            if (ImGui::IsMouseDoubleClicked(0) && ed.tool == EditTool::Select) {
                if (ed.editing_group < 0) {
                    // Not inside a group — double-click on group member enters it
                    ObjectId hit = hit_test(mw, ed.shot.scene, hit_thresh, -1);
                    if (hit.type == ObjectId::Group && hit.index >= 0) {
                        ed.editing_group = hit.index;
                        ed.clear_selection();
                        // Select the specific member that was clicked
                        ObjectId member = hit_test(mw, ed.shot.scene, hit_thresh, ed.editing_group);
                        if (member.index >= 0) ed.select(member);
                        reload();
                    }
                }
            }

            if (ImGui::IsMouseClicked(0)) {
                if (ed.tool == EditTool::Select) {
                    // Check handle hit first
                    auto handles = get_handles(ed.shot.scene, ed.selection);
                    int h_idx = handle_hit_test(handles, mw, hit_thresh);

                    if (h_idx >= 0) {
                        // Start handle drag
                        ed.undo.push(ed.shot.scene);
                        ed.handle_dragging = true;
                        ed.active_handle = handles[h_idx];
                    } else {
                        // Hit test objects
                        ObjectId hit = hit_test(mw, ed.shot.scene, hit_thresh, ed.editing_group);

                        if (hit.index >= 0) {
                            if (io.KeyShift) {
                                ed.toggle_select(hit);
                            } else if (!ed.is_selected(hit)) {
                                ed.clear_selection();
                                ed.select(hit);
                            }
                            // Start drag move
                            ed.undo.push(ed.shot.scene);
                            ed.dragging = true;
                            ed.drag_offsets.clear();
                            for (auto& sid : ed.selection) {
                                if (const Shape* shape = resolve_shape(ed.shot.scene, sid)) {
                                    std::visit(overloaded{
                                        [&](const Circle& ci) { ed.drag_offsets.push_back({ci.center - mw, {}}); },
                                        [&](const Segment& s) { ed.drag_offsets.push_back({s.a - mw, s.b - mw}); },
                                        [&](const Arc& a) { ed.drag_offsets.push_back({a.center - mw, {}}); },
                                        [&](const Bezier& b) { ed.drag_offsets.push_back({b.p0 - mw, b.p2 - mw}); },
                                    }, *shape);
                                } else if (const Light* light = resolve_light(ed.shot.scene, sid)) {
                                    std::visit(overloaded{
                                        [&](const PointLight& l) { ed.drag_offsets.push_back({l.pos - mw, {}}); },
                                        [&](const SegmentLight& l) { ed.drag_offsets.push_back({l.a - mw, l.b - mw}); },
                                        [&](const BeamLight& l) { ed.drag_offsets.push_back({l.origin - mw, {}}); },
                                    }, *light);
                                } else if (sid.type == ObjectId::Group) {
                                    auto& g = ed.shot.scene.groups[sid.index];
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
                    ObjectId hit = hit_test(mw, ed.shot.scene, hit_thresh, ed.editing_group);
                    if (hit.index >= 0) {
                        ed.clear_selection();
                        ed.select(hit);
                        delete_selected();
                    }
                } else if (ed.tool == EditTool::PointLight) {
                    ed.undo.push(ed.shot.scene);
                    ed.shot.scene.lights.push_back(PointLight{mw, 1.0f});
                    ed.clear_selection();
                    ed.select({ObjectId::Light, (int)ed.shot.scene.lights.size() - 1});
                    reload();
                } else if (ed.tool == EditTool::BeamLight) {
                    ed.undo.push(ed.shot.scene);
                    ed.shot.scene.lights.push_back(BeamLight{mw, {1.0f, 0.0f}, 0.1f, 1.0f});
                    ed.clear_selection();
                    ed.select({ObjectId::Light, (int)ed.shot.scene.lights.size() - 1});
                    reload();
                } else {
                    ed.creating = true;
                    ed.create_start = mw;
                }
            }
        }

        // Handle drag (specific parameter modification)
        if (ImGui::IsMouseDragging(0) && ed.handle_dragging) {
            apply_handle_drag(ed.shot.scene, ed.active_handle, mw);
            reload();
        }

        // Drag to move selected objects
        if (ImGui::IsMouseDragging(0) && ed.dragging && !ed.handle_dragging && !ed.box_selecting &&
            ed.drag_offsets.size() == ed.selection.size()) {
            for (int i = 0; i < (int)ed.selection.size(); ++i) {
                auto& sid = ed.selection[i];
                auto& off = ed.drag_offsets[i];
                if (Shape* shape = resolve_shape(ed.shot.scene, sid)) {
                    std::visit(overloaded{
                        [&](Circle& c) { c.center = mw + off.a; },
                        [&](Segment& s) { s.a = mw + off.a; s.b = mw + off.b; },
                        [&](Arc& a) { a.center = mw + off.a; },
                        [&](Bezier& b) {
                            Vec2 delta = (mw + off.a) - b.p0;
                            b.p0 = b.p0 + delta; b.p1 = b.p1 + delta; b.p2 = b.p2 + delta;
                        },
                    }, *shape);
                } else if (Light* light = resolve_light(ed.shot.scene, sid)) {
                    std::visit(overloaded{
                        [&](PointLight& l) { l.pos = mw + off.a; },
                        [&](SegmentLight& l) { l.a = mw + off.a; l.b = mw + off.b; },
                        [&](BeamLight& l) { l.origin = mw + off.a; },
                    }, *light);
                } else if (sid.type == ObjectId::Group && sid.index < (int)ed.shot.scene.groups.size()) {
                    ed.shot.scene.groups[sid.index].transform.translate = mw + off.a;
                }
            }
            reload();
        }

        if (ImGui::IsMouseReleased(0)) {
            // Complete creation
            if (ed.creating) {
                Vec2 end = cv.to_world(io.MousePos);
                float dist = (end - ed.create_start).length();

                ed.undo.push(ed.shot.scene);
                bool created = false;

                if (ed.tool == EditTool::Circle) {
                    float r = std::max(dist, 0.02f);
                    ed.shot.scene.shapes.push_back(Circle{ed.create_start, r, mat_glass(1.5f, 20000.0f, 0.3f)});
                    ed.clear_selection();
                    ed.select({ObjectId::Shape, (int)ed.shot.scene.shapes.size() - 1});
                    created = true;
                } else if (ed.tool == EditTool::Segment && dist > 0.01f) {
                    ed.shot.scene.shapes.push_back(Segment{ed.create_start, end, mat_mirror(0.95f)});
                    ed.clear_selection();
                    ed.select({ObjectId::Shape, (int)ed.shot.scene.shapes.size() - 1});
                    created = true;
                } else if (ed.tool == EditTool::Arc) {
                    ed.shot.scene.shapes.push_back(make_default_arc(ed.create_start, end));
                    ed.clear_selection();
                    ed.select({ObjectId::Shape, (int)ed.shot.scene.shapes.size() - 1});
                    created = true;
                } else if (ed.tool == EditTool::Bezier && dist > 0.01f) {
                    Vec2 mid = (ed.create_start + end) * 0.5f;
                    ed.shot.scene.shapes.push_back(Bezier{ed.create_start, mid, end, mat_glass(1.5f, 20000.0f, 0.3f)});
                    ed.clear_selection();
                    ed.select({ObjectId::Shape, (int)ed.shot.scene.shapes.size() - 1});
                    created = true;
                } else if (ed.tool == EditTool::SegmentLight && dist > 0.01f) {
                    ed.shot.scene.lights.push_back(SegmentLight{ed.create_start, end, 1.0f});
                    ed.clear_selection();
                    ed.select({ObjectId::Light, (int)ed.shot.scene.lights.size() - 1});
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
                for (int i = 0; i < (int)ed.shot.scene.shapes.size(); ++i) {
                    ObjectId id{ObjectId::Shape, i};
                    if (object_in_rect(ed.shot.scene, id, wmin, wmax))
                        ed.select(id);
                }
                for (int i = 0; i < (int)ed.shot.scene.lights.size(); ++i) {
                    ObjectId id{ObjectId::Light, i};
                    if (object_in_rect(ed.shot.scene, id, wmin, wmax))
                        ed.select(id);
                }
                for (int i = 0; i < (int)ed.shot.scene.groups.size(); ++i) {
                    ObjectId id{ObjectId::Group, i};
                    if (object_in_rect(ed.shot.scene, id, wmin, wmax))
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
                        ed.shot = load_builtin_scene(builtins[i]);
                        reset_editor();
                    }
                }
                ImGui::EndCombo();
            }
            if (ImGui::Button("New Scene")) {
                current_scene = -1;
                ed.shot.scene = Scene{};
                ed.shot.name = "custom";
                add_box_walls(ed.shot.scene, 1.0f, 0.7f, mat_mirror(0.95f));
                ed.shot.scene.lights.push_back(PointLight{{0.0f, 0.0f}, 1.0f});
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
                    Shot loaded = load_shot_json(load_path_buf);
                    if (!loaded.scene.shapes.empty() || !loaded.scene.lights.empty() || !loaded.scene.groups.empty()) {
                        ed.shot = loaded;
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

        // -- Camera --
        if (ImGui::CollapsingHeader("Camera", ImGuiTreeNodeFlags_DefaultOpen)) {
            ImGui::PushID("Camera");

            if (ImGui::Button("Set from View")) {
                ed.shot.camera.bounds = ed.camera.visible_bounds((float)win_w, (float)win_h);
                ed.shot.camera.center.reset();
                ed.shot.camera.width.reset();
                ed.dirty = true;
            }
            ImGui::SameLine();
            if (ImGui::Button("Clear") && !ed.shot.camera.empty()) {
                ed.shot.camera = Camera2D{};
                ed.dirty = true;
            }

            ImGui::Checkbox("Show frame", &ed.show_camera_frame);
            ImGui::SameLine();
            ImGui::Checkbox("Dim outside", &ed.dim_outside_camera);

            if (!ed.shot.camera.empty()) {
                Bounds cam = ed.shot.camera.resolve(ed.shot.canvas.aspect(), ed.scene_bounds);
                bool cam_changed = false;
                cam_changed |= ImGui::DragFloat("Min X", &cam.min.x, 0.01f);
                cam_changed |= ImGui::DragFloat("Min Y", &cam.min.y, 0.01f);
                cam_changed |= ImGui::DragFloat("Max X", &cam.max.x, 0.01f);
                cam_changed |= ImGui::DragFloat("Max Y", &cam.max.y, 0.01f);
                if (cam_changed) {
                    ed.shot.camera.bounds = cam;
                    ed.shot.camera.center.reset();
                    ed.shot.camera.width.reset();
                    ed.dirty = true;
                }
            } else {
                ImGui::TextDisabled("Camera: auto (from scene bounds)");
            }

            ImGui::Separator();
            ImGui::TextDisabled("Output resolution for export/CLI");
            int cw = ed.shot.canvas.width, ch = ed.shot.canvas.height;
            bool canvas_changed = false;
            canvas_changed |= ImGui::InputInt("Width##canvas", &cw, 0, 0);
            canvas_changed |= ImGui::InputInt("Height##canvas", &ch, 0, 0);
            if (canvas_changed) {
                ed.shot.canvas.width = std::clamp(cw, 64, 7680);
                ed.shot.canvas.height = std::clamp(ch, 64, 4320);
                ed.dirty = true;
            }
            ImGui::Text("Aspect: %.3f", ed.shot.canvas.aspect());
            ImGui::PopID();
        }

        // -- Objects --
        if (ImGui::CollapsingHeader("Objects", ImGuiTreeNodeFlags_DefaultOpen)) {
            ImGui::PushID("Objects");
            int n_items = (int)(ed.shot.scene.shapes.size() + ed.shot.scene.lights.size() + ed.shot.scene.groups.size());
            float h = std::clamp(n_items * ImGui::GetTextLineHeightWithSpacing() + 8.0f,
                                 40.0f, 200.0f * dpi_scale);
            ImGui::BeginChild("##objlist", ImVec2(0, h), ImGuiChildFlags_Borders);

            for (int i = 0; i < (int)ed.shot.scene.shapes.size(); ++i) {
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
                }, ed.shot.scene.shapes[i]);
                // Material color swatch
                ImVec4 mc = std::visit([](const auto& s) { return material_color(s.material); }, ed.shot.scene.shapes[i]);
                ImGui::PushID(i);
                ImGui::ColorButton("##sw", mc, ImGuiColorEditFlags_NoTooltip | ImGuiColorEditFlags_NoPicker, ImVec2(10, 10));
                ImGui::PopID();
                ImGui::SameLine();
                if (ImGui::Selectable(lbl, is_sel)) {
                    if (io.KeyShift) ed.toggle_select(id);
                    else { ed.clear_selection(); ed.select(id); }
                }
            }

            for (int i = 0; i < (int)ed.shot.scene.lights.size(); ++i) {
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
                }, ed.shot.scene.lights[i]);
                if (ImGui::Selectable(lbl, is_sel)) {
                    if (io.KeyShift) ed.toggle_select(id);
                    else { ed.clear_selection(); ed.select(id); }
                }
            }

            for (int i = 0; i < (int)ed.shot.scene.groups.size(); ++i) {
                ObjectId id{ObjectId::Group, i};
                bool is_sel = ed.is_selected(id);
                bool is_editing = (ed.editing_group == i);
                char lbl[96];
                const auto& group = ed.shot.scene.groups[i];
                int n_members = (int)(group.shapes.size() + group.lights.size());
                if (group.name.empty())
                    std::snprintf(lbl, sizeof(lbl), "%sGroup %d (%d items)", is_editing ? "> " : "", i, n_members);
                else
                    std::snprintf(lbl, sizeof(lbl), "%s%s (%d items)", is_editing ? "> " : "", group.name.c_str(), n_members);
                if (ImGui::Selectable(lbl, is_sel || is_editing)) {
                    if (io.KeyShift) ed.toggle_select(id);
                    else { ed.clear_selection(); ed.select(id); }
                }
                // Show expanded contents when editing inside this group
                if (is_editing) {
                    ImGui::Indent(12.0f);
                    for (int j = 0; j < (int)group.shapes.size(); ++j) {
                        ObjectId mid{ObjectId::Shape, j, i};
                        bool mid_sel = ed.is_selected(mid);
                        char mlbl[96];
                        std::visit(overloaded{
                            [&](const Circle&) { std::snprintf(mlbl, sizeof(mlbl), "  Circle %d", j); },
                            [&](const Segment&) { std::snprintf(mlbl, sizeof(mlbl), "  Segment %d", j); },
                            [&](const Arc&) { std::snprintf(mlbl, sizeof(mlbl), "  Arc %d", j); },
                            [&](const Bezier&) { std::snprintf(mlbl, sizeof(mlbl), "  Bezier %d", j); },
                        }, group.shapes[j]);
                        if (ImGui::Selectable(mlbl, mid_sel)) {
                            ed.clear_selection();
                            ed.select(mid);
                        }
                    }
                    for (int j = 0; j < (int)group.lights.size(); ++j) {
                        ObjectId mid{ObjectId::Light, j, i};
                        bool mid_sel = ed.is_selected(mid);
                        char mlbl[64];
                        std::snprintf(mlbl, sizeof(mlbl), "  Light %d", j);
                        if (ImGui::Selectable(mlbl, mid_sel)) {
                            ed.clear_selection();
                            ed.select(mid);
                        }
                    }
                    ImGui::Unindent(12.0f);
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

            if (sid.group >= 0) {
                ImGui::TextDisabled("Editing group: %s",
                    ed.shot.scene.groups[sid.group].name.empty() ? "(unnamed)" : ed.shot.scene.groups[sid.group].name.c_str());
                ImGui::Separator();
            }

            // Named material dropdown for shape properties
            auto show_material_match = [&](Material& shape_mat) {
                std::string match;
                for (auto& [name, m] : ed.shot.scene.materials)
                    if (shape_mat == m) { match = name; break; }

                if (!match.empty())
                    ImGui::TextColored(ImVec4(0.5f, 0.8f, 0.5f, 1.0f), "= %s", match.c_str());

                if (!ed.shot.scene.materials.empty()) {
                    if (ImGui::BeginCombo("Material##named", match.empty() ? "(custom)" : match.c_str())) {
                        for (auto& [name, m] : ed.shot.scene.materials) {
                            if (ImGui::Selectable(name.c_str(), shape_mat == m)) {
                                if (!ed.prop_editing) { ed.undo.push(ed.shot.scene); ed.prop_editing = true; }
                                shape_mat = m;
                                changed = true;
                            }
                        }
                        ImGui::EndCombo();
                    }
                }
            };

            if (Shape* sp = resolve_shape(ed.shot.scene, sid)) {
                auto& shape = *sp;
                std::visit(overloaded{
                    [&](Circle& c) {
                        changed |= ImGui::DragFloat2("Center", &c.center.x, 0.01f);
                        changed |= ImGui::DragFloat("Radius", &c.radius, 0.005f, 0.01f, 5.0f);
                        changed |= edit_material(c.material);
                        show_material_match(c.material);
                    },
                    [&](Segment& s) {
                        changed |= ImGui::DragFloat2("Point A", &s.a.x, 0.01f);
                        changed |= ImGui::DragFloat2("Point B", &s.b.x, 0.01f);
                        changed |= edit_material(s.material);
                        show_material_match(s.material);
                    },
                    [&](Arc& a) {
                        changed |= ImGui::DragFloat2("Center", &a.center.x, 0.01f);
                        changed |= ImGui::DragFloat("Radius", &a.radius, 0.005f, 0.01f, 5.0f);
                        changed |= ImGui::SliderAngle("Start angle", &a.angle_start, 0.0f, 360.0f);
                        changed |= ImGui::SliderAngle("Sweep", &a.sweep, 0.0f, 360.0f);
                        a.angle_start = normalize_angle(a.angle_start);
                        a.sweep = clamp_arc_sweep(a.sweep);
                        changed |= edit_material(a.material);
                        show_material_match(a.material);
                    },
                    [&](Bezier& b) {
                        changed |= ImGui::DragFloat2("P0", &b.p0.x, 0.01f);
                        changed |= ImGui::DragFloat2("P1 (ctrl)", &b.p1.x, 0.01f);
                        changed |= ImGui::DragFloat2("P2", &b.p2.x, 0.01f);
                        changed |= edit_material(b.material);
                        show_material_match(b.material);
                    },
                }, shape);
            }

            if (Light* lp = resolve_light(ed.shot.scene, sid)) {
                auto& light = *lp;
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

            if (sid.type == ObjectId::Group && sid.index < (int)ed.shot.scene.groups.size()) {
                auto& group = ed.shot.scene.groups[sid.index];
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
                    ed.undo.push(ed.shot.scene);
                    ed.prop_editing = true;
                }
                reload();
            }
            if (!ImGui::IsAnyItemActive() && ed.prop_editing) {
                ed.prop_editing = false;
            }
            ImGui::PopID();
        }

        // -- Material Library --
        if (ImGui::CollapsingHeader("Materials", ImGuiTreeNodeFlags_DefaultOpen)) {
            ImGui::PushID("Materials");
            static std::string selected_mat_name;
            static char new_name_buf[64] = "";

            // Material list
            auto& mats = ed.shot.scene.materials;
            if (mats.empty()) {
                ImGui::TextDisabled("No materials defined");
            } else {
                if (ImGui::BeginCombo("##matlist", selected_mat_name.empty() ? "(select)" : selected_mat_name.c_str())) {
                    for (auto& [name, _] : mats) {
                        if (ImGui::Selectable(name.c_str(), name == selected_mat_name))
                            selected_mat_name = name;
                    }
                    ImGui::EndCombo();
                }
            }

            // Track material snapshot for "Update Matching" feature
            static Material mat_snapshot;
            static std::string last_selected_name;
            if (selected_mat_name != last_selected_name) {
                last_selected_name = selected_mat_name;
                if (mats.count(selected_mat_name))
                    mat_snapshot = mats[selected_mat_name];
            }

            // Edit selected material
            if (!selected_mat_name.empty() && mats.count(selected_mat_name)) {
                auto& mat = mats[selected_mat_name];
                edit_material(mat);

                // Count shapes matching this material's original value
                int match_count = 0;
                auto count_mat = [&](const auto& shapes) {
                    for (auto& s : shapes)
                        std::visit([&](const auto& shape) { if (shape.material == mat_snapshot) ++match_count; }, s);
                };
                count_mat(ed.shot.scene.shapes);
                for (auto& g : ed.shot.scene.groups) count_mat(g.shapes);

                if (match_count > 0) {
                    ImGui::Text("%d shape(s) use this material", match_count);
                    ImGui::SameLine();
                    if (ImGui::Button("Update Matching")) {
                        ed.undo.push(ed.shot.scene);
                        auto apply_mat = [&](auto& shapes) {
                            for (auto& s : shapes)
                                std::visit([&](auto& shape) {
                                    if (shape.material == mat_snapshot) shape.material = mat;
                                }, s);
                        };
                        apply_mat(ed.shot.scene.shapes);
                        for (auto& g : ed.shot.scene.groups) apply_mat(g.shapes);
                        mat_snapshot = mat;
                        reload();
                    }
                }

                // Apply buttons
                if (ImGui::Button("Apply to Selection")) {
                    ed.undo.push(ed.shot.scene);
                    for (auto& id : ed.selection) {
                        if (id.type == ObjectId::Shape && id.index < (int)ed.shot.scene.shapes.size()) {
                            std::visit([&](auto& s) { s.material = mat; }, ed.shot.scene.shapes[id.index]);
                        } else if (id.type == ObjectId::Group && id.index < (int)ed.shot.scene.groups.size()) {
                            for (auto& s : ed.shot.scene.groups[id.index].shapes)
                                std::visit([&](auto& shape) { shape.material = mat; }, s);
                        }
                    }
                    reload();
                }
                ImGui::SameLine();
                if (ImGui::Button("Delete##mat")) {
                    ed.undo.push(ed.shot.scene);
                    mats.erase(selected_mat_name);
                    selected_mat_name.clear();
                    reload();
                }
            }

            ImGui::Separator();

            // Create new material
            ImGui::InputText("Name##newmat", new_name_buf, sizeof(new_name_buf));
            ImGui::SameLine();
            if (ImGui::Button("Add") && new_name_buf[0] != '\0' && !mats.count(new_name_buf)) {
                ed.undo.push(ed.shot.scene);
                mats[new_name_buf] = Material{};
                selected_mat_name = new_name_buf;
                new_name_buf[0] = '\0';
            }

            // Presets
            auto preset_btn = [&](const char* label, Material mat) {
                if (ImGui::SmallButton(label)) {
                    std::string name = label;
                    // Avoid collision
                    if (mats.count(name)) { int n = 2; while (mats.count(name + " " + std::to_string(n))) ++n; name += " " + std::to_string(n); }
                    ed.undo.push(ed.shot.scene);
                    mats[name] = mat;
                    selected_mat_name = name;
                }
            };
            preset_btn("Glass", mat_glass(1.5f, 20000.0f));
            ImGui::SameLine();
            preset_btn("Mirror", mat_opaque_mirror(0.95f));
            ImGui::SameLine();
            preset_btn("Diffuse", mat_diffuse(0.8f));
            ImGui::SameLine();
            preset_btn("Absorber", mat_absorber());

            ImGui::PopID();
        }

        // -- Tracer --
        if (ImGui::CollapsingHeader("Tracer", ImGuiTreeNodeFlags_DefaultOpen)) {
            ImGui::PushID("Tracer");
            ImGui::SliderInt("Batch", &ed.shot.trace.batch, 1000, 1000000, "%d",
                             ImGuiSliderFlags_Logarithmic);
            ImGui::SliderInt("Max depth", &ed.shot.trace.depth, 1, 30);
            ImGui::SliderFloat("Intensity", &ed.shot.trace.intensity, 0.001f, 10.0f, "%.3f",
                               ImGuiSliderFlags_Logarithmic);
            ImGui::Checkbox("Paused", &paused);
            ImGui::PopID();
        }

        // -- Display --
        if (ImGui::CollapsingHeader("Display", ImGuiTreeNodeFlags_DefaultOpen)) {
            ImGui::PushID("Display");
            ImGui::SliderFloat("Exposure", &ed.shot.look.exposure, -15.0f, 15.0f);
            ImGui::SliderFloat("Contrast", &ed.shot.look.contrast, 0.1f, 3.0f);
            ImGui::SliderFloat("Gamma", &ed.shot.look.gamma, 0.5f, 4.0f);
            ImGui::SliderFloat("White point", &ed.shot.look.white_point, 0.1f, 10.0f);
            const char* tone_names[] = {"None", "Reinhard", "Reinhard Ext", "ACES", "Logarithmic"};
            int tm = (int)ed.shot.look.tone_map;
            if (ImGui::Combo("Tone map", &tm, tone_names, 5))
                ed.shot.look.tone_map = (ToneMap)tm;
            const char* norm_names[] = {"Auto (Max)", "Ray Count", "Fixed Ref", "Off"};
            int nm = (int)ed.shot.look.normalize;
            if (ImGui::Combo("Normalize", &nm, norm_names, 4))
                ed.shot.look.normalize = (NormalizeMode)nm;
            if (ed.shot.look.normalize == NormalizeMode::Max) {
                ImGui::SliderFloat("Percentile", &ed.shot.look.normalize_pct, 0.9f, 1.0f, "%.3f");
            }
            if (ed.shot.look.normalize == NormalizeMode::Fixed) {
                ImGui::SliderFloat("Ref value", &ed.shot.look.normalize_ref, 1.0f, 1000000.0f,
                                   "%.0f", ImGuiSliderFlags_Logarithmic);
                if (ImGui::Button("Capture Ref")) {
                    ed.shot.look.normalize_ref = renderer.compute_current_max();
                }
            }
            ImGui::Separator();
            ImGui::SliderFloat("Ambient", &ed.shot.look.ambient, 0.0f, 0.5f, "%.3f");
            ImGui::ColorEdit3("Background", ed.shot.look.background,
                              ImGuiColorEditFlags_Float | ImGuiColorEditFlags_HDR);
            ImGui::SliderFloat("Opacity", &ed.shot.look.opacity, 0.0f, 1.0f);
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
            if (ed.shot.look.normalize == NormalizeMode::Max)
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
                renderer.read_pixels(pixels, ed.shot.look);
                std::string filename = ed.shot.name + ".png";
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

                // Live-apply transform every frame for real-time re-tracing
                for (auto& sid : ed.selection) {
                    if (Shape* live = resolve_shape(ed.shot.scene, sid)) {
                        if (const Shape* snap = resolve_shape(ed.transform.snapshot, sid))
                            apply_transform_shape(*live, *snap, ed.transform, mw, io.KeyShift);
                    } else if (Light* live = resolve_light(ed.shot.scene, sid)) {
                        if (const Light* snap = resolve_light(ed.transform.snapshot, sid))
                            apply_transform_light(*live, *snap, ed.transform, mw, io.KeyShift);
                    } else if (sid.type == ObjectId::Group && sid.index < (int)ed.shot.scene.groups.size()
                               && sid.index < (int)ed.transform.snapshot.groups.size()) {
                        apply_transform_group(ed.shot.scene.groups[sid.index],
                            ed.transform.snapshot.groups[sid.index], ed.transform, mw, io.KeyShift);
                    }
                }
                reload();

                // Confirm
                if (ImGui::IsKeyPressed(ImGuiKey_Enter) || ImGui::IsMouseClicked(0)) {
                    ed.transform.type = TransformMode::None;
                    ed.transform.snapshot = {};
                }

                // Cancel
                if (ImGui::IsKeyPressed(ImGuiKey_Escape) || ImGui::IsMouseClicked(1)) {
                    ed.shot.scene = ed.transform.snapshot;
                    ed.transform.type = TransformMode::None;
                    ed.transform.snapshot = {};
                    reload();
                }
            } else {
                // --- Global shortcuts ---

                // Undo/Redo
                if (io.KeyCtrl && io.KeyShift && ImGui::IsKeyPressed(ImGuiKey_Z)) {
                    if (ed.undo.redo(ed.shot.scene)) { ed.validate_selection(); reload(); }
                } else if (io.KeyCtrl && ImGui::IsKeyPressed(ImGuiKey_Z)) {
                    if (ed.undo.undo(ed.shot.scene)) { ed.validate_selection(); reload(); }
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
                        if (sid.type == ObjectId::Group && sid.index < (int)ed.shot.scene.groups.size()) {
                            any_ungrouped = true;
                            break;
                        }
                    }
                    if (any_ungrouped) {
                        ed.undo.push(ed.shot.scene);
                        std::vector<ObjectId> new_sel;
                        // Collect group indices to remove (reverse order)
                        std::vector<int> to_remove;
                        for (auto& sid : ed.selection) {
                            if (sid.type != ObjectId::Group) continue;
                            if (sid.index >= (int)ed.shot.scene.groups.size()) continue;
                            auto& group = ed.shot.scene.groups[sid.index];
                            // Bake transform into shapes/lights and add to scene
                            for (auto& s : group.shapes) {
                                Shape ws = transform_shape(s, group.transform);
                                ed.shot.scene.shapes.push_back(ws);
                                new_sel.push_back({ObjectId::Shape, (int)ed.shot.scene.shapes.size() - 1});
                            }
                            for (auto& l : group.lights) {
                                Light wl = transform_light(l, group.transform);
                                ed.shot.scene.lights.push_back(wl);
                                new_sel.push_back({ObjectId::Light, (int)ed.shot.scene.lights.size() - 1});
                            }
                            to_remove.push_back(sid.index);
                        }
                        // Remove groups in reverse order
                        std::sort(to_remove.rbegin(), to_remove.rend());
                        for (int idx : to_remove)
                            ed.shot.scene.groups.erase(ed.shot.scene.groups.begin() + idx);
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
                        if (sid.type == ObjectId::Group || sid.group >= 0) has_groups = true;
                        else n_ungrouped++;
                    }
                    if (n_ungrouped >= 2 && !has_groups) {
                        ed.undo.push(ed.shot.scene);
                        // Compute centroid
                        Vec2 centroid = ed.selection_centroid();
                        Group group;
                        static int group_counter = 0;
                        group.name = "Group " + std::to_string(group_counter++);
                        group.transform.translate = centroid;

                        // Collect shapes/lights, converting to local coords
                        std::vector<int> shape_indices, light_indices;
                        for (auto& sid : ed.selection) {
                            if (sid.type == ObjectId::Shape && sid.index < (int)ed.shot.scene.shapes.size()) {
                                Shape s = ed.shot.scene.shapes[sid.index];
                                translate_shape(s, Vec2{0, 0} - centroid);
                                group.shapes.push_back(s);
                                shape_indices.push_back(sid.index);
                            } else if (sid.type == ObjectId::Light && sid.index < (int)ed.shot.scene.lights.size()) {
                                Light l = ed.shot.scene.lights[sid.index];
                                translate_light(l, Vec2{0, 0} - centroid);
                                group.lights.push_back(l);
                                light_indices.push_back(sid.index);
                            }
                        }

                        // Remove originals (reverse order to preserve indices)
                        std::sort(shape_indices.rbegin(), shape_indices.rend());
                        std::sort(light_indices.rbegin(), light_indices.rend());
                        for (int idx : light_indices)
                            ed.shot.scene.lights.erase(ed.shot.scene.lights.begin() + idx);
                        for (int idx : shape_indices)
                            ed.shot.scene.shapes.erase(ed.shot.scene.shapes.begin() + idx);

                        ed.shot.scene.groups.push_back(std::move(group));
                        ed.clear_selection();
                        ed.select({ObjectId::Group, (int)ed.shot.scene.groups.size() - 1});
                        reload();
                    }
                }

                // Copy/Paste/Cut/Duplicate
                if (io.KeyCtrl && ImGui::IsKeyPressed(ImGuiKey_C)) {
                    copy_to_clipboard();
                }

                if (io.KeyCtrl && ImGui::IsKeyPressed(ImGuiKey_V) && !ed.clipboard.empty()) {
                    ed.undo.push(ed.shot.scene);
                    Vec2 offset = mw - ed.clipboard.centroid;
                    ed.clear_selection();
                    for (auto s : ed.clipboard.shapes) {
                        translate_shape(s, offset);
                        ed.shot.scene.shapes.push_back(s);
                        ed.select({ObjectId::Shape, (int)ed.shot.scene.shapes.size() - 1});
                    }
                    for (auto l : ed.clipboard.lights) {
                        translate_light(l, offset);
                        ed.shot.scene.lights.push_back(l);
                        ed.select({ObjectId::Light, (int)ed.shot.scene.lights.size() - 1});
                    }
                    for (auto g : ed.clipboard.groups) {
                        translate_group(g, offset);
                        ed.shot.scene.groups.push_back(g);
                        ed.select({ObjectId::Group, (int)ed.shot.scene.groups.size() - 1});
                    }
                    reload();
                }

                if (io.KeyCtrl && ImGui::IsKeyPressed(ImGuiKey_X)) {
                    copy_to_clipboard();
                    delete_selected();
                }

                if (io.KeyCtrl && ImGui::IsKeyPressed(ImGuiKey_D) && !ed.selection.empty()) {
                    // Duplicate: copy in place with small offset, then enter grab
                    ed.undo.push(ed.shot.scene);
                    std::vector<ObjectId> new_sel;
                    Vec2 offset{0.05f, 0.05f};
                    for (auto& sid : ed.selection) {
                        if (const Shape* shape = resolve_shape(ed.shot.scene, sid)) {
                            Shape s = *shape;
                            translate_shape(s, offset);
                            ed.shot.scene.shapes.push_back(s);
                            new_sel.push_back({ObjectId::Shape, (int)ed.shot.scene.shapes.size() - 1});
                        } else if (const Light* light = resolve_light(ed.shot.scene, sid)) {
                            Light l = *light;
                            translate_light(l, offset);
                            ed.shot.scene.lights.push_back(l);
                            new_sel.push_back({ObjectId::Light, (int)ed.shot.scene.lights.size() - 1});
                        } else if (sid.type == ObjectId::Group) {
                            Group g = ed.shot.scene.groups[sid.index];
                            translate_group(g, offset);
                            ed.shot.scene.groups.push_back(g);
                            new_sel.push_back({ObjectId::Group, (int)ed.shot.scene.groups.size() - 1});
                        }
                    }
                    ed.selection = new_sel;

                    // Enter grab mode
                    ed.transform.type = TransformMode::Grab;
                    ed.transform.pivot = ed.selection_centroid();
                    ed.transform.mouse_start = mw;
                    ed.transform.lock_x = ed.transform.lock_y = false;
                    ed.transform.numeric_buf.clear();
                    ed.transform.snapshot = ed.shot.scene;
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
                        ed.transform.snapshot = ed.shot.scene;
                        ed.undo.push(ed.shot.scene);
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
                    } else if (ed.editing_group >= 0) {
                        ed.editing_group = -1;
                        ed.clear_selection();
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
                ed.shot.name.empty() ? "untitled" : ed.shot.name.c_str(),
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
