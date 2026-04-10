#include "app_actions.h"

#include "export.h"
#include "geometry.h"
#include "serialize.h"

#include <algorithm>
#include <iostream>
#include <utility>
#include <variant>

// ─── Render filter snapshot ──────────────────────────────────────────

RenderFilterState capture_render_filters(const EditorState& ed) {
    return {
        ed.visibility.hidden_shapes,
        ed.visibility.hidden_lights,
        ed.visibility.hidden_groups,
        ed.visibility.solo_light_id,
        ed.visibility.solo_light_group_id,
    };
}

// ─── Compare A/B snapshot ────────────────────────────────────────────

void destroy_compare_snapshot(CompareSnapshot& snap) {
    if (snap.texture) {
        glDeleteTextures(1, &snap.texture);
        snap.texture = 0;
    }
    snap.frame = 0;
    snap.texture_width = 0;
    snap.texture_height = 0;
}

void upload_compare_snapshot(CompareSnapshot& snap, const std::vector<uint8_t>& rgba, int tex_w, int tex_h) {
    if (!snap.texture)
        glGenTextures(1, &snap.texture);
    glBindTexture(GL_TEXTURE_2D, snap.texture);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);
    glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA8, tex_w, tex_h, 0, GL_RGBA, GL_UNSIGNED_BYTE, rgba.data());
    glBindTexture(GL_TEXTURE_2D, 0);
    snap.texture_width = tex_w;
    snap.texture_height = tex_h;
}

// ─── Scene building / filtering ─────────────────────────────────────

Bounds scene_default_bounds(const Scene& scene) {
    if (scene.shapes.empty() && scene.lights.empty() && scene.groups.empty())
        return {{-1, -1}, {1, 1}};
    return compute_bounds(scene);
}

namespace {

bool shape_visible(const RenderFilterState& filters, const std::string& id) {
    return !filters.hidden_shapes.contains(id);
}

bool light_visible(const RenderFilterState& filters, const std::string& id) {
    return !filters.hidden_lights.contains(id);
}

bool group_visible(const RenderFilterState& filters, const std::string& id) {
    return !filters.hidden_groups.contains(id);
}

} // namespace

Scene build_render_scene_for(const Shot& shot, const RenderFilterState& filters) {
    Scene filtered;
    filtered.materials = shot.scene.materials;
    auto assign_emissionless_material = [&](Shape& shape) {
        Material mat = resolve_shape_material(shape, shot.scene.materials);
        if (mat.emission <= 0.0f)
            return;
        mat.emission = 0.0f;
        std::string material_id = next_scene_material_id(filtered, "Material");
        filtered.materials[material_id] = mat;
        shape_material_id(shape) = std::move(material_id);
    };
    auto strip_shape_emission = [&](Shape shape) -> Shape {
        assign_emissionless_material(shape);
        return shape;
    };
    bool any_solo = !filters.solo_light_id.empty();
    for (const auto& s : shot.scene.shapes)
        if (shape_visible(filters, shape_id(s)))
            filtered.shapes.push_back(any_solo ? strip_shape_emission(s) : s);
    if (any_solo && filters.solo_light_group_id.empty()) {
        if (const Light* sl = find_light_in(shot.scene.lights, filters.solo_light_id))
            filtered.lights.push_back(*sl);
    } else if (any_solo) {
        // Group solo: strip all top-level lights
    } else {
        for (const auto& l : shot.scene.lights)
            if (light_visible(filters, light_id(l)))
                filtered.lights.push_back(l);
    }
    for (const auto& group : shot.scene.groups) {
        if (!group_visible(filters, group.id)) continue;
        if (any_solo) {
            Group g = group;
            for (auto& shape : g.shapes)
                shape = strip_shape_emission(shape);
            if (filters.solo_light_group_id == group.id && !filters.solo_light_id.empty()) {
                if (const Light* sl = find_light_in(group.lights, filters.solo_light_id)) {
                    g.lights.clear();
                    g.lights.push_back(*sl);
                } else {
                    g.lights.clear();
                }
            } else {
                g.lights.clear();
            }
            filtered.groups.push_back(std::move(g));
        } else {
            filtered.groups.push_back(group);
        }
    }
    return filtered;
}

