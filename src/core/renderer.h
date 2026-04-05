#pragma once

#include "scene.h"

#include <GL/glew.h>
#include <array>
#include <cstdint>
#include <vector>

struct FrameMetrics {
    float mean_lum;    // mean BT.709 luminance (0-255 scale)
    float pct_black;   // fraction of pixels with luminance < 1
    float pct_clipped; // fraction of pixels with any channel == 255
    float p50;         // median luminance
    float p95;         // 95th percentile luminance
    std::array<int, 256> histogram{}; // BT.709 luminance histogram (256 bins)
};

class Renderer {
public:
    ~Renderer();

    bool init(int width, int height, bool half_float = false);
    void resize(int width, int height);
    void shutdown();
    void clear();

    // Upload scene geometry, lights, and viewport transform to GPU
    void upload_scene(const Scene& scene, const Bounds& bounds);

    // Update only the viewport transform (for pan/zoom without re-uploading geometry)
    void update_viewport(const Bounds& bounds);


    // GPU compute trace + instanced draw (one batch)
    void trace_and_draw(const TraceConfig& cfg);

    // Multi-batch: dispatch N compute batches, then one draw call
    void trace_and_draw_multi(const TraceConfig& cfg, int num_dispatches);

    // Post-processing and readback (unchanged)
    void update_display(const PostProcess& pp, float display_aspect = 0.0f);
    void read_pixels(std::vector<uint8_t>& out_rgb, const PostProcess& pp, float display_aspect = 0.0f);
    void read_display_rgba(std::vector<uint8_t>& out_rgba);

    GLuint display_texture() const { return display_texture_; }
    float last_max() const { return last_max_; }
    int width() const { return width_; }
    int height() const { return height_; }
    int num_lights() const { return num_lights_; }
    int64_t total_rays() const { return total_rays_; }

    // Compute current max luminance from the float accumulation buffer (CPU readback).
    float compute_current_max();

    // Compute per-frame stats from the post-processed RGBA8 buffer.
    // Must be called after read_pixels() (which populates rgba_buffer_).
    FrameMetrics compute_frame_metrics() const;

    // Compute metrics from the current display FBO (reads back RGBA8 pixels).
    // Standalone — does not require prior read_pixels() call.
    FrameMetrics compute_display_metrics();

private:
    int width_ = 0, height_ = 0;
    bool half_precision_ = false; // RGBA16F instead of RGBA32F (fast preview mode)

    // Float accumulation FBO
    GLuint fbo_ = 0;
    GLuint float_texture_ = 0; // GL_RGBA32F or GL_RGBA16F

    // Display FBO (8-bit for ImGui / export)
    GLuint display_fbo_ = 0;
    GLuint display_texture_ = 0; // GL_RGBA8

    // --- GPU tracing ---
    GLuint trace_program_ = 0;

    // Scene SSBOs
    GLuint circle_ssbo_ = 0;
    GLuint segment_ssbo_ = 0;
    GLuint arc_ssbo_ = 0;
    GLuint bezier_ssbo_ = 0;
    GLuint light_ssbo_ = 0;
    GLuint light_weights_ssbo_ = 0;
    GLuint ellipse_ssbo_ = 0;
    int num_circles_ = 0;
    int num_segments_ = 0;
    int num_arcs_ = 0;
    int num_beziers_ = 0;
    int num_ellipses_ = 0;
    int num_lights_ = 0;

    // Wavelength LUT texture
    GLuint wavelength_lut_ = 0;

    // Output segment SSBO + draw indirect buffer
    GLuint output_ssbo_ = 0;
    GLuint draw_cmd_buffer_ = 0;
    size_t max_output_segments_ = 0;

    // Trace shader uniform locations
    GLint trace_loc_num_circles_ = -1;
    GLint trace_loc_num_segments_ = -1;
    GLint trace_loc_num_arcs_ = -1;
    GLint trace_loc_num_beziers_ = -1;
    GLint trace_loc_num_ellipses_ = -1;
    GLint trace_loc_num_lights_ = -1;
    GLint trace_loc_max_depth_ = -1;
    GLint trace_loc_seed_ = -1;
    GLint trace_loc_intensity_ = -1;
    GLint trace_loc_max_segments_ = -1;
    GLint trace_loc_view_offset_ = -1;
    GLint trace_loc_view_scale_ = -1;
    GLint trace_loc_bounds_min_ = -1;
    GLint trace_loc_wavelength_lut_ = -1;

    uint32_t batch_counter_ = 0;
    int64_t total_rays_ = 0;

    // --- Instanced line drawing ---
    GLuint line_program_ = 0;
    GLuint line_vao_ = 0;
    GLint loc_resolution_ = -1;
    GLint loc_thickness_ = -1;

    // --- Post-processing ---
    GLuint pp_program_ = 0;
    GLuint pp_vao_ = 0;

    // Compute shader max reduction
    GLuint max_compute_ = 0;
    GLuint max_ssbo_ = 0;
    GLint max_loc_input_texture_ = -1;
    GLint max_loc_tex_size_ = -1;

    float last_max_ = 0.0f;
    float viewport_scale_ = 1.0f;
    std::vector<uint8_t> rgba_buffer_;

    // Cached PP uniform locations
    GLint loc_max_val_ = -1;
    GLint loc_exposure_ = -1;
    GLint loc_contrast_ = -1;
    GLint loc_inv_gamma_ = -1;
    GLint loc_tone_map_ = -1;
    GLint loc_white_point_ = -1;
    GLint loc_float_tex_ = -1;
    GLint loc_ambient_ = -1;
    GLint loc_background_ = -1;
    GLint loc_opacity_ = -1;
    GLint loc_saturation_ = -1;
    GLint loc_vignette_ = -1;
    GLint loc_vignette_radius_ = -1;
    GLint loc_aspect_ = -1;

    bool create_framebuffers();
    void delete_framebuffers();
    bool create_trace_shader();
    bool create_line_shader();
    bool create_pp_shader();
    bool create_compute_shader();
    void create_wavelength_lut();
    float compute_max_gpu(float percentile = 1.0f);
};
