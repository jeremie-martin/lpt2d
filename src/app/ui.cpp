#include "ui.h"

#include "color.h"
#include "editor.h"
#include "geometry.h"

#include <algorithm>
#include <cmath>
#include <cstdio>
#include <variant>

namespace {

void draw_arc_overlay(ImDrawList* dl, const CameraView& cv, Vec2 center, float radius,
                      float angle_start, float sweep, ImU32 col, float th) {
    if (radius <= 0.0f || sweep <= 0.0f) return;

    int segments = std::max(1, (int)std::ceil(64.0f * sweep / TWO_PI));
    for (int j = 0; j < segments; ++j) {
        float t0 = angle_start + sweep * j / segments;
        float t1 = angle_start + sweep * (j + 1) / segments;
        Vec2 p0 = center + Vec2{std::cos(t0) * radius, std::sin(t0) * radius};
        Vec2 p1 = center + Vec2{std::cos(t1) * radius, std::sin(t1) * radius};
        dl->AddLine(cv.to_screen(p0), cv.to_screen(p1), col, th);
    }
}

void draw_polygon_boundary_overlay(ImDrawList* dl, const CameraView& cv, const Polygon& p,
                                   ImU32 col, float th) {
    if (!polygon_has_any_rounded_corner(p)) {
        int n = (int)p.vertices.size();
        for (int i = 0; i < n; ++i)
            dl->AddLine(cv.to_screen(p.vertices[i]), cv.to_screen(p.vertices[(i + 1) % n]), col, th);
        return;
    }

    RoundedPolygonParts parts = decompose_rounded_polygon(p);
    for (const auto& edge : parts.edges)
        dl->AddLine(cv.to_screen(edge.a), cv.to_screen(edge.b), col, th);
    for (const auto& corner : parts.corners)
        draw_arc_overlay(dl, cv, corner.center, corner.radius, corner.angle_start, corner.sweep, col, th);
}

} // namespace

ImVec4 material_color(const Material& m) {
    if (m.emission > 0.0f) return {1.0f, 0.95f, 0.3f, 1.0f};
    if (m.spectral_c0 != 0.0f || m.spectral_c1 != 0.0f || m.spectral_c2 != 0.0f) {
        Vec3 rgb = spectral_to_rgb(m.spectral_c0, m.spectral_c1, m.spectral_c2);
        float scale = m.albedo;
        return {rgb.r * scale, rgb.g * scale, rgb.b * scale, 1.0f};
    }
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
    // Spectral color
    Vec3 spec_rgb = spectral_to_rgb(mat.spectral_c0, mat.spectral_c1, mat.spectral_c2);
    float col[3] = {spec_rgb.r, spec_rgb.g, spec_rgb.b};
    bool is_neutral = (mat.spectral_c0 == 0.0f && mat.spectral_c1 == 0.0f && mat.spectral_c2 == 0.0f);
    if (!is_neutral) {
        if (ImGui::ColorEdit3("Color", col, ImGuiColorEditFlags_Float)) {
            auto sc = rgb_to_spectral(col[0], col[1], col[2]);
            mat.spectral_c0 = sc.c0;
            mat.spectral_c1 = sc.c1;
            mat.spectral_c2 = sc.c2;
            changed = true;
        }
    }
    bool has_color = !is_neutral;
    if (ImGui::Checkbox("Colored", &has_color)) {
        if (has_color) {
            auto sc = rgb_to_spectral(0.8f, 0.2f, 0.2f); // default to reddish
            mat.spectral_c0 = sc.c0; mat.spectral_c1 = sc.c1; mat.spectral_c2 = sc.c2;
        } else {
            mat.spectral_c0 = mat.spectral_c1 = mat.spectral_c2 = 0.0f;
        }
        changed = true;
    }
    changed |= ImGui::SliderFloat("Fill", &mat.fill, 0.0f, 1.0f);
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
                Vec2 p0 = bezier_eval(b, (float)j / N);
                Vec2 p1 = bezier_eval(b, (float)(j + 1) / N);
                dl->AddLine(cv.to_screen(p0), cv.to_screen(p1), col, th);
            }
            dl->AddCircleFilled(cv.to_screen(b.p1), 3.0f, col);
        },
        [&](const Polygon& p) {
            draw_polygon_boundary_overlay(dl, cv, p, col, th);
        },
        [&](const Ellipse& e) {
            constexpr int N = 64;
            float cr = std::cos(e.rotation), sr = std::sin(e.rotation);
            for (int j = 0; j < N; ++j) {
                float t0 = TWO_PI * j / N, t1 = TWO_PI * (j + 1) / N;
                float lx0 = e.semi_a * std::cos(t0), ly0 = e.semi_b * std::sin(t0);
                float lx1 = e.semi_a * std::cos(t1), ly1 = e.semi_b * std::sin(t1);
                Vec2 p0 = e.center + Vec2{lx0 * cr - ly0 * sr, lx0 * sr + ly0 * cr};
                Vec2 p1 = e.center + Vec2{lx1 * cr - ly1 * sr, lx1 * sr + ly1 * cr};
                dl->AddLine(cv.to_screen(p0), cv.to_screen(p1), col, th);
            }
        },
        [&](const Path& path) {
            auto parts = decompose_path(path);
            constexpr int N = 16;
            for (auto& curve : parts.curves) {
                for (int j = 0; j < N; ++j) {
                    Vec2 p0 = bezier_eval(curve, (float)j / N);
                    Vec2 p1 = bezier_eval(curve, (float)(j + 1) / N);
                    dl->AddLine(cv.to_screen(p0), cv.to_screen(p1), col, th);
                }
            }
        },
    }, shape);
}

