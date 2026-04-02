#include "renderer.h"

#include "spectrum.h"

#include <algorithm>
#include <cmath>
#include <cstring>
#include <iostream>

// ─── Trace compute shader ────────────────────────────────────────────

static constexpr char trace_compute_src[] = R"(
#version 430 core
layout(local_size_x = 64) in;

struct GPUCircle {
    vec2 center;
    float radius;
    uint mat_type;
    float ior;
    float cauchy_b;
    float reflectance;
    float absorption;
};

struct GPUSeg {
    vec2 a;
    vec2 b;
    uint mat_type;
    float ior;
    float cauchy_b;
    float reflectance;
    float absorption;
    float _pad;
};

struct GPULight {
    uint type;
    float intensity;
    vec2 pos_a;
    vec2 pos_b;
};

struct LineSeg {
    vec2 p0;
    vec2 p1;
    vec4 color;
};

layout(std430, binding = 0) readonly buffer CircleBuf  { GPUCircle circles[]; };
layout(std430, binding = 1) readonly buffer SegmentBuf { GPUSeg segments[]; };
layout(std430, binding = 2) readonly buffer LightBuf   { GPULight lights[]; };
layout(std430, binding = 3) writeonly buffer OutputBuf  { LineSeg output_segs[]; };
layout(std430, binding = 4) buffer DrawCmd {
    uint vertex_count;
    uint instance_count;
    uint first_vertex;
    uint base_instance;
};
layout(std430, binding = 5) readonly buffer WeightBuf  { float light_cum_weights[]; };

uniform sampler1D uWavelengthLUT;

uniform uint uNumCircles;
uniform uint uNumSegments;
uniform uint uNumLights;
uniform uint uMaxDepth;
uniform uint uSeed;
uniform float uIntensity;
uniform uint uMaxSegments;
uniform vec2 uBoundsMin;
uniform vec2 uViewScale;
uniform vec2 uViewOffset;

// ── PCG RNG ──
uint rng_state;

uint pcg_next() {
    uint old = rng_state;
    rng_state = old * 747796405u + 2891336453u;
    uint word = ((old >> ((old >> 28u) + 4u)) ^ old) * 277803737u;
    return (word >> 22u) ^ word;
}

float rand01() { return float(pcg_next()) / 4294967295.0; }

// ── Constants ──
const float PI = 3.14159265358979;
const float INTERSECT_EPS = 1e-5;
const float SCATTER_EPS = 1e-4;
const float ESCAPE_DIST = 10.0;

vec2 world_to_pixel(vec2 w) {
    return (w - uBoundsMin) * uViewScale + uViewOffset;
}

vec3 wavelength_rgb(float nm) {
    float t = (nm - 380.0) / 400.0;
    return texture(uWavelengthLUT, t).rgb;
}

// ── Intersection ──
struct Hit {
    float t;
    vec2 point;
    vec2 normal;
    uint mat_type;
    float ior;
    float cauchy_b;
    float reflectance;
    float absorption;
};

const Hit NO_HIT = Hit(1e30, vec2(0), vec2(0), 0u, 0.0, 0.0, 0.0, 0.0);

Hit hit_circle(vec2 ro, vec2 rd, GPUCircle c) {
    vec2 oc = ro - c.center;
    float a = dot(rd, rd);
    float b = 2.0 * dot(oc, rd);
    float cc = dot(oc, oc) - c.radius * c.radius;
    float disc = b * b - 4.0 * a * cc;
    if (disc < 0.0) return NO_HIT;

    float sq = sqrt(disc);
    float t1 = (-b - sq) / (2.0 * a);
    float t2 = (-b + sq) / (2.0 * a);
    float t = (t1 > INTERSECT_EPS) ? t1 : t2;
    if (t < INTERSECT_EPS) return NO_HIT;

    vec2 p = ro + rd * t;
    return Hit(t, p, normalize(p - c.center), c.mat_type, c.ior, c.cauchy_b, c.reflectance, c.absorption);
}

