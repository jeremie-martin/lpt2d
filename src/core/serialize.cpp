#include "serialize.h"

#include <charconv>
#include <cmath>
#include <cstring>
#include <fstream>
#include <iostream>
#include <string>

static constexpr int SHOT_JSON_VERSION = 4;

// ─── Minimal JSON writer ────────────────────────────────────────────────

// Shortest round-tripping float representation (cleans up 0.34999999 → 0.35)
static std::string fmt(float v) {
    if (std::isnan(v) || std::isinf(v)) return "0";
    if (std::fabs(v) < 1e-6f) return "0";
    char buf[32];
    auto [ptr, ec] = std::to_chars(buf, buf + sizeof(buf), v);
    return std::string(buf, ptr);
}

static void write_indent(std::ostream& os, int depth) {
    for (int i = 0; i < depth; ++i) os << "  ";
}

static void write_material(std::ostream& os, const Material& m, int depth) {
    write_indent(os, depth); os << "\"material\": {\n";
    write_indent(os, depth + 1); os << "\"ior\": " << fmt(m.ior) << ",\n";
    write_indent(os, depth + 1); os << "\"roughness\": " << fmt(m.roughness) << ",\n";
    write_indent(os, depth + 1); os << "\"metallic\": " << fmt(m.metallic) << ",\n";
    write_indent(os, depth + 1); os << "\"transmission\": " << fmt(m.transmission) << ",\n";
    write_indent(os, depth + 1); os << "\"absorption\": " << fmt(m.absorption) << ",\n";
    write_indent(os, depth + 1); os << "\"cauchy_b\": " << fmt(m.cauchy_b) << ",\n";
    write_indent(os, depth + 1); os << "\"albedo\": " << fmt(m.albedo);
    if (m.emission > 0.0f) {
        os << ",\n";
        write_indent(os, depth + 1); os << "\"emission\": " << fmt(m.emission) << "\n";
    } else {
        os << "\n";
    }
    write_indent(os, depth); os << "}";
}

static void write_vec2(std::ostream& os, const char* name, Vec2 v) {
    os << "\"" << name << "\": [" << fmt(v.x) << ", " << fmt(v.y) << "]";
}

static void write_json_string(std::ostream& os, const std::string& s) {
    os << '"';
    for (char c : s) {
        if (c == '"') os << "\\\"";
        else if (c == '\\') os << "\\\\";
        else if (c == '\n') os << "\\n";
        else os << c;
    }
    os << '"';
}

static void write_shape(std::ostream& f, const Shape& shape, int d) {
    std::visit(overloaded{
        [&](const Circle& c) {
            write_indent(f, d); f << "\"type\": \"circle\",\n";
            write_indent(f, d); write_vec2(f, "center", c.center); f << ",\n";
            write_indent(f, d); f << "\"radius\": " << fmt(c.radius) << ",\n";
            write_material(f, c.material, d); f << "\n";
        },
        [&](const Segment& s) {
            write_indent(f, d); f << "\"type\": \"segment\",\n";
            write_indent(f, d); write_vec2(f, "a", s.a); f << ",\n";
            write_indent(f, d); write_vec2(f, "b", s.b); f << ",\n";
            write_material(f, s.material, d); f << "\n";
        },
        [&](const Arc& a) {
            write_indent(f, d); f << "\"type\": \"arc\",\n";
            write_indent(f, d); write_vec2(f, "center", a.center); f << ",\n";
            write_indent(f, d); f << "\"radius\": " << fmt(a.radius) << ",\n";
            write_indent(f, d); f << "\"angle_start\": " << fmt(a.angle_start) << ",\n";
            write_indent(f, d); f << "\"sweep\": " << fmt(a.sweep) << ",\n";
            write_material(f, a.material, d); f << "\n";
        },
        [&](const Bezier& b) {
            write_indent(f, d); f << "\"type\": \"bezier\",\n";
            write_indent(f, d); write_vec2(f, "p0", b.p0); f << ",\n";
            write_indent(f, d); write_vec2(f, "p1", b.p1); f << ",\n";
            write_indent(f, d); write_vec2(f, "p2", b.p2); f << ",\n";
            write_material(f, b.material, d); f << "\n";
        },
        [&](const Polygon& p) {
            write_indent(f, d); f << "\"type\": \"polygon\",\n";
            write_indent(f, d); f << "\"vertices\": [";
            for (int j = 0; j < (int)p.vertices.size(); ++j) {
                if (j > 0) f << ", ";
                f << "[" << fmt(p.vertices[j].x) << ", " << fmt(p.vertices[j].y) << "]";
            }
            f << "],\n";
            write_material(f, p.material, d); f << "\n";
        },
    }, shape);
}

