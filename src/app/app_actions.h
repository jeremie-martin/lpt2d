#pragma once

#include <GL/glew.h>
#include <stdint.h>

#include "editor.h"
#include "renderer.h"
#include "scene.h"

// GUI interactive batch default — applied on scene load so the slider
// starts at a responsive interactive value rather than the authored default.
inline constexpr int kGuiTraceBatch = 20'000;

#include <set>
#include <string>
#include <vector>

// ─── Render filter snapshot ──────────────────────────────────────────

struct RenderFilterState {
    std::set<std::string> hidden_shapes;
    std::set<std::string> hidden_lights;
    std::set<std::string> hidden_groups;
    std::string solo_light_id;
    std::string solo_light_group_id;
};

RenderFilterState capture_render_filters(const EditorState& ed);

// ─── Compare A/B snapshot ────────────────────────────────────────────

struct CompareSnapshot {
    bool active = false;
    bool showing_a = false;
    bool metrics_valid = false;
    Shot shot;
    int frame = 0;
    Bounds view_bounds{{-1, -1}, {1, 1}};
    FrameMetrics metrics{};
    GLuint texture = 0;
    int texture_width = 0;
    int texture_height = 0;
};

void destroy_compare_snapshot(CompareSnapshot& snap);
void upload_compare_snapshot(CompareSnapshot& snap, const std::vector<uint8_t>& rgba, int tex_w, int tex_h);

// ─── Light contribution analysis ────────────────────────────────────

struct LightContributionView {
    std::string id;
    float mean_linear_luma = 0.0f;
    float coverage_fraction = 0.0f;
    float share = 0.0f;
};

// ─── Scene building / filtering ─────────────────────────────────────

Bounds scene_default_bounds(const Scene& scene);
Scene build_render_scene_for(const Shot& shot, const RenderFilterState& filters);
Bounds current_display_view(const EditorState& ed, const CompareSnapshot& compare_ab, int win_w, int win_h);
EditorCamera current_display_camera(const EditorState& ed, const CompareSnapshot& compare_ab, int win_w, int win_h);

// ─── Scene actions ──────────────────────────────────────────────────

// Re-upload scene to GPU, clear accumulation, update bounds.
void reload_scene(EditorState& ed, Renderer& renderer, const CompareSnapshot& compare_ab,
                  bool& light_analysis_valid, bool& force_live_metrics_refresh,
                  int win_w, int win_h, bool mark_dirty = true);

// Export a high-quality PNG render of the given shot at a specific runtime frame index.
bool export_authored_png(const Shot& source_shot, int frame = 0);

// Save the current shot to JSON (to a specific path, or the default path).
bool do_save_to(EditorState& ed, const std::string& path, std::string* error = nullptr);
void do_save(EditorState& ed);

// Load a scene from a JSON file. Returns true on success.
bool try_load_scene(EditorState& ed, Renderer& renderer, CompareSnapshot& compare_ab,
                    bool& light_analysis_valid, bool& force_live_metrics_refresh,
                    int win_w, int win_h,
                    const std::string& path, std::string* error = nullptr);

// Copy selected objects to clipboard.
void copy_to_clipboard(EditorState& ed);

// Delete all selected objects from the scene.
bool delete_selected(EditorState& ed, Renderer& renderer, const CompareSnapshot& compare_ab,
                     bool& light_analysis_valid, bool& force_live_metrics_refresh,
                     int win_w, int win_h);

// Reset editor state for a new/loaded scene. Fits camera, clears undo.
void reset_editor(EditorState& ed, Renderer& renderer, CompareSnapshot& compare_ab,
                  bool& light_analysis_valid, bool& force_live_metrics_refresh,
                  int win_w, int win_h);

// Group selected ungrouped shapes/lights into a new group.
// Returns true if a group was created.
bool group_selected(EditorState& ed, Renderer& renderer, const CompareSnapshot& compare_ab,
                    bool& light_analysis_valid, bool& force_live_metrics_refresh,
                    int win_w, int win_h);

// Ungroup selected groups (bake transforms, promote members to top-level).
// Returns true if any group was ungrouped.
bool ungroup_selected(EditorState& ed, Renderer& renderer, const CompareSnapshot& compare_ab,
                      bool& light_analysis_valid, bool& force_live_metrics_refresh,
                      int win_w, int win_h);
