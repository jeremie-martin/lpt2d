#include "app.h"

#include "export.h"
#include "renderer.h"

#include <GL/glew.h>
#include <GLFW/glfw3.h>
#include <imgui.h>
#include <imgui_impl_glfw.h>
#include <imgui_impl_opengl3.h>

#include <algorithm>
#include <chrono>
#include <cstdio>
#include <iostream>

// ─── Types ──────────────────────────────────────────────────────────────

enum class EditTool { Select, Circle, Segment, Arc, Bezier, PointLight, SegmentLight, BeamLight, Erase };

struct ViewTransform {
    Bounds bounds;
    float scale, ox, oy, w, h;
};

struct Selection {
    enum Type { None, Shape, Light } type = None;
    int index = -1;
};

// ─── Coordinate helpers ─────────────────────────────────────────────────

static ViewTransform compute_view(const Bounds& bounds, float w, float h) {
    Vec2 sz = bounds.max - bounds.min;
    sz.x = std::max(sz.x, 0.01f);
    sz.y = std::max(sz.y, 0.01f);
    float s = std::min(w / sz.x, h / sz.y);
    return {bounds, s, (w - sz.x * s) * 0.5f, (h - sz.y * s) * 0.5f, w, h};
}

static ImVec2 to_screen(const ViewTransform& vt, Vec2 p) {
    return {(p.x - vt.bounds.min.x) * vt.scale + vt.ox,
            vt.h - ((p.y - vt.bounds.min.y) * vt.scale + vt.oy)};
}

static Vec2 to_world(const ViewTransform& vt, ImVec2 s) {
    return {(s.x - vt.ox) / vt.scale + vt.bounds.min.x,
            (vt.h - s.y - vt.oy) / vt.scale + vt.bounds.min.y};
}

// ─── Hit testing ────────────────────────────────────────────────────────

static float point_seg_dist(Vec2 p, Vec2 a, Vec2 b) {
    Vec2 ab = b - a;
    float len2 = ab.length_sq();
    if (len2 < 1e-10f) return (p - a).length();
    float t = std::clamp((p - a).dot(ab) / len2, 0.0f, 1.0f);
    return (p - (a + ab * t)).length();
}

static Selection hit_test(Vec2 wp, const Scene& scene, float threshold) {
    Selection sel;
    float best = threshold;
    for (int i = 0; i < (int)scene.shapes.size(); ++i) {
        float d = std::visit(overloaded{
            [&](const Circle& c) -> float {
                float dc = (wp - c.center).length();
                return dc < c.radius ? 0.0f : dc - c.radius;
            },
            [&](const Segment& s) -> float { return point_seg_dist(wp, s.a, s.b); },
            [&](const Arc& a) -> float {
                float dc = (wp - a.center).length();
                return dc < a.radius ? 0.0f : dc - a.radius;
            },
            [&](const Bezier& b) -> float {
                // Approximate: sample curve at N points, find min distance
                float best = 1e30f;
                for (int j = 0; j <= 20; ++j) {
                    float t = j / 20.0f;
                    float u = 1.0f - t;
                    Vec2 p = b.p0 * (u * u) + b.p1 * (2.0f * u * t) + b.p2 * (t * t);
                    best = std::min(best, (wp - p).length());
                }
                return best;
            },
        }, scene.shapes[i]);
        if (d < best) { best = d; sel = {Selection::Shape, i}; }
    }
    for (int i = 0; i < (int)scene.lights.size(); ++i) {
        float d = std::visit(overloaded{
            [&](const PointLight& l) -> float { return (wp - l.pos).length(); },
            [&](const SegmentLight& l) -> float { return point_seg_dist(wp, l.a, l.b); },
            [&](const BeamLight& l) -> float { return (wp - l.origin).length(); },
        }, scene.lights[i]);
        if (d < best) { best = d; sel = {Selection::Light, i}; }
    }
    return sel;
}

// ─── Helpers ────────────────────────────────────────────────────────────

static const char* material_name(const Material& m) {
    if (m.albedo <= 0.0f) return "Absorber";
    if (m.transmission > 0.5f && m.metallic < 0.5f && m.ior > 1.01f) return "Glass";
    if (m.metallic > 0.5f) return "Mirror";
    if (m.roughness > 0.5f) return "Diffuse";
    return "Material";
}

