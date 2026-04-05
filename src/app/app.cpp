#include "app.h"

#include "editor.h"
#include "export.h"
#include "renderer.h"
#include "scenes.h"
#include "serialize.h"
#include "ui.h"

#include <GL/glew.h>
#include <GLFW/glfw3.h>
#include <imgui.h>
#include <imgui_impl_glfw.h>
#include <imgui_impl_opengl3.h>

#include <algorithm>
#include <array>
#include <chrono>
#include <cstdio>
#include <cstring>
#include <iostream>

namespace {

constexpr int kGuiTraceBatch = 20'000;
constexpr float kDefaultRoomHalfWidth = 1.0f;
constexpr float kDefaultRoomHalfHeight = kDefaultRoomHalfWidth * 9.0f / 16.0f;

Material gui_wall_material() {
    return mat_mirror(0.95f, 0.1f);
}

void apply_gui_shot_defaults(Shot& shot) {
    // The GUI keeps trace batch as a session-only control. It is not loaded
    // from authored JSON and is stripped back to authored defaults on save.
    shot.trace.batch = kGuiTraceBatch;
}

struct AlignmentGuide {
    float axis = 0.0f;
    float span_min = 0.0f;
    float span_max = 0.0f;
};

} // namespace

// ─── App::run ───────────────────────────────────────────────────────────

