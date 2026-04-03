#include "ui.h"

#include <algorithm>
#include <cmath>

// ─── Helpers ────────────────────────────────────────────────────────────

const char* material_name(const Material& m) {
    if (m.albedo <= 0.0f) return "Absorber";
    if (m.transmission > 0.5f && m.metallic < 0.5f && m.ior > 1.01f) return "Glass";
    if (m.metallic > 0.5f) return "Mirror";
    if (m.roughness > 0.5f) return "Diffuse";
    return "Material";
}

ImVec4 material_color(const Material& m) {
    if (m.emission > 0.0f) return {1.0f, 0.95f, 0.3f, 1.0f};
    if (m.albedo <= 0.01f) return {0.05f, 0.05f, 0.05f, 1.0f};
    if (m.transmission > 0.5f && m.ior > 1.01f) return {0.6f, 0.85f, 1.0f, 0.7f};
    if (m.metallic > 0.5f) return {0.85f, 0.85f, 0.9f, 1.0f};
    return {m.albedo, m.albedo, m.albedo, 1.0f};
}

// ─── Material editor ────────────────────────────────────────────────────

bool edit_material(Material& mat) {
    bool changed = false;

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
    changed |= ImGui::SliderFloat("Emission", &mat.emission, 0.0f, 10.0f, "%.2f",
                                   ImGuiSliderFlags_Logarithmic);
    return changed;
}

// ─── Style ──────────────────────────────────────────────────────────────

