#pragma once

#include "scene.h"

#include <imgui.h>

#include <algorithm>
#include <deque>
#include <optional>
#include <set>
#include <string>
#include <vector>

// ─── Object identification ─────────────────────────────────────────────

struct SelectionRef {
    enum Type { Shape, Light, Group } type = Shape;
    std::string id;
    std::string group_id; // empty = top-level, non-empty = member of that group
    bool operator==(const SelectionRef&) const = default;
};

// ─── Camera ────────────────────────────────────────────────────────────

struct EditorCamera {
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
    EditorCamera cam;
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
    SelectionRef obj;
    int param_index; // which parameter (0=first, 1=second, etc.)
    Vec2 world_pos;  // current position in world space
};

// ─── Clipboard ─────────────────────────────────────────────────────────

struct Clipboard {
    std::vector<Shape> shapes;
    std::vector<Light> lights;
    std::vector<Group> groups;
    MaterialMap materials;
    Vec2 centroid{};
    bool empty() const { return shapes.empty() && lights.empty() && groups.empty(); }
};

// ─── Editor tools ──────────────────────────────────────────────────────

enum class EditTool { Select, Circle, Segment, Arc, Bezier, Polygon, Ellipse, Path, PointLight, SegmentLight, ProjectorLight, Erase, Measure };

inline bool is_add_tool(EditTool tool) {
    switch (tool) {
        case EditTool::Circle:
        case EditTool::Segment:
        case EditTool::Arc:
        case EditTool::Bezier:
        case EditTool::Polygon:
        case EditTool::Ellipse:
        case EditTool::Path:
        case EditTool::PointLight:
        case EditTool::SegmentLight:
        case EditTool::ProjectorLight:
            return true;
        default:
            return false;
    }
}

inline const char* edit_tool_name(EditTool tool) {
    switch (tool) {
        case EditTool::Select: return "Select";
        case EditTool::Circle: return "Circle";
        case EditTool::Segment: return "Segment";
        case EditTool::Arc: return "Arc";
        case EditTool::Bezier: return "Bezier";
        case EditTool::Polygon: return "Polygon";
        case EditTool::Ellipse: return "Ellipse";
        case EditTool::Path: return "Path";
        case EditTool::PointLight: return "Point Light";
        case EditTool::SegmentLight: return "Segment Light";
        case EditTool::ProjectorLight: return "Projector";
        case EditTool::Erase: return "Erase";
        case EditTool::Measure: return "Measure";
    }
    return "Unknown";
}

// Camera handle identifiers for interactive frame editing
enum class CameraHandle : int {
    None, TopLeft, Top, TopRight, Right, BottomRight, Bottom, BottomLeft, Left, Move
};

// ─── Editor state ──────────────────────────────────────────────────────

struct EditorState {
    // Authored document (serialized)
    Shot shot;

    // Session state (not serialized, reset on load)
    struct Session {
        UndoHistory undo;
        Clipboard clipboard;
        bool dirty = false;
        std::string save_path;
        int frame = 0;
    } session;

    // View state (camera, display flags — not serialized)
    struct View {
        EditorCamera camera;
        Bounds scene_bounds{{-1, -1}, {1, 1}};
        bool show_grid = false;
        bool snap_to_grid = false;
        bool show_camera_frame = true;
        bool dim_outside_camera = true;
        // Saved free camera for authored-camera toggle (0 key)
        std::optional<EditorCamera> saved_free_camera;
        bool showing_authored_camera = false;
    } view;

    // Interaction state (ephemeral — active during input gestures)
    struct Interaction {
        std::vector<SelectionRef> selection;
        std::optional<SelectionRef> active_selection;
        SelectionRef hovered{};
        std::string editing_group_id;
        EditTool tool = EditTool::Select;
        bool creating = false;
        Vec2 create_start{};
        bool dragging = false;
        struct DragOffset { Vec2 a{}, b{}; };
        std::vector<DragOffset> drag_offsets;
        bool handle_dragging = false;
        Handle active_handle{{}, {}, -1, {}};
        bool box_selecting = false;
        ImVec2 box_start{};
        std::optional<SelectionRef> box_active_before;
        TransformMode transform;
        bool prop_editing = false;
        CameraHandle cam_handle_hovered = CameraHandle::None;
        CameraHandle cam_handle_dragging = CameraHandle::None;
        Bounds cam_drag_start_bounds{};
        bool measure_active = false;
        Vec2 measure_start{};
        std::vector<Vec2> path_create_points; // multi-click path accumulator
    } interaction;

