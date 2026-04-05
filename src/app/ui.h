#pragma once

#include "editor.h"

#include <imgui.h>

#include <vector>

// Material UI
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
inline constexpr ImU32 COL_SHAPE_SEL_GLOW = IM_COL32(80, 140, 235, 60);
inline constexpr ImU32 COL_GHOST_SHAPE   = IM_COL32(100, 100, 110, 60);
inline constexpr ImU32 COL_GHOST_LIGHT   = IM_COL32(200, 180, 40, 60);
inline constexpr ImU32 COL_CAMERA_FRAME  = IM_COL32(255, 180, 40, 180);
inline constexpr ImU32 COL_CAMERA_DIM    = IM_COL32(0, 0, 0, 100);
inline constexpr ImU32 COL_CAMERA_HANDLE = IM_COL32(255, 180, 40, 200);
inline constexpr ImU32 COL_ALIGN_GUIDE   = IM_COL32(60, 220, 180, 180);

// Overlay drawing
void draw_shape_overlay(ImDrawList* dl, const CameraView& cv, const Shape& shape, ImU32 col, float th);
void draw_light_overlay(ImDrawList* dl, const CameraView& cv, const Light& light, ImU32 col, float th, float dpi);
void draw_handles(ImDrawList* dl, const CameraView& cv, const Scene& scene,
                  const std::vector<Handle>& handles, int hovered_handle);

// Material color swatch
ImVec4 material_color(const Material& m);

// Grid
float adaptive_grid_spacing(float pixels_per_unit);
Vec2 snap_to_grid_pos(Vec2 pos, float spacing);
void draw_grid(ImDrawList* dl, const CameraView& cv, float spacing);
