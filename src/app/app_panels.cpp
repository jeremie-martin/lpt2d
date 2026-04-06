#include "app_panels.h"

#include "geometry.h"
#include "renderer.h"
#include "scene.h"
#include "scenes.h"
#include "serialize.h"
#include "ui.h"

#include <imgui.h>
#include <stdint.h>
#include <algorithm>
#include <array>
#include <cmath>
#include <cstdio>
#include <iostream>
#include <map>
#include <optional>
#include <string_view>
#include <utility>
#include <variant>

namespace {

constexpr float kDefaultRoomHalfWidth = 1.0f;
constexpr float kDefaultRoomHalfHeight = kDefaultRoomHalfWidth * 9.0f / 16.0f;

Material gui_wall_material() {
    return mat_mirror(0.95f, 0.1f);
}

// ─── Helper lambdas (local to panel drawing) ─────────────────────────

std::string selection_label(const std::string& visible, const std::string& key) {
    return visible + "##" + key;
}

bool entity_id_available(const Scene& scene, std::string_view candidate, std::string_view current) {
    if (candidate.empty()) return false;
    if (candidate == current) return true;
    return !find_shape(scene, candidate)
        && !find_light(scene, candidate)
        && !find_group(scene, candidate);
}

bool material_id_available(const Scene& scene, std::string_view candidate, std::string_view current) {
    if (candidate.empty()) return false;
    if (candidate == current) return true;
    return !scene.materials.contains(std::string(candidate));
}

bool apply_material_to_selection(EditorState& ed, std::string_view material_id) {
    bool changed = false;
    for (const auto& id : ed.interaction.selection) {
        if (Shape* shape = resolve_shape(ed.shot.scene, id)) {
            bind_material(*shape, ed.shot.scene, material_id);
            changed = true;
            continue;
        }
        if (id.type == SelectionRef::Group) {
            if (Group* g = find_group(ed.shot.scene, id.id)) {
                for (auto& shape : g->shapes) {
                    bind_material(shape, ed.shot.scene, material_id);
                    changed = true;
                }
            }
        }
    }
    return changed;
}

bool detach_material_from_selection(EditorState& ed, std::string_view material_id) {
    bool changed = false;
    auto maybe_detach = [&](Shape& shape) {
        if (material_ref_id(shape_binding(shape)) == material_id) {
            detach_material(shape, ed.shot.scene.materials);
            changed = true;
        }
    };
    for (const auto& id : ed.interaction.selection) {
        if (Shape* shape = resolve_shape(ed.shot.scene, id)) {
            maybe_detach(*shape);
            continue;
        }
        if (id.type == SelectionRef::Group) {
            if (Group* g = find_group(ed.shot.scene, id.id)) {
                for (auto& shape : g->shapes)
                    maybe_detach(shape);
            }
        }
    }
    return changed;
}

void for_each_clipboard_shape(EditorState& ed, auto&& fn) {
    for (auto& shape : ed.session.clipboard.shapes)
        fn(shape);
    for (auto& group : ed.session.clipboard.groups)
        for (auto& shape : group.shapes)
            fn(shape);
}

void rewrite_clipboard_material_binding(EditorState& ed, std::string_view old_id, std::string_view new_id) {
    for_each_clipboard_shape(ed, [&](Shape& shape) {
        if (material_ref_id(shape_binding(shape)) == old_id)
            shape_binding(shape) = std::string(new_id);
    });
}

void detach_clipboard_material_binding(EditorState& ed, std::string_view material_id) {
    for_each_clipboard_shape(ed, [&](Shape& shape) {
        if (material_ref_id(shape_binding(shape)) == material_id)
            detach_material(shape, ed.shot.scene.materials);
    });
}

void rename_material_binding(EditorState& ed, std::string_view old_id, std::string_view new_id) {
    if (old_id == new_id) return;
    if (!rename_material(ed.shot.scene, old_id, new_id)) return;
    rewrite_clipboard_material_binding(ed, old_id, new_id);
}

std::string group_display_name(const Group& group, int index) {
    if (!group.id.empty()) return group.id;
    return "Group " + std::to_string(index);
}

const Shot& current_authored_shot(const EditorState& ed, const CompareSnapshot& compare_ab) {
    return (compare_ab.active && compare_ab.showing_a) ? compare_ab.shot : ed.shot;
}

int current_runtime_frame_index(const EditorState& ed, const CompareSnapshot& compare_ab) {
    return (compare_ab.active && compare_ab.showing_a) ? compare_ab.frame_index : ed.session.frame_index;
}

} // namespace