    // Visibility filters (transient, not serialized, not undone)
    struct Visibility {
        std::set<std::string> hidden_shapes;
        std::set<std::string> hidden_lights;
        std::set<std::string> hidden_groups;
        std::string solo_light_id;
        std::string solo_light_group_id;

        bool is_shape_visible(const std::string& id) const { return !hidden_shapes.contains(id); }
        bool is_light_visible(const std::string& id) const { return !hidden_lights.contains(id); }
        bool is_group_visible(const std::string& id) const { return !hidden_groups.contains(id); }

        void toggle_shape(const std::string& id) {
            if (hidden_shapes.contains(id)) hidden_shapes.erase(id); else hidden_shapes.insert(id);
        }
        void toggle_light(const std::string& id) {
            if (hidden_lights.contains(id)) hidden_lights.erase(id); else hidden_lights.insert(id);
        }
        void toggle_group(const std::string& id) {
            if (hidden_groups.contains(id)) hidden_groups.erase(id); else hidden_groups.insert(id);
        }
        void clear_solo() {
            solo_light_id.clear();
            solo_light_group_id.clear();
        }
        void show_all() {
            hidden_shapes.clear(); hidden_lights.clear(); hidden_groups.clear();
            clear_solo();
        }
    } visibility;

    // ── Selection helpers (delegate to interaction) ────────────────

    bool is_selected(const SelectionRef& id) const {
        return std::find(interaction.selection.begin(), interaction.selection.end(), id) != interaction.selection.end();
    }

    bool is_active(const SelectionRef& id) const {
        if (const SelectionRef* active = active_selection())
            return *active == id;
        return false;
    }

    SelectionRef* active_selection() {
        if (!interaction.active_selection)
            return nullptr;
        auto it = std::find(interaction.selection.begin(), interaction.selection.end(), *interaction.active_selection);
        return (it != interaction.selection.end()) ? &*it : nullptr;
    }

    const SelectionRef* active_selection() const {
        return const_cast<EditorState*>(this)->active_selection();
    }

    void set_active(const SelectionRef& id) {
        if (is_selected(id))
            interaction.active_selection = id;
        else
            interaction.active_selection.reset();
    }

    void select(const SelectionRef& id, bool make_active = false) {
        if (!is_selected(id))
            interaction.selection.push_back(id);
        if (make_active)
            interaction.active_selection = id;
    }

    void deselect(const SelectionRef& id) {
        interaction.selection.erase(std::remove(interaction.selection.begin(), interaction.selection.end(), id), interaction.selection.end());
        if (interaction.active_selection && *interaction.active_selection == id) {
            if (!interaction.selection.empty())
                interaction.active_selection = interaction.selection.front();
            else
                interaction.active_selection.reset();
        }
    }

    void toggle_select(const SelectionRef& id) {
        if (is_selected(id)) deselect(id);
        else select(id, true);
    }

    void select_only(const SelectionRef& id) {
        interaction.selection.clear();
        interaction.selection.push_back(id);
        interaction.active_selection = id;
    }

    void replace_selection(std::vector<SelectionRef> refs, std::optional<SelectionRef> active = std::nullopt) {
        interaction.selection = std::move(refs);
        if (active && std::find(interaction.selection.begin(), interaction.selection.end(), *active) != interaction.selection.end()) {
            interaction.active_selection = *active;
        } else if (!interaction.selection.empty()) {
            interaction.active_selection = interaction.selection.front();
        } else {
            interaction.active_selection.reset();
        }
    }

    void click_select(const SelectionRef& id, bool shift_held) {
        if (id.id.empty()) {
            if (!shift_held)
                clear_selection();
            return;
        }
        if (shift_held) {
            toggle_select(id);
            return;
        }
        if (is_selected(id)) {
            set_active(id);
            return;
        }
        select_only(id);
    }

    void clear_selection() {
        interaction.selection.clear();
        interaction.active_selection.reset();
    }

    void select_all() {
        interaction.selection.clear();
        for (const auto& s : shot.scene.shapes)
            interaction.selection.push_back({SelectionRef::Shape, shape_id(s), ""});
        for (const auto& l : shot.scene.lights)
            interaction.selection.push_back({SelectionRef::Light, light_id(l), ""});
        for (const auto& g : shot.scene.groups)
            interaction.selection.push_back({SelectionRef::Group, g.id, ""});
        if (!interaction.selection.empty())
            interaction.active_selection = interaction.selection.front();
        else
            interaction.active_selection.reset();
    }

    // Centroid of selected objects (for transform pivot)
    Vec2 selection_centroid() const;

    // Bounding box of selected objects
    Bounds selection_bounds() const;

