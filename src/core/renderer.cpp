#include "renderer.h"

#include "geometry.h"
#include "scene.h"
#include "shaders.h"
#include "spectrum.h"

#include <algorithm>
#include <cmath>
#include <iostream>
#include <iterator>
#include <variant>

// ─── Shader compilation helpers ──────────────────────────────────────

static GLuint compile_shader(GLenum type, const char* src) {
    GLuint shader = glCreateShader(type);
    glShaderSource(shader, 1, &src, nullptr);
    glCompileShader(shader);

    GLint ok;
    glGetShaderiv(shader, GL_COMPILE_STATUS, &ok);
    if (!ok) {
        char log[1024];
        glGetShaderInfoLog(shader, sizeof(log), nullptr, log);
        std::cerr << "Shader compile error: " << log << "\n";
        glDeleteShader(shader);
        return 0;
    }
    return shader;
}

static GLuint link_program(GLuint vert, GLuint frag) {
    GLuint prog = glCreateProgram();
    glAttachShader(prog, vert);
    glAttachShader(prog, frag);
    glLinkProgram(prog);

    GLint ok;
    glGetProgramiv(prog, GL_LINK_STATUS, &ok);
    if (!ok) {
        char log[1024];
        glGetProgramInfoLog(prog, sizeof(log), nullptr, log);
        std::cerr << "Shader link error: " << log << "\n";
        glDeleteProgram(prog);
        return 0;
    }

    glDeleteShader(vert);
    glDeleteShader(frag);
    return prog;
}

static GLuint link_compute(GLuint cs) {
    GLuint prog = glCreateProgram();
    glAttachShader(prog, cs);
    glLinkProgram(prog);

    GLint ok;
    glGetProgramiv(prog, GL_LINK_STATUS, &ok);
    if (!ok) {
        char log[1024];
        glGetProgramInfoLog(prog, sizeof(log), nullptr, log);
        std::cerr << "Compute link error: " << log << "\n";
        glDeleteProgram(prog);
        return 0;
    }
    glDeleteShader(cs);
    return prog;
}

static uint32_t mix_seed_component(uint32_t value) {
    value ^= value >> 16;
    value *= 0x7feb352du;
    value ^= value >> 15;
    value *= 0x846ca68bu;
    value ^= value >> 16;
    return value;
}

static uint32_t trace_dispatch_seed(const TraceConfig& cfg, uint32_t batch_counter) {
    uint32_t seed = batch_counter * 1000003u + 42u;
    if (cfg.seed_mode == SeedMode::Deterministic)
        return seed;

    uint32_t frame_salt = mix_seed_component(static_cast<uint32_t>(cfg.frame_index) + 0x9e3779b9u);
    return seed ^ frame_salt;
}

// ─── GPU data structures (must match GLSL layout under std430) ───────

struct GPUCircle {
    float center[2];
    float radius;
    float ior, roughness, metallic, transmission;
    float absorption, cauchy_b, albedo;
    float emission;
    float _pad; // std430: vec2 center gives alignment 8, stride must be multiple of 8
};
static_assert(sizeof(GPUCircle) == 48);

struct GPUSegment {
    float a[2];
    float b[2];
    float ior, roughness, metallic, transmission;
    float absorption, cauchy_b, albedo;
    float emission;
};
static_assert(sizeof(GPUSegment) == 48);

struct GPULight {
    uint32_t type; // 0=point, 1=segment, 2=beam, 3=parallel_beam, 4=spot
    float intensity;
    float pos_a[2];
    float pos_b[2];
    float dir[2];         // direction for parallel_beam (3) and spot (4)
    float angular_width;  // half-angle radians (converted at upload), 0 for point/segment
    float falloff;        // spot cosine-power exponent, 0 for non-spot types
    float wavelength_min; // nm, default 380
    float wavelength_max; // nm, default 780
};
static_assert(sizeof(GPULight) == 48);

struct GPUArc {
    float center[2];
    float radius;
    float angle_start;
    float sweep;
    float _pad0;
    float ior, roughness, metallic, transmission;
    float absorption, cauchy_b, albedo;
    float emission;
};
static_assert(sizeof(GPUArc) == 56);

struct GPUBezier {
    float p0[2];
    float p1[2]; // control point
    float p2[2];
    float ior, roughness, metallic, transmission;
    float absorption, cauchy_b, albedo;
    float emission;
};
static_assert(sizeof(GPUBezier) == 56);

struct GPUEllipse {
    float center[2];
    float semi_a, semi_b;
    float rotation;
    float _pad;
    float ior, roughness, metallic, transmission;
    float absorption, cauchy_b, albedo, emission;
};
static_assert(sizeof(GPUEllipse) == 56);

// ─── Renderer implementation ─────────────────────────────────────────

Renderer::~Renderer() { shutdown(); }