Hit hit_segment(vec2 ro, vec2 rd, GPUSeg s) {
    vec2 d = s.b - s.a;
    float denom = rd.x * d.y - rd.y * d.x;
    if (abs(denom) < INTERSECT_EPS) return NO_HIT;

    vec2 f = ro - s.a;
    float t = (d.x * f.y - d.y * f.x) / denom;
    float u = (rd.x * f.y - rd.y * f.x) / denom;
    if (t < INTERSECT_EPS || u < 0.0 || u > 1.0) return NO_HIT;

    vec2 p = ro + rd * t;
    vec2 n = normalize(vec2(-d.y, d.x));
    return Hit(t, p, n, s.mat_type, s.ior, s.cauchy_b, s.reflectance, s.absorption);
}

Hit hit_scene(vec2 ro, vec2 rd) {
    Hit best = NO_HIT;
    for (uint i = 0u; i < uNumCircles; i++) {
        Hit h = hit_circle(ro, rd, circles[i]);
        if (h.t < best.t) best = h;
    }
    for (uint i = 0u; i < uNumSegments; i++) {
        Hit h = hit_segment(ro, rd, segments[i]);
        if (h.t < best.t) best = h;
    }
    return best;
}

void emit(vec2 p0, vec2 p1, vec4 color) {
    uint idx = atomicAdd(instance_count, 1u);
    if (idx >= uMaxSegments) return;
    output_segs[idx].p0 = world_to_pixel(p0);
    output_segs[idx].p1 = world_to_pixel(p1);
    output_segs[idx].color = color;
}

void main() {
    uint gid = gl_GlobalInvocationID.x;
    rng_state = gid * 1099087573u + uSeed;
    pcg_next(); pcg_next();

    // Choose light (weighted)
    float total_w = light_cum_weights[uNumLights - 1u];
    float r = rand01() * total_w;
    uint li = 0u;
    for (uint i = 0u; i < uNumLights; i++) {
        if (r <= light_cum_weights[i]) { li = i; break; }
    }
    GPULight lt = lights[li];

    // Generate ray
    vec2 ro, rd;
    if (lt.type == 0u) {
        // Point light: uniform 360°
        float a = rand01() * 2.0 * PI;
        ro = lt.pos_a;
        rd = vec2(cos(a), sin(a));
    } else {
        // Segment light: random point, hemisphere
        float t = rand01();
        ro = mix(lt.pos_a, lt.pos_b, t);
        vec2 seg_d = lt.pos_b - lt.pos_a;
        vec2 normal = normalize(vec2(-seg_d.y, seg_d.x));
        vec2 tangent = normalize(seg_d);
        float a = (rand01() - 0.5) * PI;
        rd = normal * cos(a) + tangent * sin(a);
    }

    // Random wavelength → color
    float wavelength = 380.0 + rand01() * 400.0;
    vec3 rgb = wavelength_rgb(wavelength);
    vec4 color = vec4(rgb * uIntensity, uIntensity);

    // Trace
    float current_absorption = 0.0;

    for (uint depth = 0u; depth < uMaxDepth; depth++) {
        Hit h = hit_scene(ro, rd);

        if (h.t >= 1e29) {
            emit(ro, ro + rd * ESCAPE_DIST, color);
            return;
        }

        // Beer-Lambert attenuation inside absorbing medium
        color *= exp(-current_absorption * h.t);

        emit(ro, h.point, color);

        if (h.mat_type == 0u) {
            // Diffuse: scatter with probability reflectance, else absorb
            if (h.reflectance > 0.0 && rand01() < h.reflectance) {
                vec2 n = h.normal;
                if (dot(rd, n) > 0.0) n = -n;
                // Uniform random direction in 2D half-plane
                float u = rand01();
                float sin_theta = 2.0 * u - 1.0;
                float cos_theta = sqrt(1.0 - sin_theta * sin_theta);
                vec2 tangent = vec2(-n.y, n.x);
                rd = n * cos_theta + tangent * sin_theta;
                ro = h.point + n * SCATTER_EPS;
            } else {
                return;
            }
        } else if (h.mat_type == 1u) {
            // Specular: reflect with probability reflectance, else pass through
            vec2 n = h.normal;
            if (dot(rd, n) > 0.0) n = -n;
            if (rand01() < h.reflectance) {
                rd = reflect(rd, n);
                ro = h.point + n * SCATTER_EPS;
            } else {
                ro = h.point - n * SCATTER_EPS;
            }
        } else {
            // Refractive: Fresnel + Snell with Cauchy dispersion + absorption
            vec2 n = h.normal;
            float cos_i = dot(rd, n);

            float lambda_um = wavelength * 0.001;
            float ior = h.ior + h.cauchy_b / (lambda_um * lambda_um * 1e6);

            float n1, n2;
            bool entering;
            if (cos_i > 0.0) {
                n1 = ior; n2 = 1.0;
                n = -n;   cos_i = -cos_i;
                entering = false;
            } else {
                n1 = 1.0; n2 = ior;
                cos_i = -cos_i;
                entering = true;
            }

            float ratio = n1 / n2;
            float cos_t_sq = 1.0 - ratio * ratio * (1.0 - cos_i * cos_i);

            if (cos_t_sq < 0.0) {
                // Total internal reflection — stay in same medium
                rd = reflect(rd, n);
                ro = h.point + n * SCATTER_EPS;
            } else {
                float cos_t = sqrt(cos_t_sq);
                float rs = (n1 * cos_i - n2 * cos_t) / (n1 * cos_i + n2 * cos_t);
                float rp = (n2 * cos_i - n1 * cos_t) / (n1 * cos_t + n2 * cos_i);
                float R = 0.5 * (rs * rs + rp * rp);

                if (rand01() < R) {
                    // Fresnel reflection — stay in same medium
                    rd = reflect(rd, n);
                    ro = h.point + n * SCATTER_EPS;
                } else {
                    // Refraction — cross boundary, update medium
                    rd = normalize(rd * ratio + n * (ratio * cos_i - cos_t));
                    ro = h.point - n * SCATTER_EPS;
                    current_absorption = entering ? h.absorption : 0.0;
                }
            }
        }
    }
}
)";

