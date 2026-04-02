#pragma once

#include "scene.h"

#include <imgui.h>

#include <algorithm>
#include <deque>
#include <string>
#include <vector>

// ─── Object identification ─────────────────────────────────────────────

struct ObjectId {
    enum Type { Shape, Light } type;
    int index;
    bool operator==(const ObjectId&) const = default;
};

// ─── Camera ────────────────────────────────────────────────────────────

struct Camera {
    Vec2 center{0, 0};  // world-space center of viewport
    float zoom = 1.0f;  // pixels per world unit

    void fit(const Bounds& bounds, float win_w, float win_h) {
        Vec2 sz = bounds.max - bounds.min;
        sz.x = std::max(sz.x, 0.01f);
        sz.y = std::max(sz.y, 0.01f);
        center = (bounds.min + bounds.max) * 0.5f;
        zoom = std::min(win_w / sz.x, win_h / sz.y);
    }

    // Visible world-space bounds at current camera state
    Bounds visible_bounds(float win_w, float win_h) const {
        float hw = win_w * 0.5f / zoom;
        float hh = win_h * 0.5f / zoom;
        return {{center.x - hw, center.y - hh}, {center.x + hw, center.y + hh}};
    }
};

// World ↔ screen coordinate transforms (camera-based)
struct CameraView {
    Camera cam;
    float w, h; // window size in pixels

    ImVec2 to_screen(Vec2 p) const {
        return {(p.x - cam.center.x) * cam.zoom + w * 0.5f,
                h * 0.5f - (p.y - cam.center.y) * cam.zoom};
    }

    Vec2 to_world(ImVec2 s) const {
        return {(s.x - w * 0.5f) / cam.zoom + cam.center.x,
                (h * 0.5f - s.y) / cam.zoom + cam.center.y};
    }
};

// ─── Undo history ──────────────────────────────────────────────────────

struct UndoHistory {
    static constexpr int MAX = 200;
    std::deque<Scene> snapshots;
    int current = -1;

    void push(const Scene& s) {
        // Truncate redo tail
        while ((int)snapshots.size() > current + 1)
            snapshots.pop_back();
        snapshots.push_back(s);
        if ((int)snapshots.size() > MAX)
            snapshots.pop_front();
        current = (int)snapshots.size() - 1;
    }

    bool can_undo() const { return current > 0; }
    bool can_redo() const { return current + 1 < (int)snapshots.size(); }

    bool undo(Scene& out) {
        if (!can_undo()) return false;
        --current;
        out = snapshots[current];
        return true;
    }

    bool redo(Scene& out) {
        if (!can_redo()) return false;
        ++current;
        out = snapshots[current];
        return true;
    }

    void clear() { snapshots.clear(); current = -1; }
};

// ─── Transform mode ────────────────────────────────────────────────────

struct TransformMode {
    enum Type { None, Grab, Rotate, Scale } type = None;
    Vec2 pivot{};
    Vec2 mouse_start{};
    bool lock_x = false, lock_y = false;
    std::string numeric_buf;
    Scene snapshot; // scene state at transform entry

    bool active() const { return type != None; }
};

// ─── Handle system ─────────────────────────────────────────────────────

struct Handle {
    enum Kind { Position, Radius, Angle, Direction } kind;
    ObjectId obj;
    int param_index; // which parameter (0=first, 1=second, etc.)
    Vec2 world_pos;  // current position in world space
};

// ─── Clipboard ─────────────────────────────────────────────────────────

struct Clipboard {
    std::vector<Shape> shapes;
    std::vector<Light> lights;
    Vec2 centroid{};
    bool empty() const { return shapes.empty() && lights.empty(); }
};

// ─── Editor tools ──────────────────────────────────────────────────────

enum class EditTool { Select, Circle, Segment, Arc, Bezier, PointLight, SegmentLight, BeamLight, Erase };

// ─── Editor state ──────────────────────────────────────────────────────