static void write_light(std::ostream& f, const Light& light, int d) {
    std::visit(overloaded{
        [&](const PointLight& l) {
            write_indent(f, d); f << "\"type\": \"point\",\n";
            write_indent(f, d); write_vec2(f, "pos", l.pos); f << ",\n";
            write_indent(f, d); f << "\"intensity\": " << fmt(l.intensity) << ",\n";
            write_indent(f, d); f << "\"wavelength_min\": " << fmt(l.wavelength_min) << ",\n";
            write_indent(f, d); f << "\"wavelength_max\": " << fmt(l.wavelength_max) << "\n";
        },
        [&](const SegmentLight& l) {
            write_indent(f, d); f << "\"type\": \"segment\",\n";
            write_indent(f, d); write_vec2(f, "a", l.a); f << ",\n";
            write_indent(f, d); write_vec2(f, "b", l.b); f << ",\n";
            write_indent(f, d); f << "\"intensity\": " << fmt(l.intensity) << ",\n";
            write_indent(f, d); f << "\"wavelength_min\": " << fmt(l.wavelength_min) << ",\n";
            write_indent(f, d); f << "\"wavelength_max\": " << fmt(l.wavelength_max) << "\n";
        },
        [&](const BeamLight& l) {
            write_indent(f, d); f << "\"type\": \"beam\",\n";
            write_indent(f, d); write_vec2(f, "origin", l.origin); f << ",\n";
            write_indent(f, d); write_vec2(f, "direction", l.direction); f << ",\n";
            write_indent(f, d); f << "\"angular_width\": " << fmt(l.angular_width) << ",\n";
            write_indent(f, d); f << "\"intensity\": " << fmt(l.intensity) << ",\n";
            write_indent(f, d); f << "\"wavelength_min\": " << fmt(l.wavelength_min) << ",\n";
            write_indent(f, d); f << "\"wavelength_max\": " << fmt(l.wavelength_max) << "\n";
        },
        [&](const ParallelBeamLight& l) {
            write_indent(f, d); f << "\"type\": \"parallel_beam\",\n";
            write_indent(f, d); write_vec2(f, "a", l.a); f << ",\n";
            write_indent(f, d); write_vec2(f, "b", l.b); f << ",\n";
            write_indent(f, d); write_vec2(f, "direction", l.direction); f << ",\n";
            write_indent(f, d); f << "\"angular_width\": " << fmt(l.angular_width) << ",\n";
            write_indent(f, d); f << "\"intensity\": " << fmt(l.intensity) << ",\n";
            write_indent(f, d); f << "\"wavelength_min\": " << fmt(l.wavelength_min) << ",\n";
            write_indent(f, d); f << "\"wavelength_max\": " << fmt(l.wavelength_max) << "\n";
        },
        [&](const SpotLight& l) {
            write_indent(f, d); f << "\"type\": \"spot\",\n";
            write_indent(f, d); write_vec2(f, "pos", l.pos); f << ",\n";
            write_indent(f, d); write_vec2(f, "direction", l.direction); f << ",\n";
            write_indent(f, d); f << "\"angular_width\": " << fmt(l.angular_width) << ",\n";
            write_indent(f, d); f << "\"falloff\": " << fmt(l.falloff) << ",\n";
            write_indent(f, d); f << "\"intensity\": " << fmt(l.intensity) << ",\n";
            write_indent(f, d); f << "\"wavelength_min\": " << fmt(l.wavelength_min) << ",\n";
            write_indent(f, d); f << "\"wavelength_max\": " << fmt(l.wavelength_max) << "\n";
        },
    }, light);
}

// ─── Tonemap/normalize to string ────────────────────────────────────────

static const char* tonemap_to_string(ToneMap tm) {
    switch (tm) {
        case ToneMap::None: return "none";
        case ToneMap::Reinhard: return "reinhard";
        case ToneMap::ReinhardExtended: return "reinhardx";
        case ToneMap::ACES: return "aces";
        case ToneMap::Logarithmic: return "log";
    }
    return "aces";
}

