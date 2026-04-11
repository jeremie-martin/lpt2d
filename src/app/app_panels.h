#pragma once

#include "app_actions.h"
#include "editor.h"
#include "renderer.h"  // for FrameMetrics (type alias for LuminanceStats)

#include <array>
#include <functional>
#include <optional>
#include <string>
#include <vector>

class Renderer;
struct ImGuiIO;

// ─── Panel-local UI state ────────────────────────────────────────────

struct PathDialogState {
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
    std::string delete_replacement_name;
    bool delete_replacement_pending_new = false;
    std::string delete_error;
};

// What was right-clicked in the viewport (drives context menu content).
struct ContextMenuTarget {
    enum Kind { None, EmptySpace, Shape, Polygon, PolygonVertex, Light, Group };
    Kind kind = None;
    SelectionRef ref{};       // the clicked object (empty for EmptySpace)
    int vertex_index = -1;    // for PolygonVertex: which vertex
    Vec2 world_pos{};         // cursor world position (for paste placement)
    bool undo_pushed = false; // for PolygonVertex: lazy undo on first edit
};

// Aggregate of all panel-local state (lives in App::run, passed to draw_controls_panel).
struct PanelState {
    PathDialogState load_dialog;
    IdEditorState id_editor;
    MaterialLibraryPanelState material_panel;
    std::vector<LightContributionView> light_analysis;
    bool light_analysis_valid = false;
    PathDialogState save_as_dialog;
    int current_scene = 0;
    bool open_load_popup = false;
    bool open_save_as_popup = false;
    bool open_add_popup = false;
    bool show_wireframe = true;
    bool paused = false;
    bool show_controls_panel = true;
    bool show_shortcuts_help = false;
    bool show_stats_panel = true;     // floating Stats window, togglable via 'S' hotkey
    bool live_analysis = true;        // when show_stats_panel is up, update authored-camera analysis
    bool show_light_overlay = false; // draw measured point-light radius on top of viewport
    ContextMenuTarget context_menu;
    int active_tab = 0;               // 0 = Edit, 1 = Look
    bool tab_switch_requested = false; // set by keyboard shortcut, consumed by draw
};

// Shared context passed to each panel section function.
struct PanelContext {
    EditorState& ed;
    Renderer& renderer;
    CompareSnapshot& compare_ab;
    PanelState& panel;
    FrameAnalysis& live_metrics;
    std::function<bool(FrameAnalysis&)> compute_authored_analysis;
    std::function<void()> invalidate_authored_analysis;
    const ImGuiIO& io;
    float dpi_scale;
    float frame_ms;
    int win_w, win_h, fb_w, fb_h;

    void reload(bool mark_dirty = true);
    bool showing_snapshot_a() const { return compare_ab.active && compare_ab.showing_a; }
};

// ─── Controls panel ─────────────────────────────────────────────────

// Draws the full right-side controls panel including:
//   Scene selector, Edit, Camera, Objects, Properties, Materials,
//   Tracer, Display, Output.
//
// The function may call reload_scene / reset_editor / delete_selected etc. as needed.
void draw_controls_panel(
    EditorState& ed,
    Renderer& renderer,
    CompareSnapshot& compare_ab,
    PanelState& panel,
    FrameAnalysis& live_metrics,
    std::function<bool(FrameAnalysis&)> compute_authored_analysis,
    std::function<void()> invalidate_authored_analysis,
    const ImGuiIO& io,
    float dpi_scale,
    float frame_ms,
    int win_w, int win_h, int fb_w, int fb_h
);

// Draws the floating Stats window (histogram + luminance/colour rows +
// point-light appearance table + overlay toggle). No-op when
// panel.show_stats_panel is false. The top-level window has its own
// saved position/size in imgui.ini.
void draw_stats_window(
    PanelState& panel,
    FrameAnalysis& live_metrics,
    const CompareSnapshot& compare_ab,
    float dpi_scale
);

// Apply a numbered look preset (0-based index) to the given Look.
void apply_look_preset(Look& look, int index);