// ─── Material editor ────────────────────────────────────────────────────

static bool edit_material(Material& mat) {
    bool changed = false;

    // Quick presets
    const char* presets[] = {"(custom)", "Absorber", "Diffuse", "Mirror", "Glass"};
    int preset = 0;
    if (ImGui::Combo("Preset", &preset, presets, 5)) {
        if (preset == 1) mat = mat_absorber();
        else if (preset == 2) mat = mat_diffuse(0.5f);
        else if (preset == 3) mat = mat_mirror(0.95f);
        else if (preset == 4) mat = mat_glass(1.5f, 20000.0f, 0.3f);
        if (preset > 0) changed = true;
    }

    changed |= ImGui::SliderFloat("IOR", &mat.ior, 1.0f, 3.0f);
    changed |= ImGui::SliderFloat("Roughness", &mat.roughness, 0.0f, 1.0f);
    changed |= ImGui::SliderFloat("Metallic", &mat.metallic, 0.0f, 1.0f);
    changed |= ImGui::SliderFloat("Transmission", &mat.transmission, 0.0f, 1.0f);
    changed |= ImGui::SliderFloat("Absorption", &mat.absorption, 0.0f, 2.0f);
    changed |= ImGui::SliderFloat("Dispersion", &mat.cauchy_b, 0.0f, 50000.0f, "%.0f");
    changed |= ImGui::SliderFloat("Albedo", &mat.albedo, 0.0f, 1.0f);
    return changed;
}

// ─── Style ──────────────────────────────────────────────────────────────

static void apply_style(float s) {
    auto& st = ImGui::GetStyle();
    st.WindowPadding     = {10 * s, 10 * s};
    st.FramePadding      = {6 * s, 3 * s};
    st.ItemSpacing       = {8 * s, 5 * s};
    st.WindowRounding    = 6 * s;
    st.FrameRounding     = 3 * s;
    st.GrabRounding      = 3 * s;
    st.ScrollbarRounding = 3 * s;
    st.ScrollbarSize     = 12 * s;
    st.GrabMinSize       = 10 * s;
    st.WindowBorderSize  = 1;
    st.FrameBorderSize   = 0;

    auto c = [](int r, int g, int b, int a = 255) {
        return ImVec4(r / 255.f, g / 255.f, b / 255.f, a / 255.f);
    };
    auto& col = st.Colors;
    col[ImGuiCol_WindowBg]             = c(18, 20, 26, 235);
    col[ImGuiCol_ChildBg]              = c(22, 24, 30, 200);
    col[ImGuiCol_Border]               = c(50, 55, 65, 180);
    col[ImGuiCol_FrameBg]              = c(32, 35, 44);
    col[ImGuiCol_FrameBgHovered]       = c(42, 48, 60);
    col[ImGuiCol_FrameBgActive]        = c(50, 58, 72);
    col[ImGuiCol_TitleBg]              = c(18, 20, 26);
    col[ImGuiCol_TitleBgActive]        = c(24, 28, 38);
    col[ImGuiCol_Button]               = c(44, 50, 64);
    col[ImGuiCol_ButtonHovered]        = c(58, 68, 88);
    col[ImGuiCol_ButtonActive]         = c(72, 84, 108);
    col[ImGuiCol_Header]               = c(38, 42, 56);
    col[ImGuiCol_HeaderHovered]        = c(50, 58, 78);
    col[ImGuiCol_HeaderActive]         = c(60, 70, 95);
    col[ImGuiCol_SliderGrab]           = c(80, 135, 220);
    col[ImGuiCol_SliderGrabActive]     = c(100, 155, 240);
    col[ImGuiCol_CheckMark]            = c(80, 135, 220);
    col[ImGuiCol_Separator]            = c(48, 52, 64, 200);
    col[ImGuiCol_Text]                 = c(220, 222, 228);
    col[ImGuiCol_TextDisabled]         = c(110, 112, 120);
    col[ImGuiCol_ScrollbarBg]          = c(18, 20, 26, 150);
    col[ImGuiCol_ScrollbarGrab]        = c(55, 60, 72);
    col[ImGuiCol_ScrollbarGrabHovered] = c(70, 78, 92);
    col[ImGuiCol_ScrollbarGrabActive]  = c(85, 95, 112);
    col[ImGuiCol_Tab]                  = c(28, 32, 42);
    col[ImGuiCol_TabHovered]           = c(50, 58, 78);
    col[ImGuiCol_PopupBg]              = c(22, 24, 32, 245);
}