static const char* normalize_to_string(NormalizeMode nm) {
    switch (nm) {
        case NormalizeMode::Max: return "max";
        case NormalizeMode::Rays: return "rays";
        case NormalizeMode::Fixed: return "fixed";
        case NormalizeMode::Off: return "off";
    }
    return "rays";
}

// ─── Shot writer (v4) ───────────────────────────────────────────────────

static void write_camera(std::ostream& f, const Camera2D& cam) {
    if (cam.empty()) return;
    f << "  \"camera\": {\n";
    if (cam.bounds) {
        f << "    \"bounds\": [" << fmt(cam.bounds->min.x) << ", " << fmt(cam.bounds->min.y)
          << ", " << fmt(cam.bounds->max.x) << ", " << fmt(cam.bounds->max.y) << "]\n";
    } else if (cam.center && cam.width) {
        f << "    "; write_vec2(f, "center", *cam.center); f << ",\n";
        f << "    \"width\": " << fmt(*cam.width) << "\n";
    }
    f << "  },\n";
}

static void write_canvas(std::ostream& f, const Canvas& canvas) {
    f << "  \"canvas\": {\"width\": " << canvas.width << ", \"height\": " << canvas.height << "},\n";
}

static void write_look(std::ostream& f, const Look& look) {
    Look def; // defaults for comparison
    // Collect non-default fields
    std::vector<std::pair<std::string, std::string>> entries;
    if (look.exposure != def.exposure) entries.push_back({"\"exposure\"", fmt(look.exposure)});
    if (look.contrast != def.contrast) entries.push_back({"\"contrast\"", fmt(look.contrast)});
    if (look.gamma != def.gamma) entries.push_back({"\"gamma\"", fmt(look.gamma)});
    if (look.tone_map != def.tone_map) entries.push_back({"\"tonemap\"", std::string("\"") + tonemap_to_string(look.tone_map) + "\""});
    if (look.white_point != def.white_point) entries.push_back({"\"white_point\"", fmt(look.white_point)});
    if (look.normalize != def.normalize) entries.push_back({"\"normalize\"", std::string("\"") + normalize_to_string(look.normalize) + "\""});
    if (look.normalize_ref != def.normalize_ref) entries.push_back({"\"normalize_ref\"", fmt(look.normalize_ref)});
    if (look.normalize_pct != def.normalize_pct) entries.push_back({"\"normalize_pct\"", fmt(look.normalize_pct)});
    if (look.ambient != def.ambient) entries.push_back({"\"ambient\"", fmt(look.ambient)});
    if (look.background[0] != 0.0f || look.background[1] != 0.0f || look.background[2] != 0.0f) {
        entries.push_back({"\"background\"", "[" + fmt(look.background[0]) + ", " + fmt(look.background[1]) + ", " + fmt(look.background[2]) + "]"});
    }
    if (look.opacity != def.opacity) entries.push_back({"\"opacity\"", fmt(look.opacity)});

    if (entries.empty()) return; // all defaults, skip block

    f << "  \"look\": {";
    for (int i = 0; i < (int)entries.size(); ++i) {
        if (i > 0) f << ",";
        f << "\n    " << entries[i].first << ": " << entries[i].second;
    }
    f << "\n  },\n";
}

static void write_trace(std::ostream& f, const TraceDefaults& trace) {
    f << "  \"trace\": {\n";
    f << "    \"rays\": " << trace.rays << ",\n";
    f << "    \"batch\": " << trace.batch << ",\n";
    f << "    \"depth\": " << trace.depth;
    if (trace.intensity != 1.0f) {
        f << ",\n    \"intensity\": " << fmt(trace.intensity);
    }
    f << "\n  },\n";
}