// ─── Instanced line vertex shader ────────────────────────────────────

static constexpr char line_vert_src[] = R"(
#version 430 core

struct LineSeg {
    vec2 p0;
    vec2 p1;
    vec4 color;
};

layout(std430, binding = 3) readonly buffer OutputBuf { LineSeg segs[]; };

uniform vec2 uResolution;
uniform float uThickness;

out vec4 vColor;
out float vLineDist;

void main() {
    uint seg_id = gl_InstanceID;
    LineSeg s = segs[seg_id];

    vec2 dir = s.p1 - s.p0;
    float len = length(dir);
    if (len < 0.001) { gl_Position = vec4(0); return; }

    vec2 n = vec2(-dir.y, dir.x) / len * uThickness;

    // 6 vertices per quad: 0,1,2 = tri1; 3,4,5 = tri2
    vec2 pos;
    float dist;
    int vid = gl_VertexID;
    if      (vid == 0) { pos = s.p0 - n; dist = -1.0; }
    else if (vid == 1) { pos = s.p0 + n; dist =  1.0; }
    else if (vid == 2) { pos = s.p1 - n; dist = -1.0; }
    else if (vid == 3) { pos = s.p0 + n; dist =  1.0; }
    else if (vid == 4) { pos = s.p1 + n; dist =  1.0; }
    else               { pos = s.p1 - n; dist = -1.0; }

    vec2 ndc = (pos / uResolution) * 2.0 - 1.0;
    ndc.y = -ndc.y;
    gl_Position = vec4(ndc, 0.0, 1.0);
    vColor = s.color;
    vLineDist = dist;
}
)";

static constexpr char line_frag_src[] = R"(
#version 430 core
in vec4 vColor;
in float vLineDist;
out vec4 FragColor;

void main() {
    float alpha = 1.0 - smoothstep(0.5, 1.0, abs(vLineDist));
    FragColor = vColor * alpha;
}
)";

// ─── Post-processing shaders (unchanged) ─────────────────────────────

static constexpr char pp_vert_src[] = R"(
#version 430 core
out vec2 TexCoord;