// ─── Controls panel ──────────────────────────────────────────────────

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
) {
    // Shorthand reload
    auto reload = [&](bool mark_dirty = true) {
        reload_scene(ed, renderer, compare_ab, panel.light_analysis_valid, force_live_metrics_refresh,
                     win_w, win_h, mark_dirty);
    };

    const auto& builtins = get_builtin_scenes();
    bool showing_snapshot_a = compare_ab.active && compare_ab.showing_a;

    float panel_w = 280 * dpi_scale;
    ImGui::SetNextWindowPos(ImVec2((float)win_w - panel_w - 8, 8), ImGuiCond_FirstUseEver);
    ImGui::SetNextWindowSize(ImVec2(panel_w, (float)win_h - 16), ImGuiCond_FirstUseEver);
    ImGui::SetNextWindowSizeConstraints(ImVec2(220 * dpi_scale, 200), ImVec2(500 * dpi_scale, 1e6f));
    ImGui::Begin("Controls");

    // -- Scene --
    if (ImGui::CollapsingHeader("Scene", ImGuiTreeNodeFlags_DefaultOpen)) {
        ImGui::PushID("Scene");
        const char* label = (panel.current_scene >= 0) ? builtins[panel.current_scene].name.c_str() : "Custom";
        if (ImGui::BeginCombo("##scene", label)) {
            for (int i = 0; i < (int)builtins.size(); ++i) {
                if (ImGui::Selectable(builtins[i].name.c_str(), i == panel.current_scene)) {
                    panel.current_scene = i;
                    ed.shot = load_builtin_scene(builtins[i]);
                    ed.shot.trace.batch = kGuiTraceBatch;
                    reset_editor(ed, renderer, compare_ab, panel.light_analysis_valid,
                                 force_live_metrics_refresh, win_w, win_h);
                }
            }
            ImGui::EndCombo();
        }
        if (ImGui::Button("New Scene")) {
            panel.current_scene = -1;
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
            reset_editor(ed, renderer, compare_ab, panel.light_analysis_valid,
                         force_live_metrics_refresh, win_w, win_h);
        }

        // Save/Load
        ImGui::SameLine();
        if (ImGui::Button("Save")) { do_save(ed); }
        ImGui::SameLine();
        if (ImGui::Button("Load")) {
            ImGui::OpenPopup("Load Scene##popup");
        }

        // Load popup (can be triggered by Ctrl+O shortcut)
        if (panel.open_load_popup) { ImGui::OpenPopup("Load Scene##popup"); panel.open_load_popup = false; }
        if (ImGui::BeginPopup("Load Scene##popup")) {
            ImGui::Text("File path:");
            if (ImGui::InputText("##loadpath", panel.load_dialog.path.data(), panel.load_dialog.path.size()))
                panel.load_dialog.error.clear();
            if (!panel.load_dialog.error.empty())
                ImGui::TextWrapped("%s", panel.load_dialog.error.c_str());
            if (ImGui::Button("OK") && panel.load_dialog.path[0]) {
                std::string error;
                if (auto loaded = try_load_shot_json(panel.load_dialog.path.data(), &error)) {
                    ed.shot = *loaded;
                    ed.shot.trace.batch = kGuiTraceBatch;
                    ed.session.save_path = panel.load_dialog.path.data();
                    panel.current_scene = -1;
                    panel.load_dialog.error.clear();
                    reset_editor(ed, renderer, compare_ab, panel.light_analysis_valid,
                                 force_live_metrics_refresh, win_w, win_h);
                } else {
                    panel.load_dialog.error = error.empty() ? "Failed to load scene" : error;
                }
                if (panel.load_dialog.error.empty())
                    ImGui::CloseCurrentPopup();
            }
            ImGui::SameLine();
            if (ImGui::Button("Cancel")) {
                panel.load_dialog.error.clear();
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
            bool active = (ed.interaction.tool == t);
            if (active) {
                ImGui::PushStyleColor(ImGuiCol_Button, accent);
                ImGui::PushStyleColor(ImGuiCol_ButtonHovered, accent_h);
            }
            if (ImGui::Button(lbl)) { ed.interaction.tool = t; ed.interaction.creating = false; }
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

        ImGui::Checkbox("Wireframe overlay", &panel.show_wireframe);
        ImGui::Checkbox("Grid", &ed.view.show_grid);
        if (ed.view.show_grid) {
            ImGui::SameLine();
            ImGui::Checkbox("Snap", &ed.view.snap_to_grid);
        }
        ImGui::PopID();
    }

    // -- Camera --
    if (ImGui::CollapsingHeader("Camera", ImGuiTreeNodeFlags_DefaultOpen)) {
        ImGui::PushID("Camera");

        if (ImGui::Button("Set from View")) {
            ed.shot.camera.bounds = current_display_view(ed, compare_ab, win_w, win_h);
            ed.shot.camera.center.reset();
            ed.shot.camera.width.reset();
            ed.session.dirty = true;
        }
        ImGui::SameLine();
        if (ImGui::Button("Clear") && !ed.shot.camera.empty()) {
            ed.shot.camera = Camera2D{};
            ed.session.dirty = true;
        }

        ImGui::Checkbox("Show frame", &ed.view.show_camera_frame);
        ImGui::SameLine();
        ImGui::Checkbox("Dim outside", &ed.view.dim_outside_camera);

        if (!ed.shot.camera.empty()) {
            Bounds cam = ed.shot.camera.resolve(ed.shot.canvas.aspect(), ed.view.scene_bounds);
            bool cam_changed = false;
            cam_changed |= ImGui::DragFloat("Min X", &cam.min.x, 0.01f);
            cam_changed |= ImGui::DragFloat("Min Y", &cam.min.y, 0.01f);
            cam_changed |= ImGui::DragFloat("Max X", &cam.max.x, 0.01f);
            cam_changed |= ImGui::DragFloat("Max Y", &cam.max.y, 0.01f);
            if (cam_changed) {
                ed.shot.camera.bounds = cam;
                ed.shot.camera.center.reset();
                ed.shot.camera.width.reset();
                ed.session.dirty = true;
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
            ed.session.dirty = true;
        }
        ImGui::Text("Aspect: %.3f", ed.shot.canvas.aspect());
        ImGui::PopID();
    }

    // -- Objects --
    if (ImGui::CollapsingHeader("Objects", ImGuiTreeNodeFlags_DefaultOpen)) {
        ImGui::PushID("Objects");
        if (ImGui::SmallButton("Show All")) { ed.visibility.show_all(); reload(); }
        if (!ed.visibility.solo_light_id.empty()) {
            ImGui::SameLine();
            if (!ed.visibility.solo_light_group_id.empty()) {
                if (const Group* group = find_group(ed.shot.scene, ed.visibility.solo_light_group_id)) {
                    if (const Light* sl = find_light_in(group->lights, ed.visibility.solo_light_id)) {
                        std::string light_label = light_display_name(*sl, 0);
                        ImGui::TextColored(ImVec4(1.0f, 0.85f, 0.3f, 1.0f),
                            "Solo: %s / %s", group->id.c_str(), light_label.c_str());
                    } else {
                        ImGui::TextColored(ImVec4(1.0f, 0.85f, 0.3f, 1.0f), "Solo: %s", group->id.c_str());
                    }
                }
            } else {
                if (const Light* sl = find_light_in(ed.shot.scene.lights, ed.visibility.solo_light_id)) {
                    std::string label = light_display_name(*sl, 0);
                    ImGui::TextColored(ImVec4(1.0f, 0.85f, 0.3f, 1.0f), "Solo: %s", label.c_str());
                }
            }
        }
        int n_items = (int)(ed.shot.scene.shapes.size() + ed.shot.scene.lights.size() + ed.shot.scene.groups.size());
        float h = std::clamp(n_items * ImGui::GetTextLineHeightWithSpacing() + 8.0f,
                             40.0f, 200.0f * dpi_scale);
        ImGui::BeginChild("##objlist", ImVec2(0, h), ImGuiChildFlags_Borders);

        for (int i = 0; i < (int)ed.shot.scene.shapes.size(); ++i) {
            const auto& shape = ed.shot.scene.shapes[i];
            const auto& sid = shape_id(shape);
            SelectionRef ref{SelectionRef::Shape, sid, ""};
            bool is_sel = ed.is_selected(ref);
            std::string lbl = selection_label(shape_display_name(shape, i), "shape_" + sid);
            ImGui::PushID(i + 10000);
            bool svis = ed.visibility.is_shape_visible(sid);
            if (ImGui::SmallButton(svis ? "o" : "-")) {
                ed.visibility.toggle_shape(sid); reload();
            }
            ImGui::PopID();
            ImGui::SameLine();
            ImVec4 mc = material_color(resolve_shape_material(shape, ed.shot.scene.materials));
            ImGui::PushID(i);
            ImGui::ColorButton("##sw", mc, ImGuiColorEditFlags_NoTooltip | ImGuiColorEditFlags_NoPicker, ImVec2(10, 10));
            ImGui::PopID();
            ImGui::SameLine();
            if (ImGui::Selectable(lbl.c_str(), is_sel)) {
                if (io.KeyShift) ed.toggle_select(ref);
                else { ed.clear_selection(); ed.select(ref); }
            }
        }

        for (int i = 0; i < (int)ed.shot.scene.lights.size(); ++i) {
            const auto& light = ed.shot.scene.lights[i];
            const auto& lid = light_id(light);
            SelectionRef ref{SelectionRef::Light, lid, ""};
            bool is_sel = ed.is_selected(ref);
            std::string lbl = selection_label(light_display_name(light, i), "light_" + lid);
            ImGui::PushID(i + 20000);
            bool lvis = ed.visibility.is_light_visible(lid);
            if (ImGui::SmallButton(lvis ? "o" : "-")) {
                ed.visibility.toggle_light(lid); reload();
            }
            ImGui::PopID();
            ImGui::SameLine();
            ImGui::PushID(i + 30000);
            bool is_solo = (ed.visibility.solo_light_id == lid && ed.visibility.solo_light_group_id.empty());
            if (ImGui::SmallButton(is_solo ? "S" : "s")) {
                if (is_solo) {
                    ed.visibility.clear_solo();
                } else {
                    ed.visibility.solo_light_id = lid;
                    ed.visibility.solo_light_group_id.clear();
                }
                reload();
            }
            ImGui::PopID();
            ImGui::SameLine();
            if (ImGui::Selectable(lbl.c_str(), is_sel)) {
                if (io.KeyShift) ed.toggle_select(ref);
                else { ed.clear_selection(); ed.select(ref); }
            }
        }

        for (int i = 0; i < (int)ed.shot.scene.groups.size(); ++i) {
            const auto& group = ed.shot.scene.groups[i];
            SelectionRef gref{SelectionRef::Group, group.id, ""};
            bool is_sel = ed.is_selected(gref);
            bool is_editing = (ed.interaction.editing_group_id == group.id);
            int n_members = (int)(group.shapes.size() + group.lights.size());
            std::string grp_name = group_display_name(group, i);
            std::string lbl = grp_name;
            if (is_editing) lbl = "> " + lbl;
            lbl += " (" + std::to_string(n_members) + " items)";
            lbl = selection_label(lbl, "group_" + group.id);
            ImGui::PushID(i + 40000);
            bool gvis = ed.visibility.is_group_visible(group.id);
            if (ImGui::SmallButton(gvis ? "o" : "-")) {
                ed.visibility.toggle_group(group.id); reload();
            }
            ImGui::PopID();
            ImGui::SameLine();
            if (ImGui::Selectable(lbl.c_str(), is_sel || is_editing)) {
                if (io.KeyShift) ed.toggle_select(gref);
                else { ed.clear_selection(); ed.select(gref); }
            }
            if (is_editing) {
                ImGui::Indent(12.0f);
                for (int j = 0; j < (int)group.shapes.size(); ++j) {
                    SelectionRef mref{SelectionRef::Shape, shape_id(group.shapes[j]), group.id};
                    bool mid_sel = ed.is_selected(mref);
                    std::string mlbl = selection_label(
                        "  " + shape_display_name(group.shapes[j], j),
                        "group_shape_" + group.id + "_" + shape_id(group.shapes[j]));
                    if (ImGui::Selectable(mlbl.c_str(), mid_sel)) {
                        ed.clear_selection();
                        ed.select(mref);
                    }
                }
                for (int j = 0; j < (int)group.lights.size(); ++j) {
                    const auto& gl = group.lights[j];
                    const auto& glid = light_id(gl);
                    SelectionRef mref{SelectionRef::Light, glid, group.id};
                    bool mid_sel = ed.is_selected(mref);
                    ImGui::PushID(i * 1000 + j + 50000);
                    bool is_gsolo = (ed.visibility.solo_light_group_id == group.id && ed.visibility.solo_light_id == glid);
                    if (ImGui::SmallButton(is_gsolo ? "S" : "s")) {
                        if (is_gsolo) {
                            ed.visibility.clear_solo();
                        } else {
                            ed.visibility.solo_light_id = glid;
                            ed.visibility.solo_light_group_id = group.id;
                        }
                        reload();
                    }
                    ImGui::PopID();
                    ImGui::SameLine();
                    std::string mlbl = selection_label(
                        "  " + light_display_name(gl, j),
                        "group_light_" + group.id + "_" + glid);
                    if (ImGui::Selectable(mlbl.c_str(), mid_sel)) {
                        ed.clear_selection();
                        ed.select(mref);
                    }
                }
                ImGui::Unindent(12.0f);
            }
        }

        ImGui::EndChild();

        if (!ed.interaction.selection.empty()) {
            if (ed.interaction.selection.size() > 1)
                ImGui::Text("%d objects selected", (int)ed.interaction.selection.size());
            if (ImGui::Button("Delete Selected")) {
                delete_selected(ed, renderer, compare_ab, panel.light_analysis_valid,
                                force_live_metrics_refresh, win_w, win_h);
            }
        }

        // Visual diagnostics
        {
            const Shot& diagnostic_shot = current_authored_shot(ed, compare_ab);
            Shot diagnostic_copy = diagnostic_shot;
            ensure_scene_entity_ids(diagnostic_copy.scene);
            auto scene_warnings = diagnose_scene(diagnostic_copy.scene);
            if (!scene_warnings.empty()) {
                ImGui::Text("Scene Warnings:");
                for (const auto& warning : scene_warnings)
                    ImGui::BulletText("%s", warning.c_str());
            }

            if (ImGui::Button("Analyze Contributions")) {
                panel.light_analysis.clear();
                panel.light_analysis_valid = false;
                auto authored_sources = collect_authored_sources(diagnostic_copy.scene);
                if (!authored_sources.empty()) {
                    Bounds scene_bounds = scene_default_bounds(diagnostic_copy.scene);
                    Bounds view = diagnostic_copy.camera.resolve(
                        diagnostic_copy.canvas.aspect(), scene_bounds);
                    TraceConfig tcfg =
                        diagnostic_copy.trace.to_trace_config(current_runtime_frame_index(ed, compare_ab));
                    tcfg.batch_size = std::min(tcfg.batch_size, 100000);
                    tcfg.max_depth = std::min(tcfg.max_depth, 12);
                    int analysis_dispatches =
                        std::max(1, (int)std::ceil(500000.0 / std::max(1, tcfg.batch_size)));

                    renderer.upload_scene(diagnostic_copy.scene, view);
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
                        Scene solo = scene_with_solo_source(diagnostic_copy.scene, source);
                        renderer.upload_scene(solo, view);
                        renderer.clear();
                        if (renderer.num_lights() > 0)
                            renderer.trace_and_draw_multi(tcfg, analysis_dispatches);
                        renderer.update_display(contribution_look, diagnostic_copy.canvas.aspect());
                        auto metrics = renderer.compute_display_metrics();
                        panel.light_analysis.push_back({
                            source.label,
                            metrics.mean_lum,
                            1.0f - metrics.pct_black,
                            0.0f,
                        });
                        total_mean += metrics.mean_lum;
                    }

                    for (auto& entry : panel.light_analysis)
                        entry.share = (total_mean > 0.0f) ? entry.mean_linear_luma / total_mean : 0.0f;
                    std::sort(panel.light_analysis.begin(), panel.light_analysis.end(), [](const auto& a, const auto& b) {
                        return a.share > b.share;
                    });

                    reload(false);
                    panel.light_analysis_valid = !panel.light_analysis.empty();
                }
            }

            if (panel.light_analysis_valid && !panel.light_analysis.empty()) {
                ImGui::Text("Light Contributions (linear share):");
                for (int i = 0; i < (int)panel.light_analysis.size(); ++i) {
                    const auto& la = panel.light_analysis[i];
                    ImGui::Text("  %s: %.0f%% share, %.0f%% coverage",
                                la.id.c_str(), la.share * 100.0f, la.coverage_fraction * 100.0f);
                }
            }
        }

        ImGui::PopID();
    }

    // -- Properties --
    if (ed.interaction.selection.size() == 1 &&
        ImGui::CollapsingHeader("Properties", ImGuiTreeNodeFlags_DefaultOpen)) {
        ImGui::PushID("Properties");
        bool changed = false;
        auto& sid = ed.interaction.selection[0];

        if (!sid.group_id.empty()) {
            ImGui::TextDisabled("Editing group: %s", sid.group_id.c_str());
            ImGui::Separator();
        }

        auto sync_id_editor = [&](const std::string& current_id) {
            if (!(panel.id_editor.target == sid)) {
                panel.id_editor.target = sid;
                panel.id_editor.buffer = current_id;
            }
        };
        auto show_id_editor = [&](const std::string& current_id, auto&& commit) {
            sync_id_editor(current_id);
            std::array<char, 128> id_buf{};
            std::snprintf(id_buf.data(), id_buf.size(), "%s", panel.id_editor.buffer.c_str());
            if (ImGui::InputText("ID", id_buf.data(), id_buf.size())) {
                panel.id_editor.buffer = id_buf.data();
            }
            if (ImGui::IsItemDeactivatedAfterEdit()
                && panel.id_editor.buffer != current_id
                && !panel.id_editor.buffer.empty()
                && entity_id_available(ed.shot.scene, panel.id_editor.buffer, current_id)) {
                commit(panel.id_editor.buffer);
                changed = true;
            }
            if (panel.id_editor.buffer.empty()) {
                ImGui::TextColored(ImVec4(0.95f, 0.5f, 0.5f, 1.0f), "ID must be non-empty");
            } else if (panel.id_editor.buffer != current_id && !entity_id_available(ed.shot.scene, panel.id_editor.buffer, current_id)) {
                ImGui::TextColored(ImVec4(0.95f, 0.5f, 0.5f, 1.0f), "ID already in use");
            }
        };
        auto edit_shape_material_binding = [&](Shape& shape) {
            bool local_changed = false;
            auto ref = material_ref_id(shape_binding(shape));
            std::string mid(ref);
            const char* preview = mid.empty() ? "(inline custom)" : mid.c_str();
            if (ImGui::BeginCombo("Material", preview)) {
                if (ImGui::Selectable("(inline custom)", mid.empty()) && !mid.empty()) {
                    detach_material(shape, ed.shot.scene.materials);
                    local_changed = true;
                }
                for (const auto& [name, _] : ed.shot.scene.materials) {
                    bool selected = mid == name;
                    if (ImGui::Selectable(name.c_str(), selected) && mid != name) {
                        bind_material(shape, ed.shot.scene, name);
                        local_changed = true;
                    }
                }
                ImGui::EndCombo();
            }

            if (!mid.empty()) {
                ImGui::TextColored(ImVec4(0.5f, 0.8f, 0.5f, 1.0f),
                    "Editing shared material asset '%s'", mid.c_str());
                if (ImGui::SmallButton("Detach to Inline")) {
                    detach_material(shape, ed.shot.scene.materials);
                    local_changed = true;
                }
                if (auto it = ed.shot.scene.materials.find(mid); it != ed.shot.scene.materials.end()) {
                    local_changed |= edit_material(it->second);
                } else {
                    ImGui::TextColored(ImVec4(0.95f, 0.5f, 0.5f, 1.0f),
                        "Missing shared material '%s'", mid.c_str());
                }
            } else {
                ImGui::TextDisabled("Editing inline custom material");
                if (auto* mat = std::get_if<Material>(&shape_binding(shape)))
                    local_changed |= edit_material(*mat);
            }
            return local_changed;
        };

        if (Shape* sp = resolve_shape(ed.shot.scene, sid)) {
            auto& shape = *sp;
            show_id_editor(shape_id(shape), [&](const std::string& new_id) {
                shape_id(shape) = new_id;
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
            show_id_editor(light_id(light), [&](const std::string& new_id) {
                light_id(light) = new_id;
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

        if (sid.type == SelectionRef::Group) {
            if (Group* group = find_group(ed.shot.scene, sid.id)) {
                show_id_editor(group->id, [&](const std::string& new_id) {
                    group->id = new_id;
                    sid.id = new_id;
                });
                ImGui::Separator();
                ImGui::Text("Transform");
                changed |= ImGui::DragFloat2("Translate", &group->transform.translate.x, 0.01f);
                float deg = group->transform.rotate * 180.0f / PI;
                if (ImGui::DragFloat("Rotate", &deg, 0.5f, -360.0f, 360.0f, "%.1f deg")) {
                    group->transform.rotate = deg * PI / 180.0f;
                    changed = true;
                }
                changed |= ImGui::DragFloat2("Scale", &group->transform.scale.x, 0.01f, 0.01f, 100.0f);
                ImGui::Separator();
                int n_shapes = (int)group->shapes.size();
                int n_lights = (int)group->lights.size();
                ImGui::Text("%d shapes, %d lights", n_shapes, n_lights);
            }
        }

        if (changed) {
            if (!ed.interaction.prop_editing) {
                ed.session.undo.push(ed.shot.scene);
                ed.interaction.prop_editing = true;
            }
            reload();
        }
        if (!ImGui::IsAnyItemActive() && ed.interaction.prop_editing) {
            ed.interaction.prop_editing = false;
        }
        ImGui::PopID();
    }

    // -- Material Library --
    if (ImGui::CollapsingHeader("Materials", ImGuiTreeNodeFlags_DefaultOpen)) {
        ImGui::PushID("Materials");
        auto& mats = ed.shot.scene.materials;
        if (!panel.material_panel.selected_name.empty() && !mats.contains(panel.material_panel.selected_name)) {
            panel.material_panel.selected_name.clear();
            panel.material_panel.rename_buffer.clear();
        }
        if (mats.empty()) {
            ImGui::TextDisabled("No materials defined");
        } else {
            if (ImGui::BeginCombo("##matlist",
                                  panel.material_panel.selected_name.empty() ? "(select)" : panel.material_panel.selected_name.c_str())) {
                for (auto& [name, _] : mats) {
                    if (ImGui::Selectable(name.c_str(), name == panel.material_panel.selected_name)) {
                        panel.material_panel.selected_name = name;
                        panel.material_panel.rename_buffer = name;
                    }
                }
                ImGui::EndCombo();
            }
        }

        if (!panel.material_panel.selected_name.empty() && mats.contains(panel.material_panel.selected_name)) {
            auto& mat = mats[panel.material_panel.selected_name];
            if (panel.material_panel.rename_buffer.empty())
                panel.material_panel.rename_buffer = panel.material_panel.selected_name;

            std::array<char, 128> rename_buf{};
            std::snprintf(rename_buf.data(), rename_buf.size(), "%s", panel.material_panel.rename_buffer.c_str());
            if (ImGui::InputText("Rename", rename_buf.data(), rename_buf.size()))
                panel.material_panel.rename_buffer = rename_buf.data();

            if (!panel.material_panel.rename_buffer.empty()
                && panel.material_panel.rename_buffer != panel.material_panel.selected_name
                && !material_id_available(ed.shot.scene, panel.material_panel.rename_buffer, panel.material_panel.selected_name)) {
                ImGui::TextColored(ImVec4(0.95f, 0.5f, 0.5f, 1.0f), "Material ID already in use");
            } else if (panel.material_panel.rename_buffer.empty()) {
                ImGui::TextColored(ImVec4(0.95f, 0.5f, 0.5f, 1.0f), "Material ID must be non-empty");
            }

            if (ImGui::Button("Rename##mat")
                && !panel.material_panel.rename_buffer.empty()
                && material_id_available(ed.shot.scene, panel.material_panel.rename_buffer, panel.material_panel.selected_name)) {
                ed.session.undo.push(ed.shot.scene);
                rename_material_binding(ed, panel.material_panel.selected_name, panel.material_panel.rename_buffer);
                panel.material_panel.selected_name = panel.material_panel.rename_buffer;
                reload();
            }

            bool mat_changed = edit_material(mat);
            if (mat_changed) {
                if (!panel.material_panel.editing) {
                    ed.session.undo.push(ed.shot.scene);
                    panel.material_panel.editing = true;
                }
                reload();
            }

            int bound_count = material_usage_count(ed.shot.scene, panel.material_panel.selected_name);
            ImGui::Text("%d bound shape(s)", bound_count);

            if (ImGui::Button("Apply to Selection")) {
                Scene before = ed.shot.scene;
                if (apply_material_to_selection(ed, panel.material_panel.selected_name)) {
                    ed.session.undo.push(ed.shot.scene);
                    reload();
                } else {
                    ed.shot.scene = std::move(before);
                }
            }
            ImGui::SameLine();
            if (ImGui::Button("Detach Selection")) {
                Scene before = ed.shot.scene;
                if (detach_material_from_selection(ed, panel.material_panel.selected_name)) {
                    ed.session.undo.push(ed.shot.scene);
                    reload();
                } else {
                    ed.shot.scene = std::move(before);
                }
            }
            ImGui::SameLine();
            if (ImGui::Button("Delete##mat")) {
                ed.session.undo.push(ed.shot.scene);
                delete_material(ed.shot.scene, panel.material_panel.selected_name);
                detach_clipboard_material_binding(ed, panel.material_panel.selected_name);
                panel.material_panel.selected_name.clear();
                panel.material_panel.rename_buffer.clear();
                reload();
            }
            if (bound_count > 0) {
                ImGui::TextDisabled("Delete detaches bound shapes to inline materials");
            }
        }

        ImGui::Separator();

        ImGui::InputText("Name##newmat", panel.material_panel.new_name.data(), panel.material_panel.new_name.size());
        ImGui::SameLine();
        if (ImGui::Button("Add") && panel.material_panel.new_name[0] != '\0' && !mats.count(panel.material_panel.new_name.data())) {
            ed.session.undo.push(ed.shot.scene);
            mats[panel.material_panel.new_name.data()] = Material{};
            panel.material_panel.selected_name = panel.material_panel.new_name.data();
            panel.material_panel.rename_buffer = panel.material_panel.new_name.data();
            panel.material_panel.new_name[0] = '\0';
            reload();
        }

        auto preset_btn = [&](const char* label, Material mat) {
            if (ImGui::SmallButton(label)) {
                std::string name = label;
                if (mats.count(name)) { int n = 2; while (mats.count(name + " " + std::to_string(n))) ++n; name += " " + std::to_string(n); }
                ed.session.undo.push(ed.shot.scene);
                mats[name] = mat;
                panel.material_panel.selected_name = name;
                panel.material_panel.rename_buffer = name;
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

        if (!ImGui::IsAnyItemActive() && panel.material_panel.editing)
            panel.material_panel.editing = false;

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
        int seed_mode = (int)ed.shot.trace.seed_mode;
        if (ImGui::Combo("Seed mode", &seed_mode, "Deterministic\0Decorrelated\0")) {
            ed.shot.trace.seed_mode = (SeedMode)seed_mode;
            renderer.clear();
            panel.light_analysis_valid = false;
            force_live_metrics_refresh = true;
        }
        int frame_index = ed.session.frame_index;
        if (ImGui::InputInt("Frame index", &frame_index)) {
            ed.session.frame_index = std::max(frame_index, 0);
            renderer.clear();
            panel.light_analysis_valid = false;
            force_live_metrics_refresh = true;
        }
        ImGui::Checkbox("Paused", &panel.paused);
        ImGui::PopID();
    }

    // -- Display --
    if (ImGui::CollapsingHeader("Display", ImGuiTreeNodeFlags_DefaultOpen)) {
        ImGui::PushID("Display");

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
            compare_ab.frame_index = ed.session.frame_index;
            ensure_scene_entity_ids(compare_ab.shot.scene);
            compare_ab.view_bounds = current_display_view(ed, compare_ab, win_w, win_h);
            compare_ab.metrics = renderer.compute_frame_metrics();
            compare_ab.metrics_valid = true;
            upload_compare_snapshot(compare_ab, snapshot_rgba, fb_w, fb_h);
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
                destroy_compare_snapshot(compare_ab);
                compare_ab.active = false;
                compare_ab.showing_a = false;
                compare_ab.metrics_valid = false;
                compare_ab.frame_index = 0;
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
        ImGui::Separator();
        ImGui::SliderFloat("Temperature", &ed.shot.look.temperature, -1.0f, 1.0f);
        ImGui::SliderFloat("Highlights", &ed.shot.look.highlights, -1.0f, 1.0f);
        ImGui::SliderFloat("Shadows", &ed.shot.look.shadows, -1.0f, 1.0f);
        ImGui::SliderFloat("Hue Shift", &ed.shot.look.hue_shift, -180.0f, 180.0f);
        ImGui::SliderFloat("Grain", &ed.shot.look.grain, 0.0f, 0.5f, "%.3f");
        ImGui::SliderFloat("Chromatic Aberr.", &ed.shot.look.chromatic_aberration, 0.0f, 0.02f, "%.4f");
        ImGui::PopID();
    }

    // -- Output --
    if (ImGui::CollapsingHeader("Output", ImGuiTreeNodeFlags_DefaultOpen)) {
        ImGui::PushID("Output");
        char ray_str[32];
        int64_t tr = renderer.total_rays();
        const Shot& output_shot = current_authored_shot(ed, compare_ab);
        int output_frame_index = current_runtime_frame_index(ed, compare_ab);
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
            ImGui::TextDisabled("Max HDR: \xe2\x80\x94");
        ImGui::Text("%.1f FPS (%.1f ms)", 1000.0f / frame_ms, frame_ms);
        ImGui::Text("Zoom: %.0f%%", ed.view.camera.zoom / std::min((float)win_w / std::max(ed.view.scene_bounds.max.x - ed.view.scene_bounds.min.x, 0.01f), (float)win_h / std::max(ed.view.scene_bounds.max.y - ed.view.scene_bounds.min.y, 0.01f)) * 100.0f);

        if (ImGui::Button("Clear")) {
            renderer.clear();
        }
        ImGui::SameLine();
        if (ImGui::Button("Export PNG")) {
            std::string filename = output_shot.name + ".png";
            if (export_authored_png(output_shot, output_frame_index))
                std::cerr << "Exported: " << filename << "\n";
        }
        ImGui::PopID();
    }

    // -- Stats --
    if (ImGui::CollapsingHeader("Stats")) {
        ImGui::PushID("Stats");

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
}