bool save_shot_json(const Shot& shot, const std::string& path) {
    std::ofstream f(path);
    if (!f) { std::cerr << "Failed to open " << path << " for writing\n"; return false; }

    const auto& scene = shot.scene;

    f << "{\n";
    f << "  \"version\": " << SHOT_JSON_VERSION << ",\n";
    f << "  \"name\": "; write_json_string(f, shot.name); f << ",\n";

    // Shot-level blocks
    write_camera(f, shot.camera);
    write_canvas(f, shot.canvas);
    write_look(f, shot.look);
    write_trace(f, shot.trace);

    // Materials library
    if (!scene.materials.empty()) {
        f << "  \"materials\": {\n";
        int mi = 0;
        for (const auto& [name, mat] : scene.materials) {
            f << "    "; write_json_string(f, name); f << ": {\n";
            write_indent(f, 3); f << "\"ior\": " << fmt(mat.ior) << ",\n";
            write_indent(f, 3); f << "\"roughness\": " << fmt(mat.roughness) << ",\n";
            write_indent(f, 3); f << "\"metallic\": " << fmt(mat.metallic) << ",\n";
            write_indent(f, 3); f << "\"transmission\": " << fmt(mat.transmission) << ",\n";
            write_indent(f, 3); f << "\"absorption\": " << fmt(mat.absorption) << ",\n";
            write_indent(f, 3); f << "\"cauchy_b\": " << fmt(mat.cauchy_b) << ",\n";
            write_indent(f, 3); f << "\"albedo\": " << fmt(mat.albedo);
            if (mat.emission > 0.0f) {
                f << ",\n";
                write_indent(f, 3); f << "\"emission\": " << fmt(mat.emission) << "\n";
            } else {
                f << "\n";
            }
            f << "    }" << (++mi < (int)scene.materials.size() ? "," : "") << "\n";
        }
        f << "  },\n";
    }

    // Shapes
    f << "  \"shapes\": [\n";
    for (int i = 0; i < (int)scene.shapes.size(); ++i) {
        f << "    {\n";
        write_shape(f, scene.shapes[i], 3);
        f << "    }" << (i + 1 < (int)scene.shapes.size() ? "," : "") << "\n";
    }
    f << "  ],\n";

    // Lights
    f << "  \"lights\": [\n";
    for (int i = 0; i < (int)scene.lights.size(); ++i) {
        f << "    {\n";
        write_light(f, scene.lights[i], 3);
        f << "    }" << (i + 1 < (int)scene.lights.size() ? "," : "") << "\n";
    }
    f << "  ]" << (scene.groups.empty() ? "\n" : ",\n");

    // Groups
    if (!scene.groups.empty()) {
        f << "  \"groups\": [\n";
        for (int g = 0; g < (int)scene.groups.size(); ++g) {
            const auto& group = scene.groups[g];
            f << "    {\n";
            f << "      \"name\": "; write_json_string(f, group.name); f << ",\n";
            f << "      \"transform\": {\n";
            f << "        "; write_vec2(f, "translate", group.transform.translate); f << ",\n";
            f << "        \"rotate\": " << fmt(group.transform.rotate) << ",\n";
            f << "        "; write_vec2(f, "scale", group.transform.scale); f << "\n";
            f << "      },\n";

            // Group shapes
            f << "      \"shapes\": [\n";
            for (int i = 0; i < (int)group.shapes.size(); ++i) {
                f << "        {\n";
                write_shape(f, group.shapes[i], 5);
                f << "        }" << (i + 1 < (int)group.shapes.size() ? "," : "") << "\n";
            }
            f << "      ],\n";

            // Group lights
            f << "      \"lights\": [\n";
            for (int i = 0; i < (int)group.lights.size(); ++i) {
                f << "        {\n";
                write_light(f, group.lights[i], 5);
                f << "        }" << (i + 1 < (int)group.lights.size() ? "," : "") << "\n";
            }
            f << "      ]\n";

            f << "    }" << (g + 1 < (int)scene.groups.size() ? "," : "") << "\n";
        }
        f << "  ]\n";
    }
    f << "}\n";

    return true;
}

// ─── Minimal JSON reader ────────────────────────────────────────────────

// A tiny recursive-descent JSON parser — just enough for our scene format.

namespace {

struct JsonValue {
    enum Type { Null, Number, String, Array, Object } type = Null;
    double number = 0;
    std::string str;
    std::vector<JsonValue> arr;
    std::vector<std::string> obj_keys;
    std::vector<JsonValue> obj_vals;

    const JsonValue* get(const std::string& key) const {
        if (type != Object) return nullptr;
        for (int i = 0; i < (int)obj_keys.size(); ++i)
            if (obj_keys[i] == key) return &obj_vals[i];
        return nullptr;
    }