void main() {
    vec2 positions[3] = vec2[](
        vec2(-1.0, -1.0),
        vec2( 3.0, -1.0),
        vec2(-1.0,  3.0)
    );
    vec2 texcoords[3] = vec2[](
        vec2(0.0, 0.0),
        vec2(2.0, 0.0),
        vec2(0.0, 2.0)
    );
    gl_Position = vec4(positions[gl_VertexID], 0.0, 1.0);
    TexCoord = texcoords[gl_VertexID];
}
)";

static constexpr char pp_frag_src[] = R"(
#version 430 core
in vec2 TexCoord;
out vec4 FragColor;

uniform sampler2D uFloatTexture;
uniform float uMaxVal;
uniform float uExposureMult;
uniform float uContrast;
uniform float uInvGamma;
uniform int uToneMapOp;
uniform float uWhitePoint;

float toneMapReinhard(float v) { return v / (1.0 + v); }

float toneMapReinhardExt(float v, float wp) {
    float w2 = wp * wp;
    return (v * (1.0 + v / w2)) / (1.0 + v);
}

float toneMapACES(float v) {
    float a = 2.51, b = 0.03, c = 2.43, d = 0.59, e = 0.14;
    return clamp((v * (a * v + b)) / (v * (c * v + d) + e), 0.0, 1.0);
}

float toneMapLog(float v, float wp) {
    return log(1.0 + v) / log(1.0 + wp);
}

float toneMap(float v, int op, float wp) {
    if (op == 1) return toneMapReinhard(v);
    if (op == 2) return toneMapReinhardExt(v, wp);
    if (op == 3) return toneMapACES(v);
    if (op == 4) return toneMapLog(v, wp);
    return clamp(v, 0.0, 1.0);
}

void main() {
    vec2 flippedCoord = vec2(TexCoord.x, 1.0 - TexCoord.y);
    vec4 hdr = texture(uFloatTexture, flippedCoord);

    vec3 color;
    for (int c = 0; c < 3; c++) {
        float v = hdr[c];
        v = v / uMaxVal;
        v = v * uExposureMult;
        v = toneMap(v, uToneMapOp, uWhitePoint);
        v = (v - 0.5) * uContrast + 0.5;
        v = clamp(v, 0.0, 1.0);
        v = pow(v, uInvGamma);
        color[c] = v;
    }

    FragColor = vec4(color, 1.0);
}
)";

// ─── Max reduction compute shader ────────────────────────────────────

static constexpr char max_compute_src[] = R"(
#version 430 core
layout(local_size_x = 16, local_size_y = 16) in;

uniform sampler2D uInputTexture;
uniform ivec2 uTexSize;

layout(std430, binding = 1) buffer MaxBuffer {
    uint maxValueBits;
};

shared float sharedMax[256];

void main() {
    ivec2 gid = ivec2(gl_GlobalInvocationID.xy);
    uint lid = gl_LocalInvocationIndex;

    float localMax = 0.0;
    if (gid.x < uTexSize.x && gid.y < uTexSize.y) {
        vec4 pixel = texelFetch(uInputTexture, gid, 0);
        localMax = max(pixel.r, max(pixel.g, pixel.b));
    }

    sharedMax[lid] = localMax;
    barrier();

    for (uint stride = 128u; stride > 0u; stride >>= 1u) {
        if (lid < stride) {
            sharedMax[lid] = max(sharedMax[lid], sharedMax[lid + stride]);
        }
        barrier();
    }

    if (lid == 0u) {
        float newVal = sharedMax[0];
        uint newBits = floatBitsToUint(newVal);
        uint oldBits = maxValueBits;
        while (newVal > uintBitsToFloat(oldBits)) {
            uint result = atomicCompSwap(maxValueBits, oldBits, newBits);
            if (result == oldBits) break;
            oldBits = result;
        }
    }
}
)";

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

// ─── GPU data structures (must match GLSL layout under std430) ───────

struct GPUCircle {
    float center[2];
    float radius;
    uint32_t mat_type; // 0=diffuse, 1=specular, 2=refractive
    float ior;
    float cauchy_b;
    float reflectance;
    float absorption;
};
static_assert(sizeof(GPUCircle) == 32);

