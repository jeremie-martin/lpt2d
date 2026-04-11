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
    static_cast<std::size_t>(GpuImageAnalyzer::kNumSectors) *
    static_cast<std::size_t>(GpuImageAnalyzer::kLightBinStride) * sizeof(uint32_t);

inline std::size_t lights_bytes_for(int n_lights) {
    return static_cast<std::size_t>(std::max(n_lights, 1)) * 2u * sizeof(float);
}
inline std::size_t circles_bytes_for(int n_lights) {
    return static_cast<std::size_t>(std::max(n_lights, 1)) *
           static_cast<std::size_t>(GpuImageAnalyzer::kMaxBins) *
           static_cast<std::size_t>(GpuImageAnalyzer::kNumSectors) *
           static_cast<std::size_t>(GpuImageAnalyzer::kLightBinStride) * sizeof(uint32_t);
}

float clamp01(float v) {
    return std::clamp(v, 0.0f, 1.0f);
}

float quantile_sorted(std::vector<float>& values, float q) {
    if (values.empty()) return 0.0f;
    std::sort(values.begin(), values.end());
    const float clamped = clamp01(q);
    const auto idx = static_cast<std::size_t>(
        std::round(clamped * static_cast<float>(values.size() - 1u)));
    return values[idx];
}

float bin_radius_px(int bin, int max_bins, float search_radius_px) {
    if (max_bins <= 0) return 0.0f;
    return (static_cast<float>(bin) + 0.5f) * search_radius_px /
           static_cast<float>(max_bins);
}

std::vector<float> smooth_profile(const std::vector<float>& profile) {
    std::vector<float> smooth(profile.size(), 0.0f);
    const int n = static_cast<int>(profile.size());
    for (int r = 0; r < n; ++r) {
        double sum = 0.0;
        double weight = 0.0;
        for (int o = -2; o <= 2; ++o) {
            const int rr = r + o;
            if (rr < 0 || rr >= n) continue;
            const double w = (o == 0) ? 3.0 : (std::abs(o) == 1 ? 2.0 : 1.0);
            sum += static_cast<double>(profile[static_cast<std::size_t>(rr)]) * w;
            weight += w;
        }
        smooth[static_cast<std::size_t>(r)] =
            weight > 0.0 ? static_cast<float>(sum / weight) : 0.0f;
    }
    return smooth;
}

void enforce_nonincreasing_after_peak(std::vector<float>& profile, int peak_bin) {
    const int n = static_cast<int>(profile.size());
    for (int r = peak_bin + 1; r < n; ++r) {
        const auto prev = profile[static_cast<std::size_t>(r - 1)];
        auto& cur = profile[static_cast<std::size_t>(r)];
        if (cur > prev) cur = prev;
    }
}

int first_below(const std::vector<float>& profile, int start_bin, float threshold) {
    const int n = static_cast<int>(profile.size());
    for (int r = std::max(0, start_bin); r < n; ++r) {
        if (profile[static_cast<std::size_t>(r)] <= threshold) return r;
    }
    return std::max(0, n - 1);
}

int strongest_edge_bin(const std::vector<float>& envelope,
                       int peak_bin,
                       int min_edge_bin,
                       float peak_excess,
                       float* out_best_drop) {
    const int n = static_cast<int>(envelope.size());
    int edge_bin = -1;
    float best_drop = 0.0f;
    for (int r = min_edge_bin; r < n - 2; ++r) {
        const int lo = std::max(peak_bin, r - 2);
        const int hi = std::min(n - 1, r + 2);
        const float drop = envelope[static_cast<std::size_t>(lo)] -
                           envelope[static_cast<std::size_t>(hi)];
        if (drop > best_drop &&
            envelope[static_cast<std::size_t>(r)] > peak_excess * 0.05f) {
            best_drop = drop;
            edge_bin = r;
        }
    }
    if (out_best_drop != nullptr) *out_best_drop = best_drop;
    return edge_bin;
}