bool Renderer::init(int width, int height, bool half_float) {
    width_ = width;
    height_ = height;
    half_precision_ = half_float;

    glewExperimental = GL_TRUE;
    if (glewContextInit() != GLEW_OK) {
        std::cerr << "Failed to initialize GLEW\n";
        return false;
    }

    // Verify GL 4.3+
    GLint major, minor;
    glGetIntegerv(GL_MAJOR_VERSION, &major);
    glGetIntegerv(GL_MINOR_VERSION, &minor);
    if (major < 4 || (major == 4 && minor < 3)) {
        std::cerr << "OpenGL 4.3+ required (got " << major << "." << minor << ")\n";
        return false;
    }

    if (!create_framebuffers())
        return false;
    if (!create_trace_shader())
        return false;
    if (!create_line_shader())
        return false;
    if (!create_pp_shader())
        return false;
    if (!create_compute_shader())
        return false;

    create_wavelength_lut();

    // Empty VAO for instanced line drawing (data comes from SSBO)
    glGenVertexArrays(1, &line_vao_);

    // Post-process VAO (fullscreen triangle via gl_VertexID)
    glGenVertexArrays(1, &pp_vao_);

    rgba_buffer_.resize(width * height * 4);

    return true;
}

void Renderer::resize(int width, int height) {
    if (width == width_ && height == height_) return;
    glFinish();
    delete_framebuffers();
    width_ = width;
    height_ = height;
    if (!create_framebuffers())
        std::cerr << "Renderer: framebuffer recreation failed on resize\n";
    rgba_buffer_.resize(width * height * 4);
}

void Renderer::shutdown() {
    delete_framebuffers();

    auto del_prog = [](GLuint& p) {
        if (p) { glDeleteProgram(p); p = 0; }
    };
    del_prog(trace_program_);
    del_prog(line_program_);
    del_prog(pp_program_);
    del_prog(max_compute_);

    auto del_buf = [](GLuint& b) {
        if (b) { glDeleteBuffers(1, &b); b = 0; }
    };
    del_buf(circle_ssbo_);
    del_buf(segment_ssbo_);
    del_buf(arc_ssbo_);
    del_buf(bezier_ssbo_);
    del_buf(ellipse_ssbo_);
    del_buf(light_ssbo_);
    del_buf(light_weights_ssbo_);
    del_buf(output_ssbo_);
    del_buf(draw_cmd_buffer_);
    del_buf(max_ssbo_);

    auto del_vao = [](GLuint& v) {
        if (v) { glDeleteVertexArrays(1, &v); v = 0; }
    };
    del_vao(line_vao_);
    del_vao(pp_vao_);

    if (wavelength_lut_) {
        glDeleteTextures(1, &wavelength_lut_);
        wavelength_lut_ = 0;
    }
}

bool Renderer::create_framebuffers() {
    // Float accumulation texture
    glGenTextures(1, &float_texture_);
    glBindTexture(GL_TEXTURE_2D, float_texture_);
    glTexImage2D(GL_TEXTURE_2D, 0, half_precision_ ? GL_RGBA16F : GL_RGBA32F,
                 width_, height_, 0, GL_RGBA, GL_FLOAT, nullptr);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);

    glGenFramebuffers(1, &fbo_);
    glBindFramebuffer(GL_FRAMEBUFFER, fbo_);
    glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D, float_texture_, 0);
    if (glCheckFramebufferStatus(GL_FRAMEBUFFER) != GL_FRAMEBUFFER_COMPLETE) {
        std::cerr << "Float FBO incomplete\n";
        return false;
    }

    // Display texture (8-bit)
    glGenTextures(1, &display_texture_);
    glBindTexture(GL_TEXTURE_2D, display_texture_);
    glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA8, width_, height_, 0, GL_RGBA, GL_UNSIGNED_BYTE, nullptr);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_BORDER);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_BORDER);
    float black[] = {0.0f, 0.0f, 0.0f, 1.0f};
    glTexParameterfv(GL_TEXTURE_2D, GL_TEXTURE_BORDER_COLOR, black);

    glGenFramebuffers(1, &display_fbo_);
    glBindFramebuffer(GL_FRAMEBUFFER, display_fbo_);
    glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D, display_texture_, 0);
    if (glCheckFramebufferStatus(GL_FRAMEBUFFER) != GL_FRAMEBUFFER_COMPLETE) {
        std::cerr << "Display FBO incomplete\n";
        return false;
    }

    glBindFramebuffer(GL_FRAMEBUFFER, 0);
    return true;
}

void Renderer::delete_framebuffers() {
    if (fbo_) { glDeleteFramebuffers(1, &fbo_); fbo_ = 0; }
    if (display_fbo_) { glDeleteFramebuffers(1, &display_fbo_); display_fbo_ = 0; }
    if (float_texture_) { glDeleteTextures(1, &float_texture_); float_texture_ = 0; }
    if (display_texture_) { glDeleteTextures(1, &display_texture_); display_texture_ = 0; }
}

bool Renderer::create_trace_shader() {
    GLuint cs = compile_shader(GL_COMPUTE_SHADER, trace_comp);
    if (!cs) return false;
    trace_program_ = link_compute(cs);
    if (!trace_program_) return false;

    trace_loc_num_circles_ = glGetUniformLocation(trace_program_, "uNumCircles");
    trace_loc_num_segments_ = glGetUniformLocation(trace_program_, "uNumSegments");
    trace_loc_num_arcs_ = glGetUniformLocation(trace_program_, "uNumArcs");
    trace_loc_num_beziers_ = glGetUniformLocation(trace_program_, "uNumBeziers");
    trace_loc_num_ellipses_ = glGetUniformLocation(trace_program_, "uNumEllipses");
    trace_loc_num_lights_ = glGetUniformLocation(trace_program_, "uNumLights");
    trace_loc_max_depth_ = glGetUniformLocation(trace_program_, "uMaxDepth");
    trace_loc_seed_ = glGetUniformLocation(trace_program_, "uSeed");
    trace_loc_intensity_ = glGetUniformLocation(trace_program_, "uIntensity");
    trace_loc_max_segments_ = glGetUniformLocation(trace_program_, "uMaxSegments");
    trace_loc_bounds_min_ = glGetUniformLocation(trace_program_, "uBoundsMin");
    trace_loc_view_scale_ = glGetUniformLocation(trace_program_, "uViewScale");
    trace_loc_view_offset_ = glGetUniformLocation(trace_program_, "uViewOffset");
    trace_loc_wavelength_lut_ = glGetUniformLocation(trace_program_, "uWavelengthLUT");
    return true;
}