static void draw_direction_cone(ImDrawList* dl, const CameraView& cv, Vec2 origin,
                                Vec2 direction, float angular_width, ImU32 col, float th) {
    Vec2 d = direction.normalized();
    dl->AddLine(cv.to_screen(origin), cv.to_screen(origin + d * 0.3f), col, th);
    float half_w = angular_width * 0.5f;
    float base_a = std::atan2(d.y, d.x);
    Vec2 w1{std::cos(base_a + half_w), std::sin(base_a + half_w)};
    Vec2 w2{std::cos(base_a - half_w), std::sin(base_a - half_w)};
    dl->AddLine(cv.to_screen(origin), cv.to_screen(origin + w1 * 0.2f), col, th * 0.5f);
    dl->AddLine(cv.to_screen(origin), cv.to_screen(origin + w2 * 0.2f), col, th * 0.5f);
}

static void draw_projector_aperture(ImDrawList* dl, const CameraView& cv, const ProjectorLight& light,
                                    ImU32 col, float th, float dpi) {
    dl->AddCircleFilled(cv.to_screen(light.position), 4.0f * dpi, col);
    if (light.source_radius > 0.0f) {
        if (light.source == ProjectorSource::Ball) {
            float screen_radius = cv.cam.zoom * light.source_radius;
            dl->AddCircle(cv.to_screen(light.position), screen_radius, col, 32, th);
        } else {
            Vec2 dir = light.direction.length_sq() > 1e-6f ? light.direction.normalized() : Vec2{1.0f, 0.0f};
            Vec2 tangent = dir.perp() * light.source_radius;
            Vec2 a = light.position - tangent;
            Vec2 b = light.position + tangent;
            ImVec2 sa = cv.to_screen(a), sb = cv.to_screen(b);
            dl->AddLine(sa, sb, col, th);
            dl->AddCircleFilled(sa, 2.5f * dpi, col);
            dl->AddCircleFilled(sb, 2.5f * dpi, col);
        }
    }
}

void draw_light_overlay(ImDrawList* dl, const CameraView& cv, const Light& light, ImU32 col, float th, float dpi) {
    std::visit(overloaded{
        [&](const PointLight& l) {
            dl->AddCircleFilled(cv.to_screen(l.position), 4.0f * dpi, col);
        },
        [&](const SegmentLight& l) {
            ImVec2 a = cv.to_screen(l.a), b = cv.to_screen(l.b);
            dl->AddLine(a, b, col, th);
            dl->AddCircleFilled(a, 3.0f * dpi, col);
            dl->AddCircleFilled(b, 3.0f * dpi, col);
        },
        [&](const ProjectorLight& l) {
            draw_projector_aperture(dl, cv, l, col, th, dpi);
            draw_direction_cone(dl, cv, l.position, l.direction, l.spread, col, th);
        },
    }, light);
}

