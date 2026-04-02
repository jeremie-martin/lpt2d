#include "serialize.h"

#include <fstream>
#include <iostream>
#include <string>

// ─── Minimal JSON writer ────────────────────────────────────────────────

static void write_indent(std::ostream& os, int depth) {
    for (int i = 0; i < depth; ++i) os << "  ";
}

static void write_material(std::ostream& os, const Material& m, int depth) {
    write_indent(os, depth); os << "\"material\": {\n";
    write_indent(os, depth + 1); os << "\"ior\": " << m.ior << ",\n";
    write_indent(os, depth + 1); os << "\"roughness\": " << m.roughness << ",\n";
    write_indent(os, depth + 1); os << "\"metallic\": " << m.metallic << ",\n";
    write_indent(os, depth + 1); os << "\"transmission\": " << m.transmission << ",\n";
    write_indent(os, depth + 1); os << "\"absorption\": " << m.absorption << ",\n";
    write_indent(os, depth + 1); os << "\"cauchy_b\": " << m.cauchy_b << ",\n";
    write_indent(os, depth + 1); os << "\"albedo\": " << m.albedo << "\n";
    write_indent(os, depth); os << "}";
}

static void write_vec2(std::ostream& os, const char* name, Vec2 v) {
    os << "\"" << name << "\": [" << v.x << ", " << v.y << "]";
}

bool save_scene_json(const Scene& scene, const std::string& path) {
    std::ofstream f(path);
    if (!f) { std::cerr << "Failed to open " << path << " for writing\n"; return false; }

    f << std::defaultfloat;
    f.precision(8);

    f << "{\n";
    f << "  \"version\": 1,\n";
    f << "  \"name\": \"" << scene.name << "\",\n";

    // Shapes
    f << "  \"shapes\": [\n";
    for (int i = 0; i < (int)scene.shapes.size(); ++i) {
        f << "    {\n";
        std::visit(overloaded{
            [&](const Circle& c) {
                f << "      \"type\": \"circle\",\n";
                f << "      "; write_vec2(f, "center", c.center); f << ",\n";
                f << "      \"radius\": " << c.radius << ",\n";
                write_material(f, c.material, 3); f << "\n";
            },
            [&](const Segment& s) {
                f << "      \"type\": \"segment\",\n";
                f << "      "; write_vec2(f, "a", s.a); f << ",\n";
                f << "      "; write_vec2(f, "b", s.b); f << ",\n";
                write_material(f, s.material, 3); f << "\n";
            },
            [&](const Arc& a) {
                f << "      \"type\": \"arc\",\n";
                f << "      "; write_vec2(f, "center", a.center); f << ",\n";
                f << "      \"radius\": " << a.radius << ",\n";
                f << "      \"angle_start\": " << a.angle_start << ",\n";
                f << "      \"angle_end\": " << a.angle_end << ",\n";
                write_material(f, a.material, 3); f << "\n";
            },
            [&](const Bezier& b) {
                f << "      \"type\": \"bezier\",\n";
                f << "      "; write_vec2(f, "p0", b.p0); f << ",\n";
                f << "      "; write_vec2(f, "p1", b.p1); f << ",\n";
                f << "      "; write_vec2(f, "p2", b.p2); f << ",\n";
                write_material(f, b.material, 3); f << "\n";
            },
        }, scene.shapes[i]);
        f << "    }" << (i + 1 < (int)scene.shapes.size() ? "," : "") << "\n";
    }
    f << "  ],\n";

    // Lights
    f << "  \"lights\": [\n";
    for (int i = 0; i < (int)scene.lights.size(); ++i) {
        f << "    {\n";
        std::visit(overloaded{
            [&](const PointLight& l) {
                f << "      \"type\": \"point\",\n";
                f << "      "; write_vec2(f, "pos", l.pos); f << ",\n";
                f << "      \"intensity\": " << l.intensity << ",\n";
                f << "      \"wavelength_min\": " << l.wavelength_min << ",\n";
                f << "      \"wavelength_max\": " << l.wavelength_max << "\n";
            },
            [&](const SegmentLight& l) {
                f << "      \"type\": \"segment\",\n";
                f << "      "; write_vec2(f, "a", l.a); f << ",\n";
                f << "      "; write_vec2(f, "b", l.b); f << ",\n";
                f << "      \"intensity\": " << l.intensity << ",\n";
                f << "      \"wavelength_min\": " << l.wavelength_min << ",\n";
                f << "      \"wavelength_max\": " << l.wavelength_max << "\n";
            },
            [&](const BeamLight& l) {
                f << "      \"type\": \"beam\",\n";
                f << "      "; write_vec2(f, "origin", l.origin); f << ",\n";
                f << "      "; write_vec2(f, "direction", l.direction); f << ",\n";
                f << "      \"angular_width\": " << l.angular_width << ",\n";
                f << "      \"intensity\": " << l.intensity << ",\n";
                f << "      \"wavelength_min\": " << l.wavelength_min << ",\n";
                f << "      \"wavelength_max\": " << l.wavelength_max << "\n";
            },
        }, scene.lights[i]);
        f << "    }" << (i + 1 < (int)scene.lights.size() ? "," : "") << "\n";
    }
    f << "  ]\n";
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
        const char* start = p;
        if (p < end && (*p == '-' || *p == '+')) ++p;
        while (p < end && ((*p >= '0' && *p <= '9') || *p == '.' || *p == 'e' || *p == 'E' || *p == '+' || *p == '-')) ++p;
        return std::strtod(start, nullptr);
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
        if (*p == 'n' && p + 4 <= end) { p += 4; return {}; } // null
        if (*p == 't' && p + 4 <= end) { p += 4; JsonValue v; v.type = JsonValue::Number; v.number = 1; return v; }
        if (*p == 'f' && p + 5 <= end) { p += 5; JsonValue v; v.type = JsonValue::Number; v.number = 0; return v; }

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

static Material read_material(const JsonValue* v) {
    Material m;
    if (!v) return m;
    if (auto* f = v->get("ior")) m.ior = f->as_float(1.0f);
    if (auto* f = v->get("roughness")) m.roughness = f->as_float();
    if (auto* f = v->get("metallic")) m.metallic = f->as_float();
    if (auto* f = v->get("transmission")) m.transmission = f->as_float();
    if (auto* f = v->get("absorption")) m.absorption = f->as_float();
    if (auto* f = v->get("cauchy_b")) m.cauchy_b = f->as_float();
    if (auto* f = v->get("albedo")) m.albedo = f->as_float(1.0f);
    return m;
}

} // anonymous namespace

