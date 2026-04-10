#pragma once
//
// GPU compute-shader frame analyser.
//
// Runs `src/shaders/analysis.comp` on an RGB8 texture (typically
// `Renderer::display_texture_`) and produces a complete FrameAnalysis via
// SSBO readback. This path is retained for low-level renderer diagnostics;
// the public analysis contract is implemented by the CPU RGB8 analyzer in
// `src/core/image_analysis.cpp`.
//
// Lifetime is tied to the owning Renderer / RenderSession: one instance per
// GL context, created during `init()` after a current context is ready,
// torn down in `shutdown()`. Works identically under GLFW (GUI) and EGL
// pbuffer (headless) because both create GL 4.3 Core profiles.

#include "image_analysis.h"

#include <GL/glew.h>

#include <cstdint>
#include <span>
#include <vector>

struct Bounds;

class GpuImageAnalyzer {
public:
    // Radial-bin count for retained light-bin diagnostics. Must match MAX_BINS in
    // src/shaders/analysis.comp. The light count is NOT capped — the
    // Lights and CirclesResult SSBOs are dynamically resized on each
    // analyze() call so scenes with arbitrary numbers of point lights
    // all get one PointLightAppearance per input entry.
    static constexpr int kMaxBins = 201;

    // Compile analysis.comp and allocate the 4 SSBOs. The caller MUST have
    // a current GL 4.3 Core context on the calling thread. Returns false
    // on compile/link failure; in that case the instance is left in a
    // clean state and `analyze()` is not callable.
    bool init();

    // Release the program and SSBOs. Safe to call multiple times.
    void shutdown();

    ~GpuImageAnalyzer();

    GpuImageAnalyzer() = default;
    GpuImageAnalyzer(const GpuImageAnalyzer&) = delete;
    GpuImageAnalyzer& operator=(const GpuImageAnalyzer&) = delete;

    // Run the analysis. `source_texture` must be an RGB8 texture the size
    // of the framebuffer being analysed; typically `display_texture_`.
    // `world_bounds` is needed to map PointLight world coordinates back
    // into pixel space for the point-light measurement. `lights` may be empty.
    //
    // Before calling this, the renderer should issue
    //   glMemoryBarrier(GL_TEXTURE_FETCH_BARRIER_BIT |
    //                   GL_FRAMEBUFFER_BARRIER_BIT);
    // if any draws into the owning FBO have happened since the last
    // analysis dispatch — otherwise the NVIDIA EGL driver may return
    // stale data from the ROP cache (see renderer.cpp comments around
    // the compute_max_gpu path for the history of this quirk).
    FrameAnalysis analyze(GLuint source_texture, int width, int height,
                          const Bounds& world_bounds,
                          std::span<const LightRef> lights,
                          const FrameAnalysisParams& params = {});

private:
    GLuint program_      = 0;
    GLuint lum_ssbo_     = 0;  // fixed-size: LumResult struct
    GLuint color_ssbo_   = 0;  // fixed-size: ColorResult struct
    GLuint circles_ssbo_ = 0;  // dynamic:    uNLights * kMaxBins * 3 uints
    GLuint lights_ssbo_  = 0;  // dynamic:    uNLights * vec2 (= 8 bytes each)

    // Byte capacity of the two dynamically-sized SSBOs. They grow on
    // demand in analyze() via glBufferData when the scene's light
    // count exceeds what we've previously allocated. Doubling on
    // growth amortises the reallocation cost across frames.
    std::size_t lights_ssbo_capacity_  = 0;
    std::size_t circles_ssbo_capacity_ = 0;

    // Reusable CPU-side scratch buffers — `analyze()` used to allocate
    // both of these per call, which showed up as steady heap churn on
    // the per-frame GUI path. Kept as members so the second analyze()
    // onward is allocation-free whenever `lights.size()` is stable.
    std::vector<float>    lights_px_scratch_;
    std::vector<uint32_t> circles_raw_scratch_;

    // Cached uniform locations (-1 if not present).
    GLint u_resolution_ = -1;
    GLint u_nlights_    = -1;
    GLint u_bright_     = -1;
    GLint u_max_bins_   = -1;
    GLint u_sat_        = -1;
    GLint u_src_        = -1;

    // Grow a dynamic SSBO if `required_bytes` exceeds its current
    // capacity. No-op otherwise. `capacity` is the caller-held byte
    // count to update in place.
    void grow_dynamic_ssbo_(GLuint ssbo, std::size_t& capacity,
                            std::size_t required_bytes);
};
