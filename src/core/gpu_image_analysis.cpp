#include "gpu_image_analysis.h"

#include "gl_shader_utils.h"
#include "scene.h"    // Bounds, Vec2
#include "shaders.h"  // analysis_comp[] (embedded from src/shaders/analysis.comp)

#include <algorithm>
#include <array>
#include <cmath>

namespace {

// LumResult std430: uint hist[256] + lum_clipped + lum_npixels (the
// latter is a convenience slot the shader doesn't write — computed
// CPU-side). No padding uints; the old layout had two that nothing
// read or wrote.
constexpr std::size_t kLumBytes   = (256 + 2) * sizeof(uint32_t);
// ColorResult std430: uint hue_hist[36] + sat_sum_q8 + n_colored.
constexpr std::size_t kColorBytes = (36 + 2) * sizeof(uint32_t);

// Initial capacity for the dynamic SSBOs — enough for typical scenes
// without a reallocation on the first few analyze() calls. Grows by
// doubling on demand when a scene has more lights than we've seen.
constexpr std::size_t kInitialLightCount = 8;
constexpr std::size_t kInitialLightsBytes =
    kInitialLightCount * 2u * sizeof(float);
constexpr std::size_t kInitialCirclesBytes =
    kInitialLightCount * static_cast<std::size_t>(GpuImageAnalyzer::kMaxBins) *
    3u * sizeof(uint32_t);

inline std::size_t lights_bytes_for(int n_lights) {
    return static_cast<std::size_t>(std::max(n_lights, 1)) * 2u * sizeof(float);
}
inline std::size_t circles_bytes_for(int n_lights) {
    return static_cast<std::size_t>(std::max(n_lights, 1)) *
           static_cast<std::size_t>(GpuImageAnalyzer::kMaxBins) *
           3u * sizeof(uint32_t);
}

}  // namespace

// ─── Init / shutdown ───────────────────────────────────────────────────

bool GpuImageAnalyzer::init() {
    if (program_ != 0) {
        return true;  // already initialised
    }

    GLuint cs = compile_gl_shader(GL_COMPUTE_SHADER, analysis_comp, "analysis.comp");
    if (cs == 0) return false;
    program_ = link_gl_compute(cs, "analysis.comp");
    if (program_ == 0) return false;

    // Cache uniform locations. GL may return -1 for any uniform the
    // compiler optimised out; that's tolerated at use-site by glUniform*
    // silently ignoring negative locations.
    u_src_        = glGetUniformLocation(program_, "uSrc");
    u_resolution_ = glGetUniformLocation(program_, "uResolution");
    u_nlights_    = glGetUniformLocation(program_, "uNLights");
    u_bright_     = glGetUniformLocation(program_, "uBrightThreshold");
    u_max_bins_   = glGetUniformLocation(program_, "uMaxRadiusBins");
    u_sat_        = glGetUniformLocation(program_, "uSatThreshold");

    // Allocate the 4 SSBOs. Luminance and colour are fixed-size (one
    // histogram each). Lights and Circles are dynamically resized per
    // analyze() call and start at a capacity sized for ~8 lights —
    // `grow_dynamic_ssbo_` will enlarge them via glBufferData on
    // demand if the scene's PointLight count grows.
    auto make_ssbo = [](std::size_t bytes) {
        GLuint id = 0;
        glGenBuffers(1, &id);
        glBindBuffer(GL_SHADER_STORAGE_BUFFER, id);
        glBufferData(GL_SHADER_STORAGE_BUFFER,
                     static_cast<GLsizeiptr>(bytes), nullptr, GL_DYNAMIC_DRAW);
        glBindBuffer(GL_SHADER_STORAGE_BUFFER, 0);
        return id;
    };

    lum_ssbo_     = make_ssbo(kLumBytes);
    color_ssbo_   = make_ssbo(kColorBytes);
    circles_ssbo_ = make_ssbo(kInitialCirclesBytes);
    lights_ssbo_  = make_ssbo(kInitialLightsBytes);
    circles_ssbo_capacity_ = kInitialCirclesBytes;
    lights_ssbo_capacity_  = kInitialLightsBytes;

    return (lum_ssbo_ && color_ssbo_ && circles_ssbo_ && lights_ssbo_);
}

