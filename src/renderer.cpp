#include "renderer.h"

#include <algorithm>
#include <cmath>
#include <cstring>
#include <iostream>

// --- Shaders ---

static constexpr char line_vert_src[] = R"(
#version 330 core
layout (location = 0) in vec2 aPos;
layout (location = 1) in vec4 aColor;
layout (location = 2) in float aLineDist;

out vec4 vColor;
out float vLineDist;

uniform vec2 uResolution;

void main() {
    vec2 ndc = (aPos / uResolution) * 2.0 - 1.0;
    ndc.y = -ndc.y;
    gl_Position = vec4(ndc, 0.0, 1.0);
    vColor = aColor;
    vLineDist = aLineDist;
}
)";

static constexpr char line_frag_src[] = R"(
#version 330 core
in vec4 vColor;
in float vLineDist;
out vec4 FragColor;

void main() {
    float alpha = 1.0 - smoothstep(0.5, 1.0, abs(vLineDist));
    FragColor = vColor * alpha;
}
)";

static constexpr char pp_vert_src[] = R"(
#version 330 core
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
#version 330 core
in vec2 TexCoord;
out vec4 FragColor;

uniform sampler2D uFloatTexture;
uniform float uMaxVal;
uniform float uExposureMult;
uniform float uContrast;
uniform float uInvGamma;
uniform int uToneMapOp;
uniform float uWhitePoint;

float toneMapReinhard(float v) {
    return v / (1.0 + v);
}

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

static constexpr char max_compute_src[] = R"(
#version 430 core
layout(local_size_x = 16, local_size_y = 16) in;

layout(rgba32f, binding = 0) readonly uniform image2D uInputImage;

layout(std430, binding = 1) buffer MaxBuffer {
    uint maxValueBits;
};

shared float sharedMax[256];