EditorCamera current_display_camera(const EditorState& ed, const CompareSnapshot& compare_ab, int win_w, int win_h) {
    if (!compare_ab.active)
        return ed.view.camera;
    EditorCamera comparison_camera;
    comparison_camera.fit(compare_ab.view_bounds, (float)win_w, (float)win_h);
    return comparison_camera;
}

Bounds current_display_view(const EditorState& ed, const CompareSnapshot& compare_ab, int win_w, int win_h) {
    if (compare_ab.active)
        return compare_ab.view_bounds;
    EditorCamera display_camera = current_display_camera(ed, compare_ab, win_w, win_h);
    return display_camera.visible_bounds((float)win_w, (float)win_h);
}

// ─── Scene actions ──────────────────────────────────────────────────

void reload_scene(EditorState& ed, Renderer& renderer, const CompareSnapshot& compare_ab,
                  bool& light_analysis_valid,
                  int win_w, int win_h, bool mark_dirty) {
    ensure_scene_entity_ids(ed.shot.scene);

    ed.view.scene_bounds = scene_default_bounds(ed.shot.scene);
    Bounds view = current_display_view(ed, compare_ab, win_w, win_h);
    auto render_scene = build_render_scene_for(ed.shot, capture_render_filters(ed));
    renderer.upload_scene(render_scene, view);
    renderer.upload_fills(render_scene, view);
    renderer.clear();
    if (mark_dirty)
        ed.session.dirty = true;
    light_analysis_valid = false;
}

bool export_authored_png(const Shot& source_shot, int frame) {
    Shot output_shot = source_shot;
    ensure_scene_entity_ids(output_shot.scene);

    Renderer export_renderer;
    if (!export_renderer.init(output_shot.canvas.width, output_shot.canvas.height))
        return false;

    Bounds scene_bounds = scene_default_bounds(output_shot.scene);
    Bounds bounds = output_shot.camera.resolve(output_shot.canvas.aspect(), scene_bounds);
    export_renderer.upload_scene(output_shot.scene, bounds);
    export_renderer.upload_fills(output_shot.scene, bounds);
    export_renderer.clear();

    TraceConfig tcfg = output_shot.trace.to_trace_config(frame);
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
    export_renderer.read_pixels(pixels, output_shot.look.to_post_process(), output_shot.canvas.aspect());
    std::string filename = output_shot.name + ".png";
    return export_png(filename, pixels.data(), output_shot.canvas.width, output_shot.canvas.height);
}

bool try_load_scene(EditorState& ed, Renderer& renderer, CompareSnapshot& compare_ab,
                    bool& light_analysis_valid,
                    int win_w, int win_h,
                    const std::string& path, std::string* error) {
    std::string local_error;
    auto loaded = try_load_shot_json(path, &local_error);
    if (!loaded) {
        if (error) *error = local_error.empty() ? "Failed to load scene" : local_error;
        return false;
    }
    ed.shot = *loaded;
    ed.shot.trace.batch = kGuiTraceBatch;
    ed.session.save_path = path;
    reset_editor(ed, renderer, compare_ab, light_analysis_valid, win_w, win_h);
    return true;
}

bool do_save_to(EditorState& ed, const std::string& path, std::string* error) {
    Shot saved = ed.shot;
    saved.trace.batch = TraceDefaults{}.batch;
    std::string norm_error;
    if (!normalize_scene(saved.scene, &norm_error)) {
        if (error) *error = "Cannot save: " + norm_error;
        return false;
    }
    if (!save_shot_json(saved, path)) {
        if (error) *error = "Failed to save to: " + path;
        return false;
    }
    ed.session.save_path = path;
    ed.session.dirty = false;
    std::cerr << "Saved: " << path << "\n";
    return true;
}

void do_save(EditorState& ed) {
    std::string path = ed.session.save_path.empty() ? (ed.shot.name + ".json") : ed.session.save_path;
    std::string error;
    if (!do_save_to(ed, path, &error))
        std::cerr << error << "\n";
}