bool Renderer::create_line_shader() {
    GLuint v = compile_shader(GL_VERTEX_SHADER, line_vert);
    GLuint f = compile_shader(GL_FRAGMENT_SHADER, line_frag);
    if (!v || !f) return false;
    line_program_ = link_program(v, f);
    if (!line_program_) return false;
    loc_resolution_ = glGetUniformLocation(line_program_, "uResolution");
    loc_thickness_ = glGetUniformLocation(line_program_, "uThickness");
    return true;
}

bool Renderer::create_pp_shader() {
    GLuint v = compile_shader(GL_VERTEX_SHADER, postprocess_vert);
    GLuint f = compile_shader(GL_FRAGMENT_SHADER, postprocess_frag);
    if (!v || !f) return false;
    pp_program_ = link_program(v, f);
    if (!pp_program_) return false;
    loc_max_val_ = glGetUniformLocation(pp_program_, "uMaxVal");
    loc_exposure_ = glGetUniformLocation(pp_program_, "uExposureMult");
    loc_contrast_ = glGetUniformLocation(pp_program_, "uContrast");
    loc_inv_gamma_ = glGetUniformLocation(pp_program_, "uInvGamma");
    loc_tone_map_ = glGetUniformLocation(pp_program_, "uToneMapOp");
    loc_white_point_ = glGetUniformLocation(pp_program_, "uWhitePoint");
    loc_float_tex_ = glGetUniformLocation(pp_program_, "uFloatTexture");
    loc_ambient_ = glGetUniformLocation(pp_program_, "uAmbient");
    loc_background_ = glGetUniformLocation(pp_program_, "uBackground");
    loc_opacity_ = glGetUniformLocation(pp_program_, "uOpacity");
    loc_saturation_ = glGetUniformLocation(pp_program_, "uSaturation");
    loc_vignette_ = glGetUniformLocation(pp_program_, "uVignette");
    loc_vignette_radius_ = glGetUniformLocation(pp_program_, "uVignetteRadius");
    loc_vignette_center_ = glGetUniformLocation(pp_program_, "uVignetteCenter");
    loc_vignette_inv_size_ = glGetUniformLocation(pp_program_, "uVignetteInvSize");
    loc_vignette_x_scale_ = glGetUniformLocation(pp_program_, "uVignetteXScale");
    loc_temperature_ = glGetUniformLocation(pp_program_, "uTemperature");
    loc_highlights_ = glGetUniformLocation(pp_program_, "uHighlights");
    loc_shadows_ = glGetUniformLocation(pp_program_, "uShadows");
    loc_hue_rot_ = glGetUniformLocation(pp_program_, "uHueRot");
    loc_grain_ = glGetUniformLocation(pp_program_, "uGrain");
    loc_grain_seed_ = glGetUniformLocation(pp_program_, "uGrainSeed");
    loc_chromatic_aberration_ = glGetUniformLocation(pp_program_, "uChromaticAberration");
    return true;
}

bool Renderer::create_compute_shader() {
    GLuint cs = compile_shader(GL_COMPUTE_SHADER, max_reduce_comp);
    if (!cs) return false;
    max_compute_ = link_compute(cs);
    if (!max_compute_) return false;

    max_loc_input_texture_ = glGetUniformLocation(max_compute_, "uInputTexture");
    max_loc_tex_size_ = glGetUniformLocation(max_compute_, "uTexSize");

    glGenBuffers(1, &max_ssbo_);
    glBindBuffer(GL_SHADER_STORAGE_BUFFER, max_ssbo_);
    glBufferData(GL_SHADER_STORAGE_BUFFER, sizeof(uint32_t), nullptr, GL_DYNAMIC_READ);
    glBindBuffer(GL_SHADER_STORAGE_BUFFER, 0);
    return true;
}

