#pragma once

#include "gpu_image_analysis.h"
#include "image_analysis.h"

#include <GL/glew.h>
#include <stddef.h>
#include <cstdint>
#include <vector>

#include "scene.h"  // for Bounds (cached by value in Renderer)

struct PostProcess;
struct Scene;
struct TraceConfig;

// FrameMetrics is the luminance-only view of the authored-camera analysis.
// It aliases the same LuminanceStats struct exposed on
// FrameAnalysis.luminance.
using FrameMetrics = LuminanceStats;

struct VignetteFrame {
    float center[2] = {0.5f, 0.5f};
    float inv_size[2] = {1.0f, 1.0f};
    float x_scale = 1.0f;
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

    // Triangulate and render filled shape interiors into the fill texture
    void upload_fills(const Scene& scene, const Bounds& bounds);

    // Re-render cached fill geometry with updated viewport (for pan/zoom)
    void redraw_fills(const Bounds& bounds);

    GLuint fill_texture() const { return fill_texture_; }


    // GPU compute trace + instanced draw (one batch)
    void trace_and_draw(const TraceConfig& cfg);

    // Multi-batch: dispatch N compute batches, then one draw call
    void trace_and_draw_multi(const TraceConfig& cfg, int num_dispatches);

    // Draw the most recent traced world-space line batch from another
    // renderer into this renderer's accumulation buffer using this
    // renderer's viewport transform. This lets the GUI reuse one trace for
    // both the viewport and authored-camera analysis.
    void draw_trace_output_from(const Renderer& source);

    // Post-process the current accumulation buffer into the final RGB8 display texture.
    void update_display(const PostProcess& pp, float display_aspect = 0.0f,
                        const VignetteFrame* vignette_frame = nullptr);
    // Read final RGB pixels for image output. When analysis outputs are requested,
    // metrics are produced from the GPU display texture before the pixel readback.
    void read_pixels(std::vector<uint8_t>& out_rgb, const PostProcess& pp, float display_aspect = 0.0f,
                     const VignetteFrame* vignette_frame = nullptr, FrameMetrics* out_metrics = nullptr,
                     FrameAnalysis* out_analysis = nullptr);
    void read_display_rgba(std::vector<uint8_t>& out_rgba);

    GLuint display_texture() const { return display_texture_; }
    float last_max() const { return last_max_; }
    int width() const { return width_; }
    int height() const { return height_; }
    int num_lights() const { return num_lights_; }
    int64_t total_rays() const { return total_rays_; }
    int64_t last_trace_rays() const { return last_trace_rays_; }
    uint64_t trace_generation() const { return trace_generation_; }

    // Compute current max luminance from the float accumulation buffer (CPU readback).
    float compute_current_max();

    // Analyze the current display FBO. Callers that need authored-camera
    // semantics must render/upload this Renderer with authored-camera bounds
    // first; the GUI Stats path uses a dedicated renderer for that reason.
    FrameAnalysis run_frame_analysis(const FrameAnalysisParams& params = {});

private:
    int width_ = 0, height_ = 0;
    bool half_precision_ = false; // RGBA16F instead of RGBA32F (fast preview mode)

    // Float accumulation FBO
    GLuint fbo_ = 0;
    GLuint float_texture_ = 0; // GL_RGB32F or GL_RGB16F

    // Display FBO (8-bit for ImGui / export)
    GLuint display_fbo_ = 0;
    GLuint display_texture_ = 0; // GL_RGB8

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
    GLuint material_ssbo_ = 0;
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
    GLint trace_loc_depth_ = -1;
    GLint trace_loc_seed_ = -1;
    GLint trace_loc_intensity_ = -1;
    GLint trace_loc_batch_rays_ = -1;
    GLint trace_loc_num_dispatches_ = -1;
    GLint trace_loc_dispatch_seeds_ = -1;
    GLint trace_loc_max_segments_ = -1;
    GLint trace_loc_wavelength_lut_ = -1;
    GLint trace_loc_material_offsets_ = -1;

    uint32_t batch_counter_ = 0;
    int64_t total_rays_ = 0;
    int64_t last_trace_rays_ = 0;
    int last_trace_dispatches_ = 0;
    uint64_t trace_generation_ = 0;

    // --- Instanced line drawing ---
    GLuint line_program_ = 0;
    GLuint line_vao_ = 0;
    GLint loc_resolution_ = -1;
    GLint loc_thickness_ = -1;
    GLint line_loc_bounds_min_ = -1;
    GLint line_loc_view_scale_ = -1;
    GLint line_loc_view_offset_ = -1;

    // --- Fill pass (shape interiors) ---
    GLuint fill_program_ = 0;
    GLuint fill_vao_ = 0;
    GLuint fill_vbo_ = 0;
    int fill_vertex_count_ = 0;
    GLuint fill_fbo_ = 0;         // Resolve target (regular texture for post-process sampling)
    GLuint fill_texture_ = 0;     // GL_RGB16F, sampled in postprocess.frag
    GLuint fill_ms_fbo_ = 0;      // Multisample render target (4x MSAA)
    GLuint fill_ms_rbo_ = 0;      // GL_RGB16F multisample renderbuffer
    GLint fill_loc_bounds_min_ = -1;
    GLint fill_loc_view_scale_ = -1;
    GLint fill_loc_view_offset_ = -1;
    GLint fill_loc_resolution_ = -1;

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
    float viewport_offset_x_ = 0.0f;
    float viewport_offset_y_ = 0.0f;
    std::vector<uint8_t> rgba_buffer_;
    std::vector<uint8_t> rgb_row_buffer_;

    // Cached from upload_scene() / update_viewport() so run_frame_analysis
    // can run with no scene context from the caller.
    Bounds last_upload_bounds_{};
    std::vector<LightRef> light_refs_;

    // GPU frame analyser. Lifetime tied to this Renderer; init() in
    // Renderer::init() after the GL context is current, shutdown() in
    // Renderer::shutdown().
    GpuImageAnalyzer analyzer_;

    // Cached PP uniform locations
    GLint loc_max_val_ = -1;
    GLint loc_exposure_ = -1;
    GLint loc_contrast_ = -1;
    GLint loc_inv_gamma_ = -1;
    GLint loc_tonemap_ = -1;
    GLint loc_white_point_ = -1;
    GLint loc_float_tex_ = -1;
    GLint loc_fill_tex_ = -1;
    GLint loc_ambient_ = -1;
    GLint loc_background_ = -1;
    GLint loc_opacity_ = -1;
    GLint loc_saturation_ = -1;
    GLint loc_vignette_ = -1;
    GLint loc_vignette_radius_ = -1;
    GLint loc_vignette_center_ = -1;
    GLint loc_vignette_inv_size_ = -1;
    GLint loc_vignette_x_scale_ = -1;
    GLint loc_temperature_ = -1;
    GLint loc_highlights_ = -1;
    GLint loc_shadows_ = -1;
    GLint loc_hue_rot_ = -1;
    GLint loc_grain_ = -1;
    GLint loc_grain_seed_ = -1;
    GLint loc_chromatic_aberration_ = -1;

    bool create_framebuffers();
    void delete_framebuffers();
    bool create_trace_shader();
    bool create_line_shader();
    bool create_fill_shader();
    bool create_pp_shader();
    bool create_compute_shader();
    void draw_trace_output(GLuint output_ssbo, GLuint draw_cmd_buffer);
    void create_wavelength_lut();
    float compute_max_gpu(float percentile = 1.0f);
};