int knee_bin(const std::vector<float>& envelope,
             int peak_bin,
             int min_edge_bin,
             float peak_excess) {
    if (peak_excess <= 0.0f) return min_edge_bin;
    const int n = static_cast<int>(envelope.size());
    int end_bin = first_below(envelope, min_edge_bin, peak_excess * 0.05f);
    end_bin = std::min(n - 1, std::max(end_bin, min_edge_bin + 2));
    if (end_bin <= peak_bin + 1) return min_edge_bin;

    const float y0 = clamp01(envelope[static_cast<std::size_t>(peak_bin)] / peak_excess);
    const float y1 = clamp01(envelope[static_cast<std::size_t>(end_bin)] / peak_excess);
    int best_bin = min_edge_bin;
    float best_distance = -1.0f;
    for (int r = min_edge_bin; r <= end_bin; ++r) {
        const float t = static_cast<float>(r - peak_bin) /
                        static_cast<float>(std::max(1, end_bin - peak_bin));
        const float y = clamp01(envelope[static_cast<std::size_t>(r)] / peak_excess);
        const float line_y = y0 + (y1 - y0) * t;
        const float distance = y - line_y;
        if (distance > best_distance) {
            best_distance = distance;
            best_bin = r;
        }
    }
    return best_distance > 0.015f ? best_bin : first_below(envelope, peak_bin, peak_excess * 0.50f);
}

void shape_normalized_profile(const std::vector<float>& src,
                              float peak_excess,
                              float exponent,
                              std::vector<float>& dst) {
    dst.resize(src.size());
    const float inv_peak = 1.0f / std::max(peak_excess, 1.0e-6f);
    for (std::size_t i = 0; i < src.size(); ++i) {
        const float normalized = clamp01(src[i] * inv_peak);
        dst[i] = std::pow(normalized, exponent);
    }
}