    float as_float(float def = 0) const { return type == Number ? (float)number : def; }
    const std::string& as_string() const { static std::string empty; return type == String ? str : empty; }
};

struct Parser {
    const char* p;
    const char* end;

    void skip_ws() {
        while (p < end && (*p == ' ' || *p == '\n' || *p == '\r' || *p == '\t')) ++p;
    }

    bool match(char c) { skip_ws(); if (p < end && *p == c) { ++p; return true; } return false; }

    std::string parse_string() {
        skip_ws();
        if (p >= end || *p != '"') return {};
        ++p;
        std::string s;
        while (p < end && *p != '"') {
            if (*p == '\\' && p + 1 < end) { ++p; s += *p; }
            else s += *p;
            ++p;
        }
        if (p < end) ++p; // closing "
        return s;
    }

    double parse_number() {
        skip_ws();
        char* num_end = nullptr;
        double val = std::strtod(p, &num_end);
        if (num_end > p) p = num_end;
        return val;
    }

    JsonValue parse_value() {
        skip_ws();
        if (p >= end) return {};

        if (*p == '"') {
            JsonValue v;
            v.type = JsonValue::String;
            v.str = parse_string();
            return v;
        }
        if (*p == '[') {
            ++p;
            JsonValue v;
            v.type = JsonValue::Array;
            skip_ws();
            if (p < end && *p != ']') {
                v.arr.push_back(parse_value());
                while (match(',')) v.arr.push_back(parse_value());
            }
            match(']');
            return v;
        }
        if (*p == '{') {
            ++p;
            JsonValue v;
            v.type = JsonValue::Object;
            skip_ws();
            if (p < end && *p != '}') {
                v.obj_keys.push_back(parse_string());
                match(':');
                v.obj_vals.push_back(parse_value());
                while (match(',')) {
                    v.obj_keys.push_back(parse_string());
                    match(':');
                    v.obj_vals.push_back(parse_value());
                }
            }
            match('}');
            return v;
        }
        if (p + 4 <= end && memcmp(p, "null", 4) == 0) { p += 4; return {}; }
        if (p + 4 <= end && memcmp(p, "true", 4) == 0) { p += 4; JsonValue v; v.type = JsonValue::Number; v.number = 1; return v; }
        if (p + 5 <= end && memcmp(p, "false", 5) == 0) { p += 5; JsonValue v; v.type = JsonValue::Number; v.number = 0; return v; }

        JsonValue v;
        v.type = JsonValue::Number;
        v.number = parse_number();
        return v;
    }
};

static Vec2 read_vec2(const JsonValue* v) {
    if (!v || v->type != JsonValue::Array || v->arr.size() < 2) return {};
    return {v->arr[0].as_float(), v->arr[1].as_float()};
}

static Material read_material_obj(const JsonValue* v) {
    Material m;
    if (!v) return m;
    if (auto* f = v->get("ior")) m.ior = f->as_float(1.0f);
    if (auto* f = v->get("roughness")) m.roughness = f->as_float();
    if (auto* f = v->get("metallic")) m.metallic = f->as_float();
    if (auto* f = v->get("transmission")) m.transmission = f->as_float();
    if (auto* f = v->get("absorption")) m.absorption = f->as_float();
    if (auto* f = v->get("cauchy_b")) m.cauchy_b = f->as_float();
    if (auto* f = v->get("albedo")) m.albedo = f->as_float(1.0f);
    if (auto* f = v->get("emission")) m.emission = f->as_float();
    return m;
}

// Resolve a material from JSON: string → lookup in materials dict, object → inline parse
static Material read_material(const JsonValue* v, const std::map<std::string, Material>& materials) {
    if (!v) return {};
    if (v->type == JsonValue::String) {
        auto it = materials.find(v->str);
        if (it != materials.end()) return it->second;
        std::cerr << "Unknown material: " << v->str << "\n";
        return {};
    }
    return read_material_obj(v);
}

static void read_shapes(const JsonValue* shapes_arr, std::vector<Shape>& out,
                         const std::map<std::string, Material>& materials = {}) {
    if (!shapes_arr) return;
    for (auto& sv : shapes_arr->arr) {
        if (sv.type != JsonValue::Object) continue;
        auto* type = sv.get("type");
        if (!type) continue;
        const auto& t = type->as_string();

        if (t == "circle") {
            Circle c;
            c.center = read_vec2(sv.get("center"));
            if (auto* r = sv.get("radius")) c.radius = r->as_float(0.1f);
            c.material = read_material(sv.get("material"), materials);
            out.push_back(c);
        } else if (t == "segment") {
            Segment s;
            s.a = read_vec2(sv.get("a"));
            s.b = read_vec2(sv.get("b"));
            s.material = read_material(sv.get("material"), materials);
            out.push_back(s);
        } else if (t == "arc") {
            Arc a;
            a.center = read_vec2(sv.get("center"));
            if (auto* r = sv.get("radius")) a.radius = r->as_float(0.1f);
            if (auto* v = sv.get("angle_start")) a.angle_start = normalize_angle(v->as_float());
            if (auto* v = sv.get("sweep")) a.sweep = clamp_arc_sweep(v->as_float(TWO_PI));
            a.material = read_material(sv.get("material"), materials);
            out.push_back(a);
        } else if (t == "bezier") {
            Bezier b;
            b.p0 = read_vec2(sv.get("p0"));
            b.p1 = read_vec2(sv.get("p1"));
            b.p2 = read_vec2(sv.get("p2"));
            b.material = read_material(sv.get("material"), materials);
            out.push_back(b);
        } else if (t == "polygon") {
            Polygon p;
            if (auto* verts = sv.get("vertices")) {
                for (auto& v : verts->arr)
                    p.vertices.push_back(read_vec2(&v));
            }
            p.material = read_material(sv.get("material"), materials);
            out.push_back(p);
        }
    }
}

static void read_lights(const JsonValue* lights_arr, std::vector<Light>& out) {
    if (!lights_arr) return;
    for (auto& lv : lights_arr->arr) {
        if (lv.type != JsonValue::Object) continue;
        auto* type = lv.get("type");
        if (!type) continue;
        const auto& t = type->as_string();

        if (t == "point") {
            PointLight l;
            l.pos = read_vec2(lv.get("pos"));
            if (auto* v = lv.get("intensity")) l.intensity = v->as_float(1.0f);
            if (auto* v = lv.get("wavelength_min")) l.wavelength_min = v->as_float(380.0f);
            if (auto* v = lv.get("wavelength_max")) l.wavelength_max = v->as_float(780.0f);
            out.push_back(l);
        } else if (t == "segment") {
            SegmentLight l;
            l.a = read_vec2(lv.get("a"));
            l.b = read_vec2(lv.get("b"));
            if (auto* v = lv.get("intensity")) l.intensity = v->as_float(1.0f);
            if (auto* v = lv.get("wavelength_min")) l.wavelength_min = v->as_float(380.0f);
            if (auto* v = lv.get("wavelength_max")) l.wavelength_max = v->as_float(780.0f);
            out.push_back(l);
        } else if (t == "beam") {
            BeamLight l;
            l.origin = read_vec2(lv.get("origin"));
            l.direction = read_vec2(lv.get("direction"));
            if (l.direction.length_sq() > 1e-6f) l.direction = l.direction.normalized();
            else l.direction = {1, 0};
            if (auto* v = lv.get("angular_width")) l.angular_width = v->as_float(0.1f);
            if (auto* v = lv.get("intensity")) l.intensity = v->as_float(1.0f);
            if (auto* v = lv.get("wavelength_min")) l.wavelength_min = v->as_float(380.0f);
            if (auto* v = lv.get("wavelength_max")) l.wavelength_max = v->as_float(780.0f);
            out.push_back(l);
        } else if (t == "parallel_beam") {
            ParallelBeamLight l;
            l.a = read_vec2(lv.get("a"));
            l.b = read_vec2(lv.get("b"));
            l.direction = read_vec2(lv.get("direction"));
            if (l.direction.length_sq() > 1e-6f) l.direction = l.direction.normalized();
            else l.direction = {1, 0};
            if (auto* v = lv.get("angular_width")) l.angular_width = v->as_float(0.0f);
            if (auto* v = lv.get("intensity")) l.intensity = v->as_float(1.0f);
            if (auto* v = lv.get("wavelength_min")) l.wavelength_min = v->as_float(380.0f);
            if (auto* v = lv.get("wavelength_max")) l.wavelength_max = v->as_float(780.0f);
            out.push_back(l);
        } else if (t == "spot") {
            SpotLight l;
            l.pos = read_vec2(lv.get("pos"));
            l.direction = read_vec2(lv.get("direction"));
            if (l.direction.length_sq() > 1e-6f) l.direction = l.direction.normalized();
            else l.direction = {1, 0};
            if (auto* v = lv.get("angular_width")) l.angular_width = v->as_float(0.5f);
            if (auto* v = lv.get("falloff")) l.falloff = v->as_float(2.0f);
            if (auto* v = lv.get("intensity")) l.intensity = v->as_float(1.0f);
            if (auto* v = lv.get("wavelength_min")) l.wavelength_min = v->as_float(380.0f);
            if (auto* v = lv.get("wavelength_max")) l.wavelength_max = v->as_float(780.0f);
            out.push_back(l);
        }
    }
}

// ─── Shot-level block readers ───────────────────────────────────────────

static Camera2D read_camera(const JsonValue* v) {
    Camera2D cam;
    if (!v || v->type != JsonValue::Object) return cam;
    if (auto* b = v->get("bounds")) {
        if (b->type == JsonValue::Array && b->arr.size() >= 4) {
            cam.bounds = Bounds{
                {b->arr[0].as_float(), b->arr[1].as_float()},
                {b->arr[2].as_float(), b->arr[3].as_float()}};
        }
    }
    if (auto* c = v->get("center")) cam.center = read_vec2(c);
    if (auto* w = v->get("width")) cam.width = w->as_float();
    return cam;
}

static Canvas read_canvas(const JsonValue* v) {
    Canvas canvas;
    if (!v || v->type != JsonValue::Object) return canvas;
    if (auto* w = v->get("width")) canvas.width = (int)w->number;
    if (auto* h = v->get("height")) canvas.height = (int)h->number;
    return canvas;
}

static Look read_look(const JsonValue* v) {
    Look look;
    if (!v || v->type != JsonValue::Object) return look;
    if (auto* f = v->get("exposure")) look.exposure = f->as_float(2.0f);
    if (auto* f = v->get("contrast")) look.contrast = f->as_float(1.0f);
    if (auto* f = v->get("gamma")) look.gamma = f->as_float(2.2f);
    if (auto* f = v->get("white_point")) look.white_point = f->as_float(1.0f);
    if (auto* f = v->get("tonemap"))
        if (auto tm = parse_tonemap(f->as_string())) look.tone_map = *tm;
    if (auto* f = v->get("normalize"))
        if (auto nm = parse_normalize_mode(f->as_string())) look.normalize = *nm;
    if (auto* f = v->get("normalize_ref")) look.normalize_ref = f->as_float();
    if (auto* f = v->get("normalize_pct")) look.normalize_pct = f->as_float(1.0f);
    if (auto* f = v->get("ambient")) look.ambient = f->as_float();
    if (auto* f = v->get("background")) {
        if (f->type == JsonValue::Array && f->arr.size() >= 3) {
            look.background[0] = f->arr[0].as_float();
            look.background[1] = f->arr[1].as_float();
            look.background[2] = f->arr[2].as_float();
        }
    }
    if (auto* f = v->get("opacity")) look.opacity = f->as_float(1.0f);
    return look;
}

static TraceDefaults read_trace(const JsonValue* v) {
    TraceDefaults trace;
    if (!v || v->type != JsonValue::Object) return trace;
    if (auto* f = v->get("rays")) trace.rays = (int64_t)f->number;
    if (auto* f = v->get("batch")) trace.batch = (int)f->number;
    if (auto* f = v->get("depth")) trace.depth = (int)f->number;
    if (auto* f = v->get("intensity")) trace.intensity = f->as_float(1.0f);
    return trace;
}

} // anonymous namespace