void apply_style(float s) {
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

// ─── Overlay drawing ────────────────────────────────────────────────────

void draw_shape_overlay(ImDrawList* dl, const CameraView& cv, const Shape& shape, ImU32 col, float th) {
    std::visit(overloaded{
        [&](const Circle& c) {
            dl->AddCircle(cv.to_screen(c.center), c.radius * cv.cam.zoom, col, 64, th);
        },
        [&](const Segment& s) {
            dl->AddLine(cv.to_screen(s.a), cv.to_screen(s.b), col, th);
        },
        [&](const Arc& a) {
            float sweep = clamp_arc_sweep(a.sweep);
            if (sweep >= TWO_PI - INTERSECT_EPS) {
                dl->AddCircle(cv.to_screen(a.center), a.radius * cv.cam.zoom, col, 64, th);
                return;
            }

            int segments = std::max(1, (int)std::ceil(64.0f * sweep / TWO_PI));
            for (int j = 0; j < segments; ++j) {
                float t0 = a.angle_start + sweep * j / segments;
                float t1 = a.angle_start + sweep * (j + 1) / segments;
                Vec2 p0 = arc_point(a, t0);
                Vec2 p1 = arc_point(a, t1);
                dl->AddLine(cv.to_screen(p0), cv.to_screen(p1), col, th);
            }
        },
        [&](const Bezier& b) {
            constexpr int N = 32;
            for (int j = 0; j < N; ++j) {
                float t0 = (float)j / N, t1 = (float)(j + 1) / N;
                float u0 = 1.0f - t0, u1 = 1.0f - t1;
                Vec2 p0 = b.p0 * (u0*u0) + b.p1 * (2.0f*u0*t0) + b.p2 * (t0*t0);
                Vec2 p1 = b.p0 * (u1*u1) + b.p1 * (2.0f*u1*t1) + b.p2 * (t1*t1);
                dl->AddLine(cv.to_screen(p0), cv.to_screen(p1), col, th);
            }
            dl->AddCircleFilled(cv.to_screen(b.p1), 3.0f, col);
        },
    }, shape);
}

void draw_light_overlay(ImDrawList* dl, const CameraView& cv, const Light& light, ImU32 col, float th, float dpi) {
    std::visit(overloaded{
        [&](const PointLight& l) {
            float r = 4.0f * dpi;
            dl->AddCircleFilled(cv.to_screen(l.pos), r, col);
        },
        [&](const SegmentLight& l) {
            ImVec2 a = cv.to_screen(l.a), b = cv.to_screen(l.b);
            dl->AddLine(a, b, col, th);
            dl->AddCircleFilled(a, 3.0f * dpi, col);
            dl->AddCircleFilled(b, 3.0f * dpi, col);
        },
        [&](const BeamLight& l) {
            ImVec2 o = cv.to_screen(l.origin);
            dl->AddCircleFilled(o, 4.0f * dpi, col);
            Vec2 d = l.direction.normalized();
            ImVec2 tip = cv.to_screen(l.origin + d * 0.3f);
            dl->AddLine(o, tip, col, th);
            float half_w = l.angular_width * 0.5f;
            float base_a = std::atan2(d.y, d.x);
            Vec2 w1{std::cos(base_a + half_w), std::sin(base_a + half_w)};
            Vec2 w2{std::cos(base_a - half_w), std::sin(base_a - half_w)};
            dl->AddLine(o, cv.to_screen(l.origin + w1 * 0.2f), col, th * 0.5f);
            dl->AddLine(o, cv.to_screen(l.origin + w2 * 0.2f), col, th * 0.5f);
        },
    }, light);
}

void draw_handles(ImDrawList* dl, const CameraView& cv, const Scene& scene,
                  const std::vector<Handle>& handles, int hovered_handle) {
    // Draw guide lines for Bezier control points
    ImU32 guide_col = IM_COL32(120, 120, 140, 80);
    for (auto& h : handles) {
        if (h.obj.type == ObjectId::Shape && h.kind == Handle::Position && h.param_index == 1) {
            // This is a Bezier control point — draw dashed lines to P0 and P2
            auto& shape = scene.shapes[h.obj.index];
            if (auto* b = std::get_if<Bezier>(&shape)) {
                dl->AddLine(cv.to_screen(b->p0), cv.to_screen(b->p1), guide_col, 1.0f);
                dl->AddLine(cv.to_screen(b->p1), cv.to_screen(b->p2), guide_col, 1.0f);
            }
        }
    }

    for (int i = 0; i < (int)handles.size(); ++i) {
        ImVec2 sp = cv.to_screen(handles[i].world_pos);
        float r = (i == hovered_handle) ? 5.0f : 4.0f;
        ImU32 col = (i == hovered_handle) ? COL_HANDLE_HOV : COL_HANDLE;

        if (handles[i].kind == Handle::Position && handles[i].param_index == 1 &&
            handles[i].obj.type == ObjectId::Shape) {
            // Bezier control point: diamond shape
            dl->AddQuadFilled(ImVec2(sp.x, sp.y - r), ImVec2(sp.x + r, sp.y),
                              ImVec2(sp.x, sp.y + r), ImVec2(sp.x - r, sp.y), col);
        } else if (handles[i].kind == Handle::Position) {
            // Filled square
            dl->AddRectFilled(ImVec2(sp.x - r, sp.y - r), ImVec2(sp.x + r, sp.y + r), col);
        } else {
            // Diamond for radius/angle/direction
            dl->AddQuadFilled(ImVec2(sp.x, sp.y - r), ImVec2(sp.x + r, sp.y),
                              ImVec2(sp.x, sp.y + r), ImVec2(sp.x - r, sp.y), col);
        }
    }
}

// ─── UV computation for camera-independent rendering ────────────────────

void compute_display_uvs(const Camera& cam, const Bounds& scene_bounds,
                         float win_w, float win_h,
                         ImVec2& uv0, ImVec2& uv1) {
    Vec2 scene_sz = scene_bounds.max - scene_bounds.min;
    scene_sz.x = std::max(scene_sz.x, 0.01f);
    scene_sz.y = std::max(scene_sz.y, 0.01f);
    float renderer_scale = std::min(win_w / scene_sz.x, win_h / scene_sz.y);

    Bounds vis = cam.visible_bounds(win_w, win_h);

    float fbo_used_w = scene_sz.x * renderer_scale;
    float fbo_used_h = scene_sz.y * renderer_scale;
    float offset_x = (win_w - fbo_used_w) * 0.5f;
    float offset_y = (win_h - fbo_used_h) * 0.5f;

    auto world_to_uv_x = [&](float wx) -> float {
        float px = (wx - scene_bounds.min.x) * renderer_scale + offset_x;
        return px / win_w;
    };
    auto world_to_uv_y = [&](float wy) -> float {
        float py = (wy - scene_bounds.min.y) * renderer_scale + offset_y;
        return py / win_h;
    };

    float u_left  = world_to_uv_x(vis.min.x);
    float u_right = world_to_uv_x(vis.max.x);
    float v_bottom = world_to_uv_y(vis.min.y);
    float v_top    = world_to_uv_y(vis.max.y);

    uv0 = ImVec2(u_left, v_top);
    uv1 = ImVec2(u_right, v_bottom);
}