struct GPUSegment {
    float a[2];
    float b[2];
    uint32_t mat_type;
    float ior;
    float cauchy_b;
    float reflectance;
    float absorption;
    float _pad;
};
static_assert(sizeof(GPUSegment) == 40);

struct GPULight {
    uint32_t type; // 0=point, 1=segment
    float intensity;
    float pos_a[2];
    float pos_b[2];
};
static_assert(sizeof(GPULight) == 24);

// ─── Renderer implementation ─────────────────────────────────────────

Renderer::~Renderer() { shutdown(); }

bool Renderer::init(int width, int height) {
    width_ = width;
    height_ = height;

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
    glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA32F, width_, height_, 0, GL_RGBA, GL_FLOAT, nullptr);
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
    GLuint cs = compile_shader(GL_COMPUTE_SHADER, trace_compute_src);
    if (!cs) return false;
    trace_program_ = link_compute(cs);
    if (!trace_program_) return false;

    trace_loc_num_circles_ = glGetUniformLocation(trace_program_, "uNumCircles");
    trace_loc_num_segments_ = glGetUniformLocation(trace_program_, "uNumSegments");
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
    GLuint v = compile_shader(GL_VERTEX_SHADER, line_vert_src);
    GLuint f = compile_shader(GL_FRAGMENT_SHADER, line_frag_src);
    if (!v || !f) return false;
    line_program_ = link_program(v, f);
    if (!line_program_) return false;
    loc_resolution_ = glGetUniformLocation(line_program_, "uResolution");
    loc_thickness_ = glGetUniformLocation(line_program_, "uThickness");
    return true;
}

bool Renderer::create_pp_shader() {
    GLuint v = compile_shader(GL_VERTEX_SHADER, pp_vert_src);
    GLuint f = compile_shader(GL_FRAGMENT_SHADER, pp_frag_src);
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
    return true;
}