void copy_to_clipboard(EditorState& ed) {
    ed.session.clipboard.shapes.clear();
    ed.session.clipboard.lights.clear();
    ed.session.clipboard.groups.clear();
    ed.session.clipboard.materials.clear();
    auto capture_shape_material = [&](const Shape& shape) {
        const std::string& material_id = shape_material_id(shape);
        if (auto it = ed.shot.scene.materials.find(material_id); it != ed.shot.scene.materials.end())
            ed.session.clipboard.materials[material_id] = it->second;
    };
    for (auto& sid : ed.interaction.selection) {
        if (const Shape* shape = resolve_shape(ed.shot.scene, sid)) {
            ed.session.clipboard.shapes.push_back(*shape);
            capture_shape_material(*shape);
        }
        else if (const Light* light = resolve_light(ed.shot.scene, sid)) ed.session.clipboard.lights.push_back(*light);
        else if (sid.type == SelectionRef::Group) {
            if (const Group* g = find_group(ed.shot.scene, sid.id)) {
                ed.session.clipboard.groups.push_back(*g);
                for (const auto& shape : g->shapes)
                    capture_shape_material(shape);
            }
        }
    }
    ed.session.clipboard.centroid = ed.selection_centroid();
}

bool delete_selected(EditorState& ed, Renderer& renderer, const CompareSnapshot& compare_ab,
                     bool& light_analysis_valid,
                     int win_w, int win_h) {
    if (ed.interaction.selection.empty()) return false;
    ed.session.undo.push(ed.shot.scene);

    std::set<std::string> shape_ids, light_ids, group_ids;
    for (auto& id : ed.interaction.selection) {
        if (id.type == SelectionRef::Shape) shape_ids.insert(id.id);
        else if (id.type == SelectionRef::Light) light_ids.insert(id.id);
        else if (id.type == SelectionRef::Group) group_ids.insert(id.id);
    }
    std::erase_if(ed.shot.scene.shapes, [&](const Shape& s) { return shape_ids.contains(shape_id(s)); });
    std::erase_if(ed.shot.scene.lights, [&](const Light& l) { return light_ids.contains(light_id(l)); });
    std::erase_if(ed.shot.scene.groups, [&](const Group& g) { return group_ids.contains(g.id); });
    ed.clear_selection();
    reload_scene(ed, renderer, compare_ab, light_analysis_valid, win_w, win_h);
    return true;
}

void reset_editor(EditorState& ed, Renderer& renderer, CompareSnapshot& compare_ab,
                  bool& light_analysis_valid,
                  int win_w, int win_h) {
    ed.clear_selection();
    ed.interaction.creating = false;
    ed.interaction.dragging = false;
    ed.interaction.handle_dragging = false;
    ed.interaction.box_selecting = false;
    ed.interaction.box_active_before.reset();
    ed.interaction.path_create_points.clear();
    ed.interaction.measure_active = false;
    ed.interaction.editing_group_id.clear();
    ed.interaction.tool = EditTool::Select;
    ed.interaction.cam_handle_dragging = CameraHandle::None;
    ed.interaction.cam_handle_hovered = CameraHandle::None;
    destroy_compare_snapshot(compare_ab);
    compare_ab.active = false;
    compare_ab.showing_a = false;
    compare_ab.metrics_valid = false;
    compare_ab.frame = 0;
    ed.session.undo.clear();
    ed.session.undo.push(ed.shot.scene);
    ed.session.frame = 0;
    ensure_scene_entity_ids(ed.shot.scene);

    ed.view.scene_bounds = scene_default_bounds(ed.shot.scene);
    ed.view.camera.fit(ed.view.scene_bounds, (float)win_w, (float)win_h);
    reload_scene(ed, renderer, compare_ab, light_analysis_valid, win_w, win_h, false);
    ed.session.dirty = false;
}

void duplicate_selected(EditorState& ed, Renderer& renderer, const CompareSnapshot& compare_ab,
                        bool& light_analysis_valid,
                        int win_w, int win_h) {
    if (ed.interaction.selection.empty()) return;
    ed.session.undo.push(ed.shot.scene);
    std::vector<SelectionRef> new_sel;
    Vec2 offset{0.05f, 0.05f};
    for (auto& sid : ed.interaction.selection) {
        if (const Shape* shape = resolve_shape(ed.shot.scene, sid)) {
            Shape s = *shape;
            shape_id(s) = next_scene_entity_id(ed.shot.scene, shape_type_name(s));
            translate_shape(s, offset);
            ed.shot.scene.shapes.push_back(s);
            new_sel.push_back({SelectionRef::Shape, shape_id(s), ""});
        } else if (const Light* light = resolve_light(ed.shot.scene, sid)) {
            Light l = *light;
            light_id(l) = next_scene_entity_id(ed.shot.scene, light_type_name(l));
            translate_light(l, offset);
            ed.shot.scene.lights.push_back(l);
            new_sel.push_back({SelectionRef::Light, light_id(l), ""});
        } else if (sid.type == SelectionRef::Group) {
            if (const Group* gp = find_group(ed.shot.scene, sid.id)) {
                Group g = *gp;
                g.id = next_scene_entity_id(ed.shot.scene, "group");
                translate_group(g, offset);
                ed.shot.scene.groups.push_back(g);
                new_sel.push_back({SelectionRef::Group, g.id, ""});
            }
        }
    }
    ed.replace_selection(std::move(new_sel));
    reload_scene(ed, renderer, compare_ab, light_analysis_valid, win_w, win_h);
}