Scene load_scene_json(const std::string& path) {
    std::ifstream f(path);
    if (!f) { std::cerr << "Failed to open " << path << "\n"; return {}; }

    std::string content((std::istreambuf_iterator<char>(f)), std::istreambuf_iterator<char>());
    Parser parser{content.data(), content.data() + content.size()};
    JsonValue root = parser.parse_value();

    if (root.type != JsonValue::Object) { std::cerr << "Invalid JSON\n"; return {}; }

    Scene scene;
    if (auto* n = root.get("name")) scene.name = n->as_string();

    // Shapes
    if (auto* shapes = root.get("shapes")) {
        for (auto& sv : shapes->arr) {
            if (sv.type != JsonValue::Object) continue;
            auto* type = sv.get("type");
            if (!type) continue;
            const auto& t = type->as_string();

            if (t == "circle") {
                Circle c;
                c.center = read_vec2(sv.get("center"));
                if (auto* r = sv.get("radius")) c.radius = r->as_float(0.1f);
                c.material = read_material(sv.get("material"));
                scene.shapes.push_back(c);
            } else if (t == "segment") {
                Segment s;
                s.a = read_vec2(sv.get("a"));
                s.b = read_vec2(sv.get("b"));
                s.material = read_material(sv.get("material"));
                scene.shapes.push_back(s);
            } else if (t == "arc") {
                Arc a;
                a.center = read_vec2(sv.get("center"));
                if (auto* r = sv.get("radius")) a.radius = r->as_float(0.1f);
                if (auto* v = sv.get("angle_start")) a.angle_start = v->as_float();
                if (auto* v = sv.get("angle_end")) a.angle_end = v->as_float(TWO_PI);
                a.material = read_material(sv.get("material"));
                scene.shapes.push_back(a);
            } else if (t == "bezier") {
                Bezier b;
                b.p0 = read_vec2(sv.get("p0"));
                b.p1 = read_vec2(sv.get("p1"));
                b.p2 = read_vec2(sv.get("p2"));
                b.material = read_material(sv.get("material"));
                scene.shapes.push_back(b);
            }
        }
    }

    // Lights
    if (auto* lights = root.get("lights")) {
        for (auto& lv : lights->arr) {
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
                scene.lights.push_back(l);
            } else if (t == "segment") {
                SegmentLight l;
                l.a = read_vec2(lv.get("a"));
                l.b = read_vec2(lv.get("b"));
                if (auto* v = lv.get("intensity")) l.intensity = v->as_float(1.0f);
                if (auto* v = lv.get("wavelength_min")) l.wavelength_min = v->as_float(380.0f);
                if (auto* v = lv.get("wavelength_max")) l.wavelength_max = v->as_float(780.0f);
                scene.lights.push_back(l);
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
                scene.lights.push_back(l);
            }
        }
    }

    return scene;
}