void Renderer::create_wavelength_lut() {
    // Build 401-entry RGB LUT [380..780nm]
    std::vector<float> lut(401 * 3);
    for (int i = 0; i <= 400; ++i) {
        Vec3 rgb = wavelength_to_rgb(380.0f + i);
        lut[i * 3 + 0] = rgb.r;
        lut[i * 3 + 1] = rgb.g;
        lut[i * 3 + 2] = rgb.b;
    }

    glGenTextures(1, &wavelength_lut_);
    glBindTexture(GL_TEXTURE_1D, wavelength_lut_);
    glTexImage1D(GL_TEXTURE_1D, 0, GL_RGB32F, 401, 0, GL_RGB, GL_FLOAT, lut.data());
    glTexParameteri(GL_TEXTURE_1D, GL_TEXTURE_MIN_FILTER, GL_LINEAR);
    glTexParameteri(GL_TEXTURE_1D, GL_TEXTURE_MAG_FILTER, GL_LINEAR);
    glTexParameteri(GL_TEXTURE_1D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
    glBindTexture(GL_TEXTURE_1D, 0);
}

float Renderer::compute_max_gpu(float percentile) {
    // CPU readback via glReadPixels — the only reliable path on NVIDIA EGL.
    // texelFetch and glGetTexImage return stale/zero data after many
    // additive-blend draw operations (documented NVIDIA driver quirk).
    glFinish();
    glBindFramebuffer(GL_FRAMEBUFFER, fbo_);
    std::vector<float> buf(width_ * height_ * 4);
    glReadPixels(0, 0, width_, height_, GL_RGBA, GL_FLOAT, buf.data());
    glBindFramebuffer(GL_FRAMEBUFFER, 0);

    // Always compute the true max (for last_max_ / metadata).
    float max_val = 0.0f;
    for (size_t i = 0; i < buf.size(); i += 4) {
        max_val = std::max(max_val, buf[i]);
        max_val = std::max(max_val, buf[i + 1]);
        max_val = std::max(max_val, buf[i + 2]);
    }
    last_max_ = max_val;

    if (percentile >= 1.0f)
        return max_val;

    // Percentile path: collect per-pixel RGB max (non-zero only),
    // use nth_element (O(n) average).
    std::vector<float> lum;
    lum.reserve(width_ * height_);
    for (size_t i = 0; i < buf.size(); i += 4) {
        float v = std::max({buf[i], buf[i + 1], buf[i + 2]});
        if (v > 0.0f) lum.push_back(v);
    }
    if (lum.empty()) return 0.0f;
    size_t idx = std::min((size_t)(percentile * (double)(lum.size() - 1)), lum.size() - 1);
    std::nth_element(lum.begin(), lum.begin() + (ptrdiff_t)idx, lum.end());
    return lum[idx];
}

float Renderer::compute_current_max() {
    return compute_max_gpu(1.0f);
}

void Renderer::clear() {
    glBindFramebuffer(GL_FRAMEBUFFER, fbo_);
    glClearColor(0.0f, 0.0f, 0.0f, 0.0f);
    glClear(GL_COLOR_BUFFER_BIT);
    glBindFramebuffer(GL_FRAMEBUFFER, 0);
    batch_counter_ = 0;
    total_rays_ = 0;
}

// ─── Scene upload ────────────────────────────────────────────────────

void Renderer::upload_scene(const Scene& scene, const Bounds& bounds) {
    // Flatten scene shapes into GPU arrays
    std::vector<GPUCircle> circles;
    std::vector<GPUSegment> segs;
    std::vector<GPUArc> gpu_arcs;
    std::vector<GPUBezier> gpu_beziers;
    std::vector<GPUEllipse> gpu_ellipses;

    auto fill_material = [](auto& gpu, const Material& mat) {
        gpu.ior = mat.ior;
        gpu.roughness = mat.roughness;
        gpu.metallic = mat.metallic;
        gpu.transmission = mat.transmission;
        gpu.absorption = mat.absorption;
        gpu.cauchy_b = mat.cauchy_b;
        gpu.albedo = mat.albedo;
        gpu.emission = mat.emission;
    };

    // Collect all world-space shapes (ungrouped + transformed group shapes)
    std::vector<Shape> all_shapes(scene.shapes.begin(), scene.shapes.end());
    for (const auto& group : scene.groups)
        for (const auto& shape : group.shapes)
            all_shapes.push_back(transform_shape(shape, group.transform));

    for (const auto& shape : all_shapes) {
        std::visit(overloaded{
            [&](const Circle& c) {
                GPUCircle gc{};
                gc.center[0] = c.center.x;
                gc.center[1] = c.center.y;
                gc.radius = c.radius;
                fill_material(gc, resolve_binding(c.binding, scene.materials));
                circles.push_back(gc);
            },
            [&](const Segment& s) {
                GPUSegment gs{};
                gs.a[0] = s.a.x; gs.a[1] = s.a.y;
                gs.b[0] = s.b.x; gs.b[1] = s.b.y;
                fill_material(gs, resolve_binding(s.binding, scene.materials));
                segs.push_back(gs);
            },
            [&](const Arc& a) {
                GPUArc ga{};
                ga.center[0] = a.center.x; ga.center[1] = a.center.y;
                ga.radius = a.radius;
                ga.angle_start = a.angle_start;
                ga.sweep = a.sweep;
                fill_material(ga, resolve_binding(a.binding, scene.materials));
                gpu_arcs.push_back(ga);
            },
            [&](const Bezier& b) {
                GPUBezier gb{};
                gb.p0[0] = b.p0.x; gb.p0[1] = b.p0.y;
                gb.p1[0] = b.p1.x; gb.p1[1] = b.p1.y;
                gb.p2[0] = b.p2.x; gb.p2[1] = b.p2.y;
                fill_material(gb, resolve_binding(b.binding, scene.materials));
                gpu_beziers.push_back(gb);
            },
            [&](const Polygon& p) {
                int n = (int)p.vertices.size();
                if (n < 2) return;
                const Material& mat = resolve_binding(p.binding, scene.materials);

                if (p.corner_radius > 0.0f && n >= 3) {
                    auto parts = decompose_rounded_polygon(p);
                    if (!parts.edges.empty() || !parts.corners.empty()) {
                        for (auto& e : parts.edges) {
                            GPUSegment gs{};
                            gs.a[0] = e.a.x; gs.a[1] = e.a.y;
                            gs.b[0] = e.b.x; gs.b[1] = e.b.y;
                            fill_material(gs, mat);
                            segs.push_back(gs);
                        }
                        for (auto& c : parts.corners) {
                            GPUArc ga{};
                            ga.center[0] = c.center.x; ga.center[1] = c.center.y;
                            ga.radius = c.radius;
                            ga.angle_start = c.angle_start;
                            ga.sweep = c.sweep;
                            fill_material(ga, mat);
                            gpu_arcs.push_back(ga);
                        }
                        return;
                    }
                }

                // Sharp polygon fallback
                bool clockwise = polygon_is_clockwise(p);
                for (int i = 0; i < n; ++i) {
                    Vec2 a = p.vertices[i];
                    Vec2 b = p.vertices[(i + 1) % n];
                    GPUSegment gs{};
                    Vec2 edge_a = clockwise ? a : b;
                    Vec2 edge_b = clockwise ? b : a;
                    gs.a[0] = edge_a.x; gs.a[1] = edge_a.y;
                    gs.b[0] = edge_b.x; gs.b[1] = edge_b.y;
                    fill_material(gs, mat);
                    segs.push_back(gs);
                }
            },
            [&](const Ellipse& e) {
                GPUEllipse ge{};
                ge.center[0] = e.center.x; ge.center[1] = e.center.y;
                ge.semi_a = e.semi_a;
                ge.semi_b = e.semi_b;
                ge.rotation = e.rotation;
                fill_material(ge, resolve_binding(e.binding, scene.materials));
                gpu_ellipses.push_back(ge);
            },
        }, shape);
    }

    // Collect all world-space lights (ungrouped + transformed group lights)
    std::vector<Light> all_lights(scene.lights.begin(), scene.lights.end());
    for (const auto& group : scene.groups)
        for (const auto& light : group.lights)
            all_lights.push_back(transform_light(light, group.transform));

    for (const auto& shape : all_shapes) {
        auto el = emission_light(shape, scene.materials);
        all_lights.insert(all_lights.end(), el.begin(), el.end());
    }

    std::vector<GPULight> gpu_lights;
    std::vector<float> cum_weights;
    float total = 0.0f;

    for (const auto& light : all_lights) {
        GPULight gl{};
        std::visit(overloaded{
            [&](const PointLight& l) {
                gl.type = 0;
                gl.intensity = l.intensity;
                gl.pos_a[0] = l.pos.x; gl.pos_a[1] = l.pos.y;
                gl.wavelength_min = l.wavelength_min;
                gl.wavelength_max = l.wavelength_max;
            },
            [&](const SegmentLight& l) {
                gl.type = 1;
                gl.intensity = l.intensity;
                gl.pos_a[0] = l.a.x; gl.pos_a[1] = l.a.y;
                gl.pos_b[0] = l.b.x; gl.pos_b[1] = l.b.y;
                gl.wavelength_min = l.wavelength_min;
                gl.wavelength_max = l.wavelength_max;
            },
            [&](const BeamLight& l) {
                gl.type = 2;
                gl.intensity = l.intensity;
                gl.pos_a[0] = l.origin.x; gl.pos_a[1] = l.origin.y;
                Vec2 d = l.direction.normalized();
                gl.pos_b[0] = d.x; gl.pos_b[1] = d.y;
                gl.angular_width = l.angular_width * 0.5f; // store half-angle
                gl.wavelength_min = l.wavelength_min;
                gl.wavelength_max = l.wavelength_max;
            },
            [&](const ParallelBeamLight& l) {
                gl.type = 3;
                gl.intensity = l.intensity;
                gl.pos_a[0] = l.a.x; gl.pos_a[1] = l.a.y;
                gl.pos_b[0] = l.b.x; gl.pos_b[1] = l.b.y;
                Vec2 d = l.direction.normalized();
                gl.dir[0] = d.x; gl.dir[1] = d.y;
                gl.angular_width = l.angular_width * 0.5f; // store half-angle
                gl.wavelength_min = l.wavelength_min;
                gl.wavelength_max = l.wavelength_max;
            },
            [&](const SpotLight& l) {
                gl.type = 4;
                gl.intensity = l.intensity;
                gl.pos_a[0] = l.pos.x; gl.pos_a[1] = l.pos.y;
                Vec2 d = l.direction.normalized();
                gl.dir[0] = d.x; gl.dir[1] = d.y;
                gl.angular_width = l.angular_width * 0.5f; // store half-angle
                gl.falloff = l.falloff;
                gl.wavelength_min = l.wavelength_min;
                gl.wavelength_max = l.wavelength_max;
            },
        }, light);
        total += gl.intensity;
        cum_weights.push_back(total);
        gpu_lights.push_back(gl);
    }

    num_circles_ = (int)circles.size();
    num_segments_ = (int)segs.size();
    num_arcs_ = (int)gpu_arcs.size();
    num_beziers_ = (int)gpu_beziers.size();
    num_ellipses_ = (int)gpu_ellipses.size();
    num_lights_ = (int)gpu_lights.size();

    // Upload SSBOs
    auto upload = [](GLuint& ssbo, const void* data, size_t bytes) {
        if (!ssbo) glGenBuffers(1, &ssbo);
        glBindBuffer(GL_SHADER_STORAGE_BUFFER, ssbo);
        glBufferData(GL_SHADER_STORAGE_BUFFER, std::max(bytes, (size_t)4), data, GL_STATIC_DRAW);
        glBindBuffer(GL_SHADER_STORAGE_BUFFER, 0);
    };

    upload(circle_ssbo_, circles.data(), circles.size() * sizeof(GPUCircle));
    upload(segment_ssbo_, segs.data(), segs.size() * sizeof(GPUSegment));
    upload(arc_ssbo_, gpu_arcs.data(), gpu_arcs.size() * sizeof(GPUArc));
    upload(bezier_ssbo_, gpu_beziers.data(), gpu_beziers.size() * sizeof(GPUBezier));
    upload(ellipse_ssbo_, gpu_ellipses.data(), gpu_ellipses.size() * sizeof(GPUEllipse));
    upload(light_ssbo_, gpu_lights.data(), gpu_lights.size() * sizeof(GPULight));
    upload(light_weights_ssbo_, cum_weights.data(), cum_weights.size() * sizeof(float));

    update_viewport(bounds);

    glUseProgram(trace_program_);
    glUniform1ui(trace_loc_num_circles_, num_circles_);
    glUniform1ui(trace_loc_num_segments_, num_segments_);
    glUniform1ui(trace_loc_num_arcs_, num_arcs_);
    glUniform1ui(trace_loc_num_beziers_, num_beziers_);
    glUniform1ui(trace_loc_num_ellipses_, num_ellipses_);
    glUniform1ui(trace_loc_num_lights_, num_lights_);
}

// ─── Viewport update ────────────────────────────────────────────────

void Renderer::update_viewport(const Bounds& bounds) {
    Vec2 size = bounds.max - bounds.min;
    float scale_x = (float)width_ / size.x;
    float scale_y = (float)height_ / size.y;
    float scale = std::min(scale_x, scale_y);
    float offset_x = (width_ - size.x * scale) * 0.5f;
    float offset_y = (height_ - size.y * scale) * 0.5f;

    viewport_scale_ = scale;

    glUseProgram(trace_program_);
    glUniform2f(trace_loc_bounds_min_, bounds.min.x, bounds.min.y);
    glUniform2f(trace_loc_view_scale_, scale, scale);
    glUniform2f(trace_loc_view_offset_, offset_x, offset_y);
}

// ─── GPU trace + draw ────────────────────────────────────────────────

void Renderer::trace_and_draw(const TraceConfig& cfg) {
    trace_and_draw_multi(cfg, 1);
}

void Renderer::trace_and_draw_multi(const TraceConfig& cfg, int num_dispatches) {
    size_t max_segs = (size_t)cfg.batch_size * (size_t)cfg.max_depth * (size_t)num_dispatches;

    // Reallocate output SSBO if needed (sized for all dispatches)
    if (max_segs > max_output_segments_) {
        max_output_segments_ = max_segs;
        if (!output_ssbo_) glGenBuffers(1, &output_ssbo_);
        glBindBuffer(GL_SHADER_STORAGE_BUFFER, output_ssbo_);
        // LineSeg = vec2 p0 + vec2 p1 + vec4 color = 32 bytes (must match GLSL std430)
        static constexpr size_t kLineSegBytes = 32;
        glBufferData(GL_SHADER_STORAGE_BUFFER, max_segs * kLineSegBytes, nullptr, GL_DYNAMIC_COPY);
        glBindBuffer(GL_SHADER_STORAGE_BUFFER, 0);
    }

    // Initialize draw indirect command buffer
    if (!draw_cmd_buffer_) {
        glGenBuffers(1, &draw_cmd_buffer_);
        glBindBuffer(GL_DRAW_INDIRECT_BUFFER, draw_cmd_buffer_);
        uint32_t cmd[4] = {6, 0, 0, 0};
        glBufferData(GL_DRAW_INDIRECT_BUFFER, sizeof(cmd), cmd, GL_DYNAMIC_DRAW);
        glBindBuffer(GL_DRAW_INDIRECT_BUFFER, 0);
    }

    // Reset instance count to 0
    uint32_t zero = 0;
    glBindBuffer(GL_SHADER_STORAGE_BUFFER, draw_cmd_buffer_);
    glBufferSubData(GL_SHADER_STORAGE_BUFFER, sizeof(uint32_t), sizeof(uint32_t), &zero);
    glBindBuffer(GL_SHADER_STORAGE_BUFFER, 0);

    // ── Dispatch N compute batches ──
    glUseProgram(trace_program_);
    glUniform1ui(trace_loc_max_depth_, cfg.max_depth);
    glUniform1f(trace_loc_intensity_, cfg.intensity);
    glUniform1ui(trace_loc_max_segments_, max_segs);

    glActiveTexture(GL_TEXTURE0);
    glBindTexture(GL_TEXTURE_1D, wavelength_lut_);
    glUniform1i(trace_loc_wavelength_lut_, 0);

    glBindBufferBase(GL_SHADER_STORAGE_BUFFER, 0, circle_ssbo_);
    glBindBufferBase(GL_SHADER_STORAGE_BUFFER, 1, segment_ssbo_);
    glBindBufferBase(GL_SHADER_STORAGE_BUFFER, 2, light_ssbo_);
    glBindBufferBase(GL_SHADER_STORAGE_BUFFER, 3, output_ssbo_);
    glBindBufferBase(GL_SHADER_STORAGE_BUFFER, 4, draw_cmd_buffer_);
    glBindBufferBase(GL_SHADER_STORAGE_BUFFER, 5, light_weights_ssbo_);
    glBindBufferBase(GL_SHADER_STORAGE_BUFFER, 6, arc_ssbo_);
    glBindBufferBase(GL_SHADER_STORAGE_BUFFER, 7, bezier_ssbo_);
    glBindBufferBase(GL_SHADER_STORAGE_BUFFER, 8, ellipse_ssbo_);

    GLuint groups = (cfg.batch_size + 63) / 64;

    for (int d = 0; d < num_dispatches; d++) {
        glUniform1ui(trace_loc_seed_, trace_dispatch_seed(cfg, batch_counter_));
        glDispatchCompute(groups, 1, 1);
        // Barrier between dispatches to ensure atomic counter is visible
        glMemoryBarrier(GL_SHADER_STORAGE_BARRIER_BIT);
        batch_counter_++;
    }
    total_rays_ += (int64_t)cfg.batch_size * num_dispatches;

    // Final barrier before draw (need command barrier for indirect draw)
    glMemoryBarrier(GL_SHADER_STORAGE_BARRIER_BIT | GL_COMMAND_BARRIER_BIT);

    // ── Single draw for all accumulated segments ──
    glBindFramebuffer(GL_FRAMEBUFFER, fbo_);
    glViewport(0, 0, width_, height_);
    glEnable(GL_BLEND);
    glBlendFunc(GL_ONE, GL_ONE);

    glUseProgram(line_program_);
    glUniform2f(loc_resolution_, (float)width_, (float)height_);
    glUniform1f(loc_thickness_, 1.5f);

    glBindVertexArray(line_vao_);
    glBindBuffer(GL_DRAW_INDIRECT_BUFFER, draw_cmd_buffer_);
    glDrawArraysIndirect(GL_TRIANGLES, nullptr);

    glBindVertexArray(0);
    glDisable(GL_BLEND);
    glBindFramebuffer(GL_FRAMEBUFFER, 0);
}

// ─── Post-processing (unchanged logic) ───────────────────────────────

void Renderer::update_display(const PostProcess& pp, float display_aspect, const VignetteFrame* vignette_frame) {
    // Only do the expensive glReadPixels + CPU scan when Max normalization
    // actually needs it.  Other modes compute their divisor without GPU readback.
    // compute_current_max() is still available on demand (e.g. GUI "Capture Ref").
    // Resolution-independence correction
    //
    // Line segments are rasterized with a fixed pixel-space width (1.5 px).
    // This means per-pixel accumulated energy scales as  N / viewport_scale
    // (more pixels → each pixel captures a narrower world-space cross-section
    // of the light field).  Modes that use an external divisor (Rays, Fixed,
    // Off) must compensate by dividing the divisor by viewport_scale so that
    // the displayed brightness is independent of canvas resolution and camera
    // zoom.  Max mode is already self-normalizing (both numerator and
    // denominator carry the same 1/scale factor, which cancels).
    float scale = (viewport_scale_ > 0.0f) ? viewport_scale_ : 1.0f;

    float divisor;
    switch (pp.normalize) {
    case NormalizeMode::Max: {
        float pct_val = compute_max_gpu(pp.normalize_pct);
        divisor = (pct_val < 1e-6f) ? 1.0f : pct_val;
        break;
    }
    case NormalizeMode::Rays:
        divisor = (total_rays_ > 0) ? (float)total_rays_ / scale : 1.0f;
        break;
    case NormalizeMode::Fixed:
        divisor = (pp.normalize_ref > 0.0f) ? pp.normalize_ref / scale : 1.0f;
        break;
    case NormalizeMode::Off:
    default:
        divisor = 1.0f / scale;
        break;
    }

    float exposure_mult = std::pow(2.0f, pp.exposure);
    float inv_gamma = 1.0f / pp.gamma;
    float aspect = display_aspect > 0.0f
        ? display_aspect
        : ((width_ > 0 && height_ > 0) ? (float)width_ / (float)height_ : 1.0f);
    VignetteFrame full_frame{};
    full_frame.x_scale = aspect;
    const VignetteFrame& vf = vignette_frame ? *vignette_frame : full_frame;

    glBindFramebuffer(GL_FRAMEBUFFER, display_fbo_);
    glViewport(0, 0, width_, height_);
    glDisable(GL_BLEND);

    glUseProgram(pp_program_);
    glUniform1f(loc_max_val_, divisor);
    glUniform1f(loc_exposure_, exposure_mult);
    glUniform1f(loc_contrast_, pp.contrast);
    glUniform1f(loc_inv_gamma_, inv_gamma);
    glUniform1i(loc_tone_map_, (int)pp.tone_map);
    glUniform1f(loc_white_point_, pp.white_point);
    glUniform1f(loc_ambient_, pp.ambient);
    glUniform3f(loc_background_, pp.background[0], pp.background[1], pp.background[2]);
    glUniform1f(loc_opacity_, pp.opacity);
    glUniform1f(loc_saturation_, pp.saturation);
    glUniform1f(loc_vignette_, pp.vignette);
    glUniform1f(loc_vignette_radius_, pp.vignette_radius);
    glUniform2f(loc_vignette_center_, vf.center[0], vf.center[1]);
    glUniform2f(loc_vignette_inv_size_, vf.inv_size[0], vf.inv_size[1]);
    glUniform1f(loc_vignette_x_scale_, vf.x_scale);
    glUniform1f(loc_temperature_, pp.temperature);
    glUniform1f(loc_highlights_, pp.highlights);
    glUniform1f(loc_shadows_, pp.shadows);
    // Precompute hue rotation matrix on CPU (Rodrigues' formula around (1,1,1)/sqrt(3))
    {
        float angle = pp.hue_shift * 3.14159265f / 180.0f;
        float cosA = std::cos(angle);
        float sinA = std::sin(angle);
        float k = (1.0f - cosA) / 3.0f;
        float s = sinA * 0.57735026919f; // 1/sqrt(3)
        // Column-major for OpenGL
        float hue_rot[9] = {
            cosA + k, k + s, k - s,
            k - s, cosA + k, k + s,
            k + s, k - s, cosA + k,
        };
        glUniformMatrix3fv(loc_hue_rot_, 1, GL_FALSE, hue_rot);
    }
    glUniform1f(loc_grain_, pp.grain);
    glUniform1i(loc_grain_seed_, pp.grain_seed);
    glUniform1f(loc_chromatic_aberration_, pp.chromatic_aberration);

    glActiveTexture(GL_TEXTURE0);
    glBindTexture(GL_TEXTURE_2D, float_texture_);
    glUniform1i(loc_float_tex_, 0);

    glBindVertexArray(pp_vao_);
    glDrawArrays(GL_TRIANGLES, 0, 3);
    glBindVertexArray(0);

    glBindFramebuffer(GL_FRAMEBUFFER, 0);
}

void Renderer::read_pixels(std::vector<uint8_t>& out_rgb, const PostProcess& pp, float display_aspect,
                           const VignetteFrame* vignette_frame) {
    update_display(pp, display_aspect, vignette_frame);

    read_display_rgba(rgba_buffer_);

    out_rgb.resize(width_ * height_ * 3);
    // OpenGL returns rows bottom-up; flip here so saved PNG/video rows
    // match the world-space orientation seen in the interactive viewport.
    for (int y = 0; y < height_; ++y) {
        int src_y = height_ - 1 - y;
        const uint8_t* src = rgba_buffer_.data() + (size_t)src_y * width_ * 4;
        uint8_t* dst = out_rgb.data() + (size_t)y * width_ * 3;
        for (int x = 0; x < width_; ++x) {
            dst[x * 3 + 0] = src[x * 4 + 0];
            dst[x * 3 + 1] = src[x * 4 + 1];
            dst[x * 3 + 2] = src[x * 4 + 2];
        }
    }
}

void Renderer::read_display_rgba(std::vector<uint8_t>& out_rgba) {
    // Use glReadPixels via the display FBO — glGetTexImage returns stale data
    // on NVIDIA EGL after many additive-blend draw operations.
    rgba_buffer_.resize((size_t)width_ * height_ * 4);
    glFinish();
    glBindFramebuffer(GL_FRAMEBUFFER, display_fbo_);
    glReadPixels(0, 0, width_, height_, GL_RGBA, GL_UNSIGNED_BYTE, rgba_buffer_.data());
    glBindFramebuffer(GL_FRAMEBUFFER, 0);
    out_rgba = rgba_buffer_;
}

FrameMetrics Renderer::compute_display_metrics() {
    read_display_rgba(rgba_buffer_);
    return compute_frame_metrics();
}

FrameMetrics Renderer::compute_frame_metrics() const {
    // Single pass over rgba_buffer_ (already populated by read_pixels).
    // BT.709 luminance: integer approximation (>>10) of 0.2126/0.7152/0.0722.
    // Must match Python stats.py and GLSL postprocess.frag.
    static constexpr uint32_t BT709_R = 218, BT709_G = 732, BT709_B = 74;
    const size_t n_pixels = (size_t)width_ * height_;
    if (n_pixels == 0) return {0, 1, 0, 0, 0};

    int histogram[256] = {};
    size_t clipped = 0;

    for (size_t i = 0; i < n_pixels; ++i) {
        size_t off = i * 4; // RGBA8
        uint8_t r = rgba_buffer_[off];
        uint8_t g = rgba_buffer_[off + 1];
        uint8_t b = rgba_buffer_[off + 2];

        uint32_t lum = (BT709_R * r + BT709_G * g + BT709_B * b) >> 10;
        if (lum > 255) lum = 255;
        histogram[lum]++;

        if (r == 255 || g == 255 || b == 255) ++clipped;
    }

    // Mean luminance
    double sum = 0;
    for (int i = 0; i < 256; ++i) sum += (double)i * histogram[i];
    float mean = (float)(sum / n_pixels);

    // pct_black: fraction with luminance < 1 (i.e., bin 0)
    float pct_black = (float)histogram[0] / n_pixels;

    // pct_clipped: any channel == 255
    float pct_clip = (float)clipped / n_pixels;

    // Percentiles from cumulative histogram (single pass for both p50 and p95)
    size_t target_50 = (size_t)(0.5f * n_pixels);
    size_t target_95 = (size_t)(0.95f * n_pixels);
    float p50 = 255.0f, p95 = 255.0f;
    size_t cumul = 0;
    for (int i = 0; i < 256; ++i) {
        cumul += histogram[i];
        if (p50 == 255.0f && cumul >= target_50) p50 = (float)i;
        if (cumul >= target_95) { p95 = (float)i; break; }
    }

    FrameMetrics m{mean, pct_black, pct_clip, p50, p95, {}};
    std::copy(std::begin(histogram), std::end(histogram), m.histogram.begin());
    return m;
}