    // Validate selection indices after scene changes
    void validate_selection() {
        const auto& sc = shot.scene;
        auto resolve_shape_ref = [&](const SelectionRef& ref) -> bool {
            if (ref.id.empty()) return false;
            if (!ref.group_id.empty()) {
                const Group* g = find_group(sc, ref.group_id);
                return g && find_shape_in(g->shapes, ref.id);
            }
            return find_shape_in(sc.shapes, ref.id) != nullptr;
        };
        auto resolve_light_ref = [&](const SelectionRef& ref) -> bool {
            if (ref.id.empty()) return false;
            if (!ref.group_id.empty()) {
                const Group* g = find_group(sc, ref.group_id);
                return g && find_light_in(g->lights, ref.id);
            }
            return find_light_in(sc.lights, ref.id) != nullptr;
        };
        interaction.selection.erase(
            std::remove_if(interaction.selection.begin(), interaction.selection.end(), [&](const SelectionRef& ref) {
                if (ref.type == SelectionRef::Shape)
                    return !resolve_shape_ref(ref);
                if (ref.type == SelectionRef::Light)
                    return !resolve_light_ref(ref);
                if (ref.type == SelectionRef::Group)
                    return find_group(sc, ref.id) == nullptr;
                return true;
            }),
            interaction.selection.end());
        if (interaction.active_selection
            && std::find(interaction.selection.begin(), interaction.selection.end(), *interaction.active_selection)
                == interaction.selection.end()) {
            if (!interaction.selection.empty())
                interaction.active_selection = interaction.selection.front();
            else
                interaction.active_selection.reset();
        }
        // Validate editing_group
        if (!interaction.editing_group_id.empty() && !find_group(sc, interaction.editing_group_id))
            interaction.editing_group_id.clear();
        // Prune stale visibility ids
        std::erase_if(visibility.hidden_shapes, [&](const std::string& id) { return !find_shape(sc, id); });
        std::erase_if(visibility.hidden_lights, [&](const std::string& id) { return !find_light(sc, id); });
        std::erase_if(visibility.hidden_groups, [&](const std::string& id) { return !find_group(sc, id); });
        if (!visibility.solo_light_id.empty() && !find_light(sc, visibility.solo_light_id))
            visibility.clear_solo();
        if (!visibility.solo_light_group_id.empty() && !find_group(sc, visibility.solo_light_group_id))
            visibility.clear_solo();
    }
};

// ─── Hit testing ───────────────────────────────────────────────────────

// Returns SelectionRef with empty id if nothing hit.
// When editing_group_id is non-empty, only tests members of that group (returns group-scoped SelectionRefs).
SelectionRef hit_test(Vec2 wp, const Scene& scene, float threshold, const std::string& editing_group_id = "");

// Test if an object's geometry intersects a world-space rectangle
bool object_in_rect(const Scene& scene, SelectionRef id, Vec2 rect_min, Vec2 rect_max);

// Resolve top-level or group-member objects from an SelectionRef.
Shape* resolve_shape(Scene& scene, const SelectionRef& id);
const Shape* resolve_shape(const Scene& scene, const SelectionRef& id);
Light* resolve_light(Scene& scene, const SelectionRef& id);
const Light* resolve_light(const Scene& scene, const SelectionRef& id);
std::optional<Bounds> object_bounds(const Scene& scene, const SelectionRef& id);

// ─── Transform application ─────────────────────────────────────────────

// Apply grab/rotate/scale to a shape (from snapshot → live scene)
void apply_transform_shape(Shape& dst, const Shape& src, const TransformMode& tm, Vec2 mouse_world, bool shift_held = false);
void apply_transform_light(Light& dst, const Light& src, const TransformMode& tm, Vec2 mouse_world, bool shift_held = false);

// Translate a shape or light by a delta
void translate_shape(Shape& s, Vec2 delta);
void translate_light(Light& l, Vec2 delta);

// Compute the centroid of a shape or light
Vec2 object_centroid(const Scene& scene, const SelectionRef& id);

// ─── Handle generation ─────────────────────────────────────────────────

std::vector<Handle> get_handles(const Scene& scene, const std::vector<SelectionRef>& selection);
int handle_hit_test(const std::vector<Handle>& handles, Vec2 wp, float threshold);

// Apply a handle drag — modifies the specific object parameter
void apply_handle_drag(Scene& scene, const Handle& handle, Vec2 new_world_pos);

// Apply grab/rotate/scale to a group's transform (from snapshot → live scene)
void apply_transform_group(Group& dst, const Group& src, const TransformMode& tm, Vec2 mouse_world, bool shift_held = false);

// Translate a group by a delta (modifies transform.translate)
void translate_group(Group& g, Vec2 delta);