Shot load_shot_json_string(std::string_view json_content) {
    Parser parser{json_content.data(), json_content.data() + json_content.size()};
    JsonValue root = parser.parse_value();

    if (root.type != JsonValue::Object) { std::cerr << "Invalid JSON\n"; return {}; }
    auto* version = root.get("version");
    if (!version || version->type != JsonValue::Number || (int)version->number != SHOT_JSON_VERSION) {
        std::cerr << "Unsupported shot version (expected " << SHOT_JSON_VERSION << ")\n";
        return {};
    }

    Shot shot;
    if (auto* n = root.get("name")) shot.name = n->as_string();

    // Shot-level blocks
    shot.camera = read_camera(root.get("camera"));
    shot.canvas = read_canvas(root.get("canvas"));
    shot.look = read_look(root.get("look"));
    shot.trace = read_trace(root.get("trace"));

    // Scene content
    auto& scene = shot.scene;

    // Parse named materials library (must come before shapes to resolve references)
    if (auto* mats = root.get("materials")) {
        if (mats->type == JsonValue::Object) {
            for (int i = 0; i < (int)mats->obj_keys.size(); ++i)
                scene.materials[mats->obj_keys[i]] = read_material_obj(&mats->obj_vals[i]);
        }
    }

    read_shapes(root.get("shapes"), scene.shapes, scene.materials);
    read_lights(root.get("lights"), scene.lights);

    // Groups
    if (auto* groups = root.get("groups")) {
        for (auto& gv : groups->arr) {
            if (gv.type != JsonValue::Object) continue;
            Group group;
            if (auto* n = gv.get("name")) group.name = n->as_string();
            if (auto* tf = gv.get("transform")) {
                group.transform.translate = read_vec2(tf->get("translate"));
                if (auto* r = tf->get("rotate")) group.transform.rotate = r->as_float();
                group.transform.scale = read_vec2(tf->get("scale"));
                if (group.transform.scale.x == 0) group.transform.scale.x = 1;
                if (group.transform.scale.y == 0) group.transform.scale.y = 1;
            }
            read_shapes(gv.get("shapes"), group.shapes, scene.materials);
            read_lights(gv.get("lights"), group.lights);
            if (!group.shapes.empty() || !group.lights.empty())
                scene.groups.push_back(std::move(group));
        }
    }

    return shot;
}