void draw_handles(ImDrawList* dl, const CameraView& cv, const Scene& scene,
                  const std::vector<Handle>& handles, int hovered_handle) {
    // Draw guide lines for Bezier control points
    ImU32 guide_col = IM_COL32(120, 120, 140, 80);
    for (auto& h : handles) {
        if (h.obj.type == SelectionRef::Shape && h.kind == Handle::Position && h.param_index == 1) {
            // This is a Bezier control point — draw dashed lines to P0 and P2
            if (const Shape* shape = resolve_shape(scene, h.obj)) {
                if (const auto* b = std::get_if<Bezier>(shape)) {
                    dl->AddLine(cv.to_screen(b->p0), cv.to_screen(b->p1), guide_col, 1.0f);
                    dl->AddLine(cv.to_screen(b->p1), cv.to_screen(b->p2), guide_col, 1.0f);
                }
            }
        }
    }

    for (int i = 0; i < (int)handles.size(); ++i) {
        ImVec2 sp = cv.to_screen(handles[i].world_pos);
        float r = (i == hovered_handle) ? 5.0f : 4.0f;
        ImU32 col = (i == hovered_handle) ? COL_HANDLE_HOV : COL_HANDLE;

        // Check if this is a polygon vertex handle (for join mode indicators)
        const Polygon* poly = nullptr;
        if (handles[i].kind == Handle::Position && handles[i].obj.type == SelectionRef::Shape) {
            if (const Shape* shape = resolve_shape(scene, handles[i].obj))
                poly = std::get_if<Polygon>(shape);
        }

        if (handles[i].kind == Handle::Position && handles[i].param_index == 1 &&
            handles[i].obj.type == SelectionRef::Shape && !poly) {
            // Bezier control point: diamond shape
            dl->AddQuadFilled(ImVec2(sp.x, sp.y - r), ImVec2(sp.x + r, sp.y),
                              ImVec2(sp.x, sp.y + r), ImVec2(sp.x - r, sp.y), col);
        } else if (poly && handles[i].kind == Handle::Position) {
            // Polygon vertex: shape varies by join mode
            int vi = handles[i].param_index;
            PolygonJoinMode jm = polygon_effective_join_mode(*poly, vi);
            switch (jm) {
                case PolygonJoinMode::Auto:
                    dl->AddRectFilled(ImVec2(sp.x - r, sp.y - r), ImVec2(sp.x + r, sp.y + r), col);
                    break;
                case PolygonJoinMode::Sharp:
                    dl->AddRect(ImVec2(sp.x - r, sp.y - r), ImVec2(sp.x + r, sp.y + r), col, 0.0f, 0, 1.5f);
                    break;
                case PolygonJoinMode::Smooth:
                    dl->AddCircleFilled(sp, r, col);
                    break;
            }
            // Vertex label
            char label[8];
            std::snprintf(label, sizeof(label), "V%d", vi);
            ImVec2 text_pos(sp.x + r + 3.0f, sp.y - r - 2.0f);
            dl->AddText(text_pos, IM_COL32(200, 200, 210, 140), label);
        } else if (handles[i].kind == Handle::Position) {
            // Filled square (default for non-polygon Position handles)
            dl->AddRectFilled(ImVec2(sp.x - r, sp.y - r), ImVec2(sp.x + r, sp.y + r), col);
        } else {
            // Diamond for radius/angle/direction
            dl->AddQuadFilled(ImVec2(sp.x, sp.y - r), ImVec2(sp.x + r, sp.y),
                              ImVec2(sp.x, sp.y + r), ImVec2(sp.x - r, sp.y), col);
        }
    }
}

// ─── Grid ──────────────────────────────────────────────────────────────

float adaptive_grid_spacing(float pixels_per_unit) {
    // Target: grid lines ~80px apart on screen
    float world_per_80px = 80.0f / pixels_per_unit;
    float log10_val = std::log10(world_per_80px);
    float base = std::pow(10.0f, std::floor(log10_val));
    float frac = world_per_80px / base;
    if (frac < 1.5f) return base;
    if (frac < 3.5f) return base * 2.0f;
    if (frac < 7.5f) return base * 5.0f;
    return base * 10.0f;
}

Vec2 snap_to_grid_pos(Vec2 pos, float spacing) {
    return {std::round(pos.x / spacing) * spacing,
            std::round(pos.y / spacing) * spacing};
}

void draw_grid(ImDrawList* dl, const CameraView& cv, float spacing) {
    ImU32 col_minor = IM_COL32(255, 255, 255, 15);
    ImU32 col_major = IM_COL32(255, 255, 255, 35);
    ImU32 col_axis  = IM_COL32(255, 255, 255, 60);

    Bounds vis = cv.cam.visible_bounds(cv.w, cv.h);

    int ix_start = (int)std::floor(vis.min.x / spacing);
    int ix_end   = (int)std::ceil(vis.max.x / spacing);
    int iy_start = (int)std::floor(vis.min.y / spacing);
    int iy_end   = (int)std::ceil(vis.max.y / spacing);

    for (int ix = ix_start; ix <= ix_end; ++ix) {
        float x = ix * spacing;
        ImU32 col = (ix == 0) ? col_axis : (ix % 5 == 0) ? col_major : col_minor;
        dl->AddLine(cv.to_screen({x, vis.max.y}), cv.to_screen({x, vis.min.y}), col, 1.0f);
    }
    for (int iy = iy_start; iy <= iy_end; ++iy) {
        float y = iy * spacing;
        ImU32 col = (iy == 0) ? col_axis : (iy % 5 == 0) ? col_major : col_minor;
        dl->AddLine(cv.to_screen({vis.min.x, y}), cv.to_screen({vis.max.x, y}), col, 1.0f);
    }
}
