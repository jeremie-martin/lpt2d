#pragma once

#include "scene.h"

#include <GL/glew.h>
#include <cstdint>
#include <vector>

class Renderer {
public:
    ~Renderer();

    bool init(int width, int height);
    void shutdown();
    void clear();

    void draw_lines(std::span<const LineSegment> segments, float thickness = 1.5f);
    void flush();

    void update_display(const PostProcess& pp);
    void read_pixels(std::vector<uint8_t>& out_rgb, const PostProcess& pp);

    GLuint display_texture() const { return display_texture_; }
    float last_max() const { return last_max_; }
    int width() const { return width_; }
    int height() const { return height_; }

private:
    int width_ = 0, height_ = 0;

    // Float accumulation FBO
    GLuint fbo_ = 0;
    GLuint float_texture_ = 0; // GL_RGBA32F

    // Display FBO (8-bit for ImGui / export)
    GLuint display_fbo_ = 0;
    GLuint display_texture_ = 0; // GL_RGBA8

    // Line drawing
    GLuint line_program_ = 0;
    GLuint line_vao_ = 0;
    GLuint line_vbo_ = 0;
    std::vector<float> vertex_buffer_;

    // Post-processing
    GLuint pp_program_ = 0;
    GLuint pp_vao_ = 0;

    // Compute shader max reduction (GL 4.3+)
    GLuint max_compute_ = 0;
    GLuint max_ssbo_ = 0;
    bool has_compute_ = false;

    float last_max_ = 0.0f;
    std::vector<float> float_buffer_;

    // Cached uniform locations
    GLint loc_resolution_ = -1;
    GLint loc_max_val_ = -1;
    GLint loc_exposure_ = -1;
    GLint loc_contrast_ = -1;
    GLint loc_inv_gamma_ = -1;
    GLint loc_tone_map_ = -1;
    GLint loc_white_point_ = -1;
    GLint loc_float_tex_ = -1;

    bool create_framebuffers();
    void delete_framebuffers();
    bool create_line_shader();
    bool create_pp_shader();
    bool create_compute_shader();
    float compute_max_gpu();
};