void GpuImageAnalyzer::grow_dynamic_ssbo_(GLuint ssbo, std::size_t& capacity,
                                          std::size_t required_bytes) {
    if (required_bytes <= capacity) return;
    // Double the capacity until it covers the requirement, so repeated
    // scene edits that add lights one-by-one don't trigger a
    // glBufferData reallocation every frame.
    std::size_t new_capacity = capacity == 0 ? required_bytes : capacity * 2;
    while (new_capacity < required_bytes) new_capacity *= 2;
    glBindBuffer(GL_SHADER_STORAGE_BUFFER, ssbo);
    glBufferData(GL_SHADER_STORAGE_BUFFER,
                 static_cast<GLsizeiptr>(new_capacity), nullptr, GL_DYNAMIC_DRAW);
    glBindBuffer(GL_SHADER_STORAGE_BUFFER, 0);
    capacity = new_capacity;
}

void GpuImageAnalyzer::shutdown() {
    if (program_ != 0)     { glDeleteProgram(program_);       program_ = 0; }
    if (lum_ssbo_ != 0)    { glDeleteBuffers(1, &lum_ssbo_);    lum_ssbo_ = 0; }
    if (color_ssbo_ != 0)  { glDeleteBuffers(1, &color_ssbo_);  color_ssbo_ = 0; }
    if (circles_ssbo_ != 0){ glDeleteBuffers(1, &circles_ssbo_); circles_ssbo_ = 0; }
    if (lights_ssbo_ != 0) { glDeleteBuffers(1, &lights_ssbo_); lights_ssbo_ = 0; }
    lights_ssbo_capacity_ = 0;
    circles_ssbo_capacity_ = 0;
    // Uniform location caches are unconditionally overwritten by the
    // next init() call, so no reset here.
}

GpuImageAnalyzer::~GpuImageAnalyzer() {
    shutdown();
}

// ─── Analyze ───────────────────────────────────────────────────────────