float trimmed_quantile(std::vector<float> values, float q) {
    if (values.empty()) return 0.0f;
    if (values.size() < 6u) {
        return quantile_sorted(values, q);
    }

    std::vector<float> sorted = values;
    const float q25 = quantile_sorted(sorted, 0.25f);
    sorted = values;
    const float q75 = quantile_sorted(sorted, 0.75f);
    const float iqr = q75 - q25;
    if (iqr <= 1.0e-6f) {
        return quantile_sorted(values, q);
    }

    const float lo = q25 - 1.5f * iqr;
    const float hi = q75 + 1.5f * iqr;
    std::vector<float> trimmed;
    trimmed.reserve(values.size());
    for (float v : values) {
        if (v >= lo && v <= hi) trimmed.push_back(v);
    }
    if (trimmed.size() >= std::max<std::size_t>(4u, values.size() / 2u)) {
        return quantile_sorted(trimmed, q);
    }
    return quantile_sorted(values, q);
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
    u_search_radius_px_ = glGetUniformLocation(program_, "uSearchRadiusPx");
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
    const int max_bins = std::min(std::max(search_radius + 1, 8), kMaxBins);
    const float search_radius_px = static_cast<float>(search_radius);

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
    if (u_bright_ >= 0)     glUniform1f(u_bright_, params.lights.saturated_core_threshold);
    if (u_max_bins_ >= 0)   glUniform1i(u_max_bins_, max_bins);
    if (u_search_radius_px_ >= 0) glUniform1f(u_search_radius_px_, search_radius_px);
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
    // Lum + colour are always < 1.5 KB. The light-bin buffer is compact
    // compared with full-frame RGB readback and is skipped entirely when
    // the caller opted out of point-light analysis.

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
                                    static_cast<std::size_t>(kMaxBins) *
                                    static_cast<std::size_t>(kNumSectors) *
                                    static_cast<std::size_t>(kLightBinStride));
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

    // ── Light appearance finalize (per-light) ──────────────────────────
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

            // Flat interleaved layout per (bin, sector):
            // [sumR, sumG, sumB, count, brightCount].
            const uint32_t* base =
                circles_raw_scratch_.data() +
                static_cast<std::size_t>(i) * kMaxBins *
                static_cast<std::size_t>(kNumSectors) *
                static_cast<std::size_t>(kLightBinStride);

            const auto bin_index = [](int r, int sector) -> std::size_t {
                return (static_cast<std::size_t>(r) *
                        static_cast<std::size_t>(GpuImageAnalyzer::kNumSectors) +
                        static_cast<std::size_t>(sector)) *
                       static_cast<std::size_t>(GpuImageAnalyzer::kLightBinStride);
            };

            std::vector<float> mean_r(static_cast<std::size_t>(max_bins) * kNumSectors, 0.0f);
            std::vector<float> mean_g(mean_r.size(), 0.0f);
            std::vector<float> mean_b(mean_r.size(), 0.0f);
            std::vector<uint32_t> counts(mean_r.size(), 0u);
            uint32_t total_bright = 0;
            for (int r = 0; r < max_bins; ++r) {
                for (int s = 0; s < kNumSectors; ++s) {
                    const std::size_t raw = bin_index(r, s);
                    const uint32_t sr = base[raw + 0];
                    const uint32_t sg = base[raw + 1];
                    const uint32_t sb = base[raw + 2];
                    const uint32_t pcnt = base[raw + 3];
                    const uint32_t pbr = base[raw + 4];
                    const std::size_t idx = static_cast<std::size_t>(r) *
                                            static_cast<std::size_t>(kNumSectors) +
                                            static_cast<std::size_t>(s);
                    counts[idx] = pcnt;
                    total_bright += pbr;
                    if (pcnt > 0) {
                        const float inv = 1.0f / static_cast<float>(pcnt);
                        mean_r[idx] = static_cast<float>(sr) * inv;
                        mean_g[idx] = static_cast<float>(sg) * inv;
                        mean_b[idx] = static_cast<float>(sb) * inv;
                    }
                }
            }

            const int bright_pixels = static_cast<int>(total_bright);

            float saturated_core_radius_px = 0.0f;
            if (bright_pixels >= params.lights.min_saturated_core_pixels &&
                total_bright > 0) {
                const float pct = std::clamp(
                    params.lights.saturated_core_percentile / 100.0f, 0.0f, 1.0f);
                const uint32_t target = static_cast<uint32_t>(
                    std::floor(static_cast<float>(total_bright) * pct));
                bool radius_set = false;
                uint32_t cumul = 0;
                for (int r = 0; r < max_bins; ++r) {
                    for (int s = 0; s < kNumSectors; ++s) {
                        cumul += base[bin_index(r, s) + 4];
                    }
                    if (cumul > target) {
                        saturated_core_radius_px = bin_radius_px(r, max_bins, search_radius_px);
                        radius_set = true;
                        break;
                    }
                }
                if (!radius_set) {
                    for (int r = max_bins - 1; r >= 0; --r) {
                        uint32_t bin_bright = 0;
                        for (int s = 0; s < kNumSectors; ++s) {
                            bin_bright += base[bin_index(r, s) + 4];
                        }
                        if (bin_bright > 0) {
                            saturated_core_radius_px = bin_radius_px(r, max_bins, search_radius_px);
                            break;
                        }
                    }
                }
            }
            c.saturated_radius_ratio = saturated_core_radius_px / short_side;

            const int outer_start = std::max(0, static_cast<int>(std::floor(max_bins * 0.85f)));
            double bg_r_sum = 0.0;
            double bg_g_sum = 0.0;
            double bg_b_sum = 0.0;
            double bg_count = 0.0;
            for (int r = outer_start; r < max_bins; ++r) {
                for (int s = 0; s < kNumSectors; ++s) {
                    const std::size_t idx = static_cast<std::size_t>(r) *
                                            static_cast<std::size_t>(kNumSectors) +
                                            static_cast<std::size_t>(s);
                    const double count = static_cast<double>(counts[idx]);
                    if (count <= 0.0) continue;
                    bg_r_sum += static_cast<double>(mean_r[idx]) * count;
                    bg_g_sum += static_cast<double>(mean_g[idx]) * count;
                    bg_b_sum += static_cast<double>(mean_b[idx]) * count;
                    bg_count += count;
                }
            }
            const float bg_r = bg_count > 0.0 ? static_cast<float>(bg_r_sum / bg_count) : 0.0f;
            const float bg_g = bg_count > 0.0 ? static_cast<float>(bg_g_sum / bg_count) : 0.0f;
            const float bg_b = bg_count > 0.0 ? static_cast<float>(bg_b_sum / bg_count) : 0.0f;
            c.background_luminance =
                clamp01((0.2126f * bg_r + 0.7152f * bg_g + 0.0722f * bg_b) / 255.0f);

            const int inner_end = std::max(
                1, std::min(max_bins - 1,
                            static_cast<int>(std::ceil(std::max(4.0f, 0.04f * search_radius_px) *
                                                        static_cast<float>(max_bins) /
                                                        search_radius_px))));
            double inner_r_sum = 0.0;
            double inner_g_sum = 0.0;
            double inner_b_sum = 0.0;
            double inner_count = 0.0;
            for (int r = 0; r <= inner_end; ++r) {
                for (int s = 0; s < kNumSectors; ++s) {
                    const std::size_t idx = static_cast<std::size_t>(r) *
                                            static_cast<std::size_t>(kNumSectors) +
                                            static_cast<std::size_t>(s);
                    const double count = static_cast<double>(counts[idx]);
                    if (count <= 0.0) continue;
                    inner_r_sum += static_cast<double>(mean_r[idx]) * count;
                    inner_g_sum += static_cast<double>(mean_g[idx]) * count;
                    inner_b_sum += static_cast<double>(mean_b[idx]) * count;
                    inner_count += count;
                }
            }

            float dir_r = inner_count > 0.0 ? static_cast<float>(inner_r_sum / inner_count) - bg_r : 1.0f;
            float dir_g = inner_count > 0.0 ? static_cast<float>(inner_g_sum / inner_count) - bg_g : 1.0f;
            float dir_b = inner_count > 0.0 ? static_cast<float>(inner_b_sum / inner_count) - bg_b : 1.0f;
            dir_r = std::max(0.0f, dir_r);
            dir_g = std::max(0.0f, dir_g);
            dir_b = std::max(0.0f, dir_b);
            const float dir_sum = dir_r + dir_g + dir_b;
            if (dir_sum <= 1.0e-3f) {
                dir_r = 1.0f;
                dir_g = 1.0f;
                dir_b = 1.0f;
            }
            const float signal_norm = 255.0f * std::max(1.0e-6f, dir_r + dir_g + dir_b);
            const float bg_signal = (bg_r * dir_r + bg_g * dir_g + bg_b * dir_b) / signal_norm;

            std::vector<float> profile(static_cast<std::size_t>(max_bins), 0.0f);
            std::vector<float> profile_low(static_cast<std::size_t>(max_bins), 0.0f);
            std::vector<float> profile_high(static_cast<std::size_t>(max_bins), 0.0f);
            std::vector<float> luminance_profile(static_cast<std::size_t>(max_bins), 0.0f);
            std::vector<float> sector_values;
            std::vector<float> luminance_values;
            sector_values.reserve(kNumSectors);
            luminance_values.reserve(kNumSectors);
            for (int r = 0; r < max_bins; ++r) {
                sector_values.clear();
                luminance_values.clear();
                for (int s = 0; s < kNumSectors; ++s) {
                    const std::size_t idx = static_cast<std::size_t>(r) *
                                            static_cast<std::size_t>(kNumSectors) +
                                            static_cast<std::size_t>(s);
                    if (counts[idx] == 0u) continue;
                    const float signal =
                        (mean_r[idx] * dir_r + mean_g[idx] * dir_g + mean_b[idx] * dir_b) /
                        signal_norm;
                    sector_values.push_back(std::max(0.0f, signal - bg_signal));
                    luminance_values.push_back(
                        clamp01((0.2126f * mean_r[idx] +
                                 0.7152f * mean_g[idx] +
                                 0.0722f * mean_b[idx]) / 255.0f));
                }
                if (!sector_values.empty()) {
                    std::vector<float> tmp = sector_values;
                    profile[static_cast<std::size_t>(r)] = quantile_sorted(tmp, 0.50f);
                    tmp = sector_values;
                    profile_low[static_cast<std::size_t>(r)] = quantile_sorted(tmp, 0.25f);
                    tmp = sector_values;
                    profile_high[static_cast<std::size_t>(r)] = quantile_sorted(tmp, 0.75f);
                }
                if (!luminance_values.empty()) {
                    std::vector<float> tmp = luminance_values;
                    luminance_profile[static_cast<std::size_t>(r)] =
                        quantile_sorted(tmp, 0.50f);
                }
            }

            std::vector<float> smooth = smooth_profile(profile);
            std::vector<float> luminance_smooth = smooth_profile(luminance_profile);

            const int peak_search_end = std::max(
                inner_end, std::min(max_bins - 1, static_cast<int>(std::ceil(0.12f * max_bins))));
            int peak_bin = 0;
            float signal_peak_excess = 0.0f;
            float peak_luminance = c.background_luminance;
            for (int r = 0; r <= peak_search_end; ++r) {
                if (smooth[static_cast<std::size_t>(r)] > signal_peak_excess) {
                    signal_peak_excess = smooth[static_cast<std::size_t>(r)];
                    peak_bin = r;
                }
                peak_luminance =
                    std::max(peak_luminance, luminance_smooth[static_cast<std::size_t>(r)]);
            }

            c.peak_luminance = clamp01(peak_luminance);
            c.peak_contrast = std::max(0.0f, c.peak_luminance - c.background_luminance);
            if (signal_peak_excess <= 0.015f) {
                out.lights.push_back(std::move(c));
                continue;
            }

            std::vector<float> envelope = smooth;
            enforce_nonincreasing_after_peak(envelope, peak_bin);

            const int min_edge_bin = std::min(
                max_bins - 2,
                std::max(peak_bin + 1,
                         static_cast<int>(std::ceil(2.0f * static_cast<float>(max_bins) /
                                                     search_radius_px))));
            float best_drop = 0.0f;
            const int edge_bin = strongest_edge_bin(envelope, peak_bin, min_edge_bin,
                                                    signal_peak_excess, &best_drop);

            const int r80 = first_below(envelope, peak_bin, 0.80f * signal_peak_excess);
            const int r50 = first_below(envelope, peak_bin, 0.50f * signal_peak_excess);
            const int r20 = first_below(envelope, peak_bin, 0.20f * signal_peak_excess);

            const bool has_edge = edge_bin >= 0 && best_drop >= signal_peak_excess * 0.035f;
            const int radius_bin = has_edge ? edge_bin : r50;
            const float radius_px = bin_radius_px(radius_bin, max_bins, search_radius_px);

            const int knee_candidate_bin =
                knee_bin(envelope, peak_bin, min_edge_bin, signal_peak_excess);
            const float knee_px = bin_radius_px(knee_candidate_bin, max_bins, search_radius_px);

            std::vector<float> sector_envelopes(
                static_cast<std::size_t>(kNumSectors) * static_cast<std::size_t>(max_bins),
                0.0f);
            std::vector<float> sector_peaks(static_cast<std::size_t>(kNumSectors), 0.0f);
            std::vector<int> sector_peak_bins(static_cast<std::size_t>(kNumSectors), 0);
            std::vector<float> sector_edge_px;
            sector_edge_px.reserve(kNumSectors);
            int valid_sectors = 0;
            std::vector<float> sector_profile(static_cast<std::size_t>(max_bins), 0.0f);
            std::vector<float> sector_shaped(static_cast<std::size_t>(max_bins), 0.0f);
            for (int s = 0; s < kNumSectors; ++s) {
                std::fill(sector_profile.begin(), sector_profile.end(), 0.0f);
                for (int r = 0; r < max_bins; ++r) {
                    const std::size_t idx = static_cast<std::size_t>(r) *
                                            static_cast<std::size_t>(kNumSectors) +
                                            static_cast<std::size_t>(s);
                    if (counts[idx] == 0u) continue;
                    const float signal =
                        (mean_r[idx] * dir_r + mean_g[idx] * dir_g + mean_b[idx] * dir_b) /
                        signal_norm;
                    sector_profile[static_cast<std::size_t>(r)] =
                        std::max(0.0f, signal - bg_signal);
                }
                std::vector<float> sector_smooth = smooth_profile(sector_profile);
                int sector_peak_bin = 0;
                float sector_peak_excess = 0.0f;
                for (int r = 0; r <= peak_search_end; ++r) {
                    if (sector_smooth[static_cast<std::size_t>(r)] > sector_peak_excess) {
                        sector_peak_excess = sector_smooth[static_cast<std::size_t>(r)];
                        sector_peak_bin = r;
                    }
                }
                if (sector_peak_excess < std::max(0.015f, signal_peak_excess * 0.18f)) {
                    continue;
                }
                enforce_nonincreasing_after_peak(sector_smooth, sector_peak_bin);

                const int sector_min_edge_bin = std::min(
                    max_bins - 2,
                    std::max(sector_peak_bin + 1,
                             static_cast<int>(std::ceil(2.0f * static_cast<float>(max_bins) /
                                                         search_radius_px))));
                shape_normalized_profile(sector_smooth, sector_peak_excess, 1.75f,
                                         sector_shaped);
                float shaped_drop = 0.0f;
                const int shaped_edge_bin = strongest_edge_bin(
                    sector_shaped, sector_peak_bin, sector_min_edge_bin, 1.0f,
                    &shaped_drop);
                const int shaped_knee_bin =
                    knee_bin(sector_shaped, sector_peak_bin, sector_min_edge_bin, 1.0f);
                const int sector_candidate_bin =
                    (shaped_edge_bin >= 0 && shaped_drop >= 0.025f)
                        ? shaped_edge_bin
                        : shaped_knee_bin;
                const int shaped_tail_bin =
                    first_below(sector_shaped, sector_min_edge_bin, 0.08f);
                const bool shaped_has_falloff =
                    shaped_tail_bin > sector_min_edge_bin && shaped_tail_bin < max_bins - 1;
                if (sector_candidate_bin >= sector_min_edge_bin &&
                    (shaped_has_falloff ||
                     (shaped_edge_bin >= 0 && shaped_drop >= 0.025f))) {
                    sector_edge_px.push_back(
                        bin_radius_px(sector_candidate_bin, max_bins, search_radius_px));
                }

                sector_peaks[static_cast<std::size_t>(s)] = sector_peak_excess;
                sector_peak_bins[static_cast<std::size_t>(s)] = sector_peak_bin;
                ++valid_sectors;
                for (int r = 0; r < max_bins; ++r) {
                    sector_envelopes[static_cast<std::size_t>(s) *
                                         static_cast<std::size_t>(max_bins) +
                                     static_cast<std::size_t>(r)] =
                        sector_smooth[static_cast<std::size_t>(r)];
                }
            }
            float sector_consensus_px = radius_px;
            float robust_sector_edge_px = knee_px;
            const int min_valid_sectors = std::max(6, kNumSectors / 4);
            if (valid_sectors >= min_valid_sectors) {
                std::vector<float> sector_drops;
                sector_drops.reserve(kNumSectors);
                int sector_consensus_bin = -1;
                float best_sector_score = 0.0f;
                for (int r = min_edge_bin; r < max_bins - 2; ++r) {
                    sector_drops.clear();
                    for (int s = 0; s < kNumSectors; ++s) {
                        const float sector_peak = sector_peaks[static_cast<std::size_t>(s)];
                        if (sector_peak <= 0.0f) continue;
                        const int sector_peak_bin = sector_peak_bins[static_cast<std::size_t>(s)];
                        const int lo = std::max(sector_peak_bin, r - 2);
                        const int hi = std::min(max_bins - 1, r + 2);
                        const auto base_idx =
                            static_cast<std::size_t>(s) * static_cast<std::size_t>(max_bins);
                        const float mid = sector_envelopes[base_idx + static_cast<std::size_t>(r)];
                        const float drop =
                            sector_envelopes[base_idx + static_cast<std::size_t>(lo)] -
                            sector_envelopes[base_idx + static_cast<std::size_t>(hi)];
                        if (drop > 0.0f && mid > sector_peak * 0.05f) {
                            sector_drops.push_back(drop);
                        }
                    }
                    if (sector_drops.size() <
                        static_cast<std::size_t>(std::max(4, valid_sectors / 3))) {
                        continue;
                    }
                    const float score = quantile_sorted(sector_drops, 0.50f);
                    if (score > best_sector_score) {
                        best_sector_score = score;
                        sector_consensus_bin = r;
                    }
                }
                if (sector_consensus_bin >= 0 &&
                    best_sector_score >= signal_peak_excess * 0.02f) {
                    sector_consensus_px =
                        bin_radius_px(sector_consensus_bin, max_bins, search_radius_px);
                }
            }
            if (sector_edge_px.size() >=
                static_cast<std::size_t>(std::max(6, valid_sectors / 3))) {
                robust_sector_edge_px = trimmed_quantile(sector_edge_px, 0.50f);
            }

            c.visible = radius_px > 0.0f;
            c.radius_ratio = radius_px / short_side;
            c.radius_candidate_sector_consensus_ratio = sector_consensus_px / short_side;
            c.radius_candidate_knee_ratio = knee_px / short_side;
            c.radius_candidate_robust_sector_edge_ratio = robust_sector_edge_px / short_side;
            c.coverage_fraction = clamp01((PI * radius_px * radius_px) /
                                          static_cast<float>(width * height));
            c.transition_width_ratio =
                std::max(0.0f, bin_radius_px(r20, max_bins, search_radius_px) -
                                   bin_radius_px(r80, max_bins, search_radius_px)) /
                short_side;
            c.touches_frame_edge =
                c.image_x - radius_px <= 0.0f || c.image_x + radius_px >= static_cast<float>(width - 1) ||
                c.image_y - radius_px <= 0.0f || c.image_y + radius_px >= static_cast<float>(height - 1) ||
                radius_bin >= max_bins - 2;

            const float contrast_score = clamp01((signal_peak_excess - 0.015f) / 0.18f);
            const float edge_score = has_edge
                ? clamp01(best_drop / std::max(signal_peak_excess * 0.08f, 1.0e-4f))
                : 0.55f;
            const float spread =
                profile_high[static_cast<std::size_t>(radius_bin)] -
                profile_low[static_cast<std::size_t>(radius_bin)];
            const float sector_score =
                clamp01(1.0f - spread / std::max(signal_peak_excess, 1.0e-4f));
            const float truncation_score = c.touches_frame_edge ? 0.5f : 1.0f;
            c.confidence = contrast_score * edge_score *
                           std::max(0.25f, sector_score) * truncation_score;

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
