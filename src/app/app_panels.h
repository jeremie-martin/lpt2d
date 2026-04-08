#pragma once

#include "app_actions.h"
#include "editor.h"

#include <array>
#include <optional>
#include <string>
#include <vector>

class Renderer;
struct FrameMetrics;
struct ImGuiIO;

// ─── Panel-local UI state ────────────────────────────────────────────

struct LoadSceneDialogState {
    std::array<char, 256> path{};
    std::string error;
};

struct IdEditorState {
    SelectionRef target{};
    std::string buffer;
};

struct MaterialLibraryPanelState {
    std::string selected_name;
    std::string rename_buffer;
    std::array<char, 64> new_name{};
    bool editing = false;
    std::optional<SelectionRef> synced_target;
};

// Aggregate of all panel-local state (lives in App::run, passed to draw_controls_panel).
struct PanelState {
    LoadSceneDialogState load_dialog;
    IdEditorState id_editor;
    MaterialLibraryPanelState material_panel;
    std::vector<LightContributionView> light_analysis;
    bool light_analysis_valid = false;
    int current_scene = 0;
    bool open_load_popup = false;
    bool show_wireframe = true;
    bool paused = false;
};

// ─── Controls panel ─────────────────────────────────────────────────

// Draws the full right-side controls panel including:
//   Scene selector, Edit, Camera, Objects, Properties, Materials,
//   Tracer, Display, Output, Stats.
//
// The function may call reload_scene / reset_editor / delete_selected etc. as needed.
void draw_controls_panel(
    EditorState& ed,
    Renderer& renderer,
    CompareSnapshot& compare_ab,
    PanelState& panel,
    FrameMetrics& live_metrics,
    bool& force_live_metrics_refresh,
    const ImGuiIO& io,
    float dpi_scale,
    float frame_ms,
    int win_w, int win_h, int fb_w, int fb_h
);