FrameAnalysis
GpuImageAnalyzer::analyze(GLuint source_texture, int width, int height,
                          const Bounds& world_bounds,
                          std::span<const LightRef> lights,
                          const FrameAnalysisParams& params) {
    FrameAnalysis out;

    if (program_ == 0 || width <= 0 || height <= 0 || source_texture == 0) {
        return out;
    }

    // `n_lights` is the number of point-light appearance records the caller
    // will receive — one per input LightRef, no cap. The shader sees
    // `n_lights_gpu`, which is zero when light analysis is disabled so the
    // per-pixel Voronoi loop short-circuits and the expensive O(W*H*L) work is
    // actually skipped (not just skipped on the CPU side of readback).
    const int n_lights = static_cast<int>(lights.size());
    const bool want_circles = params.analyze_lights && n_lights > 0;
    const int n_lights_gpu = want_circles ? n_lights : 0;
    const int search_radius = std::max(
        2, static_cast<int>(std::ceil(params.lights.search_radius_ratio *
                                      static_cast<float>(std::min(width, height)))));
    const int max_bins = std::min(search_radius + 1, kMaxBins);

    // Precompute pixel-space light centres in the TOP-LEFT convention
    // used by viewport_xform. The shader flips gid.y internally so
    // distances against these centres are correct regardless of the
    // underlying GL texel bottom-left origin. `lights_px_scratch_` is
    // a member buffer so steady-state analyse() calls don't allocate.
    const auto vp = viewport_xform(world_bounds, width, height);
    lights_px_scratch_.resize(static_cast<std::size_t>(std::max(n_lights, 0)) * 2u);
    for (int i = 0; i < n_lights; ++i) {
        const auto& lr = lights[i];
        lights_px_scratch_[2 * i + 0] =
            (lr.world_x - world_bounds.min.x) * vp.scale + vp.offset_x;
        lights_px_scratch_[2 * i + 1] =
            (world_bounds.max.y - lr.world_y) * vp.scale + vp.offset_y;
    }

    // Grow the dynamic SSBOs if the scene's light count exceeds our
    // current allocation. For common steady-state scenes this is a
    // no-op after the first few frames.
    if (n_lights_gpu > 0) {
        grow_dynamic_ssbo_(lights_ssbo_, lights_ssbo_capacity_,
                           lights_bytes_for(n_lights_gpu));
        grow_dynamic_ssbo_(circles_ssbo_, circles_ssbo_capacity_,
                           circles_bytes_for(n_lights_gpu));
    }

    // Upload lights and zero the output SSBOs. `glClearBufferData` is
    // faster than uploading a CPU-side zero blob each call.
    if (n_lights_gpu > 0) {
        glBindBuffer(GL_SHADER_STORAGE_BUFFER, lights_ssbo_);
        glBufferSubData(GL_SHADER_STORAGE_BUFFER, 0,
                        static_cast<GLsizeiptr>(lights_bytes_for(n_lights_gpu)),
                        lights_px_scratch_.data());
    }

    const uint32_t zero = 0;
    glBindBuffer(GL_SHADER_STORAGE_BUFFER, lum_ssbo_);
    glClearBufferData(GL_SHADER_STORAGE_BUFFER, GL_R32UI, GL_RED_INTEGER,
                      GL_UNSIGNED_INT, &zero);
    glBindBuffer(GL_SHADER_STORAGE_BUFFER, color_ssbo_);
    glClearBufferData(GL_SHADER_STORAGE_BUFFER, GL_R32UI, GL_RED_INTEGER,
                      GL_UNSIGNED_INT, &zero);
    if (want_circles) {
        glBindBuffer(GL_SHADER_STORAGE_BUFFER, circles_ssbo_);
        glClearBufferData(GL_SHADER_STORAGE_BUFFER, GL_R32UI, GL_RED_INTEGER,
                          GL_UNSIGNED_INT, &zero);
    }
    glBindBuffer(GL_SHADER_STORAGE_BUFFER, 0);

    // Bind program, sampler, SSBOs.
    glUseProgram(program_);

    glActiveTexture(GL_TEXTURE0);
    glBindTexture(GL_TEXTURE_2D, source_texture);
    if (u_src_ >= 0) glUniform1i(u_src_, 0);

    if (u_resolution_ >= 0) glUniform2i(u_resolution_, width, height);
    if (u_nlights_ >= 0)    glUniform1i(u_nlights_, n_lights_gpu);
    if (u_bright_ >= 0)     glUniform1f(u_bright_, params.lights.legacy_bright_threshold);
    if (u_max_bins_ >= 0)   glUniform1i(u_max_bins_, max_bins);
    if (u_sat_ >= 0)        glUniform1f(u_sat_, params.saturation_threshold);

    glBindBufferBase(GL_SHADER_STORAGE_BUFFER, 0, lum_ssbo_);
    glBindBufferBase(GL_SHADER_STORAGE_BUFFER, 1, color_ssbo_);
    glBindBufferBase(GL_SHADER_STORAGE_BUFFER, 2, circles_ssbo_);
    glBindBufferBase(GL_SHADER_STORAGE_BUFFER, 3, lights_ssbo_);

    // Dispatch. 16x16 tiles, rounded up.
    const GLuint gx = static_cast<GLuint>((width  + 15) / 16);
    const GLuint gy = static_cast<GLuint>((height + 15) / 16);
    glDispatchCompute(gx, gy, 1);

    // Ensure the SSBOs are visible to the subsequent glGetBufferSubData.
    glMemoryBarrier(GL_BUFFER_UPDATE_BARRIER_BIT | GL_SHADER_STORAGE_BARRIER_BIT);

    // ── Readback ───────────────────────────────────────────────────────
    //
    // Lum + colour are always < 1.5 KB. The circles buffer scales with
    // n_lights_gpu (~2.4 KB per light at kMaxBins=201), but the call is
    // skipped entirely when the caller opted out of circle analysis.

    std::array<uint32_t, 256 + 2> lum_raw{};
    glBindBuffer(GL_SHADER_STORAGE_BUFFER, lum_ssbo_);
    glGetBufferSubData(GL_SHADER_STORAGE_BUFFER, 0,
                       static_cast<GLsizeiptr>(kLumBytes), lum_raw.data());

    std::array<uint32_t, 36 + 2> color_raw{};
    glBindBuffer(GL_SHADER_STORAGE_BUFFER, color_ssbo_);
    glGetBufferSubData(GL_SHADER_STORAGE_BUFFER, 0,
                       static_cast<GLsizeiptr>(kColorBytes), color_raw.data());

    if (want_circles) {
        circles_raw_scratch_.resize(static_cast<std::size_t>(n_lights_gpu) *
                                    static_cast<std::size_t>(kMaxBins) * 3u);
        glBindBuffer(GL_SHADER_STORAGE_BUFFER, circles_ssbo_);
        glGetBufferSubData(GL_SHADER_STORAGE_BUFFER, 0,
                           static_cast<GLsizeiptr>(circles_bytes_for(n_lights_gpu)),
                           circles_raw_scratch_.data());
    }
    glBindBuffer(GL_SHADER_STORAGE_BUFFER, 0);

    // ── Luminance finalize (shared with CPU path) ──────────────────────
    if (params.analyze_luminance) {
        std::array<int, 256> hist_int{};
        for (int i = 0; i < 256; ++i) {
            hist_int[i] = static_cast<int>(lum_raw[i]);
        }
        const int clipped = static_cast<int>(lum_raw[256]);
        out.luminance = finalize_luminance(hist_int, clipped, width, height,
                                           params.near_black_bin_max,
                                           params.near_white_bin_min);
    }

    // ── Color finalize (inline) ────────────────────────────────────────
    if (params.analyze_color) {
        ColorStats cs;
        for (int i = 0; i < 36; ++i) {
            cs.hue_histogram[i] = static_cast<int>(color_raw[i]);
        }
        const uint32_t sat_sum_q8 = color_raw[36];
        const uint32_t n_colored = color_raw[37];
        const std::size_t n_pixels  =
            static_cast<std::size_t>(width) * static_cast<std::size_t>(height);

        cs.n_colored = static_cast<int>(n_colored);
        cs.colored_fraction = n_pixels > 0
            ? static_cast<float>(n_colored) / static_cast<float>(n_pixels)
            : 0.0f;
        cs.mean_saturation = n_colored > 0
            ? (static_cast<float>(sat_sum_q8) / 255.0f) / static_cast<float>(n_colored)
            : 0.0f;

        // Shannon entropy on the hue histogram (bits).
        if (n_colored > 0) {
            const double inv = 1.0 / static_cast<double>(n_colored);
            double entropy = 0.0;
            for (int k = 0; k < 36; ++k) {
                if (cs.hue_histogram[k] > 0) {
                    const double p = static_cast<double>(cs.hue_histogram[k]) * inv;
                    entropy -= p * std::log2(p);
                }
            }
            cs.hue_entropy = static_cast<float>(entropy);
        }
        cs.richness = cs.hue_entropy * cs.mean_saturation * cs.colored_fraction;
        out.color = cs;
    }

    // ── Circles finalize (per-light) ───────────────────────────────────
    //
    // One PointLightAppearance per input light. When light binning is
    // disabled on the GPU side (want_circles == false) we still emit the
    // per-input ids/world coords with zeroed metric fields, so downstream
    // code never has to guess whether a light was silently dropped.
    if (n_lights > 0) {
        out.lights.reserve(static_cast<std::size_t>(n_lights));

        const float short_side = static_cast<float>(std::min(width, height));

        for (int i = 0; i < n_lights; ++i) {
            PointLightAppearance c;
            c.id = lights[i].id;
            c.world_x = lights[i].world_x;
            c.world_y = lights[i].world_y;
            c.image_x = lights_px_scratch_[2 * i + 0];
            c.image_y = lights_px_scratch_[2 * i + 1];

            if (!want_circles) {
                out.lights.push_back(std::move(c));
                continue;
            }

            // Flat interleaved layout: per-bin [sum, cnt, bright]
            // triples, MAX_BINS bins per light.
            const uint32_t* base =
                circles_raw_scratch_.data() +
                static_cast<std::size_t>(i) * kMaxBins * 3u;

            // Radial profile directly in 0..1 luminance scale so that
            // downstream FWHM and sharpness are scale-correct. The old
            // code built it in 0..255 first and only rescaled after
            // computing sharpness, producing a ~255x overshoot that
            // broke every sharpness threshold downstream.
            std::vector<float> profile(static_cast<std::size_t>(max_bins), 0.0f);
            uint32_t total_bright = 0;
            for (int r = 0; r < max_bins; ++r) {
                const uint32_t psum = base[r * 3 + 0];
                const uint32_t pcnt = base[r * 3 + 1];
                const uint32_t pbr  = base[r * 3 + 2];
                total_bright += pbr;
                if (pcnt > 0) {
                    profile[r] = (static_cast<float>(psum) /
                                  static_cast<float>(pcnt)) / 255.0f;
                }
            }
            const int bright_pixels = static_cast<int>(total_bright);
            c.visible = bright_pixels > 0;
            c.coverage_fraction = static_cast<float>(bright_pixels) /
                                  static_cast<float>(width * height);

            float legacy_radius_px = 0.0f;
            if (bright_pixels >= params.lights.legacy_min_bright_pixels &&
                total_bright > 0) {
                const float pct = std::clamp(
                    params.lights.legacy_radius_percentile / 100.0f, 0.0f, 1.0f);
                const uint32_t target = static_cast<uint32_t>(
                    std::floor(static_cast<float>(total_bright) * pct));
                bool radius_set = false;
                uint32_t cumul = 0;
                for (int r = 0; r < max_bins; ++r) {
                    cumul += base[r * 3 + 2];
                    if (cumul > target) {
                        legacy_radius_px = static_cast<float>(r);
                        radius_set = true;
                        break;
                    }
                }
                if (!radius_set) {
                    for (int r = max_bins - 1; r >= 0; --r) {
                        if (base[r * 3 + 2] > 0) {
                            legacy_radius_px = static_cast<float>(r);
                            break;
                        }
                    }
                }
            }
            c.saturated_radius_ratio = legacy_radius_px / short_side;

            float peak = 0.0f;
            for (int r = 0; r < max_bins; ++r) {
                peak = std::max(peak, profile[r]);
            }
            c.peak_luminance = peak;
            c.background_luminance = max_bins > 0 ? profile[max_bins - 1] : 0.0f;
            c.peak_contrast = std::max(0.0f, c.peak_luminance - c.background_luminance);
            c.radius_ratio = c.saturated_radius_ratio;
            c.transition_width_ratio = 0.0f;
            if (legacy_radius_px > 2.0f) {
                const int r_lo = std::max(1, static_cast<int>(legacy_radius_px * 0.5f));
                const int r_hi = std::min(max_bins - 2,
                                           static_cast<int>(legacy_radius_px * 1.5f) + 1);
                if (r_hi > r_lo) {
                    const float sharpness = (profile[r_lo] - profile[r_hi]) /
                                            static_cast<float>(r_hi - r_lo);
                    c.transition_width_ratio = sharpness > 0.0f
                        ? (1.0f / sharpness) / short_side
                        : 0.0f;
                }
            }
            c.confidence = c.visible
                ? std::clamp(c.peak_contrast / 0.15f, 0.0f, 1.0f)
                : 0.0f;

            out.lights.push_back(std::move(c));
        }
    }

    // Unbind state we touched. SSBO bindings 0..3 persist across
    // dispatches by default, which is harmless here (we rebind them at
    // the top of every analyze() call) but confuses anyone debugging
    // the GL state with apitrace or RenderDoc.
    glUseProgram(0);
    glBindTexture(GL_TEXTURE_2D, 0);
    for (GLuint i = 0; i < 4; ++i)
        glBindBufferBase(GL_SHADER_STORAGE_BUFFER, i, 0);

    return out;
}
