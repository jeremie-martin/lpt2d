#pragma once

#include "editor.h"

#include <imgui.h>

#include <vector>

// Material UI
const char* material_name(const Material& m);
bool edit_material(Material& mat);

// Style
void apply_style(float dpi_scale);

// Overlay colors
inline constexpr ImU32 COL_SHAPE          = IM_COL32(200, 200, 210, 90);
inline constexpr ImU32 COL_SHAPE_SEL      = IM_COL32(80, 140, 235, 200);
inline constexpr ImU32 COL_SHAPE_HOV      = IM_COL32(160, 170, 220, 140);
inline constexpr ImU32 COL_LIGHT          = IM_COL32(255, 210, 60, 120);
inline constexpr ImU32 COL_LIGHT_SEL      = IM_COL32(255, 230, 80, 220);
inline constexpr ImU32 COL_LIGHT_HOV      = IM_COL32(255, 230, 80, 160);
inline constexpr ImU32 COL_PREVIEW        = IM_COL32(255, 255, 255, 140);
inline constexpr ImU32 COL_HANDLE         = IM_COL32(255, 255, 255, 200);
inline constexpr ImU32 COL_HANDLE_HOV     = IM_COL32(80, 140, 235, 255);
inline constexpr ImU32 COL_BOX_SEL_FILL   = IM_COL32(80, 140, 235, 40);
inline constexpr ImU32 COL_BOX_SEL_BORDER = IM_COL32(80, 140, 235, 160);
inline constexpr ImU32 COL_PIVOT          = IM_COL32(255, 160, 40, 200);

// Overlay drawing
void draw_shape_overlay(ImDrawList* dl, const CameraView& cv, const Shape& shape, ImU32 col, float th);
void draw_light_overlay(ImDrawList* dl, const CameraView& cv, const Light& light, ImU32 col, float th, float dpi);
void draw_handles(ImDrawList* dl, const CameraView& cv, const Scene& scene,
                  const std::vector<Handle>& handles, int hovered_handle);

// Camera UV mapping
void compute_display_uvs(const Camera& cam, const Bounds& scene_bounds,
                         float win_w, float win_h, ImVec2& uv0, ImVec2& uv1);