bool Renderer::create_compute_shader() {
    GLuint cs = compile_shader(GL_COMPUTE_SHADER, max_compute_src);
    if (!cs) return false;
    max_compute_ = link_compute(cs);
    if (!max_compute_) return false;

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

float Renderer::compute_max_gpu() {
    // Read float FBO back via glReadPixels (reliable after framebuffer blending)
    glFinish();
    glBindFramebuffer(GL_FRAMEBUFFER, fbo_);
    std::vector<float> buf(width_ * height_ * 4);
    glReadPixels(0, 0, width_, height_, GL_RGBA, GL_FLOAT, buf.data());
    glBindFramebuffer(GL_FRAMEBUFFER, 0);

    float max_val = 0.0f;
    for (size_t i = 0; i < buf.size(); i += 4) {
        max_val = std::max(max_val, buf[i]);
        max_val = std::max(max_val, buf[i + 1]);
        max_val = std::max(max_val, buf[i + 2]);
    }
    return max_val;
}

void Renderer::clear() {
    glBindFramebuffer(GL_FRAMEBUFFER, fbo_);
    glClearColor(0.0f, 0.0f, 0.0f, 0.0f);
    glClear(GL_COLOR_BUFFER_BIT);
    glBindFramebuffer(GL_FRAMEBUFFER, 0);
    batch_counter_ = 0;
}

// ─── Scene upload ────────────────────────────────────────────────────

void Renderer::upload_scene(const Scene& scene, const Bounds& bounds) {
    // Flatten scene shapes into GPU arrays
    std::vector<GPUCircle> circles;
    std::vector<GPUSegment> segs;

    auto fill_material = [](auto& gpu, const Material& mat) {
        std::visit(overloaded{
            [&](const Diffuse& d) { gpu.mat_type = 0; gpu.reflectance = d.reflectance; },
            [&](const Specular& s) { gpu.mat_type = 1; gpu.reflectance = s.reflectance; },
            [&](const Refractive& r) { gpu.mat_type = 2; gpu.ior = r.ior; gpu.cauchy_b = r.cauchy_b; gpu.absorption = r.absorption; },
        }, mat);
    };

    for (const auto& shape : scene.shapes) {
        std::visit(overloaded{
            [&](const Circle& c) {
                GPUCircle gc{};
                gc.center[0] = c.center.x;
                gc.center[1] = c.center.y;
                gc.radius = c.radius;
                fill_material(gc, c.material);
                circles.push_back(gc);
            },
            [&](const Segment& s) {
                GPUSegment gs{};
                gs.a[0] = s.a.x; gs.a[1] = s.a.y;
                gs.b[0] = s.b.x; gs.b[1] = s.b.y;
                fill_material(gs, s.material);
                segs.push_back(gs);
            },
        }, shape);
    }

    // Flatten lights
    std::vector<GPULight> gpu_lights;
    std::vector<float> cum_weights;
    float total = 0.0f;

    for (const auto& light : scene.lights) {
        GPULight gl{};
        std::visit(overloaded{
            [&](const PointLight& l) {
                gl.type = 0;
                gl.intensity = l.intensity;
                gl.pos_a[0] = l.pos.x; gl.pos_a[1] = l.pos.y;
            },
            [&](const SegmentLight& l) {
                gl.type = 1;
                gl.intensity = l.intensity;
                gl.pos_a[0] = l.a.x; gl.pos_a[1] = l.a.y;
                gl.pos_b[0] = l.b.x; gl.pos_b[1] = l.b.y;
            },
        }, light);
        total += gl.intensity;
        cum_weights.push_back(total);
        gpu_lights.push_back(gl);
    }

    num_circles_ = (int)circles.size();
    num_segments_ = (int)segs.size();
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
    upload(light_ssbo_, gpu_lights.data(), gpu_lights.size() * sizeof(GPULight));
    upload(light_weights_ssbo_, cum_weights.data(), cum_weights.size() * sizeof(float));

    // Precompute viewport transform uniforms
    Vec2 size = bounds.max - bounds.min;
    float scale_x = (float)width_ / size.x;
    float scale_y = (float)height_ / size.y;
    float scale = std::min(scale_x, scale_y);
    float offset_x = (width_ - size.x * scale) * 0.5f;
    float offset_y = (height_ - size.y * scale) * 0.5f;

    glUseProgram(trace_program_);
    glUniform2f(trace_loc_bounds_min_, bounds.min.x, bounds.min.y);
    glUniform2f(trace_loc_view_scale_, scale, scale);
    glUniform2f(trace_loc_view_offset_, offset_x, offset_y);
    glUniform1ui(trace_loc_num_circles_, num_circles_);
    glUniform1ui(trace_loc_num_segments_, num_segments_);
    glUniform1ui(trace_loc_num_lights_, num_lights_);
}

// ─── GPU trace + draw ────────────────────────────────────────────────

void Renderer::trace_and_draw(const TraceConfig& cfg) {
    int max_segs = cfg.batch_size * cfg.max_depth;

    // Reallocate output SSBO if needed
    if (max_segs > max_output_segments_) {
        max_output_segments_ = max_segs;
        if (!output_ssbo_) glGenBuffers(1, &output_ssbo_);
        glBindBuffer(GL_SHADER_STORAGE_BUFFER, output_ssbo_);
        // Each segment = 32 bytes (vec2 p0 + vec2 p1 + vec4 color)
        glBufferData(GL_SHADER_STORAGE_BUFFER, (size_t)max_segs * 32, nullptr, GL_DYNAMIC_COPY);
        glBindBuffer(GL_SHADER_STORAGE_BUFFER, 0);
    }

    // Initialize draw indirect command buffer
    if (!draw_cmd_buffer_) {
        glGenBuffers(1, &draw_cmd_buffer_);
        glBindBuffer(GL_DRAW_INDIRECT_BUFFER, draw_cmd_buffer_);
        uint32_t cmd[4] = {6, 0, 0, 0}; // count=6, instanceCount=0, first=0, baseInstance=0
        glBufferData(GL_DRAW_INDIRECT_BUFFER, sizeof(cmd), cmd, GL_DYNAMIC_DRAW);
        glBindBuffer(GL_DRAW_INDIRECT_BUFFER, 0);
    }

    // Reset instance count to 0
    uint32_t zero = 0;
    glBindBuffer(GL_SHADER_STORAGE_BUFFER, draw_cmd_buffer_);
    glBufferSubData(GL_SHADER_STORAGE_BUFFER, sizeof(uint32_t), sizeof(uint32_t), &zero);
    glBindBuffer(GL_SHADER_STORAGE_BUFFER, 0);

    // ── Dispatch trace compute shader ──
    glUseProgram(trace_program_);
    glUniform1ui(trace_loc_max_depth_, cfg.max_depth);
    glUniform1f(trace_loc_intensity_, cfg.intensity);
    glUniform1ui(trace_loc_max_segments_, max_segs);
    glUniform1ui(trace_loc_seed_, batch_counter_ * 1000003u + 42u);

    // Bind wavelength LUT
    glActiveTexture(GL_TEXTURE0);
    glBindTexture(GL_TEXTURE_1D, wavelength_lut_);
    glUniform1i(trace_loc_wavelength_lut_, 0);

    // Bind SSBOs
    glBindBufferBase(GL_SHADER_STORAGE_BUFFER, 0, circle_ssbo_);
    glBindBufferBase(GL_SHADER_STORAGE_BUFFER, 1, segment_ssbo_);
    glBindBufferBase(GL_SHADER_STORAGE_BUFFER, 2, light_ssbo_);
    glBindBufferBase(GL_SHADER_STORAGE_BUFFER, 3, output_ssbo_);
    glBindBufferBase(GL_SHADER_STORAGE_BUFFER, 4, draw_cmd_buffer_);
    glBindBufferBase(GL_SHADER_STORAGE_BUFFER, 5, light_weights_ssbo_);

    GLuint groups = (cfg.batch_size + 63) / 64;
    glDispatchCompute(groups, 1, 1);
    glMemoryBarrier(GL_SHADER_STORAGE_BARRIER_BIT | GL_COMMAND_BARRIER_BIT);

    // ── Draw instanced lines from SSBO ──
    glBindFramebuffer(GL_FRAMEBUFFER, fbo_);
    glViewport(0, 0, width_, height_);
    glEnable(GL_BLEND);
    glBlendFunc(GL_ONE, GL_ONE);

    glUseProgram(line_program_);
    glUniform2f(loc_resolution_, (float)width_, (float)height_);
    glUniform1f(loc_thickness_, 1.5f);

    // SSBO binding 3 is already bound (output_segs)
    glBindVertexArray(line_vao_);
    glBindBuffer(GL_DRAW_INDIRECT_BUFFER, draw_cmd_buffer_);
    glDrawArraysIndirect(GL_TRIANGLES, nullptr);

    glBindVertexArray(0);
    glDisable(GL_BLEND);
    glBindFramebuffer(GL_FRAMEBUFFER, 0);

    batch_counter_++;
}

// ─── Post-processing (unchanged logic) ───────────────────────────────

void Renderer::update_display(const PostProcess& pp) {
    float divisor = compute_max_gpu();
    if (divisor < 1e-6f)
        divisor = 1.0f;
    last_max_ = divisor;

    float exposure_mult = std::pow(2.0f, pp.exposure);
    float inv_gamma = 1.0f / pp.gamma;

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

    glActiveTexture(GL_TEXTURE0);
    glBindTexture(GL_TEXTURE_2D, float_texture_);
    glUniform1i(loc_float_tex_, 0);

    glBindVertexArray(pp_vao_);
    glDrawArrays(GL_TRIANGLES, 0, 3);
    glBindVertexArray(0);

    glBindFramebuffer(GL_FRAMEBUFFER, 0);
}

void Renderer::read_pixels(std::vector<uint8_t>& out_rgb, const PostProcess& pp) {
    update_display(pp);

    glBindTexture(GL_TEXTURE_2D, display_texture_);
    glGetTexImage(GL_TEXTURE_2D, 0, GL_RGBA, GL_UNSIGNED_BYTE, rgba_buffer_.data());

    out_rgb.resize(width_ * height_ * 3);
    for (int i = 0; i < width_ * height_; ++i) {
        out_rgb[i * 3 + 0] = rgba_buffer_[i * 4 + 0];
        out_rgb[i * 3 + 1] = rgba_buffer_[i * 4 + 1];
        out_rgb[i * 3 + 2] = rgba_buffer_[i * 4 + 2];
    }
}