bool group_selected(EditorState& ed, Renderer& renderer, const CompareSnapshot& compare_ab,
                    bool& light_analysis_valid,
                    int win_w, int win_h) {
    int n_ungrouped = 0;
    bool has_groups = false;
    for (auto& sid : ed.interaction.selection) {
        if (sid.type == SelectionRef::Group || !sid.group_id.empty()) has_groups = true;
        else n_ungrouped++;
    }
    if (n_ungrouped < 2 || has_groups) return false;

    ed.session.undo.push(ed.shot.scene);
    Vec2 centroid = ed.selection_centroid();
    Group group;
    group.id = next_scene_entity_id(ed.shot.scene, "group");
    group.transform.translate = centroid;

    std::set<std::string> shape_ids_to_remove, light_ids_to_remove;
    for (auto& sid : ed.interaction.selection) {
        if (sid.type == SelectionRef::Shape) {
            if (Shape* sp = find_shape_in(ed.shot.scene.shapes, sid.id)) {
                Shape s = *sp;
                translate_shape(s, Vec2{0, 0} - centroid);
                group.shapes.push_back(s);
                shape_ids_to_remove.insert(sid.id);
            }
        } else if (sid.type == SelectionRef::Light) {
            if (Light* lp = find_light_in(ed.shot.scene.lights, sid.id)) {
                Light l = *lp;
                translate_light(l, Vec2{0, 0} - centroid);
                group.lights.push_back(l);
                light_ids_to_remove.insert(sid.id);
            }
        }
    }

    std::erase_if(ed.shot.scene.shapes, [&](const Shape& s) { return shape_ids_to_remove.contains(shape_id(s)); });
    std::erase_if(ed.shot.scene.lights, [&](const Light& l) { return light_ids_to_remove.contains(light_id(l)); });

    std::string new_group_id = group.id;
    ed.shot.scene.groups.push_back(std::move(group));
    ed.select_only({SelectionRef::Group, new_group_id, ""});
    reload_scene(ed, renderer, compare_ab, light_analysis_valid, win_w, win_h);
    return true;
}

bool ungroup_selected(EditorState& ed, Renderer& renderer, const CompareSnapshot& compare_ab,
                      bool& light_analysis_valid,
                      int win_w, int win_h) {
    bool any_ungrouped = false;
    for (auto& sid : ed.interaction.selection) {
        if (sid.type == SelectionRef::Group && find_group(ed.shot.scene, sid.id)) {
            any_ungrouped = true;
            break;
        }
    }
    if (!any_ungrouped) return false;

    ed.session.undo.push(ed.shot.scene);
    std::vector<SelectionRef> new_sel;
    std::set<std::string> groups_to_remove;
    for (auto& sid : ed.interaction.selection) {
        if (sid.type != SelectionRef::Group) continue;
        Group* group = find_group(ed.shot.scene, sid.id);
        if (!group) continue;
        for (auto& s : group->shapes) {
            Shape ws = transform_shape(s, group->transform);
            ed.shot.scene.shapes.push_back(ws);
            new_sel.push_back({SelectionRef::Shape, shape_id(ws), ""});
        }
        for (auto& l : group->lights) {
            Light wl = transform_light(l, group->transform);
            ed.shot.scene.lights.push_back(wl);
            new_sel.push_back({SelectionRef::Light, light_id(wl), ""});
        }
        groups_to_remove.insert(sid.id);
    }
    std::erase_if(ed.shot.scene.groups, [&](const Group& g) { return groups_to_remove.contains(g.id); });
    ed.replace_selection(std::move(new_sel));
    ed.validate_selection();
    reload_scene(ed, renderer, compare_ab, light_analysis_valid, win_w, win_h);
    return true;
}