Shot load_shot_json(const std::string& path) {
    std::ifstream f(path);
    if (!f) { std::cerr << "Failed to open " << path << "\n"; return {}; }

    std::string content((std::istreambuf_iterator<char>(f)), std::istreambuf_iterator<char>());
    return load_shot_json_string(content);
}

FrameOverrides parse_frame_overrides(std::string_view json) {
    FrameOverrides fo;
    Parser parser{json.data(), json.data() + json.size()};
    JsonValue root = parser.parse_value();
    if (root.type != JsonValue::Object) return fo;

    auto* render = root.get("render");
    if (!render || render->type != JsonValue::Object) return fo;

    if (auto* v = render->get("rays")) fo.rays = (int64_t)v->number;
    if (auto* v = render->get("batch")) fo.batch = (int)v->number;
    if (auto* v = render->get("depth")) fo.depth = (int)v->number;
    if (auto* v = render->get("exposure")) fo.exposure = v->as_float();
    if (auto* v = render->get("contrast")) fo.contrast = v->as_float();
    if (auto* v = render->get("gamma")) fo.gamma = v->as_float();
    if (auto* v = render->get("white_point")) fo.white_point = v->as_float();
    if (auto* v = render->get("tonemap"))
        fo.tonemap = parse_tonemap(v->as_string());
    if (auto* v = render->get("bounds")) {
        if (v->type == JsonValue::Array && v->arr.size() >= 4) {
            fo.bounds = Bounds{
                {v->arr[0].as_float(), v->arr[1].as_float()},
                {v->arr[2].as_float(), v->arr[3].as_float()}};
        }
    }
    if (auto* v = render->get("normalize"))
        fo.normalize = parse_normalize_mode(v->as_string());
    if (auto* v = render->get("normalize_ref")) fo.normalize_ref = v->as_float();
    if (auto* v = render->get("normalize_pct")) fo.normalize_pct = v->as_float();
    if (auto* v = render->get("ambient")) fo.ambient = v->as_float();
    if (auto* v = render->get("background")) {
        if (v->type == JsonValue::Array && v->arr.size() >= 3) {
            fo.background = {v->arr[0].as_float(), v->arr[1].as_float(), v->arr[2].as_float()};
        }
    }
    if (auto* v = render->get("opacity")) fo.opacity = v->as_float();
    if (auto* v = render->get("intensity")) fo.intensity = v->as_float();

    return fo;
}