struct EditorState {
    // Scene
    Scene scene;
    Bounds scene_bounds{{-1, -1}, {1, 1}};

    // Camera
    Camera camera;

    // Selection
    std::vector<ObjectId> selection;
    ObjectId hovered{ObjectId::Shape, -1};

    // Tool
    EditTool tool = EditTool::Select;
    bool creating = false;
    Vec2 create_start{};

    // Drag state
    bool dragging = false;
    struct DragOffset { Vec2 a{}, b{}; };
    std::vector<DragOffset> drag_offsets; // one per selected object

    // Handle drag state
    bool handle_dragging = false;
    Handle active_handle{{}, {ObjectId::Shape, -1}, -1, {}};

    // Box select
    bool box_selecting = false;
    ImVec2 box_start{};

    // Transform
    TransformMode transform;

    // Undo
    UndoHistory undo;

    // Clipboard
    Clipboard clipboard;

    // Property editing state (for undo grouping)
    bool prop_editing = false;

    // Dirty flag (unsaved changes)
    bool dirty = false;
    std::string save_path;

    // ── Selection helpers ───────────────────────────────────────────

    bool is_selected(ObjectId id) const {
        return std::find(selection.begin(), selection.end(), id) != selection.end();
    }

    void select(ObjectId id) {
        if (!is_selected(id)) selection.push_back(id);
    }

    void deselect(ObjectId id) {
        selection.erase(std::remove(selection.begin(), selection.end(), id), selection.end());
    }

    void toggle_select(ObjectId id) {
        if (is_selected(id)) deselect(id);
        else select(id);
    }

    void clear_selection() { selection.clear(); }

    void select_all() {
        selection.clear();
        for (int i = 0; i < (int)scene.shapes.size(); ++i)
            selection.push_back({ObjectId::Shape, i});
        for (int i = 0; i < (int)scene.lights.size(); ++i)
            selection.push_back({ObjectId::Light, i});
    }

    // Centroid of selected objects (for transform pivot)
    Vec2 selection_centroid() const;

    // Bounding box of selected objects
    Bounds selection_bounds() const;

    // Validate selection indices after scene changes
    void validate_selection() {
        selection.erase(
            std::remove_if(selection.begin(), selection.end(), [&](const ObjectId& id) {
                if (id.type == ObjectId::Shape) return id.index >= (int)scene.shapes.size();
                return id.index >= (int)scene.lights.size();
            }),
            selection.end());
    }
};

// ─── Hit testing ───────────────────────────────────────────────────────

// Returns ObjectId with index=-1 if nothing hit
ObjectId hit_test(Vec2 wp, const Scene& scene, float threshold);

// Test if an object's geometry intersects a world-space rectangle
bool object_in_rect(const Scene& scene, ObjectId id, Vec2 rect_min, Vec2 rect_max);

// ─── Transform application ─────────────────────────────────────────────

// Apply grab/rotate/scale to a shape (from snapshot → live scene)
void apply_transform_shape(Shape& dst, const Shape& src, const TransformMode& tm, Vec2 mouse_world, bool shift_held = false);
void apply_transform_light(Light& dst, const Light& src, const TransformMode& tm, Vec2 mouse_world, bool shift_held = false);

// Translate a shape or light by a delta
void translate_shape(Shape& s, Vec2 delta);
void translate_light(Light& l, Vec2 delta);

// Compute the centroid of a shape or light
Vec2 object_centroid(const Scene& scene, ObjectId id);

// ─── Handle generation ─────────────────────────────────────────────────

std::vector<Handle> get_handles(const Scene& scene, const std::vector<ObjectId>& selection);
int handle_hit_test(const std::vector<Handle>& handles, Vec2 wp, float threshold);

// Apply a handle drag — modifies the specific object parameter
void apply_handle_drag(Scene& scene, const Handle& handle, Vec2 new_world_pos);