void main() {
    ivec2 texSize = imageSize(uInputImage);
    ivec2 gid = ivec2(gl_GlobalInvocationID.xy);
    uint lid = gl_LocalInvocationIndex;

    float localMax = 0.0;
    if (gid.x < texSize.x && gid.y < texSize.y) {
        vec4 pixel = imageLoad(uInputImage, gid);
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

// --- Shader compilation helpers ---

static GLuint compile_shader(GLenum type, const char* src) {
    GLuint shader = glCreateShader(type);
    glShaderSource(shader, 1, &src, nullptr);
    glCompileShader(shader);

    GLint ok;
    glGetShaderiv(shader, GL_COMPILE_STATUS, &ok);
    if (!ok) {
        char log[512];
        glGetShaderInfoLog(shader, 512, nullptr, log);
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
        char log[512];
        glGetProgramInfoLog(prog, 512, nullptr, log);
        std::cerr << "Shader link error: " << log << "\n";
        glDeleteProgram(prog);
        return 0;
    }

    glDeleteShader(vert);
    glDeleteShader(frag);
    return prog;
}

// --- Renderer ---

Renderer::~Renderer() { shutdown(); }

bool Renderer::init(int width, int height) {
    width_ = width;
    height_ = height;

    glewExperimental = GL_TRUE;
    if (glewContextInit() != GLEW_OK) {
        std::cerr << "Failed to initialize GLEW\n";
        return false;
    }

    if (!create_framebuffers())
        return false;
    if (!create_line_shader())
        return false;
    if (!create_pp_shader())
        return false;

    // Line VAO/VBO
    glGenVertexArrays(1, &line_vao_);
    glGenBuffers(1, &line_vbo_);
    glBindVertexArray(line_vao_);
    glBindBuffer(GL_ARRAY_BUFFER, line_vbo_);

    // pos(2) + color(4) + lineDist(1) = 7 floats
    size_t stride = 7 * sizeof(float);
    glVertexAttribPointer(0, 2, GL_FLOAT, GL_FALSE, stride, (void*)0);
    glEnableVertexAttribArray(0);
    glVertexAttribPointer(1, 4, GL_FLOAT, GL_FALSE, stride, (void*)(2 * sizeof(float)));
    glEnableVertexAttribArray(1);
    glVertexAttribPointer(2, 1, GL_FLOAT, GL_FALSE, stride, (void*)(6 * sizeof(float)));
    glEnableVertexAttribArray(2);
    glBindVertexArray(0);

    // Post-process VAO (empty — fullscreen triangle uses gl_VertexID)
    glGenVertexArrays(1, &pp_vao_);

    create_compute_shader();
    float_buffer_.resize(width * height * 4);
    rgba_buffer_.resize(width * height * 4);

    return true;
}

void Renderer::shutdown() {
    delete_framebuffers();
    if (line_program_) {
        glDeleteProgram(line_program_);
        line_program_ = 0;
    }
    if (pp_program_) {
        glDeleteProgram(pp_program_);
        pp_program_ = 0;
    }
    if (max_compute_) {
        glDeleteProgram(max_compute_);
        max_compute_ = 0;
    }
    if (max_ssbo_) {
        glDeleteBuffers(1, &max_ssbo_);
        max_ssbo_ = 0;
    }
    if (line_vao_) {
        glDeleteVertexArrays(1, &line_vao_);
        line_vao_ = 0;
    }
    if (pp_vao_) {
        glDeleteVertexArrays(1, &pp_vao_);
        pp_vao_ = 0;
    }
    if (line_vbo_) {
        glDeleteBuffers(1, &line_vbo_);
        line_vbo_ = 0;
    }
    has_compute_ = false;
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
    if (fbo_) {
        glDeleteFramebuffers(1, &fbo_);
        fbo_ = 0;
    }
    if (display_fbo_) {
        glDeleteFramebuffers(1, &display_fbo_);
        display_fbo_ = 0;
    }
    if (float_texture_) {
        glDeleteTextures(1, &float_texture_);
        float_texture_ = 0;
    }
    if (display_texture_) {
        glDeleteTextures(1, &display_texture_);
        display_texture_ = 0;
    }
}

bool Renderer::create_line_shader() {
    GLuint v = compile_shader(GL_VERTEX_SHADER, line_vert_src);
    GLuint f = compile_shader(GL_FRAGMENT_SHADER, line_frag_src);
    if (!v || !f)
        return false;
    line_program_ = link_program(v, f);
    if (line_program_)
        loc_resolution_ = glGetUniformLocation(line_program_, "uResolution");
    return line_program_ != 0;
}

bool Renderer::create_pp_shader() {
    GLuint v = compile_shader(GL_VERTEX_SHADER, pp_vert_src);
    GLuint f = compile_shader(GL_FRAGMENT_SHADER, pp_frag_src);
    if (!v || !f)
        return false;
    pp_program_ = link_program(v, f);
    if (pp_program_) {
        loc_max_val_ = glGetUniformLocation(pp_program_, "uMaxVal");
        loc_exposure_ = glGetUniformLocation(pp_program_, "uExposureMult");
        loc_contrast_ = glGetUniformLocation(pp_program_, "uContrast");
        loc_inv_gamma_ = glGetUniformLocation(pp_program_, "uInvGamma");
        loc_tone_map_ = glGetUniformLocation(pp_program_, "uToneMapOp");
        loc_white_point_ = glGetUniformLocation(pp_program_, "uWhitePoint");
        loc_float_tex_ = glGetUniformLocation(pp_program_, "uFloatTexture");
    }
    return pp_program_ != 0;
}

bool Renderer::create_compute_shader() {
    GLint major, minor;
    glGetIntegerv(GL_MAJOR_VERSION, &major);
    glGetIntegerv(GL_MINOR_VERSION, &minor);

    if (major < 4 || (major == 4 && minor < 3)) {
        has_compute_ = false;
        return false;
    }

    GLuint cs = glCreateShader(GL_COMPUTE_SHADER);
    const char* src = max_compute_src;
    glShaderSource(cs, 1, &src, nullptr);
    glCompileShader(cs);

    GLint ok;
    glGetShaderiv(cs, GL_COMPILE_STATUS, &ok);
    if (!ok) {
        glDeleteShader(cs);
        has_compute_ = false;
        return false;
    }

    max_compute_ = glCreateProgram();
    glAttachShader(max_compute_, cs);
    glLinkProgram(max_compute_);

    glGetProgramiv(max_compute_, GL_LINK_STATUS, &ok);
    if (!ok) {
        glDeleteShader(cs);
        glDeleteProgram(max_compute_);
        max_compute_ = 0;
        has_compute_ = false;
        return false;
    }

    glDeleteShader(cs);

    glGenBuffers(1, &max_ssbo_);
    glBindBuffer(GL_SHADER_STORAGE_BUFFER, max_ssbo_);
    glBufferData(GL_SHADER_STORAGE_BUFFER, sizeof(uint32_t), nullptr, GL_DYNAMIC_READ);
    glBindBuffer(GL_SHADER_STORAGE_BUFFER, 0);

    has_compute_ = true;
    return true;
}

float Renderer::compute_max_gpu() {
    if (!has_compute_)
        return 0.0f;

    uint32_t zero = 0;
    glBindBuffer(GL_SHADER_STORAGE_BUFFER, max_ssbo_);
    glBufferSubData(GL_SHADER_STORAGE_BUFFER, 0, sizeof(uint32_t), &zero);

    glUseProgram(max_compute_);
    glBindImageTexture(0, float_texture_, 0, GL_FALSE, 0, GL_READ_ONLY, GL_RGBA32F);
    glBindBufferBase(GL_SHADER_STORAGE_BUFFER, 1, max_ssbo_);

    GLuint gx = (width_ + 15) / 16;
    GLuint gy = (height_ + 15) / 16;
    glDispatchCompute(gx, gy, 1);
    glMemoryBarrier(GL_SHADER_STORAGE_BARRIER_BIT);

    uint32_t max_bits;
    glGetBufferSubData(GL_SHADER_STORAGE_BUFFER, 0, sizeof(uint32_t), &max_bits);
    glBindBuffer(GL_SHADER_STORAGE_BUFFER, 0);

    float max_val;
    std::memcpy(&max_val, &max_bits, sizeof(float));
    return max_val;
}

void Renderer::clear() {
    glBindFramebuffer(GL_FRAMEBUFFER, fbo_);
    glClearColor(0.0f, 0.0f, 0.0f, 0.0f);
    glClear(GL_COLOR_BUFFER_BIT);
    glBindFramebuffer(GL_FRAMEBUFFER, 0);
    vertex_buffer_.clear();
}

void Renderer::draw_lines(std::span<const LineSegment> segments, float thickness) {
    vertex_buffer_.reserve(vertex_buffer_.size() + segments.size() * 6 * 7);

    for (const auto& seg : segments) {
        float dx = seg.p1.x - seg.p0.x;
        float dy = seg.p1.y - seg.p0.y;
        float len = std::sqrt(dx * dx + dy * dy);
        if (len < 0.001f)
            continue;

        float nx = -dy / len * thickness;
        float ny = dx / len * thickness;

        float cr = seg.color.r * seg.intensity;
        float cg = seg.color.g * seg.intensity;
        float cb = seg.color.b * seg.intensity;
        float ca = seg.intensity;

        float p0x = seg.p0.x - nx, p0y = seg.p0.y - ny;
        float p1x = seg.p0.x + nx, p1y = seg.p0.y + ny;
        float p2x = seg.p1.x - nx, p2y = seg.p1.y - ny;
        float p3x = seg.p1.x + nx, p3y = seg.p1.y + ny;

        auto add = [&](float px, float py, float dist) {
            vertex_buffer_.push_back(px);
            vertex_buffer_.push_back(py);
            vertex_buffer_.push_back(cr);
            vertex_buffer_.push_back(cg);
            vertex_buffer_.push_back(cb);
            vertex_buffer_.push_back(ca);
            vertex_buffer_.push_back(dist);
        };

        // Triangle 1
        add(p0x, p0y, -1.0f);
        add(p1x, p1y, 1.0f);
        add(p2x, p2y, -1.0f);
        // Triangle 2
        add(p1x, p1y, 1.0f);
        add(p3x, p3y, 1.0f);
        add(p2x, p2y, -1.0f);
    }
}

void Renderer::flush() {
    if (vertex_buffer_.empty())
        return;

    glBindFramebuffer(GL_FRAMEBUFFER, fbo_);
    glViewport(0, 0, width_, height_);
    glEnable(GL_BLEND);
    glBlendFunc(GL_ONE, GL_ONE);

    glUseProgram(line_program_);
    glUniform2f(loc_resolution_, (float)width_, (float)height_);

    glBindVertexArray(line_vao_);
    glBindBuffer(GL_ARRAY_BUFFER, line_vbo_);
    glBufferData(GL_ARRAY_BUFFER, vertex_buffer_.size() * sizeof(float), vertex_buffer_.data(), GL_DYNAMIC_DRAW);
    glDrawArrays(GL_TRIANGLES, 0, (GLsizei)(vertex_buffer_.size() / 7));

    glBindVertexArray(0);
    glDisable(GL_BLEND);
    glBindFramebuffer(GL_FRAMEBUFFER, 0);

    vertex_buffer_.clear();
}

void Renderer::update_display(const PostProcess& pp) {
    flush();

    float divisor = 1.0f;
    if (has_compute_) {
        divisor = compute_max_gpu();
    } else {
        glBindTexture(GL_TEXTURE_2D, float_texture_);
        glGetTexImage(GL_TEXTURE_2D, 0, GL_RGBA, GL_FLOAT, float_buffer_.data());
        for (size_t i = 0; i < float_buffer_.size(); i += 4) {
            divisor = std::max(divisor, float_buffer_[i]);
            divisor = std::max(divisor, float_buffer_[i + 1]);
            divisor = std::max(divisor, float_buffer_[i + 2]);
        }
    }
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