int App::run(const AppConfig& config) {
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
    if (!io.Fonts->AddFontFromFileTTF(LPT2D_FONT_PATH, font_size)) {
        ImFontConfig cfg;
        cfg.SizePixels = font_size;
        io.Fonts->AddFontDefault(&cfg);
    }
    apply_style(dpi_scale);

    // ── Editor state ──
    EditorState ed;
    const auto& builtins = get_builtin_scenes();

    int current_scene = 0;
    if (!config.initial_scene.empty()) {
        bool found = false;
        for (int i = 0; i < (int)builtins.size(); ++i) {
            if (builtins[i].name == config.initial_scene) { current_scene = i; found = true; break; }
        }
        if (!found)
            std::cerr << "Unknown scene: " << config.initial_scene << ", using " << builtins[0].name << "\n";
    }
    ed.shot = load_builtin_scene(builtins[current_scene]);
    apply_gui_shot_defaults(ed.shot);
    ed.scene_bounds = compute_bounds(ed.shot.scene);
    ed.camera.fit(ed.scene_bounds, (float)win_w, (float)win_h);

    Bounds initial_view = ed.camera.visible_bounds((float)win_w, (float)win_h);
    renderer.upload_scene(ed.shot.scene, initial_view);
    renderer.clear();
    ed.undo.push(ed.shot.scene); // initial state

    bool paused = false;
    float frame_ms = 16.0f;
    bool show_wireframe = true;
    bool open_load_popup = false;

    struct RenderFilterState {
        std::set<int> hidden_shapes;
        std::set<int> hidden_lights;
        std::set<int> hidden_groups;
        int solo_light = -1;
        int solo_light_group = -1;
        int solo_light_index = -1;
    };

    // Full-shot A/B comparison state
    struct CompareSnapshot {
        bool active = false;
        bool showing_a = false;
        bool metrics_valid = false;
        Shot shot;
        Bounds view_bounds{{-1, -1}, {1, 1}};
        FrameMetrics metrics{};
        GLuint texture = 0;
        int texture_width = 0;
        int texture_height = 0;
    } compare_ab;

    FrameMetrics live_metrics{};
    int stats_counter = 30; // trigger immediate compute on first frame
    bool force_live_metrics_refresh = true;

    // Light contribution analysis results (cleared on scene reload)
    struct LightContributionView {
        std::string id;
        float mean_linear_luma = 0.0f;
        float coverage_fraction = 0.0f;
        float share = 0.0f;
    };
    std::vector<LightContributionView> light_analysis;
    bool light_analysis_valid = false;
    struct LoadSceneDialogState {
        std::array<char, 256> path{};
        std::string error;
    } load_dialog;
    struct IdEditorState {
        SelectionRef target{SelectionRef::Shape, -2};
        std::string buffer;
    } id_editor;
    struct MaterialLibraryPanelState {
        std::string selected_name;
        std::string rename_buffer;
        std::array<char, 64> new_name{};
        bool editing = false;
    } material_panel;
    auto make_default_arc = [](Vec2 center, Vec2 target) {
        Vec2 delta = target - center;
        float angle = delta.length_sq() > 1e-10f
            ? normalize_angle(std::atan2(delta.y, delta.x))
            : 0.0f;
        Arc arc;
        arc.center = center;
        arc.radius = std::max(delta.length(), 0.02f);
        arc.angle_start = normalize_angle(angle - 0.5f * PI);
        arc.sweep = PI;
        arc.material = mat_glass(1.5f, 20000.0f, 0.3f);
        return arc;
    };
    auto object_fallback_label = [](const char* kind, int index) {
        return std::string(kind) + " " + std::to_string(index);
    };
    auto selection_label = [](const std::string& visible, const std::string& key) {
        return visible + "##" + key;
    };
    auto shape_authored_id = [](const Shape& shape) -> const std::string& {
        return std::visit([](const auto& value) -> const std::string& {
            return value.id;
        }, shape);
    };
    auto shape_authored_id_mut = [](Shape& shape) -> std::string& {
        return std::visit([](auto& value) -> std::string& {
            return value.id;
        }, shape);
    };
    auto shape_material_id = [](const Shape& shape) -> const std::string& {
        return std::visit([](const auto& value) -> const std::string& {
            return value.material_id;
        }, shape);
    };
    auto shape_material_id_mut = [](Shape& shape) -> std::string& {
        return std::visit([](auto& value) -> std::string& {
            return value.material_id;
        }, shape);
    };
    auto shape_material = [](const Shape& shape) -> const Material& {
        return std::visit([](const auto& value) -> const Material& {
            return value.material;
        }, shape);
    };
    auto shape_material_mut = [](Shape& shape) -> Material& {
        return std::visit([](auto& value) -> Material& {
            return value.material;
        }, shape);
    };
    auto light_authored_id = [](const Light& light) -> const std::string& {
        return std::visit([](const auto& value) -> const std::string& {
            return value.id;
        }, light);
    };
    auto light_authored_id_mut = [](Light& light) -> std::string& {
        return std::visit([](auto& value) -> std::string& {
            return value.id;
        }, light);
    };
    auto shape_display_name = [&](const Shape& shape, int index) {
        const std::string& authored_id = shape_authored_id(shape);
        if (!authored_id.empty()) return authored_id;
        return std::visit(overloaded{
            [&](const Circle&) { return object_fallback_label("Circle", index); },
            [&](const Segment&) { return object_fallback_label("Segment", index); },
            [&](const Arc&) { return object_fallback_label("Arc", index); },
            [&](const Bezier&) { return object_fallback_label("Bezier", index); },
            [&](const Polygon&) { return object_fallback_label("Polygon", index); },
            [&](const Ellipse&) { return object_fallback_label("Ellipse", index); },
        }, shape);
    };
    auto light_display_name = [&](const Light& light, int index) {
        const std::string& authored_id = light_authored_id(light);
        if (!authored_id.empty()) return authored_id;
        return std::visit(overloaded{
            [&](const PointLight&) { return object_fallback_label("Point Light", index); },
            [&](const SegmentLight&) { return object_fallback_label("Segment Light", index); },
            [&](const BeamLight&) { return object_fallback_label("Beam Light", index); },
            [&](const ParallelBeamLight&) { return object_fallback_label("Parallel Beam", index); },
            [&](const SpotLight&) { return object_fallback_label("Spot Light", index); },
        }, light);
    };
    auto group_display_name = [&](const Group& group, int index) {
        if (!group.id.empty()) return group.id;
        return object_fallback_label("Group", index);
    };
    auto entity_id_available = [&](std::string_view candidate, std::string_view current) {
        if (candidate.empty()) return false;
        if (candidate == current) return true;
        return !find_shape(ed.shot.scene, candidate)
            && !find_light(ed.shot.scene, candidate)
            && !find_group(ed.shot.scene, candidate);
    };
    auto material_id_available = [&](std::string_view candidate, std::string_view current) {
        if (candidate.empty()) return false;
        if (candidate == current) return true;
        return !ed.shot.scene.materials.contains(std::string(candidate));
    };
    auto rewrite_shape_material_binding = [&](Shape& shape, std::string_view old_id, std::string_view new_id) {
        if (shape_material_id(shape) == old_id)
            shape_material_id_mut(shape) = std::string(new_id);
    };
    auto detach_shape_if_missing_material = [&](Shape& shape) {
        const std::string& material_id = shape_material_id(shape);
        if (!material_id.empty() && !ed.shot.scene.materials.contains(material_id))
            shape_material_id_mut(shape).clear();
    };
    auto for_each_clipboard_shape = [&](auto&& fn) {
        for (auto& shape : ed.clipboard.shapes)
            fn(shape);
        for (auto& group : ed.clipboard.groups)
            for (auto& shape : group.shapes)
                fn(shape);
    };
    auto rewrite_clipboard_material_binding = [&](std::string_view old_id, std::string_view new_id) {
        for_each_clipboard_shape([&](Shape& shape) {
            rewrite_shape_material_binding(shape, old_id, new_id);
        });
    };
    auto detach_clipboard_material_binding = [&](std::string_view material_id) {
        for_each_clipboard_shape([&](Shape& shape) {
            if (shape_material_id(shape) == material_id)
                shape_material_id_mut(shape).clear();
        });
    };
    auto sanitize_clipboard_material_bindings = [&]() {
        for_each_clipboard_shape([&](Shape& shape) {
            detach_shape_if_missing_material(shape);
        });
    };
    auto rename_material_binding = [&](std::string_view old_id, std::string_view new_id) {
        if (old_id == new_id) return;
        if (!rename_material(ed.shot.scene, old_id, new_id)) return;
        rewrite_clipboard_material_binding(old_id, new_id);
    };
    auto bind_shape_material = [&](Shape& shape, std::string_view material_id) {
        bind_material(shape, ed.shot.scene, material_id);
    };
    auto detach_shape_material = [&](Shape& shape) {
        detach_material(shape);
    };
    auto apply_material_to_selection = [&](std::string_view material_id) {
        bool changed = false;
        for (const auto& id : ed.selection) {
            if (Shape* shape = resolve_shape(ed.shot.scene, id)) {
                bind_shape_material(*shape, material_id);
                changed = true;
                continue;
            }
            if (id.type == SelectionRef::Group && id.index >= 0 && id.index < (int)ed.shot.scene.groups.size()) {
                for (auto& shape : ed.shot.scene.groups[id.index].shapes) {
                    bind_shape_material(shape, material_id);
                    changed = true;
                }
            }
        }
        return changed;
    };
    auto detach_material_from_selection = [&](std::string_view material_id) {
        bool changed = false;
        auto maybe_detach = [&](Shape& shape) {
            if (shape_material_id(shape) == material_id) {
                detach_shape_material(shape);
                changed = true;
            }
        };
        for (const auto& id : ed.selection) {
            if (Shape* shape = resolve_shape(ed.shot.scene, id)) {
                maybe_detach(*shape);
                continue;
            }
            if (id.type == SelectionRef::Group && id.index >= 0 && id.index < (int)ed.shot.scene.groups.size()) {
                for (auto& shape : ed.shot.scene.groups[id.index].shapes)
                    maybe_detach(shape);
            }
        }
        return changed;
    };

    // Build a filtered scene applying editor visibility/solo state.
    auto capture_render_filters = [&]() -> RenderFilterState {
        return {
            ed.hidden_shapes,
            ed.hidden_lights,
            ed.hidden_groups,
            ed.solo_light,
            ed.solo_light_group,
            ed.solo_light_index,
        };
    };
    auto current_display_camera = [&]() -> Camera {
        if (!compare_ab.active)
            return ed.camera;
        Camera comparison_camera;
        comparison_camera.fit(compare_ab.view_bounds, (float)win_w, (float)win_h);
        return comparison_camera;
    };
    auto current_display_view = [&]() -> Bounds {
        if (compare_ab.active)
            return compare_ab.view_bounds;
        Camera display_camera = current_display_camera();
        return display_camera.visible_bounds((float)win_w, (float)win_h);
    };
    auto shape_visible = [](const RenderFilterState& filters, int index) {
        return !filters.hidden_shapes.contains(index);
    };
    auto light_visible = [](const RenderFilterState& filters, int index) {
        return !filters.hidden_lights.contains(index);
    };
    auto group_visible = [](const RenderFilterState& filters, int index) {
        return !filters.hidden_groups.contains(index);
    };
    auto build_render_scene_for = [&](const Shot& shot, const RenderFilterState& filters) -> Scene {
        auto strip_shape_emission = [](Shape shape) -> Shape {
            std::visit([](auto& value) {
                if (value.material.emission > 0.0f)
                    value.material.emission = 0.0f;
            }, shape);
            return shape;
        };
        Scene filtered;
        bool any_solo = (filters.solo_light >= 0 || filters.solo_light_group >= 0);
        for (int i = 0; i < (int)shot.scene.shapes.size(); ++i)
            if (shape_visible(filters, i))
                filtered.shapes.push_back(any_solo ? strip_shape_emission(shot.scene.shapes[i])
                                                   : shot.scene.shapes[i]);
        if (filters.solo_light >= 0) {
            // Top-level solo: only include the soloed top-level light
            if (filters.solo_light < (int)shot.scene.lights.size())
                filtered.lights.push_back(shot.scene.lights[filters.solo_light]);
        } else if (filters.solo_light_group >= 0) {
            // Group solo: strip all top-level lights
        } else {
            for (int i = 0; i < (int)shot.scene.lights.size(); ++i)
                if (light_visible(filters, i))
                    filtered.lights.push_back(shot.scene.lights[i]);
        }
        for (int i = 0; i < (int)shot.scene.groups.size(); ++i) {
            if (!group_visible(filters, i)) continue;
            if (any_solo) {
                Group g = shot.scene.groups[i];
                for (auto& shape : g.shapes)
                    shape = strip_shape_emission(shape);
                if (filters.solo_light_group == i &&
                    filters.solo_light_index >= 0 &&
                    filters.solo_light_index < (int)g.lights.size()) {
                    Light soloed = g.lights[filters.solo_light_index];
                    g.lights.clear();
                    g.lights.push_back(std::move(soloed));
                } else {
                    g.lights.clear();
                }
                filtered.groups.push_back(std::move(g));
            } else {
                filtered.groups.push_back(shot.scene.groups[i]);
            }
        }
        return filtered;
    };
    struct AuthoredSource {
        enum class Kind { SceneLight, GroupLight, ShapeEmission } kind = Kind::SceneLight;
        std::string label;
        int group_index = -1;
        int light_index = -1;
        int shape_index = -1;
    };
    auto zero_shape_emission = [&](Shape shape) -> Shape {
        if (shape_material(shape).emission > 0.0f)
            shape_material_mut(shape).emission = 0.0f;
        return shape;
    };
    auto collect_authored_sources = [&](const Scene& scene) {
        std::vector<AuthoredSource> sources;
        for (int i = 0; i < (int)scene.lights.size(); ++i) {
            sources.push_back({AuthoredSource::Kind::SceneLight, light_display_name(scene.lights[i], i), -1, i, -1});
        }
        for (int gi = 0; gi < (int)scene.groups.size(); ++gi) {
            const auto& group = scene.groups[gi];
            for (int li = 0; li < (int)group.lights.size(); ++li) {
                sources.push_back({
                    AuthoredSource::Kind::GroupLight,
                    group_display_name(group, gi) + "/" + light_display_name(group.lights[li], li),
                    gi,
                    li,
                    -1,
                });
            }
        }
        for (int i = 0; i < (int)scene.shapes.size(); ++i) {
            if (shape_material(scene.shapes[i]).emission <= 0.0f) continue;
            sources.push_back({
                AuthoredSource::Kind::ShapeEmission,
                shape_display_name(scene.shapes[i], i),
                -1,
                -1,
                i,
            });
        }
        for (int gi = 0; gi < (int)scene.groups.size(); ++gi) {
            const auto& group = scene.groups[gi];
            for (int si = 0; si < (int)group.shapes.size(); ++si) {
                if (shape_material(group.shapes[si]).emission <= 0.0f) continue;
                sources.push_back({
                    AuthoredSource::Kind::ShapeEmission,
                    group_display_name(group, gi) + "/" + shape_display_name(group.shapes[si], si),
                    gi,
                    -1,
                    si,
                });
            }
        }
        return sources;
    };
    auto scene_with_only_source = [&](const Scene& scene, const AuthoredSource& source) {
        Scene isolated = scene;
        for (auto& shape : isolated.shapes)
            shape = zero_shape_emission(shape);
        for (auto& group : isolated.groups)
            for (auto& shape : group.shapes)
                shape = zero_shape_emission(shape);
        isolated.lights.clear();
        for (auto& group : isolated.groups)
            group.lights.clear();

        switch (source.kind) {
        case AuthoredSource::Kind::SceneLight:
            if (source.light_index >= 0 && source.light_index < (int)scene.lights.size())
                isolated.lights.push_back(scene.lights[source.light_index]);
            break;
        case AuthoredSource::Kind::GroupLight:
            if (source.group_index >= 0 && source.group_index < (int)scene.groups.size()
                && source.light_index >= 0 && source.light_index < (int)scene.groups[source.group_index].lights.size()) {
                isolated.groups[source.group_index].lights.push_back(
                    scene.groups[source.group_index].lights[source.light_index]);
            }
            break;
        case AuthoredSource::Kind::ShapeEmission:
            for (int i = 0; i < (int)scene.shapes.size(); ++i) {
                if (source.group_index < 0 && i == source.shape_index)
                    isolated.shapes[i] = scene.shapes[i];
            }
            for (int gi = 0; gi < (int)scene.groups.size(); ++gi) {
                for (int si = 0; si < (int)scene.groups[gi].shapes.size(); ++si) {
                    if (gi == source.group_index && si == source.shape_index)
                        isolated.groups[gi].shapes[si] = scene.groups[gi].shapes[si];
                }
            }
            break;
        }
        return isolated;
    };
    auto current_authored_shot = [&]() -> const Shot& {
        return (compare_ab.active && compare_ab.showing_a) ? compare_ab.shot : ed.shot;
    };
    auto scene_default_bounds = [](const Scene& scene) -> Bounds {
        if (scene.shapes.empty() && scene.lights.empty() && scene.groups.empty())
            return {{-1, -1}, {1, 1}};
        return compute_bounds(scene);
    };
    auto fit_bounds_rect = [](const Bounds& bounds, float width, float height) -> std::array<float, 4> {
        Vec2 size = bounds.max - bounds.min;
        size.x = std::max(size.x, 0.01f);
        size.y = std::max(size.y, 0.01f);
        float scale = std::min(width / size.x, height / size.y);
        return {
            (width - size.x * scale) * 0.5f,
            (height - size.y * scale) * 0.5f,
            size.x * scale,
            size.y * scale,
        };
    };
    auto destroy_compare_snapshot = [&]() {
        if (compare_ab.texture) {
            glDeleteTextures(1, &compare_ab.texture);
            compare_ab.texture = 0;
        }
        compare_ab.texture_width = 0;
        compare_ab.texture_height = 0;
    };
    auto upload_compare_snapshot = [&](const std::vector<uint8_t>& rgba, int tex_w, int tex_h) {
        if (!compare_ab.texture)
            glGenTextures(1, &compare_ab.texture);
        glBindTexture(GL_TEXTURE_2D, compare_ab.texture);
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR);
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR);
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);
        glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA8, tex_w, tex_h, 0, GL_RGBA, GL_UNSIGNED_BYTE, rgba.data());
        glBindTexture(GL_TEXTURE_2D, 0);
        compare_ab.texture_width = tex_w;
        compare_ab.texture_height = tex_h;
    };

    // Reload: re-upload scene to GPU, clear accumulation
    // Renderer viewport always tracks the camera's visible bounds.
    // Bounds computed from FULL scene (hiding objects doesn't shift viewport).
    auto reload = [&](bool mark_dirty = true) {
        ensure_scene_entity_ids(ed.shot.scene);
        sync_material_bindings(ed.shot.scene);
        ed.scene_bounds = scene_default_bounds(ed.shot.scene);
        Bounds view = current_display_view();
        renderer.upload_scene(build_render_scene_for(ed.shot, capture_render_filters()), view);
        renderer.clear();
        if (mark_dirty)
            ed.dirty = true;
        light_analysis_valid = false;
        force_live_metrics_refresh = true;
    };

    auto export_authored_png = [&](const Shot& source_shot) -> bool {
        Shot output_shot = source_shot;
        ensure_scene_entity_ids(output_shot.scene);
        sync_material_bindings(output_shot.scene);

        Renderer export_renderer;
        if (!export_renderer.init(output_shot.canvas.width, output_shot.canvas.height))
            return false;

        Bounds scene_bounds = scene_default_bounds(output_shot.scene);
        Bounds bounds = output_shot.camera.resolve(output_shot.canvas.aspect(), scene_bounds);
        export_renderer.upload_scene(output_shot.scene, bounds);
        export_renderer.clear();

        TraceConfig tcfg = output_shot.trace.to_trace_config();
        int64_t total_rays = output_shot.trace.rays;
        int64_t num_batches = (total_rays + tcfg.batch_size - 1) / tcfg.batch_size;
        const int dispatches_per_draw = 4;
        int64_t batch = 0;
        while (batch < num_batches) {
            int n = std::min((int64_t)dispatches_per_draw, num_batches - batch);
            export_renderer.trace_and_draw_multi(tcfg, n);
            batch += n;
        }

        std::vector<uint8_t> pixels;
        export_renderer.read_pixels(pixels, output_shot.look, output_shot.canvas.aspect());
        std::string filename = output_shot.name + ".png";
        return export_png(filename, pixels.data(), output_shot.canvas.width, output_shot.canvas.height);
    };

    auto do_save = [&]() {
        std::string path = ed.save_path.empty() ? (ed.shot.name + ".json") : ed.save_path;
        Shot saved = ed.shot;
        // GUI batch is session-only; authored JSON falls back to TraceDefaults batch.
        saved.trace.batch = TraceDefaults{}.batch;
        if (save_shot_json(saved, path)) {
            ed.save_path = path;
            ed.dirty = false;
            std::cerr << "Saved: " << path << "\n";
        }
    };

    auto copy_to_clipboard = [&]() {
        ed.clipboard.shapes.clear();
        ed.clipboard.lights.clear();
        ed.clipboard.groups.clear();
        for (auto& sid : ed.selection) {
            if (const Shape* shape = resolve_shape(ed.shot.scene, sid)) ed.clipboard.shapes.push_back(*shape);
            else if (const Light* light = resolve_light(ed.shot.scene, sid)) ed.clipboard.lights.push_back(*light);
            else if (sid.type == SelectionRef::Group) ed.clipboard.groups.push_back(ed.shot.scene.groups[sid.index]);
        }
        ed.clipboard.centroid = ed.selection_centroid();
    };

    auto reset_editor = [&]() {
        ed.clear_selection();
        ed.creating = false;
        ed.dragging = false;
        ed.handle_dragging = false;
        ed.cam_handle_dragging = CameraHandle::None;
        ed.cam_handle_hovered = CameraHandle::None;
        destroy_compare_snapshot();
        compare_ab.active = false;
        compare_ab.showing_a = false;
        compare_ab.metrics_valid = false;
        ed.undo.clear();
        ed.undo.push(ed.shot.scene);
        // reload() updates ed.scene_bounds, then fit camera
        reload();
        ed.camera.fit(ed.scene_bounds, (float)win_w, (float)win_h);
        reload(false); // re-upload with fitted camera view
        ed.dirty = false;
    };

    auto delete_selected = [&]() {
        if (ed.selection.empty()) return false;
        ed.undo.push(ed.shot.scene);

        // Sort selection in reverse order so deletion doesn't invalidate indices
        auto sorted = ed.selection;
        std::sort(sorted.begin(), sorted.end(), [](const SelectionRef& a, const SelectionRef& b) {
            if (a.type != b.type) return a.type > b.type; // groups (2) > lights (1) > shapes (0)
            return a.index > b.index; // higher indices first
        });
        for (auto& id : sorted) {
            if (id.type == SelectionRef::Shape && id.index < (int)ed.shot.scene.shapes.size())
                ed.shot.scene.shapes.erase(ed.shot.scene.shapes.begin() + id.index);
            else if (id.type == SelectionRef::Light && id.index < (int)ed.shot.scene.lights.size())
                ed.shot.scene.lights.erase(ed.shot.scene.lights.begin() + id.index);
            else if (id.type == SelectionRef::Group && id.index < (int)ed.shot.scene.groups.size())
                ed.shot.scene.groups.erase(ed.shot.scene.groups.begin() + id.index);
        }
        ed.clear_selection();
        // Clear visibility state (indices shifted after deletion)
        ed.hidden_shapes.clear();
        ed.hidden_lights.clear();
        ed.hidden_groups.clear();
        // Deletion shifts indices — clear solo to avoid stale references.
        ed.clear_solo();
        reload();
        return true;
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
        ed.validate_selection();

        // Camera view for this frame
        Camera active_camera = current_display_camera();
        CameraView cv{active_camera, (float)win_w, (float)win_h};
        bool showing_snapshot_a = compare_ab.active && compare_ab.showing_a;

        // Trace
        auto t0 = std::chrono::steady_clock::now();
        if (!showing_snapshot_a && !paused && renderer.num_lights() > 0) {
            renderer.trace_and_draw(ed.shot.trace.to_trace_config());
            glFinish();
        }
        if (!showing_snapshot_a)
            renderer.update_display(ed.shot.look, ed.shot.canvas.aspect());

        if (showing_snapshot_a && compare_ab.metrics_valid) {
            live_metrics = compare_ab.metrics;
        } else if (force_live_metrics_refresh || ++stats_counter >= 30) {
            stats_counter = 0;
            force_live_metrics_refresh = false;
            live_metrics = renderer.compute_display_metrics();
        }

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

        // Display rendered image (FBO always matches camera view)
        if (showing_snapshot_a && compare_ab.texture) {
            auto src = fit_bounds_rect(compare_ab.view_bounds,
                                       (float)compare_ab.texture_width,
                                       (float)compare_ab.texture_height);
            auto dst = fit_bounds_rect(compare_ab.view_bounds, (float)win_w, (float)win_h);
            ImGui::SetCursorPos(ImVec2(dst[0], dst[1]));
            ImVec2 uv0(src[0] / (float)compare_ab.texture_width,
                       1.0f - src[1] / (float)compare_ab.texture_height);
            ImVec2 uv1((src[0] + src[2]) / (float)compare_ab.texture_width,
                       1.0f - (src[1] + src[3]) / (float)compare_ab.texture_height);
            ImGui::Image((ImTextureID)(intptr_t)compare_ab.texture,
                         ImVec2(dst[2], dst[3]), uv0, uv1);
            ImGui::SetCursorPos(ImVec2(0, 0));
        } else {
            ImGui::Image((ImTextureID)(intptr_t)renderer.display_texture(),
                         ImVec2((float)win_w, (float)win_h), ImVec2(0, 1), ImVec2(1, 0));
        }

        bool vp_hovered = ImGui::IsWindowHovered();

        // ── Grid overlay ───────────────────────────────────────────────
        float grid_spacing = 0;
        if (ed.show_grid) {
            ImDrawList* gdl = ImGui::GetWindowDrawList();
            grid_spacing = adaptive_grid_spacing(cv.cam.zoom);
            draw_grid(gdl, cv, grid_spacing);
        }

        // ── Wireframe overlay ───────────────────────────────────────────

        if (show_wireframe && !showing_snapshot_a) {
            ImDrawList* dl = ImGui::GetWindowDrawList();

            for (int i = 0; i < (int)ed.shot.scene.shapes.size(); ++i) {
                SelectionRef id{SelectionRef::Shape, i};
                bool is_sel = ed.is_selected(id);
                bool is_hov = (ed.hovered == id);
                bool hidden = !ed.is_shape_visible(i);
                ImU32 col = hidden ? IM_COL32(100, 100, 110, 30)
                                   : (is_sel ? COL_SHAPE_SEL : (is_hov ? COL_SHAPE_HOV : COL_SHAPE));
                float th = hidden ? 1.0f * dpi_scale : (is_sel ? 2.5f : 1.5f) * dpi_scale;

                if (ed.transform.active() && is_sel && i < (int)ed.transform.snapshot.shapes.size()) {
                    draw_shape_overlay(dl, cv, ed.transform.snapshot.shapes[i], COL_GHOST_SHAPE, 1.0f * dpi_scale);
                    draw_shape_overlay(dl, cv, ed.shot.scene.shapes[i], COL_SHAPE_SEL, 2.5f * dpi_scale);
                } else {
                    if (is_sel && !hidden && !ed.transform.active())
                        draw_shape_overlay(dl, cv, ed.shot.scene.shapes[i], COL_SHAPE_SEL_GLOW, 6.0f * dpi_scale);
                    draw_shape_overlay(dl, cv, ed.shot.scene.shapes[i], col, th);
                }
            }

            for (int i = 0; i < (int)ed.shot.scene.lights.size(); ++i) {
                SelectionRef id{SelectionRef::Light, i};
                bool is_sel = ed.is_selected(id);
                bool is_hov = (ed.hovered == id);
                bool hidden = !ed.is_light_visible(i);
                ImU32 col = hidden ? IM_COL32(200, 180, 40, 30)
                                   : (is_sel ? COL_LIGHT_SEL : (is_hov ? COL_LIGHT_HOV : COL_LIGHT));
                float th = hidden ? 1.0f * dpi_scale : (is_sel ? 3.0f : 2.0f) * dpi_scale;

                if (ed.transform.active() && is_sel && i < (int)ed.transform.snapshot.lights.size()) {
                    draw_light_overlay(dl, cv, ed.transform.snapshot.lights[i], COL_GHOST_LIGHT, 1.0f * dpi_scale, dpi_scale);
                    draw_light_overlay(dl, cv, ed.shot.scene.lights[i], COL_LIGHT_SEL, 3.0f * dpi_scale, dpi_scale);
                } else {
                    draw_light_overlay(dl, cv, ed.shot.scene.lights[i], col, th, dpi_scale);
                }
            }

            // Draw groups
            for (int g = 0; g < (int)ed.shot.scene.groups.size(); ++g) {
                SelectionRef gid{SelectionRef::Group, g};
                bool is_sel = ed.is_selected(gid);
                bool is_hov = (ed.hovered == gid);
                bool hidden = !ed.is_group_visible(g);

                const auto& group = ed.shot.scene.groups[g];

                if (ed.transform.active() && is_sel && g < (int)ed.transform.snapshot.groups.size()) {
                    // Ghost at original position (dim)
                    const auto& snap_group = ed.transform.snapshot.groups[g];
                    for (const auto& s : snap_group.shapes) {
                        Shape ws = transform_shape(s, snap_group.transform);
                        draw_shape_overlay(dl, cv, ws, COL_GHOST_SHAPE, 1.0f * dpi_scale);
                    }
                    for (const auto& l : snap_group.lights) {
                        Light wl = transform_light(l, snap_group.transform);
                        draw_light_overlay(dl, cv, wl, COL_GHOST_LIGHT, 1.0f * dpi_scale, dpi_scale);
                    }
                }

                ImU32 shape_col = hidden ? IM_COL32(100, 100, 110, 30)
                                        : (is_sel ? COL_SHAPE_SEL : (is_hov ? COL_SHAPE_HOV : COL_SHAPE));
                ImU32 light_col = hidden ? IM_COL32(200, 180, 40, 30)
                                        : (is_sel ? COL_LIGHT_SEL : (is_hov ? COL_LIGHT_HOV : COL_LIGHT));
                float s_th = hidden ? 1.0f * dpi_scale : (is_sel ? 2.5f : 1.5f) * dpi_scale;
                float l_th = hidden ? 1.0f * dpi_scale : (is_sel ? 3.0f : 2.0f) * dpi_scale;

                for (const auto& s : group.shapes) {
                    Shape ws = transform_shape(s, group.transform);
                    draw_shape_overlay(dl, cv, ws, shape_col, s_th);
                }
                for (const auto& l : group.lights) {
                    Light wl = transform_light(l, group.transform);
                    draw_light_overlay(dl, cv, wl, light_col, l_th, dpi_scale);
                }

                // Draw group bounding box when selected
                if (is_sel) {
                    Bounds gb = ed.selection_bounds();
                    ImVec2 mn = cv.to_screen(gb.min);
                    ImVec2 mx = cv.to_screen(gb.max);
                    // Fix Y inversion (screen Y is flipped)
                    if (mn.y > mx.y) std::swap(mn.y, mx.y);
                    dl->AddRect(mn, mx, IM_COL32(80, 140, 235, 80), 0, 0, 1.0f * dpi_scale);
                }
            }

            // Handles for selected objects
            if (!ed.selection.empty() && ed.tool == EditTool::Select && !ed.transform.active()) {
                auto handles = get_handles(ed.shot.scene, ed.selection);
                Vec2 mw = cv.to_world(io.MousePos);
                int hov_h = vp_hovered ? handle_hit_test(handles, mw, 8.0f / cv.cam.zoom) : -1;
                draw_handles(dl, cv, ed.shot.scene, handles, hov_h);
            }

            // Alignment guides while dragging top-level objects
            if (ed.dragging && ed.editing_group < 0 && !ed.selection.empty()) {
                Bounds sel = ed.selection_bounds();
                float sel_xs[3] = {sel.min.x, (sel.min.x + sel.max.x) * 0.5f, sel.max.x};
                float sel_ys[3] = {sel.min.y, (sel.min.y + sel.max.y) * 0.5f, sel.max.y};
                float guide_thresh = 8.0f / cv.cam.zoom;

                struct BestGuide {
                    bool found = false;
                    float diff = 1e30f;
                    AlignmentGuide guide{};
                };
                BestGuide best_v, best_h;

                auto consider_vertical = [&](float sx, float cx, float y0, float y1) {
                    float diff = std::abs(sx - cx);
                    if (diff <= guide_thresh && diff < best_v.diff) {
                        best_v.found = true;
                        best_v.diff = diff;
                        best_v.guide = AlignmentGuide{cx, y0, y1};
                    }
                };
                auto consider_horizontal = [&](float sy, float cy, float x0, float x1) {
                    float diff = std::abs(sy - cy);
                    if (diff <= guide_thresh && diff < best_h.diff) {
                        best_h.found = true;
                        best_h.diff = diff;
                        best_h.guide = AlignmentGuide{cy, x0, x1};
                    }
                };
                auto compare_against = [&](const Bounds& b) {
                    float cand_xs[3] = {b.min.x, (b.min.x + b.max.x) * 0.5f, b.max.x};
                    float cand_ys[3] = {b.min.y, (b.min.y + b.max.y) * 0.5f, b.max.y};
                    for (float sx : sel_xs)
                        for (float cx : cand_xs)
                            consider_vertical(
                                sx, cx, std::min(sel.min.y, b.min.y), std::max(sel.max.y, b.max.y));
                    for (float sy : sel_ys)
                        for (float cy : cand_ys)
                            consider_horizontal(
                                sy, cy, std::min(sel.min.x, b.min.x), std::max(sel.max.x, b.max.x));
                };

                for (int i = 0; i < (int)ed.shot.scene.shapes.size(); ++i) {
                    SelectionRef id{SelectionRef::Shape, i};
                    if (ed.is_selected(id) || !ed.is_shape_visible(i)) continue;
                    if (auto b = object_bounds(ed.shot.scene, id)) compare_against(*b);
                }
                for (int i = 0; i < (int)ed.shot.scene.lights.size(); ++i) {
                    SelectionRef id{SelectionRef::Light, i};
                    if (ed.is_selected(id) || !ed.is_light_visible(i)) continue;
                    if (auto b = object_bounds(ed.shot.scene, id)) compare_against(*b);
                }
                for (int i = 0; i < (int)ed.shot.scene.groups.size(); ++i) {
                    SelectionRef id{SelectionRef::Group, i};
                    if (ed.is_selected(id) || !ed.is_group_visible(i)) continue;
                    if (auto b = object_bounds(ed.shot.scene, id)) compare_against(*b);
                }

                if (best_v.found) {
                    ImVec2 a = cv.to_screen({best_v.guide.axis, best_v.guide.span_min});
                    ImVec2 b = cv.to_screen({best_v.guide.axis, best_v.guide.span_max});
                    dl->AddLine(a, b, COL_ALIGN_GUIDE, 1.5f * dpi_scale);
                }
                if (best_h.found) {
                    ImVec2 a = cv.to_screen({best_h.guide.span_min, best_h.guide.axis});
                    ImVec2 b = cv.to_screen({best_h.guide.span_max, best_h.guide.axis});
                    dl->AddLine(a, b, COL_ALIGN_GUIDE, 1.5f * dpi_scale);
                }
            }

            // Creation preview
            if (ed.creating) {
                Vec2 mw = cv.to_world(io.MousePos);
                if (ed.tool == EditTool::Circle) {
                    float r = (mw - ed.create_start).length() * cv.cam.zoom;
                    dl->AddCircle(cv.to_screen(ed.create_start), r, COL_PREVIEW, 64, 1.5f * dpi_scale);
                } else if (ed.tool == EditTool::Arc) {
                    Vec2 delta = mw - ed.create_start;
                    if (delta.length_sq() > 1e-10f) {
                        Arc preview = make_default_arc(ed.create_start, mw);
                        draw_shape_overlay(dl, cv, preview, COL_PREVIEW, 1.5f * dpi_scale);
                    }
                } else if (ed.tool == EditTool::Polygon) {
                    ImVec2 a = cv.to_screen(ed.create_start);
                    ImVec2 b = io.MousePos;
                    dl->AddRect(ImVec2(std::min(a.x,b.x), std::min(a.y,b.y)),
                                ImVec2(std::max(a.x,b.x), std::max(a.y,b.y)), COL_PREVIEW, 0.0f, 0, 1.5f * dpi_scale);
                } else if (ed.tool == EditTool::Ellipse) {
                    ImVec2 a = cv.to_screen(ed.create_start);
                    ImVec2 b = io.MousePos;
                    // Preview as rectangle (same as polygon creation)
                    dl->AddRect(ImVec2(std::min(a.x,b.x), std::min(a.y,b.y)),
                                ImVec2(std::max(a.x,b.x), std::max(a.y,b.y)), COL_PREVIEW, 0.0f, 0, 1.5f * dpi_scale);
                } else if (ed.tool == EditTool::Segment || ed.tool == EditTool::SegmentLight || ed.tool == EditTool::Bezier || ed.tool == EditTool::ParallelBeamLight) {
                    dl->AddLine(cv.to_screen(ed.create_start), io.MousePos, COL_PREVIEW, 1.5f * dpi_scale);
                }
            }

            // Box selection preview
            if (ed.box_selecting) {
                ImVec2 cur = io.MousePos;
                ImVec2 mn(std::min(ed.box_start.x, cur.x), std::min(ed.box_start.y, cur.y));
                ImVec2 mx(std::max(ed.box_start.x, cur.x), std::max(ed.box_start.y, cur.y));
                dl->AddRectFilled(mn, mx, COL_BOX_SEL_FILL);
                dl->AddRect(mn, mx, COL_BOX_SEL_BORDER, 0, 0, 1.0f * dpi_scale);
            }

            // Transform pivot
            if (ed.transform.active() && ed.transform.type != TransformMode::Grab) {
                ImVec2 pivot_screen = cv.to_screen(ed.transform.pivot);
                float r = 6.0f * dpi_scale;
                dl->AddLine(ImVec2(pivot_screen.x - r, pivot_screen.y), ImVec2(pivot_screen.x + r, pivot_screen.y), COL_PIVOT, 2.0f * dpi_scale);
                dl->AddLine(ImVec2(pivot_screen.x, pivot_screen.y - r), ImVec2(pivot_screen.x, pivot_screen.y + r), COL_PIVOT, 2.0f * dpi_scale);
            }

            // Transform status text
            if (ed.transform.active()) {
                Vec2 mw = cv.to_world(io.MousePos);
                char status[128];
                switch (ed.transform.type) {
                case TransformMode::Grab: {
                    Vec2 delta = mw - ed.transform.mouse_start;
                    if (ed.transform.lock_x) delta.y = 0;
                    if (ed.transform.lock_y) delta.x = 0;
                    std::snprintf(status, sizeof(status), "Grab: dx=%.3f dy=%.3f%s",
                        delta.x, delta.y,
                        ed.transform.lock_x ? " [X]" : (ed.transform.lock_y ? " [Y]" : ""));
                    break;
                }
                case TransformMode::Rotate: {
                    Vec2 v0 = ed.transform.mouse_start - ed.transform.pivot;
                    Vec2 v1 = mw - ed.transform.pivot;
                    float angle = std::atan2(v1.y, v1.x) - std::atan2(v0.y, v0.x);
                    std::snprintf(status, sizeof(status), "Rotate: %.1f deg", angle * 180.0f / PI);
                    break;
                }
                case TransformMode::Scale: {
                    float d0 = (ed.transform.mouse_start - ed.transform.pivot).length();
                    float d1 = (mw - ed.transform.pivot).length();
                    float factor = (d0 > 1e-6f) ? d1 / d0 : 1.0f;
                    std::snprintf(status, sizeof(status), "Scale: %.2fx%s", factor,
                        ed.transform.lock_x ? " [X]" : (ed.transform.lock_y ? " [Y]" : ""));
                    break;
                }
                default: status[0] = 0;
                }
                if (status[0]) {
                    ImVec2 text_pos((float)win_w * 0.5f - 100, (float)win_h - 30 * dpi_scale);
                    dl->AddText(text_pos, IM_COL32(255, 255, 255, 220), status);
                }
            }
        }

        // ── Measurement overlay ──────────────────────────────────────────
        if (!showing_snapshot_a && ed.tool == EditTool::Measure && ed.measure_active) {
            ImDrawList* dl = ImGui::GetWindowDrawList();
            ImU32 meas_col = IM_COL32(0, 255, 180, 200);
            Vec2 mend = cv.to_world(io.MousePos);
            if (ed.snap_to_grid && ed.show_grid && grid_spacing > 0)
                mend = snap_to_grid_pos(mend, grid_spacing);
            ImVec2 s0 = cv.to_screen(ed.measure_start);
            ImVec2 s1 = cv.to_screen(mend);
            dl->AddLine(s0, s1, meas_col, 1.5f * dpi_scale);
            dl->AddCircleFilled(s0, 3.0f * dpi_scale, meas_col);
            dl->AddCircleFilled(s1, 3.0f * dpi_scale, meas_col);
            Vec2 delta = mend - ed.measure_start;
            float dist = delta.length();
            float angle_deg = std::atan2(delta.y, delta.x) * 180.0f / PI;
            char mtext[128];
            std::snprintf(mtext, sizeof(mtext), "d=%.4f  a=%.1f deg  dx=%.4f  dy=%.4f",
                          dist, angle_deg, delta.x, delta.y);
            ImVec2 mid = {(s0.x + s1.x) * 0.5f, std::min(s0.y, s1.y) - 20.0f * dpi_scale};
            dl->AddText(mid, meas_col, mtext);
        }

        // ── Camera frame overlay ───────────────────────────────────────
        // Resolve camera bounds once per frame for both drawing and interaction
        struct CamHandlePt { CameraHandle id; Vec2 pos; };
        Bounds cam_frame{};
        CamHandlePt cam_handle_pts[8] = {};
        int n_cam_handles = 0;
        bool cam_active = !showing_snapshot_a && ed.show_camera_frame && !ed.shot.camera.empty();

        if (cam_active) {
            cam_frame = ed.shot.camera.resolve(ed.shot.canvas.aspect(), ed.scene_bounds);
            Vec2 mn = cam_frame.min, mx = cam_frame.max, mid = (mn + mx) * 0.5f;
            cam_handle_pts[0] = {CameraHandle::TopLeft,     {mn.x, mx.y}};
            cam_handle_pts[1] = {CameraHandle::TopRight,    mx};
            cam_handle_pts[2] = {CameraHandle::BottomLeft,  mn};
            cam_handle_pts[3] = {CameraHandle::BottomRight, {mx.x, mn.y}};
            cam_handle_pts[4] = {CameraHandle::Top,         {mid.x, mx.y}};
            cam_handle_pts[5] = {CameraHandle::Bottom,      {mid.x, mn.y}};
            cam_handle_pts[6] = {CameraHandle::Left,        {mn.x, mid.y}};
            cam_handle_pts[7] = {CameraHandle::Right,       {mx.x, mid.y}};
            n_cam_handles = 8;

            ImDrawList* dl = ImGui::GetWindowDrawList();
            ImVec2 scr_max = cv.to_screen(cam_frame.max);
            ImVec2 scr_min = cv.to_screen(cam_frame.min);
            float sl = scr_min.x, sr = scr_max.x;
            float st = scr_max.y, sb = scr_min.y;

            if (ed.dim_outside_camera) {
                float vr = (float)win_w, vb = (float)win_h;
                dl->AddRectFilled(ImVec2(0, 0), ImVec2(vr, st), COL_CAMERA_DIM);
                dl->AddRectFilled(ImVec2(0, sb), ImVec2(vr, vb), COL_CAMERA_DIM);
                dl->AddRectFilled(ImVec2(0, st), ImVec2(sl, sb), COL_CAMERA_DIM);
                dl->AddRectFilled(ImVec2(sr, st), ImVec2(vr, sb), COL_CAMERA_DIM);
            }

            dl->AddRect(ImVec2(sl, st), ImVec2(sr, sb), COL_CAMERA_FRAME, 0, 0, 1.5f * dpi_scale);

            if (ed.selection.empty() && ed.tool == EditTool::Select && !ed.transform.active()) {
                float hs = 4.0f * dpi_scale;
                for (int h = 0; h < n_cam_handles; ++h) {
                    ImVec2 sp = cv.to_screen(cam_handle_pts[h].pos);
                    ImU32 col = (ed.cam_handle_hovered == cam_handle_pts[h].id) ? COL_HANDLE_HOV : COL_CAMERA_HANDLE;
                    dl->AddRectFilled(ImVec2(sp.x - hs, sp.y - hs), ImVec2(sp.x + hs, sp.y + hs), col);
                }
            }
        }

        ImGui::End();
        ImGui::PopStyleVar();

        // ── Mouse interaction ───────────────────────────────────────────

        Vec2 mw_raw = cv.to_world(io.MousePos);
        bool snapping = ed.snap_to_grid && ed.show_grid && grid_spacing > 0;
        Vec2 mw = snapping ? snap_to_grid_pos(mw_raw, grid_spacing) : mw_raw;
        float hit_thresh = 8.0f / cv.cam.zoom;

        // Camera handle interaction (hover + start drag)
        if (!showing_snapshot_a && vp_hovered && ed.selection.empty() && ed.tool == EditTool::Select
            && !ed.transform.active() && cam_active
            && ed.cam_handle_dragging == CameraHandle::None) {

            ed.cam_handle_hovered = CameraHandle::None;
            for (int h = 0; h < n_cam_handles; ++h) {
                if ((mw - cam_handle_pts[h].pos).length() < hit_thresh) {
                    ed.cam_handle_hovered = cam_handle_pts[h].id;
                    break;
                }
            }

            if (ed.cam_handle_hovered != CameraHandle::None && ImGui::IsMouseClicked(0)) {
                ed.cam_handle_dragging = ed.cam_handle_hovered;
                ed.cam_drag_start_bounds = cam_frame;
            }
        } else if (ed.cam_handle_dragging == CameraHandle::None) {
            ed.cam_handle_hovered = CameraHandle::None;
        }

        // Camera handle drag (continues even outside viewport)
        if (!showing_snapshot_a && ed.cam_handle_dragging != CameraHandle::None) {
            if (ImGui::IsMouseDragging(0)) {
                Bounds b = ed.cam_drag_start_bounds;
                Vec2 drag_origin = cv.to_world(io.MouseClickedPos[0]);
                Vec2 drag_offset = mw - drag_origin;

                switch (ed.cam_handle_dragging) {
                case CameraHandle::Move:        b.min = b.min + drag_offset;
                                                b.max = b.max + drag_offset; break;
                case CameraHandle::TopLeft:     b.min.x = mw.x; b.max.y = mw.y; break;
                case CameraHandle::Top:         b.max.y = mw.y; break;
                case CameraHandle::TopRight:    b.max.x = mw.x; b.max.y = mw.y; break;
                case CameraHandle::Right:       b.max.x = mw.x; break;
                case CameraHandle::BottomRight: b.max.x = mw.x; b.min.y = mw.y; break;
                case CameraHandle::Bottom:      b.min.y = mw.y; break;
                case CameraHandle::BottomLeft:  b.min.x = mw.x; b.min.y = mw.y; break;
                case CameraHandle::Left:        b.min.x = mw.x; break;
                default: break;
                }

                // Normalize if dragged past opposite edge
                if (b.min.x > b.max.x) std::swap(b.min.x, b.max.x);
                if (b.min.y > b.max.y) std::swap(b.min.y, b.max.y);

                ed.shot.camera.bounds = b;
                ed.shot.camera.center.reset();
                ed.shot.camera.width.reset();
                ed.dirty = true;
            }
            if (ImGui::IsMouseReleased(0)) {
                ed.cam_handle_dragging = CameraHandle::None;
            }
        }

        // Hover detection (Select tool only, skip during camera drag)
        if (!showing_snapshot_a && vp_hovered && ed.tool == EditTool::Select && !ed.dragging && !ed.creating && !ed.box_selecting && !ed.transform.active()
            && ed.cam_handle_dragging == CameraHandle::None) {
            SelectionRef hit = hit_test(mw_raw, ed.shot.scene, hit_thresh, ed.editing_group);
            ed.hovered = hit;
        } else if (!vp_hovered) {
            ed.hovered = {SelectionRef::Shape, -1};
        } else if (showing_snapshot_a) {
            ed.hovered = {SelectionRef::Shape, -1};
        }

        // --- Viewport navigation: pan & zoom ---

        // Pan: middle mouse drag or Alt+LMB drag
        if (vp_hovered) {
            bool compare_view_locked = compare_ab.active;
            bool middle_drag = ImGui::IsMouseDragging(2); // middle button
            bool alt_drag = io.KeyAlt && ImGui::IsMouseDragging(0);

            if (!compare_view_locked && (middle_drag || alt_drag)) {
                ImVec2 delta = io.MouseDelta;
                ed.camera.center.x -= delta.x / ed.camera.zoom;
                ed.camera.center.y += delta.y / ed.camera.zoom;
                renderer.update_viewport(ed.camera.visible_bounds((float)win_w, (float)win_h));
                renderer.clear();
            }

            // Scroll wheel: Alt+scroll = exposure scrub, otherwise zoom
            if (io.MouseWheel != 0) {
                if (io.KeyAlt && !ImGui::IsMouseDragging(0)) {
                    // Exposure scrub
                    ed.shot.look.exposure += io.MouseWheel * 0.5f;
                } else if (!compare_view_locked) {
                    Vec2 world_before = cv.to_world(io.MousePos);
                    float factor = (io.MouseWheel > 0) ? 1.1f : (1.0f / 1.1f);
                    ed.camera.zoom *= factor;
                    ed.camera.zoom = std::clamp(ed.camera.zoom, 1.0f, 100000.0f);
                    // Recompute cv after zoom change
                    CameraView cv2{ed.camera, (float)win_w, (float)win_h};
                    Vec2 world_after = cv2.to_world(io.MousePos);
                    ed.camera.center = ed.camera.center + (world_before - world_after);
                    cv = CameraView{ed.camera, (float)win_w, (float)win_h};
                    renderer.update_viewport(ed.camera.visible_bounds((float)win_w, (float)win_h));
                    renderer.clear();
                }
            }
        }

        // --- Tool interactions ---

        // Skip tool interactions during alt-drag (pan) or middle drag
        bool panning = (io.KeyAlt && ImGui::IsMouseDown(0)) || ImGui::IsMouseDown(2);

        if (!showing_snapshot_a && vp_hovered && !panning && !ed.transform.active()
            && ed.cam_handle_dragging == CameraHandle::None) {
            // Double-click: enter group editing mode
            if (ImGui::IsMouseDoubleClicked(0) && ed.tool == EditTool::Select) {
                if (ed.editing_group < 0) {
                    // Not inside a group — double-click on group member enters it
                    SelectionRef hit = hit_test(mw_raw, ed.shot.scene, hit_thresh, -1);
                    if (hit.type == SelectionRef::Group && hit.index >= 0) {
                        ed.editing_group = hit.index;
                        ed.clear_selection();
                        // Select the specific member that was clicked
                        SelectionRef member = hit_test(mw_raw, ed.shot.scene, hit_thresh, ed.editing_group);
                        if (member.index >= 0) ed.select(member);
                        reload();
                    }
                }
            }

            if (ImGui::IsMouseClicked(0)) {
                if (ed.tool == EditTool::Select) {
                    // Check handle hit first
                    auto handles = get_handles(ed.shot.scene, ed.selection);
                    int h_idx = handle_hit_test(handles, mw_raw, hit_thresh);

                    if (h_idx >= 0) {
                        // Start handle drag
                        ed.undo.push(ed.shot.scene);
                        ed.handle_dragging = true;
                        ed.active_handle = handles[h_idx];
                    } else {
                        // Hit test objects
                        SelectionRef hit = hit_test(mw_raw, ed.shot.scene, hit_thresh, ed.editing_group);

                        if (hit.index >= 0) {
                            if (io.KeyShift) {
                                ed.toggle_select(hit);
                            } else if (!ed.is_selected(hit)) {
                                ed.clear_selection();
                                ed.select(hit);
                            }
                            // Start drag move
                            ed.undo.push(ed.shot.scene);
                            ed.dragging = true;
                            ed.drag_offsets.clear();
                            for (auto& sid : ed.selection) {
                                if (const Shape* shape = resolve_shape(ed.shot.scene, sid)) {
                                    std::visit(overloaded{
                                        [&](const Circle& ci) { ed.drag_offsets.push_back({ci.center - mw_raw, {}}); },
                                        [&](const Segment& s) { ed.drag_offsets.push_back({s.a - mw_raw, s.b - mw_raw}); },
                                        [&](const Arc& a) { ed.drag_offsets.push_back({a.center - mw_raw, {}}); },
                                        [&](const Bezier& b) { ed.drag_offsets.push_back({b.p0 - mw_raw, b.p2 - mw_raw}); },
                                        [&](const Polygon& p) { ed.drag_offsets.push_back({p.centroid() - mw_raw, {}}); },
                                        [&](const Ellipse& e) { ed.drag_offsets.push_back({e.center - mw_raw, {}}); },
                                    }, *shape);
                                } else if (const Light* light = resolve_light(ed.shot.scene, sid)) {
                                    std::visit(overloaded{
                                        [&](const PointLight& l) { ed.drag_offsets.push_back({l.pos - mw_raw, {}}); },
                                        [&](const SegmentLight& l) { ed.drag_offsets.push_back({l.a - mw_raw, l.b - mw_raw}); },
                                        [&](const BeamLight& l) { ed.drag_offsets.push_back({l.origin - mw_raw, {}}); },
                                        [&](const ParallelBeamLight& l) { ed.drag_offsets.push_back({l.a - mw_raw, l.b - mw_raw}); },
                                        [&](const SpotLight& l) { ed.drag_offsets.push_back({l.pos - mw_raw, {}}); },
                                    }, *light);
                                } else if (sid.type == SelectionRef::Group) {
                                    auto& g = ed.shot.scene.groups[sid.index];
                                    ed.drag_offsets.push_back({g.transform.translate - mw_raw, {}});
                                }
                            }
                        } else {
                            if (!io.KeyShift) ed.clear_selection();
                            // Start box select
                            ed.box_selecting = true;
                            ed.box_start = io.MousePos;
                        }
                    }
                } else if (ed.tool == EditTool::Erase) {
                    SelectionRef hit = hit_test(mw_raw, ed.shot.scene, hit_thresh, ed.editing_group);
                    if (hit.index >= 0) {
                        ed.clear_selection();
                        ed.select(hit);
                        delete_selected();
                    }
                } else if (ed.tool == EditTool::PointLight) {
                    ed.undo.push(ed.shot.scene);
                    PointLight light;
                    light.id = next_scene_entity_id(ed.shot.scene, "point_light");
                    light.pos = mw;
                    light.intensity = 1.0f;
                    ed.shot.scene.lights.push_back(light);
                    ed.clear_selection();
                    ed.select({SelectionRef::Light, (int)ed.shot.scene.lights.size() - 1});
                    reload();
                } else if (ed.tool == EditTool::BeamLight) {
                    ed.undo.push(ed.shot.scene);
                    BeamLight light;
                    light.id = next_scene_entity_id(ed.shot.scene, "beam_light");
                    light.origin = mw;
                    light.direction = {1.0f, 0.0f};
                    light.angular_width = 0.1f;
                    light.intensity = 1.0f;
                    ed.shot.scene.lights.push_back(light);
                    ed.clear_selection();
                    ed.select({SelectionRef::Light, (int)ed.shot.scene.lights.size() - 1});
                    reload();
                } else if (ed.tool == EditTool::SpotLight) {
                    ed.undo.push(ed.shot.scene);
                    SpotLight light;
                    light.id = next_scene_entity_id(ed.shot.scene, "spot_light");
                    light.pos = mw;
                    light.direction = {1.0f, 0.0f};
                    light.angular_width = 0.5f;
                    light.falloff = 2.0f;
                    light.intensity = 1.0f;
                    ed.shot.scene.lights.push_back(light);
                    ed.clear_selection();
                    ed.select({SelectionRef::Light, (int)ed.shot.scene.lights.size() - 1});
                    reload();
                } else if (ed.tool == EditTool::Measure) {
                    if (!ed.measure_active) {
                        ed.measure_start = mw;
                        ed.measure_active = true;
                    } else {
                        ed.measure_active = false;
                    }
                } else {
                    ed.creating = true;
                    ed.create_start = mw;
                }
            }
        }

        // Handle drag (specific parameter modification)
        if (ImGui::IsMouseDragging(0) && ed.handle_dragging) {
            apply_handle_drag(ed.shot.scene, ed.active_handle, mw);
            reload();
        }

        // Drag to move selected objects
        if (ImGui::IsMouseDragging(0) && ed.dragging && !ed.handle_dragging && !ed.box_selecting &&
            ed.drag_offsets.size() == ed.selection.size()) {
            for (int i = 0; i < (int)ed.selection.size(); ++i) {
                auto& sid = ed.selection[i];
                auto& off = ed.drag_offsets[i];
                if (Shape* shape = resolve_shape(ed.shot.scene, sid)) {
                    std::visit(overloaded{
                        [&](Circle& c) { c.center = mw + off.a; },
                        [&](Segment& s) { s.a = mw + off.a; s.b = mw + off.b; },
                        [&](Arc& a) { a.center = mw + off.a; },
                        [&](Bezier& b) {
                            Vec2 delta = (mw + off.a) - b.p0;
                            b.p0 = b.p0 + delta; b.p1 = b.p1 + delta; b.p2 = b.p2 + delta;
                        },
                        [&](Polygon& p) {
                            if (p.vertices.empty()) return;
                            Vec2 delta = (mw + off.a) - p.centroid();
                            for (auto& v : p.vertices) v = v + delta;
                        },
                        [&](Ellipse& e) { e.center = mw + off.a; },
                    }, *shape);
                } else if (Light* light = resolve_light(ed.shot.scene, sid)) {
                    std::visit(overloaded{
                        [&](PointLight& l) { l.pos = mw + off.a; },
                        [&](SegmentLight& l) { l.a = mw + off.a; l.b = mw + off.b; },
                        [&](BeamLight& l) { l.origin = mw + off.a; },
                        [&](ParallelBeamLight& l) { l.a = mw + off.a; l.b = mw + off.b; },
                        [&](SpotLight& l) { l.pos = mw + off.a; },
                    }, *light);
                } else if (sid.type == SelectionRef::Group && sid.index < (int)ed.shot.scene.groups.size()) {
                    ed.shot.scene.groups[sid.index].transform.translate = mw + off.a;
                }
            }
            reload();
        }

        if (ImGui::IsMouseReleased(0)) {
            // Complete creation
            if (ed.creating) {
                Vec2 end = cv.to_world(io.MousePos);
                float dist = (end - ed.create_start).length();

                ed.undo.push(ed.shot.scene);
                bool created = false;

                if (ed.tool == EditTool::Circle) {
                    float r = std::max(dist, 0.02f);
                    Circle circle;
                    circle.id = next_scene_entity_id(ed.shot.scene, "circle");
                    circle.center = ed.create_start;
                    circle.radius = r;
                    circle.material = mat_glass(1.5f, 20000.0f, 0.3f);
                    ed.shot.scene.shapes.push_back(circle);
                    ed.clear_selection();
                    ed.select({SelectionRef::Shape, (int)ed.shot.scene.shapes.size() - 1});
                    created = true;
                } else if (ed.tool == EditTool::Segment && dist > 0.01f) {
                    Segment segment;
                    segment.id = next_scene_entity_id(ed.shot.scene, "segment");
                    segment.a = ed.create_start;
                    segment.b = end;
                    segment.material = mat_mirror(0.95f);
                    ed.shot.scene.shapes.push_back(segment);
                    ed.clear_selection();
                    ed.select({SelectionRef::Shape, (int)ed.shot.scene.shapes.size() - 1});
                    created = true;
                } else if (ed.tool == EditTool::Arc) {
                    Arc arc = make_default_arc(ed.create_start, end);
                    arc.id = next_scene_entity_id(ed.shot.scene, "arc");
                    ed.shot.scene.shapes.push_back(arc);
                    ed.clear_selection();
                    ed.select({SelectionRef::Shape, (int)ed.shot.scene.shapes.size() - 1});
                    created = true;
                } else if (ed.tool == EditTool::Bezier && dist > 0.01f) {
                    Vec2 mid = (ed.create_start + end) * 0.5f;
                    Bezier bezier;
                    bezier.id = next_scene_entity_id(ed.shot.scene, "bezier");
                    bezier.p0 = ed.create_start;
                    bezier.p1 = mid;
                    bezier.p2 = end;
                    bezier.material = mat_glass(1.5f, 20000.0f, 0.3f);
                    ed.shot.scene.shapes.push_back(bezier);
                    ed.clear_selection();
                    ed.select({SelectionRef::Shape, (int)ed.shot.scene.shapes.size() - 1});
                    created = true;
                } else if (ed.tool == EditTool::Polygon && dist > 0.01f) {
                    Vec2 a = ed.create_start, b = end;
                    Polygon p;
                    p.id = next_scene_entity_id(ed.shot.scene, "polygon");
                    p.vertices = {{a.x, a.y}, {b.x, a.y}, {b.x, b.y}, {a.x, b.y}};
                    if (!polygon_is_clockwise(p))
                        std::reverse(p.vertices.begin(), p.vertices.end());
                    p.material = mat_glass(1.5f, 20000.0f, 0.3f);
                    ed.shot.scene.shapes.push_back(p);
                    ed.clear_selection();
                    ed.select({SelectionRef::Shape, (int)ed.shot.scene.shapes.size() - 1});
                    created = true;
                } else if (ed.tool == EditTool::Ellipse && dist > 0.01f) {
                    Vec2 center = (ed.create_start + end) * 0.5f;
                    float sa = std::max(std::abs(end.x - ed.create_start.x) * 0.5f, 0.02f);
                    float sb = std::max(std::abs(end.y - ed.create_start.y) * 0.5f, 0.02f);
                    Ellipse ellipse;
                    ellipse.id = next_scene_entity_id(ed.shot.scene, "ellipse");
                    ellipse.center = center;
                    ellipse.semi_a = sa;
                    ellipse.semi_b = sb;
                    ellipse.rotation = 0.0f;
                    ellipse.material = mat_glass(1.5f, 20000.0f, 0.3f);
                    ed.shot.scene.shapes.push_back(ellipse);
                    ed.clear_selection();
                    ed.select({SelectionRef::Shape, (int)ed.shot.scene.shapes.size() - 1});
                    created = true;
                } else if (ed.tool == EditTool::SegmentLight && dist > 0.01f) {
                    SegmentLight light;
                    light.id = next_scene_entity_id(ed.shot.scene, "segment_light");
                    light.a = ed.create_start;
                    light.b = end;
                    light.intensity = 1.0f;
                    ed.shot.scene.lights.push_back(light);
                    ed.clear_selection();
                    ed.select({SelectionRef::Light, (int)ed.shot.scene.lights.size() - 1});
                    created = true;
                } else if (ed.tool == EditTool::ParallelBeamLight && dist > 0.01f) {
                    Vec2 seg_dir = end - ed.create_start;
                    Vec2 perp = Vec2{-seg_dir.y, seg_dir.x}.normalized();
                    ParallelBeamLight light;
                    light.id = next_scene_entity_id(ed.shot.scene, "parallel_beam_light");
                    light.a = ed.create_start;
                    light.b = end;
                    light.direction = perp;
                    light.angular_width = 0.0f;
                    light.intensity = 1.0f;
                    ed.shot.scene.lights.push_back(light);
                    ed.clear_selection();
                    ed.select({SelectionRef::Light, (int)ed.shot.scene.lights.size() - 1});
                    created = true;
                }

                if (created) reload();
                else { ed.undo.snapshots.pop_back(); ed.undo.current--; } // nothing created, revert push
                ed.creating = false;
            }

            // Complete box selection
            if (ed.box_selecting) {
                ImVec2 cur = io.MousePos;
                Vec2 wmin = cv.to_world(ImVec2(std::min(ed.box_start.x, cur.x), std::max(ed.box_start.y, cur.y)));
                Vec2 wmax = cv.to_world(ImVec2(std::max(ed.box_start.x, cur.x), std::min(ed.box_start.y, cur.y)));

                if (!io.KeyShift) ed.clear_selection();
                for (int i = 0; i < (int)ed.shot.scene.shapes.size(); ++i) {
                    SelectionRef id{SelectionRef::Shape, i};
                    if (object_in_rect(ed.shot.scene, id, wmin, wmax))
                        ed.select(id);
                }
                for (int i = 0; i < (int)ed.shot.scene.lights.size(); ++i) {
                    SelectionRef id{SelectionRef::Light, i};
                    if (object_in_rect(ed.shot.scene, id, wmin, wmax))
                        ed.select(id);
                }
                for (int i = 0; i < (int)ed.shot.scene.groups.size(); ++i) {
                    SelectionRef id{SelectionRef::Group, i};
                    if (object_in_rect(ed.shot.scene, id, wmin, wmax))
                        ed.select(id);
                }
                ed.box_selecting = false;
            }

            ed.dragging = false;
            ed.handle_dragging = false;
            ed.drag_offsets.clear();
        }

        // ── Controls panel ──────────────────────────────────────────────

        float panel_w = 280 * dpi_scale;
        ImGui::SetNextWindowPos(ImVec2((float)win_w - panel_w - 8, 8), ImGuiCond_FirstUseEver);
        ImGui::SetNextWindowSize(ImVec2(panel_w, (float)win_h - 16), ImGuiCond_FirstUseEver);
        ImGui::SetNextWindowSizeConstraints(ImVec2(220 * dpi_scale, 200), ImVec2(500 * dpi_scale, 1e6f));
        ImGui::Begin("Controls");

        // -- Scene --
        if (ImGui::CollapsingHeader("Scene", ImGuiTreeNodeFlags_DefaultOpen)) {
            ImGui::PushID("Scene");
            const char* label = (current_scene >= 0) ? builtins[current_scene].name.c_str() : "Custom";
            if (ImGui::BeginCombo("##scene", label)) {
                for (int i = 0; i < (int)builtins.size(); ++i) {
                    if (ImGui::Selectable(builtins[i].name.c_str(), i == current_scene)) {
                        current_scene = i;
                        ed.shot = load_builtin_scene(builtins[i]);
                        apply_gui_shot_defaults(ed.shot);
                        reset_editor();
                    }
                }
                ImGui::EndCombo();
            }
            if (ImGui::Button("New Scene")) {
                current_scene = -1;
                ed.shot = Shot{};
                ed.shot.name = "custom";
                add_box_walls(ed.shot.scene, kDefaultRoomHalfWidth, kDefaultRoomHalfHeight,
                              gui_wall_material());
                PointLight light;
                light.pos = {0.0f, 0.0f};
                light.intensity = 1.0f;
                ed.shot.scene.lights.push_back(light);
                ed.shot.camera.bounds = Bounds{{-kDefaultRoomHalfWidth, -kDefaultRoomHalfHeight},
                                               {kDefaultRoomHalfWidth, kDefaultRoomHalfHeight}};
                apply_gui_shot_defaults(ed.shot);
                reset_editor();
            }

            // Save/Load
            ImGui::SameLine();
            if (ImGui::Button("Save")) { do_save(); }
            ImGui::SameLine();
            if (ImGui::Button("Load")) {
                ImGui::OpenPopup("Load Scene##popup");
            }

            // Load popup (can be triggered by Ctrl+O shortcut)
            if (open_load_popup) { ImGui::OpenPopup("Load Scene##popup"); open_load_popup = false; }
            if (ImGui::BeginPopup("Load Scene##popup")) {
                ImGui::Text("File path:");
                if (ImGui::InputText("##loadpath", load_dialog.path.data(), load_dialog.path.size()))
                    load_dialog.error.clear();
                if (!load_dialog.error.empty())
                    ImGui::TextWrapped("%s", load_dialog.error.c_str());
                if (ImGui::Button("OK") && load_dialog.path[0]) {
                    std::string error;
                    if (auto loaded = try_load_shot_json(load_dialog.path.data(), &error)) {
                        apply_gui_shot_defaults(*loaded);
                        ed.shot = *loaded;
                        ed.save_path = load_dialog.path.data();
                        current_scene = -1;
                        load_dialog.error.clear();
                        reset_editor();
                    } else {
                        load_dialog.error = error.empty() ? "Failed to load scene" : error;
                    }
                    if (load_dialog.error.empty())
                        ImGui::CloseCurrentPopup();
                }
                ImGui::SameLine();
                if (ImGui::Button("Cancel")) {
                    load_dialog.error.clear();
                    ImGui::CloseCurrentPopup();
                }
                ImGui::EndPopup();
            }
            ImGui::PopID();
        }

        // -- Tools --
        if (ImGui::CollapsingHeader("Tools", ImGuiTreeNodeFlags_DefaultOpen)) {
            ImGui::PushID("Tools");
            ImVec4 accent(0.31f, 0.53f, 0.86f, 1.0f);
            ImVec4 accent_h(0.38f, 0.60f, 0.92f, 1.0f);
            auto tbtn = [&](const char* lbl, EditTool t) {
                bool active = (ed.tool == t);
                if (active) {
                    ImGui::PushStyleColor(ImGuiCol_Button, accent);
                    ImGui::PushStyleColor(ImGuiCol_ButtonHovered, accent_h);
                }
                if (ImGui::Button(lbl)) { ed.tool = t; ed.creating = false; }
                if (active) ImGui::PopStyleColor(2);
            };
            tbtn("Select", EditTool::Select); ImGui::SameLine();
            tbtn("Circle", EditTool::Circle); ImGui::SameLine();
            tbtn("Segment", EditTool::Segment);
            tbtn("Arc", EditTool::Arc); ImGui::SameLine();
            tbtn("Bezier", EditTool::Bezier); ImGui::SameLine();
            tbtn("Polygon", EditTool::Polygon);
            tbtn("Ellipse", EditTool::Ellipse); ImGui::SameLine();
            tbtn("Erase", EditTool::Erase);
            tbtn("Pt Light", EditTool::PointLight); ImGui::SameLine();
            tbtn("Seg Light", EditTool::SegmentLight); ImGui::SameLine();
            tbtn("Beam", EditTool::BeamLight);
            tbtn("Par.Beam", EditTool::ParallelBeamLight); ImGui::SameLine();
            tbtn("Spot", EditTool::SpotLight); ImGui::SameLine();
            tbtn("Measure", EditTool::Measure);

            ImGui::Checkbox("Wireframe overlay", &show_wireframe);
            ImGui::Checkbox("Grid", &ed.show_grid);
            if (ed.show_grid) {
                ImGui::SameLine();
                ImGui::Checkbox("Snap", &ed.snap_to_grid);
            }
            ImGui::PopID();
        }

        // -- Camera --
        if (ImGui::CollapsingHeader("Camera", ImGuiTreeNodeFlags_DefaultOpen)) {
            ImGui::PushID("Camera");

            if (ImGui::Button("Set from View")) {
                ed.shot.camera.bounds = current_display_view();
                ed.shot.camera.center.reset();
                ed.shot.camera.width.reset();
                ed.dirty = true;
            }
            ImGui::SameLine();
            if (ImGui::Button("Clear") && !ed.shot.camera.empty()) {
                ed.shot.camera = Camera2D{};
                ed.dirty = true;
            }

            ImGui::Checkbox("Show frame", &ed.show_camera_frame);
            ImGui::SameLine();
            ImGui::Checkbox("Dim outside", &ed.dim_outside_camera);

            if (!ed.shot.camera.empty()) {
                Bounds cam = ed.shot.camera.resolve(ed.shot.canvas.aspect(), ed.scene_bounds);
                bool cam_changed = false;
                cam_changed |= ImGui::DragFloat("Min X", &cam.min.x, 0.01f);
                cam_changed |= ImGui::DragFloat("Min Y", &cam.min.y, 0.01f);
                cam_changed |= ImGui::DragFloat("Max X", &cam.max.x, 0.01f);
                cam_changed |= ImGui::DragFloat("Max Y", &cam.max.y, 0.01f);
                if (cam_changed) {
                    ed.shot.camera.bounds = cam;
                    ed.shot.camera.center.reset();
                    ed.shot.camera.width.reset();
                    ed.dirty = true;
                }
            } else {
                ImGui::TextDisabled("Camera: auto (from scene bounds)");
            }

            ImGui::Separator();
            ImGui::TextDisabled("Output resolution for export/CLI");
            int cw = ed.shot.canvas.width, ch = ed.shot.canvas.height;
            bool canvas_changed = false;
            canvas_changed |= ImGui::InputInt("Width##canvas", &cw, 0, 0);
            canvas_changed |= ImGui::InputInt("Height##canvas", &ch, 0, 0);
            if (canvas_changed) {
                ed.shot.canvas.width = std::clamp(cw, 64, 7680);
                ed.shot.canvas.height = std::clamp(ch, 64, 4320);
                ed.dirty = true;
            }
            ImGui::Text("Aspect: %.3f", ed.shot.canvas.aspect());
            ImGui::PopID();
        }

        // -- Objects --
        if (ImGui::CollapsingHeader("Objects", ImGuiTreeNodeFlags_DefaultOpen)) {
            ImGui::PushID("Objects");
            if (ImGui::SmallButton("Show All")) { ed.show_all(); reload(); }
            if (ed.solo_light >= 0) {
                ImGui::SameLine();
                if (ed.solo_light < (int)ed.shot.scene.lights.size()) {
                    const auto& light = ed.shot.scene.lights[ed.solo_light];
                    std::string label = light_display_name(light, ed.solo_light);
                    ImGui::TextColored(ImVec4(1.0f, 0.85f, 0.3f, 1.0f), "Solo: %s", label.c_str());
                }
            } else if (ed.solo_light_group >= 0) {
                ImGui::SameLine();
                if (ed.solo_light_group < (int)ed.shot.scene.groups.size()) {
                    const auto& group = ed.shot.scene.groups[ed.solo_light_group];
                    std::string group_label = group_display_name(group, ed.solo_light_group);
                    if (ed.solo_light_index >= 0 && ed.solo_light_index < (int)group.lights.size()) {
                        std::string light_label = light_display_name(group.lights[ed.solo_light_index], ed.solo_light_index);
                        ImGui::TextColored(ImVec4(1.0f, 0.85f, 0.3f, 1.0f),
                            "Solo: %s / %s", group_label.c_str(), light_label.c_str());
                    } else {
                        ImGui::TextColored(ImVec4(1.0f, 0.85f, 0.3f, 1.0f), "Solo: %s", group_label.c_str());
                    }
                }
            }
            int n_items = (int)(ed.shot.scene.shapes.size() + ed.shot.scene.lights.size() + ed.shot.scene.groups.size());
            float h = std::clamp(n_items * ImGui::GetTextLineHeightWithSpacing() + 8.0f,
                                 40.0f, 200.0f * dpi_scale);
            ImGui::BeginChild("##objlist", ImVec2(0, h), ImGuiChildFlags_Borders);

            for (int i = 0; i < (int)ed.shot.scene.shapes.size(); ++i) {
                SelectionRef id{SelectionRef::Shape, i};
                bool is_sel = ed.is_selected(id);
                const auto& shape = ed.shot.scene.shapes[i];
                std::string lbl = selection_label(shape_display_name(shape, i), "shape_" + std::to_string(i));
                // Visibility toggle
                ImGui::PushID(i + 10000);
                bool svis = ed.is_shape_visible(i);
                if (ImGui::SmallButton(svis ? "o" : "-")) {
                    ed.toggle_shape_visibility(i); reload();
                }
                ImGui::PopID();
                ImGui::SameLine();
                // Material color swatch
                ImVec4 mc = std::visit([](const auto& s) { return material_color(s.material); }, ed.shot.scene.shapes[i]);
                ImGui::PushID(i);
                ImGui::ColorButton("##sw", mc, ImGuiColorEditFlags_NoTooltip | ImGuiColorEditFlags_NoPicker, ImVec2(10, 10));
                ImGui::PopID();
                ImGui::SameLine();
                if (ImGui::Selectable(lbl.c_str(), is_sel)) {
                    if (io.KeyShift) ed.toggle_select(id);
                    else { ed.clear_selection(); ed.select(id); }
                }
            }

            for (int i = 0; i < (int)ed.shot.scene.lights.size(); ++i) {
                SelectionRef id{SelectionRef::Light, i};
                bool is_sel = ed.is_selected(id);
                std::string lbl = selection_label(light_display_name(ed.shot.scene.lights[i], i), "light_" + std::to_string(i));
                // Visibility toggle
                ImGui::PushID(i + 20000);
                bool lvis = ed.is_light_visible(i);
                if (ImGui::SmallButton(lvis ? "o" : "-")) {
                    ed.toggle_light_visibility(i); reload();
                }
                ImGui::PopID();
                ImGui::SameLine();
                // Solo toggle
                ImGui::PushID(i + 30000);
                bool is_solo = (ed.solo_light == i);
                if (ImGui::SmallButton(is_solo ? "S" : "s")) {
                    ed.solo_light = is_solo ? -1 : i;
                    ed.solo_light_group = -1;
                    ed.solo_light_index = -1;
                    reload();
                }
                ImGui::PopID();
                ImGui::SameLine();
                if (ImGui::Selectable(lbl.c_str(), is_sel)) {
                    if (io.KeyShift) ed.toggle_select(id);
                    else { ed.clear_selection(); ed.select(id); }
                }
            }

            for (int i = 0; i < (int)ed.shot.scene.groups.size(); ++i) {
                SelectionRef id{SelectionRef::Group, i};
                bool is_sel = ed.is_selected(id);
                bool is_editing = (ed.editing_group == i);
                const auto& group = ed.shot.scene.groups[i];
                int n_members = (int)(group.shapes.size() + group.lights.size());
                std::string group_name = group_display_name(group, i);
                std::string lbl = group_name;
                if (is_editing) lbl = "> " + lbl;
                lbl += " (" + std::to_string(n_members) + " items)";
                lbl = selection_label(lbl, "group_" + std::to_string(i));
                // Visibility toggle
                ImGui::PushID(i + 40000);
                bool gvis = ed.is_group_visible(i);
                if (ImGui::SmallButton(gvis ? "o" : "-")) {
                    ed.toggle_group_visibility(i); reload();
                }
                ImGui::PopID();
                ImGui::SameLine();
                if (ImGui::Selectable(lbl.c_str(), is_sel || is_editing)) {
                    if (io.KeyShift) ed.toggle_select(id);
                    else { ed.clear_selection(); ed.select(id); }
                }
                // Show expanded contents when editing inside this group
                if (is_editing) {
                    ImGui::Indent(12.0f);
                    for (int j = 0; j < (int)group.shapes.size(); ++j) {
                        SelectionRef mid{SelectionRef::Shape, j, i};
                        bool mid_sel = ed.is_selected(mid);
                        std::string mlbl = selection_label(
                            "  " + shape_display_name(group.shapes[j], j),
                            "group_shape_" + std::to_string(i) + "_" + std::to_string(j));
                        if (ImGui::Selectable(mlbl.c_str(), mid_sel)) {
                            ed.clear_selection();
                            ed.select(mid);
                        }
                    }
                    for (int j = 0; j < (int)group.lights.size(); ++j) {
                        SelectionRef mid{SelectionRef::Light, j, i};
                        bool mid_sel = ed.is_selected(mid);
                        // Solo toggle for group light
                        ImGui::PushID(i * 1000 + j + 50000);
                        bool is_gsolo = (ed.solo_light_group == i && ed.solo_light_index == j);
                        if (ImGui::SmallButton(is_gsolo ? "S" : "s")) {
                            if (is_gsolo) {
                                ed.solo_light_group = -1;
                                ed.solo_light_index = -1;
                            } else {
                                ed.solo_light_group = i;
                                ed.solo_light_index = j;
                                ed.solo_light = -1;
                            }
                            reload();
                        }
                        ImGui::PopID();
                        ImGui::SameLine();
                        std::string mlbl = selection_label(
                            "  " + light_display_name(group.lights[j], j),
                            "group_light_" + std::to_string(i) + "_" + std::to_string(j));
                        if (ImGui::Selectable(mlbl.c_str(), mid_sel)) {
                            ed.clear_selection();
                            ed.select(mid);
                        }
                    }
                    ImGui::Unindent(12.0f);
                }
            }

            ImGui::EndChild();

            if (!ed.selection.empty()) {
                if (ed.selection.size() > 1)
                    ImGui::Text("%d objects selected", (int)ed.selection.size());
                if (ImGui::Button("Delete Selected")) {
                    delete_selected();
                }
            }

            // Visual diagnostics
            {
                Shot diagnostic_shot = current_authored_shot();
                ensure_scene_entity_ids(diagnostic_shot.scene);
                sync_material_bindings(diagnostic_shot.scene);
                auto scene_warnings = diagnose_scene(diagnostic_shot.scene);
                if (!scene_warnings.empty()) {
                    ImGui::Text("Scene Warnings:");
                    for (const auto& warning : scene_warnings)
                        ImGui::BulletText("%s", warning.c_str());
                }

                if (ImGui::Button("Analyze Contributions")) {
                    light_analysis.clear();
                    light_analysis_valid = false;
                    auto authored_sources = collect_authored_sources(diagnostic_shot.scene);
                    if (!authored_sources.empty()) {
                        Bounds scene_bounds = scene_default_bounds(diagnostic_shot.scene);
                        Bounds view = diagnostic_shot.camera.resolve(
                            diagnostic_shot.canvas.aspect(), scene_bounds);
                        TraceConfig tcfg{
                            std::min(diagnostic_shot.trace.batch, 100000),
                            std::min(diagnostic_shot.trace.depth, 12),
                            diagnostic_shot.trace.intensity,
                        };
                        int analysis_dispatches =
                            std::max(1, (int)std::ceil(500000.0 / std::max(1, tcfg.batch_size)));

                        renderer.upload_scene(diagnostic_shot.scene, view);
                        renderer.clear();
                        if (renderer.num_lights() > 0)
                            renderer.trace_and_draw_multi(tcfg, analysis_dispatches);
                        float normalize_ref = std::max(renderer.compute_current_max(), 1.0f);

                        PostProcess contribution_look{};
                        contribution_look.exposure = 0.0f;
                        contribution_look.contrast = 1.0f;
                        contribution_look.gamma = 1.0f;
                        contribution_look.tone_map = ToneMap::None;
                        contribution_look.normalize = NormalizeMode::Fixed;
                        contribution_look.normalize_ref = normalize_ref;
                        contribution_look.ambient = 0.0f;
                        contribution_look.background[0] = 0.0f;
                        contribution_look.background[1] = 0.0f;
                        contribution_look.background[2] = 0.0f;
                        contribution_look.opacity = 1.0f;
                        contribution_look.saturation = 1.0f;
                        contribution_look.vignette = 0.0f;
                        contribution_look.vignette_radius = 0.7f;

                        float total_mean = 0.0f;
                        for (const auto& source : authored_sources) {
                            Scene solo = scene_with_only_source(diagnostic_shot.scene, source);
                            renderer.upload_scene(solo, view);
                            renderer.clear();
                            if (renderer.num_lights() > 0)
                                renderer.trace_and_draw_multi(tcfg, analysis_dispatches);
                            renderer.update_display(contribution_look, diagnostic_shot.canvas.aspect());
                            auto metrics = renderer.compute_display_metrics();
                            light_analysis.push_back({
                                source.label,
                                metrics.mean_lum,
                                1.0f - metrics.pct_black,
                                0.0f,
                            });
                            total_mean += metrics.mean_lum;
                        }

                        for (auto& entry : light_analysis)
                            entry.share = (total_mean > 0.0f) ? entry.mean_linear_luma / total_mean : 0.0f;
                        std::sort(light_analysis.begin(), light_analysis.end(), [](const auto& a, const auto& b) {
                            return a.share > b.share;
                        });

                        reload(false);
                        light_analysis_valid = !light_analysis.empty();
                    }
                }

                if (light_analysis_valid && !light_analysis.empty()) {
                    ImGui::Text("Light Contributions (linear share):");
                    for (int i = 0; i < (int)light_analysis.size(); ++i) {
                        const auto& la = light_analysis[i];
                        ImGui::Text("  %s: %.0f%% share, %.0f%% coverage",
                                    la.id.c_str(), la.share * 100.0f, la.coverage_fraction * 100.0f);
                    }
                }
            }

            ImGui::PopID();
        }

        // -- Properties --
        if (ed.selection.size() == 1 &&
            ImGui::CollapsingHeader("Properties", ImGuiTreeNodeFlags_DefaultOpen)) {
            ImGui::PushID("Properties");
            bool changed = false;
            auto& sid = ed.selection[0];

            if (sid.group >= 0) {
                ImGui::TextDisabled("Editing group: %s",
                    ed.shot.scene.groups[sid.group].id.empty() ? "(unnamed)" : ed.shot.scene.groups[sid.group].id.c_str());
                ImGui::Separator();
            }

            auto sync_id_editor = [&](const std::string& current_id) {
                if (!(id_editor.target == sid)) {
                    id_editor.target = sid;
                    id_editor.buffer = current_id;
                }
            };
            auto show_id_editor = [&](const std::string& current_id, auto&& commit) {
                sync_id_editor(current_id);
                std::array<char, 128> id_buf{};
                std::snprintf(id_buf.data(), id_buf.size(), "%s", id_editor.buffer.c_str());
                if (ImGui::InputText("ID", id_buf.data(), id_buf.size())) {
                    id_editor.buffer = id_buf.data();
                }
                if (ImGui::IsItemDeactivatedAfterEdit()
                    && id_editor.buffer != current_id
                    && !id_editor.buffer.empty()
                    && entity_id_available(id_editor.buffer, current_id)) {
                    commit(id_editor.buffer);
                    changed = true;
                }
                if (id_editor.buffer.empty()) {
                    ImGui::TextColored(ImVec4(0.95f, 0.5f, 0.5f, 1.0f), "ID must be non-empty");
                } else if (id_editor.buffer != current_id && !entity_id_available(id_editor.buffer, current_id)) {
                    ImGui::TextColored(ImVec4(0.95f, 0.5f, 0.5f, 1.0f), "ID already in use");
                }
            };
            auto edit_shape_material_binding = [&](Shape& shape) {
                bool local_changed = false;
                std::string& material_id = shape_material_id_mut(shape);
                Material& inline_material = shape_material_mut(shape);
                const char* preview = material_id.empty() ? "(inline custom)" : material_id.c_str();
                if (ImGui::BeginCombo("Material", preview)) {
                    if (ImGui::Selectable("(inline custom)", material_id.empty()) && !material_id.empty()) {
                        detach_shape_material(shape);
                        local_changed = true;
                    }
                    for (const auto& [name, _] : ed.shot.scene.materials) {
                        bool selected = material_id == name;
                        if (ImGui::Selectable(name.c_str(), selected) && material_id != name) {
                            bind_shape_material(shape, name);
                            local_changed = true;
                        }
                    }
                    ImGui::EndCombo();
                }

                if (!material_id.empty()) {
                    ImGui::TextColored(ImVec4(0.5f, 0.8f, 0.5f, 1.0f),
                        "Editing shared material asset '%s'", material_id.c_str());
                    if (ImGui::SmallButton("Detach to Inline")) {
                        detach_shape_material(shape);
                        local_changed = true;
                    }
                    if (auto it = ed.shot.scene.materials.find(material_id); it != ed.shot.scene.materials.end()) {
                        local_changed |= edit_material(it->second);
                    } else {
                        ImGui::TextColored(ImVec4(0.95f, 0.5f, 0.5f, 1.0f),
                            "Missing shared material '%s'", material_id.c_str());
                    }
                } else {
                    ImGui::TextDisabled("Editing inline custom material");
                    local_changed |= edit_material(inline_material);
                }
                return local_changed;
            };

            if (Shape* sp = resolve_shape(ed.shot.scene, sid)) {
                auto& shape = *sp;
                show_id_editor(shape_authored_id(shape), [&](const std::string& new_id) {
                    shape_authored_id_mut(shape) = new_id;
                });
                ImGui::Separator();
                std::visit(overloaded{
                    [&](Circle& c) {
                        changed |= ImGui::DragFloat2("Center", &c.center.x, 0.01f);
                        changed |= ImGui::DragFloat("Radius", &c.radius, 0.005f, 0.01f, 5.0f);
                        changed |= edit_shape_material_binding(shape);
                    },
                    [&](Segment& s) {
                        changed |= ImGui::DragFloat2("Point A", &s.a.x, 0.01f);
                        changed |= ImGui::DragFloat2("Point B", &s.b.x, 0.01f);
                        changed |= edit_shape_material_binding(shape);
                    },
                    [&](Arc& a) {
                        changed |= ImGui::DragFloat2("Center", &a.center.x, 0.01f);
                        changed |= ImGui::DragFloat("Radius", &a.radius, 0.005f, 0.01f, 5.0f);
                        changed |= ImGui::SliderAngle("Start angle", &a.angle_start, 0.0f, 360.0f);
                        changed |= ImGui::SliderAngle("Sweep", &a.sweep, 0.0f, 360.0f);
                        a.angle_start = normalize_angle(a.angle_start);
                        a.sweep = clamp_arc_sweep(a.sweep);
                        changed |= edit_shape_material_binding(shape);
                    },
                    [&](Bezier& b) {
                        changed |= ImGui::DragFloat2("P0", &b.p0.x, 0.01f);
                        changed |= ImGui::DragFloat2("P1 (ctrl)", &b.p1.x, 0.01f);
                        changed |= ImGui::DragFloat2("P2", &b.p2.x, 0.01f);
                        changed |= edit_shape_material_binding(shape);
                    },
                    [&](Polygon& p) {
                        ImGui::Text("Vertices: %d", (int)p.vertices.size());
                        for (int vi = 0; vi < (int)p.vertices.size(); ++vi) {
                            char vlbl[16];
                            std::snprintf(vlbl, sizeof(vlbl), "V%d", vi);
                            changed |= ImGui::DragFloat2(vlbl, &p.vertices[vi].x, 0.01f);
                        }
                        changed |= edit_shape_material_binding(shape);
                    },
                    [&](Ellipse& e) {
                        changed |= ImGui::DragFloat2("Center", &e.center.x, 0.01f);
                        changed |= ImGui::DragFloat("Semi-A", &e.semi_a, 0.005f, 0.01f, 5.0f);
                        changed |= ImGui::DragFloat("Semi-B", &e.semi_b, 0.005f, 0.01f, 5.0f);
                        changed |= ImGui::SliderAngle("Rotation", &e.rotation, -180.0f, 180.0f);
                        changed |= edit_shape_material_binding(shape);
                    },
                }, shape);
            }

            if (Light* lp = resolve_light(ed.shot.scene, sid)) {
                auto& light = *lp;
                show_id_editor(light_authored_id(light), [&](const std::string& new_id) {
                    light_authored_id_mut(light) = new_id;
                });
                ImGui::Separator();
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
                    [&](ParallelBeamLight& l) {
                        changed |= ImGui::DragFloat2("Point A", &l.a.x, 0.01f);
                        changed |= ImGui::DragFloat2("Point B", &l.b.x, 0.01f);
                        changed |= ImGui::DragFloat2("Direction", &l.direction.x, 0.01f);
                        if (l.direction.length_sq() > 1e-6f) l.direction = l.direction.normalized();
                        else l.direction = {1.0f, 0.0f};
                        changed |= ImGui::SliderFloat("Ang. width", &l.angular_width, 0.0f, PI);
                        changed |= ImGui::SliderFloat("Intensity", &l.intensity, 0.01f, 5.0f);
                        edit_wavelength(l.wavelength_min, l.wavelength_max);
                    },
                    [&](SpotLight& l) {
                        changed |= ImGui::DragFloat2("Position", &l.pos.x, 0.01f);
                        changed |= ImGui::DragFloat2("Direction", &l.direction.x, 0.01f);
                        if (l.direction.length_sq() > 1e-6f) l.direction = l.direction.normalized();
                        else l.direction = {1.0f, 0.0f};
                        changed |= ImGui::SliderFloat("Ang. width", &l.angular_width, 0.01f, PI);
                        changed |= ImGui::SliderFloat("Falloff", &l.falloff, 0.0f, 20.0f, "%.1f", ImGuiSliderFlags_Logarithmic);
                        changed |= ImGui::SliderFloat("Intensity", &l.intensity, 0.01f, 5.0f);
                        edit_wavelength(l.wavelength_min, l.wavelength_max);
                    },
                }, light);
            }

            if (sid.type == SelectionRef::Group && sid.index < (int)ed.shot.scene.groups.size()) {
                auto& group = ed.shot.scene.groups[sid.index];
                show_id_editor(group.id, [&](const std::string& new_id) {
                    group.id = new_id;
                });
                ImGui::Separator();
                ImGui::Text("Transform");
                changed |= ImGui::DragFloat2("Translate", &group.transform.translate.x, 0.01f);
                float deg = group.transform.rotate * 180.0f / PI;
                if (ImGui::DragFloat("Rotate", &deg, 0.5f, -360.0f, 360.0f, "%.1f deg")) {
                    group.transform.rotate = deg * PI / 180.0f;
                    changed = true;
                }
                changed |= ImGui::DragFloat2("Scale", &group.transform.scale.x, 0.01f, 0.01f, 100.0f);
                ImGui::Separator();
                int n_shapes = (int)group.shapes.size();
                int n_lights = (int)group.lights.size();
                ImGui::Text("%d shapes, %d lights", n_shapes, n_lights);
            }

            if (changed) {
                if (!ed.prop_editing) {
                    ed.undo.push(ed.shot.scene);
                    ed.prop_editing = true;
                }
                reload();
            }
            if (!ImGui::IsAnyItemActive() && ed.prop_editing) {
                ed.prop_editing = false;
            }
            ImGui::PopID();
        }

        // -- Material Library --
        if (ImGui::CollapsingHeader("Materials", ImGuiTreeNodeFlags_DefaultOpen)) {
            ImGui::PushID("Materials");
            // Material list
            auto& mats = ed.shot.scene.materials;
            if (!material_panel.selected_name.empty() && !mats.contains(material_panel.selected_name)) {
                material_panel.selected_name.clear();
                material_panel.rename_buffer.clear();
            }
            if (mats.empty()) {
                ImGui::TextDisabled("No materials defined");
            } else {
                if (ImGui::BeginCombo("##matlist",
                                      material_panel.selected_name.empty() ? "(select)" : material_panel.selected_name.c_str())) {
                    for (auto& [name, _] : mats) {
                        if (ImGui::Selectable(name.c_str(), name == material_panel.selected_name)) {
                            material_panel.selected_name = name;
                            material_panel.rename_buffer = name;
                        }
                    }
                    ImGui::EndCombo();
                }
            }

            // Edit selected material
            if (!material_panel.selected_name.empty() && mats.contains(material_panel.selected_name)) {
                auto& mat = mats[material_panel.selected_name];
                if (material_panel.rename_buffer.empty())
                    material_panel.rename_buffer = material_panel.selected_name;

                std::array<char, 128> rename_buf{};
                std::snprintf(rename_buf.data(), rename_buf.size(), "%s", material_panel.rename_buffer.c_str());
                if (ImGui::InputText("Rename", rename_buf.data(), rename_buf.size()))
                    material_panel.rename_buffer = rename_buf.data();

                if (!material_panel.rename_buffer.empty()
                    && material_panel.rename_buffer != material_panel.selected_name
                    && !material_id_available(material_panel.rename_buffer, material_panel.selected_name)) {
                    ImGui::TextColored(ImVec4(0.95f, 0.5f, 0.5f, 1.0f), "Material ID already in use");
                } else if (material_panel.rename_buffer.empty()) {
                    ImGui::TextColored(ImVec4(0.95f, 0.5f, 0.5f, 1.0f), "Material ID must be non-empty");
                }

                if (ImGui::Button("Rename##mat")
                    && !material_panel.rename_buffer.empty()
                    && material_id_available(material_panel.rename_buffer, material_panel.selected_name)) {
                    ed.undo.push(ed.shot.scene);
                    rename_material_binding(material_panel.selected_name, material_panel.rename_buffer);
                    material_panel.selected_name = material_panel.rename_buffer;
                    reload();
                }

                bool mat_changed = edit_material(mat);
                if (mat_changed) {
                    if (!material_panel.editing) {
                        ed.undo.push(ed.shot.scene);
                        material_panel.editing = true;
                    }
                    reload();
                }

                int bound_count = material_usage_count(ed.shot.scene, material_panel.selected_name);
                ImGui::Text("%d bound shape(s)", bound_count);

                if (ImGui::Button("Apply to Selection")) {
                    Scene before = ed.shot.scene;
                    if (apply_material_to_selection(material_panel.selected_name)) {
                        ed.undo.push(ed.shot.scene);
                        reload();
                    } else {
                        ed.shot.scene = std::move(before);
                    }
                }
                ImGui::SameLine();
                if (ImGui::Button("Detach Selection")) {
                    Scene before = ed.shot.scene;
                    if (detach_material_from_selection(material_panel.selected_name)) {
                        ed.undo.push(ed.shot.scene);
                        reload();
                    } else {
                        ed.shot.scene = std::move(before);
                    }
                }
                ImGui::SameLine();
                if (ImGui::Button("Delete##mat")) {
                    ed.undo.push(ed.shot.scene);
                    delete_material(ed.shot.scene, material_panel.selected_name);
                    detach_clipboard_material_binding(material_panel.selected_name);
                    material_panel.selected_name.clear();
                    material_panel.rename_buffer.clear();
                    reload();
                }
                if (bound_count > 0) {
                    ImGui::TextDisabled("Delete detaches bound shapes to inline materials");
                }
            }

            ImGui::Separator();

            // Create new material
            ImGui::InputText("Name##newmat", material_panel.new_name.data(), material_panel.new_name.size());
            ImGui::SameLine();
            if (ImGui::Button("Add") && material_panel.new_name[0] != '\0' && !mats.count(material_panel.new_name.data())) {
                ed.undo.push(ed.shot.scene);
                mats[material_panel.new_name.data()] = Material{};
                material_panel.selected_name = material_panel.new_name.data();
                material_panel.rename_buffer = material_panel.new_name.data();
                material_panel.new_name[0] = '\0';
                reload();
            }

            // Presets
            auto preset_btn = [&](const char* label, Material mat) {
                if (ImGui::SmallButton(label)) {
                    std::string name = label;
                    // Avoid collision
                    if (mats.count(name)) { int n = 2; while (mats.count(name + " " + std::to_string(n))) ++n; name += " " + std::to_string(n); }
                    ed.undo.push(ed.shot.scene);
                    mats[name] = mat;
                    material_panel.selected_name = name;
                    material_panel.rename_buffer = name;
                    reload();
                }
            };
            preset_btn("Glass", mat_glass(1.5f, 20000.0f));
            ImGui::SameLine();
            preset_btn("Mirror", mat_opaque_mirror(0.95f));
            ImGui::SameLine();
            preset_btn("Diffuse", mat_diffuse(0.8f));
            ImGui::SameLine();
            preset_btn("Absorber", mat_absorber());

            if (!ImGui::IsAnyItemActive() && material_panel.editing)
                material_panel.editing = false;

            ImGui::PopID();
        }

        // -- Tracer --
        if (ImGui::CollapsingHeader("Tracer", ImGuiTreeNodeFlags_DefaultOpen)) {
            ImGui::PushID("Tracer");
            ImGui::SliderInt("Batch", &ed.shot.trace.batch, 1000, 1000000, "%d",
                             ImGuiSliderFlags_Logarithmic);
            ImGui::SliderInt("Max depth", &ed.shot.trace.depth, 1, 30);
            ImGui::SliderFloat("Intensity", &ed.shot.trace.intensity, 0.001f, 10.0f, "%.3f",
                               ImGuiSliderFlags_Logarithmic);
            ImGui::Checkbox("Paused", &paused);
            ImGui::PopID();
        }

        // -- Display --
        if (ImGui::CollapsingHeader("Display", ImGuiTreeNodeFlags_DefaultOpen)) {
            ImGui::PushID("Display");

            // Look presets
            static const struct { const char* name; float exp; float contrast; float gamma;
                                  ToneMap tm; float wp; NormalizeMode norm; float ambient; } look_presets[] = {
                {"Default",      -5.0f, 1.0f, 2.0f, ToneMap::ReinhardExtended, 0.5f, NormalizeMode::Rays, 0.0f},
                {"Bright",        4.0f, 1.1f, 2.2f, ToneMap::ACES,             1.5f, NormalizeMode::Rays, 0.0f},
                {"Dark/Moody",    1.0f, 1.3f, 2.4f, ToneMap::ACES,             0.8f, NormalizeMode::Rays, 0.0f},
                {"Linear",        0.0f, 1.0f, 1.0f, ToneMap::None,             1.0f, NormalizeMode::Max,  0.0f},
                {"High Contrast", 3.0f, 1.5f, 2.2f, ToneMap::ReinhardExtended, 2.0f, NormalizeMode::Rays, 0.0f},
                {"Soft",          2.5f, 0.8f, 2.0f, ToneMap::Reinhard,         1.0f, NormalizeMode::Rays, 0.02f},
            };
            if (ImGui::BeginCombo("Preset", "(select)")) {
                for (auto& p : look_presets) {
                    if (ImGui::Selectable(p.name)) {
                        ed.shot.look.exposure = p.exp;
                        ed.shot.look.contrast = p.contrast;
                        ed.shot.look.gamma = p.gamma;
                        ed.shot.look.tone_map = p.tm;
                        ed.shot.look.white_point = p.wp;
                        ed.shot.look.normalize = p.norm;
                        ed.shot.look.ambient = p.ambient;
                        ed.shot.look.saturation = 1.0f;
                        ed.shot.look.vignette = 0.0f;
                        ed.shot.look.vignette_radius = 0.7f;
                        // Preserve scene-specific: normalize_ref, normalize_pct, background, opacity
                    }
                }
                ImGui::EndCombo();
            }

            // Full-shot A/B comparison
            if (showing_snapshot_a)
                ImGui::BeginDisabled();
            if (ImGui::Button("Snapshot A")) {
                std::vector<uint8_t> snapshot_rgba;
                renderer.read_display_rgba(snapshot_rgba);
                compare_ab.shot = ed.shot;
                ensure_scene_entity_ids(compare_ab.shot.scene);
                sync_material_bindings(compare_ab.shot.scene);
                compare_ab.view_bounds = current_display_view();
                compare_ab.metrics = renderer.compute_frame_metrics();
                compare_ab.metrics_valid = true;
                upload_compare_snapshot(snapshot_rgba, fb_w, fb_h);
                compare_ab.active = true;
                compare_ab.showing_a = false;
                force_live_metrics_refresh = true;
            }
            if (showing_snapshot_a)
                ImGui::EndDisabled();
            if (compare_ab.active) {
                ImGui::SameLine();
                if (ImGui::Button(compare_ab.showing_a ? "Show B (live)" : "Show A")) {
                    compare_ab.showing_a = !compare_ab.showing_a;
                    if (!compare_ab.showing_a)
                        reload(false);
                    force_live_metrics_refresh = true;
                }
                ImGui::SameLine();
                if (ImGui::Button("Clear A/B")) {
                    bool was_showing_a = compare_ab.showing_a;
                    destroy_compare_snapshot();
                    compare_ab.active = false;
                    compare_ab.showing_a = false;
                    compare_ab.metrics_valid = false;
                    if (was_showing_a)
                        reload(false);
                    force_live_metrics_refresh = true;
                }
                if (compare_ab.showing_a) {
                    ImGui::TextColored(ImVec4(1, 0.7f, 0.3f, 1),
                                       "Showing: A (frozen snapshot, snapshot framing)");
                } else {
                    ImGui::TextDisabled("Snapshot A is available for frozen-image comparison");
                }
                ImGui::TextDisabled("Comparison framing is locked to Snapshot A while A/B is active.");
            }

            ImGui::SliderFloat("Exposure", &ed.shot.look.exposure, -15.0f, 15.0f);
            ImGui::SliderFloat("Contrast", &ed.shot.look.contrast, 0.1f, 3.0f);
            ImGui::SliderFloat("Gamma", &ed.shot.look.gamma, 0.5f, 4.0f);
            ImGui::SliderFloat("White point", &ed.shot.look.white_point, 0.1f, 10.0f);
            const char* tone_names[] = {"None", "Reinhard", "Reinhard Ext", "ACES", "Logarithmic"};
            int tm = (int)ed.shot.look.tone_map;
            if (ImGui::Combo("Tone map", &tm, tone_names, 5))
                ed.shot.look.tone_map = (ToneMap)tm;
            const char* norm_names[] = {"Auto (Max)", "Ray Count", "Fixed Ref", "Off"};
            int nm = (int)ed.shot.look.normalize;
            if (ImGui::Combo("Normalize", &nm, norm_names, 4))
                ed.shot.look.normalize = (NormalizeMode)nm;
            if (ed.shot.look.normalize == NormalizeMode::Max) {
                ImGui::SliderFloat("Percentile", &ed.shot.look.normalize_pct, 0.9f, 1.0f, "%.3f");
            }
            if (ed.shot.look.normalize == NormalizeMode::Fixed) {
                ImGui::SliderFloat("Ref value", &ed.shot.look.normalize_ref, 1.0f, 1000000.0f,
                                   "%.0f", ImGuiSliderFlags_Logarithmic);
                if (ImGui::Button("Capture Ref")) {
                    ed.shot.look.normalize_ref = renderer.compute_current_max();
                }
            }
            ImGui::Separator();
            ImGui::SliderFloat("Ambient", &ed.shot.look.ambient, 0.0f, 0.5f, "%.3f");
            ImGui::ColorEdit3("Background", ed.shot.look.background,
                              ImGuiColorEditFlags_Float | ImGuiColorEditFlags_HDR);
            ImGui::SliderFloat("Opacity", &ed.shot.look.opacity, 0.0f, 1.0f);
            ImGui::Separator();
            ImGui::SliderFloat("Saturation", &ed.shot.look.saturation, 0.0f, 3.0f);
            ImGui::SliderFloat("Vignette", &ed.shot.look.vignette, 0.0f, 1.0f);
            if (ed.shot.look.vignette > 0.0f)
                ImGui::SliderFloat("Vignette Radius", &ed.shot.look.vignette_radius, 0.3f, 1.5f);
            ImGui::PopID();
        }

        // -- Output --
        if (ImGui::CollapsingHeader("Output", ImGuiTreeNodeFlags_DefaultOpen)) {
            ImGui::PushID("Output");
            char ray_str[32];
            int64_t tr = renderer.total_rays();
            const Shot& output_shot = current_authored_shot();
            const Look& output_look = output_shot.look;
            if (tr >= 1'000'000)
                std::snprintf(ray_str, sizeof(ray_str), "%.1fM", tr / 1e6);
            else if (tr >= 1'000)
                std::snprintf(ray_str, sizeof(ray_str), "%.1fK", tr / 1e3);
            else
                std::snprintf(ray_str, sizeof(ray_str), "%lld", (long long)tr);
            ImGui::Text("Rays: %s", ray_str);
            if (!showing_snapshot_a && output_look.normalize == NormalizeMode::Max)
                ImGui::Text("Max HDR: %.2f", renderer.last_max());
            else
                ImGui::TextDisabled("Max HDR: —");
            ImGui::Text("%.1f FPS (%.1f ms)", 1000.0f / frame_ms, frame_ms);
            ImGui::Text("Zoom: %.0f%%", ed.camera.zoom / std::min((float)win_w / std::max(ed.scene_bounds.max.x - ed.scene_bounds.min.x, 0.01f), (float)win_h / std::max(ed.scene_bounds.max.y - ed.scene_bounds.min.y, 0.01f)) * 100.0f);

            if (ImGui::Button("Clear")) {
                renderer.clear();
            }
            ImGui::SameLine();
            if (ImGui::Button("Export PNG")) {
                std::string filename = output_shot.name + ".png";
                if (export_authored_png(output_shot))
                    std::cerr << "Exported: " << filename << "\n";
            }
            ImGui::PopID();
        }

        // -- Stats --
        if (ImGui::CollapsingHeader("Stats")) {
            ImGui::PushID("Stats");

            // Histogram
            float hist_f[256];
            float hist_max = 0;
            for (int i = 0; i < 256; ++i) {
                hist_f[i] = (float)live_metrics.histogram[i];
                if (hist_f[i] > hist_max) hist_max = hist_f[i];
            }
            ImGui::PlotHistogram("##lum_hist", hist_f, 256, 0, nullptr, 0, hist_max,
                                 ImVec2(-1, 60.0f * dpi_scale));

            ImGui::Text("Mean: %.1f  Median: %.0f  P95: %.0f",
                        live_metrics.mean_lum, live_metrics.p50, live_metrics.p95);
            ImGui::Text("Black: %.1f%%  Clipped: %.1f%%",
                        live_metrics.pct_black * 100, live_metrics.pct_clipped * 100);
            if (compare_ab.metrics_valid) {
                ImGui::Separator();
                ImGui::Text("Snapshot A: mean %.1f  black %.1f%%  clipped %.1f%%",
                            compare_ab.metrics.mean_lum,
                            compare_ab.metrics.pct_black * 100.0f,
                            compare_ab.metrics.pct_clipped * 100.0f);
                ImGui::Text("Delta vs A: mean %+.1f  black %+.1f%%  clipped %+.1f%%",
                            live_metrics.mean_lum - compare_ab.metrics.mean_lum,
                            (live_metrics.pct_black - compare_ab.metrics.pct_black) * 100.0f,
                            (live_metrics.pct_clipped - compare_ab.metrics.pct_clipped) * 100.0f);
            }
            ImGui::PopID();
        }

        ImGui::End(); // Controls

        // ── Keyboard shortcuts ──────────────────────────────────────────

        if (!io.WantCaptureKeyboard) {
            // --- Modal transform input ---
            if (ed.transform.active()) {
                // Axis constraints
                if (ImGui::IsKeyPressed(ImGuiKey_X)) {
                    ed.transform.lock_x = !ed.transform.lock_x;
                    ed.transform.lock_y = false;
                }
                if (ImGui::IsKeyPressed(ImGuiKey_Y)) {
                    ed.transform.lock_y = !ed.transform.lock_y;
                    ed.transform.lock_x = false;
                }

                // Numeric input
                for (int k = ImGuiKey_0; k <= ImGuiKey_9; ++k) {
                    if (ImGui::IsKeyPressed((ImGuiKey)k))
                        ed.transform.numeric_buf += ('0' + (k - ImGuiKey_0));
                }
                if (ImGui::IsKeyPressed(ImGuiKey_Period))
                    ed.transform.numeric_buf += '.';
                if (ImGui::IsKeyPressed(ImGuiKey_Minus))
                    ed.transform.numeric_buf += '-';
                if (ImGui::IsKeyPressed(ImGuiKey_Backspace) && !ed.transform.numeric_buf.empty())
                    ed.transform.numeric_buf.pop_back();

                // Live-apply transform every frame for real-time re-tracing
                for (auto& sid : ed.selection) {
                    if (Shape* live = resolve_shape(ed.shot.scene, sid)) {
                        if (const Shape* snap = resolve_shape(ed.transform.snapshot, sid))
                            apply_transform_shape(*live, *snap, ed.transform, mw, io.KeyShift);
                    } else if (Light* live = resolve_light(ed.shot.scene, sid)) {
                        if (const Light* snap = resolve_light(ed.transform.snapshot, sid))
                            apply_transform_light(*live, *snap, ed.transform, mw, io.KeyShift);
                    } else if (sid.type == SelectionRef::Group && sid.index < (int)ed.shot.scene.groups.size()
                               && sid.index < (int)ed.transform.snapshot.groups.size()) {
                        apply_transform_group(ed.shot.scene.groups[sid.index],
                            ed.transform.snapshot.groups[sid.index], ed.transform, mw, io.KeyShift);
                    }
                }
                reload();

                // Confirm
                if (ImGui::IsKeyPressed(ImGuiKey_Enter) || ImGui::IsMouseClicked(0)) {
                    ed.transform.type = TransformMode::None;
                    ed.transform.snapshot = {};
                }

                // Cancel
                if (ImGui::IsKeyPressed(ImGuiKey_Escape) || ImGui::IsMouseClicked(1)) {
                    ed.shot.scene = ed.transform.snapshot;
                    ed.transform.type = TransformMode::None;
                    ed.transform.snapshot = {};
                    reload();
                }
            } else {
                // --- Global shortcuts ---

                // Undo/Redo
                if (io.KeyCtrl && io.KeyShift && ImGui::IsKeyPressed(ImGuiKey_Z)) {
                    if (ed.undo.redo(ed.shot.scene)) { ed.validate_selection(); reload(); }
                } else if (io.KeyCtrl && ImGui::IsKeyPressed(ImGuiKey_Z)) {
                    if (ed.undo.undo(ed.shot.scene)) { ed.validate_selection(); reload(); }
                }

                // Exposure nudge: [ / ]
                if (ImGui::IsKeyPressed(ImGuiKey_LeftBracket)) ed.shot.look.exposure -= 0.5f;
                if (ImGui::IsKeyPressed(ImGuiKey_RightBracket)) ed.shot.look.exposure += 0.5f;

                // A/B look toggle: ` (grave accent)
                if (ImGui::IsKeyPressed(ImGuiKey_GraveAccent) && compare_ab.active) {
                    compare_ab.showing_a = !compare_ab.showing_a;
                    if (!compare_ab.showing_a)
                        reload(false);
                    force_live_metrics_refresh = true;
                }

                // Save/Load
                if (io.KeyCtrl && ImGui::IsKeyPressed(ImGuiKey_S)) { do_save(); }
                if (io.KeyCtrl && ImGui::IsKeyPressed(ImGuiKey_O)) {
                    open_load_popup = true;
                }

                // Select all
                if (io.KeyCtrl && ImGui::IsKeyPressed(ImGuiKey_A)) {
                    ed.select_all();
                }

                // Group / Ungroup
                if (io.KeyCtrl && io.KeyShift && ImGui::IsKeyPressed(ImGuiKey_G)) {
                    // Ungroup selected groups
                    bool any_ungrouped = false;
                    for (auto& sid : ed.selection) {
                        if (sid.type == SelectionRef::Group && sid.index < (int)ed.shot.scene.groups.size()) {
                            any_ungrouped = true;
                            break;
                        }
                    }
                    if (any_ungrouped) {
                        ed.undo.push(ed.shot.scene);
                        std::vector<SelectionRef> new_sel;
                        // Collect group indices to remove (reverse order)
                        std::vector<int> to_remove;
                        for (auto& sid : ed.selection) {
                            if (sid.type != SelectionRef::Group) continue;
                            if (sid.index >= (int)ed.shot.scene.groups.size()) continue;
                            auto& group = ed.shot.scene.groups[sid.index];
                            // Bake transform into shapes/lights and add to scene
                            for (auto& s : group.shapes) {
                                Shape ws = transform_shape(s, group.transform);
                                ed.shot.scene.shapes.push_back(ws);
                                new_sel.push_back({SelectionRef::Shape, (int)ed.shot.scene.shapes.size() - 1});
                            }
                            for (auto& l : group.lights) {
                                Light wl = transform_light(l, group.transform);
                                ed.shot.scene.lights.push_back(wl);
                                new_sel.push_back({SelectionRef::Light, (int)ed.shot.scene.lights.size() - 1});
                            }
                            to_remove.push_back(sid.index);
                        }
                        // Remove groups in reverse order
                        std::sort(to_remove.rbegin(), to_remove.rend());
                        for (int idx : to_remove)
                            ed.shot.scene.groups.erase(ed.shot.scene.groups.begin() + idx);
                        ed.selection = new_sel;
                        ed.validate_selection();
                        reload();
                    }
                } else if (io.KeyCtrl && ImGui::IsKeyPressed(ImGuiKey_G)) {
                    // Group selected ungrouped shapes/lights
                    // Only group if 2+ ungrouped objects selected and no groups in selection
                    int n_ungrouped = 0;
                    bool has_groups = false;
                    for (auto& sid : ed.selection) {
                        if (sid.type == SelectionRef::Group || sid.group >= 0) has_groups = true;
                        else n_ungrouped++;
                    }
                    if (n_ungrouped >= 2 && !has_groups) {
                        ed.undo.push(ed.shot.scene);
                        // Compute centroid
                        Vec2 centroid = ed.selection_centroid();
                        Group group;
                        group.id = next_scene_entity_id(ed.shot.scene, "group");
                        group.transform.translate = centroid;

                        // Collect shapes/lights, converting to local coords
                        std::vector<int> shape_indices, light_indices;
                        for (auto& sid : ed.selection) {
                            if (sid.type == SelectionRef::Shape && sid.index < (int)ed.shot.scene.shapes.size()) {
                                Shape s = ed.shot.scene.shapes[sid.index];
                                translate_shape(s, Vec2{0, 0} - centroid);
                                group.shapes.push_back(s);
                                shape_indices.push_back(sid.index);
                            } else if (sid.type == SelectionRef::Light && sid.index < (int)ed.shot.scene.lights.size()) {
                                Light l = ed.shot.scene.lights[sid.index];
                                translate_light(l, Vec2{0, 0} - centroid);
                                group.lights.push_back(l);
                                light_indices.push_back(sid.index);
                            }
                        }

                        // Remove originals (reverse order to preserve indices)
                        std::sort(shape_indices.rbegin(), shape_indices.rend());
                        std::sort(light_indices.rbegin(), light_indices.rend());
                        for (int idx : light_indices)
                            ed.shot.scene.lights.erase(ed.shot.scene.lights.begin() + idx);
                        for (int idx : shape_indices)
                            ed.shot.scene.shapes.erase(ed.shot.scene.shapes.begin() + idx);

                        ed.shot.scene.groups.push_back(std::move(group));
                        ed.clear_selection();
                        ed.select({SelectionRef::Group, (int)ed.shot.scene.groups.size() - 1});
                        reload();
                    }
                }

                // Copy/Paste/Cut/Duplicate
                if (io.KeyCtrl && ImGui::IsKeyPressed(ImGuiKey_C)) {
                    copy_to_clipboard();
                }

                if (io.KeyCtrl && ImGui::IsKeyPressed(ImGuiKey_V) && !ed.clipboard.empty()) {
                    ed.undo.push(ed.shot.scene);
                    Vec2 offset = mw - ed.clipboard.centroid;
                    sanitize_clipboard_material_bindings();
                    ed.clear_selection();
                    for (auto s : ed.clipboard.shapes) {
                        translate_shape(s, offset);
                        ed.shot.scene.shapes.push_back(s);
                        ed.select({SelectionRef::Shape, (int)ed.shot.scene.shapes.size() - 1});
                    }
                    for (auto l : ed.clipboard.lights) {
                        translate_light(l, offset);
                        ed.shot.scene.lights.push_back(l);
                        ed.select({SelectionRef::Light, (int)ed.shot.scene.lights.size() - 1});
                    }
                    for (auto g : ed.clipboard.groups) {
                        translate_group(g, offset);
                        ed.shot.scene.groups.push_back(g);
                        ed.select({SelectionRef::Group, (int)ed.shot.scene.groups.size() - 1});
                    }
                    reload();
                }

                if (io.KeyCtrl && ImGui::IsKeyPressed(ImGuiKey_X)) {
                    copy_to_clipboard();
                    delete_selected();
                }

                if (io.KeyCtrl && ImGui::IsKeyPressed(ImGuiKey_D) && !ed.selection.empty()) {
                    // Duplicate: copy in place with small offset, then enter grab
                    ed.undo.push(ed.shot.scene);
                    std::vector<SelectionRef> new_sel;
                    Vec2 offset{0.05f, 0.05f};
                    for (auto& sid : ed.selection) {
                        if (const Shape* shape = resolve_shape(ed.shot.scene, sid)) {
                            Shape s = *shape;
                            translate_shape(s, offset);
                            ed.shot.scene.shapes.push_back(s);
                            new_sel.push_back({SelectionRef::Shape, (int)ed.shot.scene.shapes.size() - 1});
                        } else if (const Light* light = resolve_light(ed.shot.scene, sid)) {
                            Light l = *light;
                            translate_light(l, offset);
                            ed.shot.scene.lights.push_back(l);
                            new_sel.push_back({SelectionRef::Light, (int)ed.shot.scene.lights.size() - 1});
                        } else if (sid.type == SelectionRef::Group) {
                            Group g = ed.shot.scene.groups[sid.index];
                            translate_group(g, offset);
                            ed.shot.scene.groups.push_back(g);
                            new_sel.push_back({SelectionRef::Group, (int)ed.shot.scene.groups.size() - 1});
                        }
                    }
                    ed.selection = new_sel;

                    // Enter grab mode
                    ed.transform.type = TransformMode::Grab;
                    ed.transform.pivot = ed.selection_centroid();
                    ed.transform.mouse_start = mw;
                    ed.transform.lock_x = ed.transform.lock_y = false;
                    ed.transform.numeric_buf.clear();
                    ed.transform.snapshot = ed.shot.scene;
                    reload();
                }

                // Transform shortcuts (G/R/S)
                if (!ed.selection.empty()) {
                    auto start_transform = [&](TransformMode::Type type) {
                        ed.transform.type = type;
                        ed.transform.pivot = ed.selection_centroid();
                        ed.transform.mouse_start = mw;
                        ed.transform.lock_x = ed.transform.lock_y = false;
                        ed.transform.numeric_buf.clear();
                        ed.transform.snapshot = ed.shot.scene;
                        ed.undo.push(ed.shot.scene);
                    };

                    if (ImGui::IsKeyPressed(ImGuiKey_G)) start_transform(TransformMode::Grab);
                    if (ImGui::IsKeyPressed(ImGuiKey_R)) start_transform(TransformMode::Rotate);
                    if (ImGui::IsKeyPressed(ImGuiKey_S) && !io.KeyCtrl) start_transform(TransformMode::Scale);
                }

                // Tool switching
                if (!io.KeyCtrl && !io.KeyAlt) {
                    auto switch_tool = [&](EditTool t) {
                        if (ed.tool == EditTool::Measure) ed.measure_active = false;
                        ed.tool = t;
                    };
                    if (ImGui::IsKeyPressed(ImGuiKey_Q)) switch_tool(EditTool::Select);
                    if (ImGui::IsKeyPressed(ImGuiKey_C)) switch_tool(EditTool::Circle);
                    if (ImGui::IsKeyPressed(ImGuiKey_L)) switch_tool(EditTool::Segment);
                    if (ImGui::IsKeyPressed(ImGuiKey_A) && !io.KeyCtrl) switch_tool(EditTool::Arc);
                    if (ImGui::IsKeyPressed(ImGuiKey_B)) switch_tool(EditTool::Bezier);
                    if (ImGui::IsKeyPressed(ImGuiKey_E)) switch_tool(EditTool::Ellipse);
                    if (ImGui::IsKeyPressed(ImGuiKey_X) && !ed.transform.active()) switch_tool(EditTool::Erase);
                    if (ImGui::IsKeyPressed(ImGuiKey_P)) switch_tool(EditTool::PointLight);
                    if (ImGui::IsKeyPressed(ImGuiKey_T)) switch_tool(EditTool::SegmentLight);
                    if (ImGui::IsKeyPressed(ImGuiKey_W)) switch_tool(EditTool::BeamLight);
                    if (ImGui::IsKeyPressed(ImGuiKey_M)) switch_tool(EditTool::Measure);
                }

                // Visibility: H = toggle selected, Alt+H = show all
                if (ImGui::IsKeyPressed(ImGuiKey_H)) {
                    if (io.KeyAlt) {
                        ed.show_all();
                    } else {
                        for (auto& sid : ed.selection) {
                            if (sid.type == SelectionRef::Shape) ed.toggle_shape_visibility(sid.index);
                            else if (sid.type == SelectionRef::Light) ed.toggle_light_visibility(sid.index);
                            else if (sid.type == SelectionRef::Group) ed.toggle_group_visibility(sid.index);
                        }
                    }
                    reload();
                }

                // Fit to view
                if (!compare_ab.active && ImGui::IsKeyPressed(ImGuiKey_F)) {
                    if (!ed.selection.empty()) {
                        Bounds sb = ed.selection_bounds();
                        Vec2 sz = sb.max - sb.min;
                        Vec2 scene_sz = ed.scene_bounds.max - ed.scene_bounds.min;
                        float min_pad = std::max(scene_sz.x, scene_sz.y) * 0.2f;
                        float pad = std::max(std::max(sz.x, sz.y) * 0.2f, min_pad);
                        sb.min = sb.min - Vec2{pad, pad};
                        sb.max = sb.max + Vec2{pad, pad};
                        ed.camera.fit(sb, (float)win_w, (float)win_h);
                    } else {
                        ed.camera.fit(ed.scene_bounds, (float)win_w, (float)win_h);
                    }
                    renderer.update_viewport(ed.camera.visible_bounds((float)win_w, (float)win_h));
                    renderer.clear();
                }
                if (!compare_ab.active && ImGui::IsKeyPressed(ImGuiKey_Home)) {
                    ed.camera.fit(ed.scene_bounds, (float)win_w, (float)win_h);
                    renderer.update_viewport(ed.camera.visible_bounds((float)win_w, (float)win_h));
                    renderer.clear();
                }

                // Space: pause
                if (ImGui::IsKeyPressed(ImGuiKey_Space)) paused = !paused;

                // Escape cascade
                if (ImGui::IsKeyPressed(ImGuiKey_Escape)) {
                    if (ed.tool == EditTool::Measure && ed.measure_active) {
                        ed.measure_active = false;
                    } else if (ed.creating) {
                        ed.creating = false;
                    } else if (ed.editing_group >= 0) {
                        ed.editing_group = -1;
                        ed.clear_selection();
                    } else if (!ed.selection.empty()) {
                        ed.clear_selection();
                    } else {
                        ed.tool = EditTool::Select;
                    }
                }

                // Delete
                if (ImGui::IsKeyPressed(ImGuiKey_Delete) || ImGui::IsKeyPressed(ImGuiKey_Backspace)) {
                    delete_selected();
                }
            }
        }

        // ── Update window title (only when changed) ────────────────────

        {
            static std::string last_title;
            char title[256];
            std::snprintf(title, sizeof(title), "lpt2d \xe2\x80\x94 %s%s",
                ed.shot.name.empty() ? "untitled" : ed.shot.name.c_str(),
                ed.dirty ? " *" : "");
            if (last_title != title) { glfwSetWindowTitle(window, title); last_title = title; }
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
    destroy_compare_snapshot();
    renderer.shutdown();
    glfwDestroyWindow(window);
    glfwTerminate();
    return 0;
}