// ─── Overlay colors ─────────────────────────────────────────────────────

static constexpr ImU32 COL_SHAPE     = IM_COL32(200, 200, 210, 90);
static constexpr ImU32 COL_SHAPE_SEL = IM_COL32(80, 140, 235, 200);
static constexpr ImU32 COL_LIGHT     = IM_COL32(255, 210, 60, 120);
static constexpr ImU32 COL_LIGHT_SEL = IM_COL32(255, 230, 80, 220);
static constexpr ImU32 COL_PREVIEW   = IM_COL32(255, 255, 255, 140);

// ─── App::run ───────────────────────────────────────────────────────────

int App::run(const std::vector<SceneFactory>& scenes, const AppConfig& config) {
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
    if (!io.Fonts->AddFontFromFileTTF("external/imgui/misc/fonts/Roboto-Medium.ttf", font_size)) {
        ImFontConfig cfg;
        cfg.SizePixels = font_size;
        io.Fonts->AddFontDefault(&cfg);
    }
    apply_style(dpi_scale);

    // ── Scene state ──
    int current_scene = 0;
    if (!config.initial_scene.empty()) {
        for (int i = 0; i < (int)scenes.size(); ++i) {
            if (scenes[i].first == config.initial_scene) { current_scene = i; break; }
        }
    }
    Scene scene = scenes[current_scene].second();
    Bounds bounds = compute_bounds(scene);
    renderer.upload_scene(scene, bounds);
    renderer.clear();
    ViewTransform vt = compute_view(bounds, (float)win_w, (float)win_h);

    TraceConfig tcfg;
    tcfg.batch_size = 50000; // Lower default for interactive responsiveness
    PostProcess pp;
    int64_t total_rays = 0;
    bool paused = false;
    float frame_ms = 16.0f;

    // ── Edit state ──
    EditTool tool = EditTool::Select;
    Selection sel;
    bool show_wireframe = true;
    bool creating = false;
    bool dragging = false;
    Vec2 create_start{};
    Vec2 drag_offset{}, drag_offset_b{};

    auto delete_selected = [&]() {
        if (sel.type == Selection::Shape && sel.index < (int)scene.shapes.size()) {
            scene.shapes.erase(scene.shapes.begin() + sel.index);
            sel = {};
            return true;
        }
        if (sel.type == Selection::Light && sel.index < (int)scene.lights.size()) {
            scene.lights.erase(scene.lights.begin() + sel.index);
            sel = {};
            return true;
        }
        return false;
    };

    auto reload = [&]() {
        if (scene.shapes.empty() && scene.lights.empty())
            bounds = {{-1, -1}, {1, 1}};
        else
            bounds = compute_bounds(scene);
        renderer.upload_scene(scene, bounds);
        renderer.clear();
        total_rays = 0;
        vt = compute_view(bounds, (float)win_w, (float)win_h);
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
        if (sel.type == Selection::Shape && sel.index >= (int)scene.shapes.size()) sel = {};
        if (sel.type == Selection::Light && sel.index >= (int)scene.lights.size()) sel = {};

        // Trace
        auto t0 = std::chrono::steady_clock::now();
        if (!paused && !scene.lights.empty()) {
            renderer.trace_and_draw(tcfg);
            glFinish(); // Prevent GPU command queue buildup — keeps system responsive
            total_rays += tcfg.batch_size;
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

        ImGui::Image((ImTextureID)(intptr_t)renderer.display_texture(),
                     ImVec2((float)win_w, (float)win_h),
                     ImVec2(0, 1), ImVec2(1, 0)); // Flip V: OpenGL texture has Y-up

        bool vp_hovered = ImGui::IsWindowHovered();

        // Overlay
        if (show_wireframe) {
            ImDrawList* dl = ImGui::GetWindowDrawList();

            for (int i = 0; i < (int)scene.shapes.size(); ++i) {
                bool is_sel = (sel.type == Selection::Shape && sel.index == i);
                ImU32 col = is_sel ? COL_SHAPE_SEL : COL_SHAPE;
                float th = (is_sel ? 2.5f : 1.5f) * dpi_scale;
                std::visit(overloaded{
                    [&](const Circle& c) {
                        dl->AddCircle(to_screen(vt, c.center), c.radius * vt.scale, col, 64, th);
                    },
                    [&](const Segment& s) {
                        dl->AddLine(to_screen(vt, s.a), to_screen(vt, s.b), col, th);
                    },
                    [&](const Arc& a) {
                        // Draw arc as polyline
                        constexpr int N = 64;
                        float span = a.angle_end - a.angle_start;
                        if (span < 0) span += TWO_PI;
                        for (int j = 0; j < N; ++j) {
                            float t0 = a.angle_start + span * j / N;
                            float t1 = a.angle_start + span * (j + 1) / N;
                            Vec2 p0 = a.center + Vec2{a.radius * std::cos(t0), a.radius * std::sin(t0)};
                            Vec2 p1 = a.center + Vec2{a.radius * std::cos(t1), a.radius * std::sin(t1)};
                            dl->AddLine(to_screen(vt, p0), to_screen(vt, p1), col, th);
                        }
                    },
                    [&](const Bezier& b) {
                        // Draw bezier as polyline + control point
                        constexpr int N = 32;
                        for (int j = 0; j < N; ++j) {
                            float t0 = (float)j / N, t1 = (float)(j + 1) / N;
                            float u0 = 1.0f - t0, u1 = 1.0f - t1;
                            Vec2 p0 = b.p0 * (u0*u0) + b.p1 * (2.0f*u0*t0) + b.p2 * (t0*t0);
                            Vec2 p1 = b.p0 * (u1*u1) + b.p1 * (2.0f*u1*t1) + b.p2 * (t1*t1);
                            dl->AddLine(to_screen(vt, p0), to_screen(vt, p1), col, th);
                        }
                        // Draw control point marker
                        dl->AddCircleFilled(to_screen(vt, b.p1), 3.0f * dpi_scale, col);
                    },
                }, scene.shapes[i]);
            }

            for (int i = 0; i < (int)scene.lights.size(); ++i) {
                bool is_sel = (sel.type == Selection::Light && sel.index == i);
                ImU32 col = is_sel ? COL_LIGHT_SEL : COL_LIGHT;
                float th = (is_sel ? 3.0f : 2.0f) * dpi_scale;
                std::visit(overloaded{
                    [&](const PointLight& l) {
                        float r = (is_sel ? 5.0f : 4.0f) * dpi_scale;
                        dl->AddCircleFilled(to_screen(vt, l.pos), r, col);
                    },
                    [&](const SegmentLight& l) {
                        ImVec2 a = to_screen(vt, l.a), b = to_screen(vt, l.b);
                        dl->AddLine(a, b, col, th);
                        dl->AddCircleFilled(a, 3.0f * dpi_scale, col);
                        dl->AddCircleFilled(b, 3.0f * dpi_scale, col);
                    },
                    [&](const BeamLight& l) {
                        ImVec2 o = to_screen(vt, l.origin);
                        dl->AddCircleFilled(o, (is_sel ? 5.0f : 4.0f) * dpi_scale, col);
                        // Draw direction line and angular wedge
                        Vec2 d = l.direction.normalized();
                        ImVec2 tip = to_screen(vt, l.origin + d * 0.3f);
                        dl->AddLine(o, tip, col, th);
                        // Wedge edges
                        float half_w = l.angular_width * 0.5f;
                        float base_a = std::atan2(d.y, d.x);
                        Vec2 w1{std::cos(base_a + half_w), std::sin(base_a + half_w)};
                        Vec2 w2{std::cos(base_a - half_w), std::sin(base_a - half_w)};
                        dl->AddLine(o, to_screen(vt, l.origin + w1 * 0.2f), col, th * 0.5f);
                        dl->AddLine(o, to_screen(vt, l.origin + w2 * 0.2f), col, th * 0.5f);
                    },
                }, scene.lights[i]);
            }

            // Creation preview
            if (creating) {
                Vec2 mw = to_world(vt, io.MousePos);
                if (tool == EditTool::Circle || tool == EditTool::Arc) {
                    float r = (mw - create_start).length() * vt.scale;
                    dl->AddCircle(to_screen(vt, create_start), r, COL_PREVIEW, 64, 1.5f * dpi_scale);
                } else if (tool == EditTool::Segment || tool == EditTool::SegmentLight || tool == EditTool::Bezier) {
                    dl->AddLine(to_screen(vt, create_start), io.MousePos, COL_PREVIEW, 1.5f * dpi_scale);
                }
            }
        }

        ImGui::End();
        ImGui::PopStyleVar();

        // ── Mouse interaction ───────────────────────────────────────────

        Vec2 mw = to_world(vt, io.MousePos);
        float hit_thresh = 8.0f / vt.scale;

        if (vp_hovered && ImGui::IsMouseClicked(0)) {
            if (tool == EditTool::Select) {
                Selection hit = hit_test(mw, scene, hit_thresh);
                if (hit.type != Selection::None) {
                    sel = hit;
                    dragging = true;
                    if (sel.type == Selection::Shape) {
                        std::visit(overloaded{
                            [&](const Circle& c) { drag_offset = c.center - mw; },
                            [&](const Segment& s) { drag_offset = s.a - mw; drag_offset_b = s.b - mw; },
                            [&](const Arc& a) { drag_offset = a.center - mw; },
                            [&](const Bezier& b) { drag_offset = b.p0 - mw; drag_offset_b = b.p2 - mw; },
                        }, scene.shapes[sel.index]);
                    } else {
                        std::visit(overloaded{
                            [&](const PointLight& l) { drag_offset = l.pos - mw; },
                            [&](const SegmentLight& l) { drag_offset = l.a - mw; drag_offset_b = l.b - mw; },
                            [&](const BeamLight& l) { drag_offset = l.origin - mw; },
                        }, scene.lights[sel.index]);
                    }
                } else {
                    sel = {};
                }
            } else if (tool == EditTool::Erase) {
                sel = hit_test(mw, scene, hit_thresh);
                if (delete_selected()) reload();
            } else if (tool == EditTool::PointLight) {
                scene.lights.push_back(PointLight{mw, 1.0f});
                sel = {Selection::Light, (int)scene.lights.size() - 1};
                reload();
            } else if (tool == EditTool::BeamLight) {
                scene.lights.push_back(BeamLight{mw, {1.0f, 0.0f}, 0.1f, 1.0f});
                sel = {Selection::Light, (int)scene.lights.size() - 1};
                reload();
            } else {
                creating = true;
                create_start = mw;
            }
        }

        // Drag to move objects
        if (ImGui::IsMouseDragging(0) && dragging && sel.type != Selection::None) {
            if (sel.type == Selection::Shape) {
                std::visit(overloaded{
                    [&](Circle& c) { c.center = mw + drag_offset; },
                    [&](Segment& s) { s.a = mw + drag_offset; s.b = mw + drag_offset_b; },
                    [&](Arc& a) { a.center = mw + drag_offset; },
                    [&](Bezier& b) {
                        Vec2 delta = (mw + drag_offset) - b.p0;
                        b.p0 = b.p0 + delta; b.p1 = b.p1 + delta; b.p2 = b.p2 + delta;
                    },
                }, scene.shapes[sel.index]);
                reload();
            } else {
                std::visit(overloaded{
                    [&](PointLight& l) { l.pos = mw + drag_offset; },
                    [&](SegmentLight& l) { l.a = mw + drag_offset; l.b = mw + drag_offset_b; },
                    [&](BeamLight& l) { l.origin = mw + drag_offset; },
                }, scene.lights[sel.index]);
                reload();
            }
        }

        if (ImGui::IsMouseReleased(0)) {
            if (creating) {
                Vec2 end = to_world(vt, io.MousePos);
                float dist = (end - create_start).length();

                if (tool == EditTool::Circle) {
                    float r = std::max(dist, 0.02f);
                    scene.shapes.push_back(Circle{create_start, r, mat_glass(1.5f, 20000.0f, 0.3f)});
                    sel = {Selection::Shape, (int)scene.shapes.size() - 1};
                    reload();
                } else if (tool == EditTool::Segment && dist > 0.01f) {
                    scene.shapes.push_back(Segment{create_start, end, mat_mirror(0.95f)});
                    sel = {Selection::Shape, (int)scene.shapes.size() - 1};
                    reload();
                } else if (tool == EditTool::Arc) {
                    float r = std::max(dist, 0.02f);
                    scene.shapes.push_back(Arc{create_start, r, 0.0f, TWO_PI, mat_glass(1.5f, 20000.0f, 0.3f)});
                    sel = {Selection::Shape, (int)scene.shapes.size() - 1};
                    reload();
                } else if (tool == EditTool::Bezier && dist > 0.01f) {
                    Vec2 mid = (create_start + end) * 0.5f;
                    scene.shapes.push_back(Bezier{create_start, mid, end, mat_glass(1.5f, 20000.0f, 0.3f)});
                    sel = {Selection::Shape, (int)scene.shapes.size() - 1};
                    reload();
                } else if (tool == EditTool::SegmentLight && dist > 0.01f) {
                    scene.lights.push_back(SegmentLight{create_start, end, 1.0f});
                    sel = {Selection::Light, (int)scene.lights.size() - 1};
                    reload();
                }
                creating = false;
            }
            dragging = false;
        }

        // ── Controls panel ──────────────────────────────────────────────

        float panel_w = 280 * dpi_scale;
        ImGui::SetNextWindowPos(ImVec2((float)win_w - panel_w - 8, 8), ImGuiCond_FirstUseEver);
        ImGui::SetNextWindowSize(ImVec2(panel_w, (float)win_h - 16), ImGuiCond_FirstUseEver);
        ImGui::SetNextWindowSizeConstraints(ImVec2(220 * dpi_scale, 200), ImVec2(500 * dpi_scale, 1e6f));
        ImGui::Begin("Controls");

        // -- Scene --
        if (ImGui::CollapsingHeader("Scene", ImGuiTreeNodeFlags_DefaultOpen)) {
            const char* label = (current_scene >= 0) ? scenes[current_scene].first.c_str() : "Custom";
            if (ImGui::BeginCombo("##scene", label)) {
                for (int i = 0; i < (int)scenes.size(); ++i) {
                    if (ImGui::Selectable(scenes[i].first.c_str(), i == current_scene)) {
                        current_scene = i;
                        scene = scenes[i].second();
                        sel = {};
                        creating = false;
                        dragging = false;
                        reload();
                    }
                }
                ImGui::EndCombo();
            }
            if (ImGui::Button("New Scene")) {
                current_scene = -1;
                scene = Scene{};
                scene.name = "custom";
                add_box_walls(scene, 1.0f, 0.7f, mat_mirror(0.95f));
                scene.lights.push_back(PointLight{{0.0f, 0.0f}, 1.0f});
                sel = {};
                creating = false;
                dragging = false;
                reload();
            }
        }

        // -- Tools --
        if (ImGui::CollapsingHeader("Tools", ImGuiTreeNodeFlags_DefaultOpen)) {
            ImVec4 accent(0.31f, 0.53f, 0.86f, 1.0f);
            ImVec4 accent_h(0.38f, 0.60f, 0.92f, 1.0f);
            auto tbtn = [&](const char* lbl, EditTool t) {
                bool active = (tool == t);
                if (active) {
                    ImGui::PushStyleColor(ImGuiCol_Button, accent);
                    ImGui::PushStyleColor(ImGuiCol_ButtonHovered, accent_h);
                }
                if (ImGui::Button(lbl)) { tool = t; creating = false; }
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
        }

        // -- Objects --
        if (ImGui::CollapsingHeader("Objects", ImGuiTreeNodeFlags_DefaultOpen)) {
            int n_items = (int)(scene.shapes.size() + scene.lights.size());
            float h = std::clamp(n_items * ImGui::GetTextLineHeightWithSpacing() + 8.0f,
                                 40.0f, 200.0f * dpi_scale);
            ImGui::BeginChild("##objlist", ImVec2(0, h), ImGuiChildFlags_Borders);

            for (int i = 0; i < (int)scene.shapes.size(); ++i) {
                bool is_sel = (sel.type == Selection::Shape && sel.index == i);
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
                }, scene.shapes[i]);
                if (ImGui::Selectable(lbl, is_sel))
                    sel = {Selection::Shape, i};
            }

            for (int i = 0; i < (int)scene.lights.size(); ++i) {
                bool is_sel = (sel.type == Selection::Light && sel.index == i);
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
                }, scene.lights[i]);
                if (ImGui::Selectable(lbl, is_sel))
                    sel = {Selection::Light, i};
            }

            ImGui::EndChild();

            if (sel.type != Selection::None && ImGui::Button("Delete Selected")) {
                if (delete_selected()) reload();
            }
        }

        // -- Properties --
        if (sel.type != Selection::None &&
            ImGui::CollapsingHeader("Properties", ImGuiTreeNodeFlags_DefaultOpen)) {
            bool changed = false;

            if (sel.type == Selection::Shape && sel.index < (int)scene.shapes.size()) {
                auto& shape = scene.shapes[sel.index];
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

            if (sel.type == Selection::Light && sel.index < (int)scene.lights.size()) {
                auto& light = scene.lights[sel.index];
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

            if (changed) reload();
        }

        // -- Tracer --
        if (ImGui::CollapsingHeader("Tracer", ImGuiTreeNodeFlags_DefaultOpen)) {
            ImGui::SliderInt("Batch", &tcfg.batch_size, 1000, 1000000, "%d",
                             ImGuiSliderFlags_Logarithmic);
            ImGui::SliderInt("Max depth", &tcfg.max_depth, 1, 30);
            ImGui::SliderFloat("Intensity", &tcfg.intensity, 0.001f, 10.0f, "%.3f",
                               ImGuiSliderFlags_Logarithmic);
            ImGui::Checkbox("Paused", &paused);
        }

        // -- Display --
        if (ImGui::CollapsingHeader("Display", ImGuiTreeNodeFlags_DefaultOpen)) {
            ImGui::SliderFloat("Exposure", &pp.exposure, -5.0f, 5.0f);
            ImGui::SliderFloat("Contrast", &pp.contrast, 0.1f, 3.0f);
            ImGui::SliderFloat("Gamma", &pp.gamma, 0.5f, 4.0f);
            ImGui::SliderFloat("White point", &pp.white_point, 0.1f, 10.0f);
            const char* tone_names[] = {"None", "Reinhard", "Reinhard Ext", "ACES", "Logarithmic"};
            int tm = (int)pp.tone_map;
            if (ImGui::Combo("Tone map", &tm, tone_names, 5))
                pp.tone_map = (ToneMap)tm;
        }

        // -- Output --
        if (ImGui::CollapsingHeader("Output", ImGuiTreeNodeFlags_DefaultOpen)) {
            char ray_str[32];
            if (total_rays >= 1'000'000)
                std::snprintf(ray_str, sizeof(ray_str), "%.1fM", total_rays / 1e6);
            else if (total_rays >= 1'000)
                std::snprintf(ray_str, sizeof(ray_str), "%.1fK", total_rays / 1e3);
            else
                std::snprintf(ray_str, sizeof(ray_str), "%lld", (long long)total_rays);
            ImGui::Text("Rays: %s", ray_str);
            ImGui::Text("Max HDR: %.2f", renderer.last_max());
            ImGui::Text("%.1f FPS (%.1f ms)", 1000.0f / frame_ms, frame_ms);

            if (ImGui::Button("Clear")) {
                renderer.clear();
                total_rays = 0;
            }
            ImGui::SameLine();
            if (ImGui::Button("Export PNG")) {
                std::vector<uint8_t> pixels;
                renderer.read_pixels(pixels, pp);
                std::string filename = scene.name + ".png";
                if (export_png(filename, pixels.data(), fb_w, fb_h))
                    std::cerr << "Exported: " << filename << "\n";
            }
        }

        ImGui::End(); // Controls

        // ── Keyboard shortcuts ──────────────────────────────────────────

        if (!io.WantCaptureKeyboard) {
            if (ImGui::IsKeyPressed(ImGuiKey_Space)) paused = !paused;
            if (ImGui::IsKeyPressed(ImGuiKey_Escape)) {
                sel = {};
                tool = EditTool::Select;
                creating = false;
            }
            if (ImGui::IsKeyPressed(ImGuiKey_Delete) || ImGui::IsKeyPressed(ImGuiKey_Backspace)) {
                if (delete_selected()) reload();
            }
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
