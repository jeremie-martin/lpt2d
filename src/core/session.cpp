#include "session.h"

#include "geometry.h"
#include "headless.h"
#include "renderer.h"
#include "scene.h"

#include <algorithm>
#include <chrono>
#include <cstdint>
#include <stdexcept>

namespace {

constexpr int64_t kTraceLineSegBytes = 32;
constexpr int64_t kTraceOutputBudgetBytes = 512ll * 1024ll * 1024ll;

int budgeted_batch_size(const TraceConfig& cfg) {
    const int64_t requested = std::max<int64_t>(1, cfg.batch_size);
    const int64_t depth = std::max<int64_t>(1, cfg.depth);
    const int64_t max_batch =
        std::max<int64_t>(1, kTraceOutputBudgetBytes / (depth * kTraceLineSegBytes));
    return static_cast<int>(std::min(requested, max_batch));
}

int budgeted_dispatches_per_draw(const TraceConfig& cfg) {
    constexpr int kMaxDispatchesPerDraw = 16;
    const int64_t batch = std::max<int64_t>(1, cfg.batch_size);
    const int64_t depth = std::max<int64_t>(1, cfg.depth);
    const int64_t bytes_per_dispatch = batch * depth * kTraceLineSegBytes;
    const int64_t max_dispatches =
        std::max<int64_t>(1, kTraceOutputBudgetBytes / std::max<int64_t>(1, bytes_per_dispatch));
    return static_cast<int>(std::min<int64_t>(kMaxDispatchesPerDraw, max_dispatches));
}

}  // namespace

struct RenderSession::Impl {
    HeadlessGL gl;
    Renderer renderer;
    int width;
    int height;
    bool has_current_frame = false;
};

RenderSession::RenderSession(int width, int height, bool half_float) : impl_(std::make_unique<Impl>()) {
    if (width < 1 || height < 1)
        throw std::runtime_error("RenderSession: width and height must be >= 1");

    impl_->width = width;
    impl_->height = height;

    if (!impl_->gl.init())
        throw std::runtime_error("RenderSession: failed to initialize EGL context");

    if (!impl_->renderer.init(width, height, half_float))
        throw std::runtime_error("RenderSession: failed to initialize renderer");
}

RenderSession::~RenderSession() { close(); }

RenderSession::RenderSession(RenderSession&&) noexcept = default;
RenderSession& RenderSession::operator=(RenderSession&&) noexcept = default;

RenderResult RenderSession::render_shot(const Shot& shot, int frame, bool analyze) {
    if (!impl_)
        throw std::runtime_error("RenderSession: session is closed");

    // Resize if canvas dimensions changed
    if (shot.canvas.width != impl_->width || shot.canvas.height != impl_->height)
        resize(shot.canvas.width, shot.canvas.height);

    // Resolve camera bounds
    Bounds scene_bounds = compute_bounds(shot.scene);
    Bounds bounds = shot.camera.resolve(shot.canvas.aspect(), scene_bounds);

    // Convert authored types to runtime types
    TraceConfig tcfg = shot.trace.to_trace_config(frame);
    PostProcess pp = shot.look.to_post_process();
    int64_t total_rays = shot.trace.rays;

    return render_frame(shot.scene, bounds, tcfg, pp, total_rays, analyze);
}

RenderResult RenderSession::render_frame(const Scene& scene, const Bounds& bounds,
                                          const TraceConfig& trace_cfg, const PostProcess& pp,
                                          int64_t total_rays, bool analyze) {
    if (!impl_)
        throw std::runtime_error("RenderSession: session is closed");

    auto t0 = std::chrono::steady_clock::now();
    auto& r = impl_->renderer;

    r.upload_scene(scene, bounds);
    r.upload_fills(scene, bounds);
    r.clear();

    // Trace rays in batched dispatches (skip if no lights)
    if (r.num_lights() > 0 && total_rays > 0) {
        TraceConfig batch_cfg = trace_cfg;
        batch_cfg.batch_size = budgeted_batch_size(trace_cfg);
        const int dispatches_per_draw = budgeted_dispatches_per_draw(batch_cfg);
        int64_t remaining = total_rays;
        while (remaining > 0) {
            int64_t full_batches = remaining / batch_cfg.batch_size;
            if (full_batches > 0) {
                int n = (int)std::min((int64_t)dispatches_per_draw, full_batches);
                r.trace_and_draw_multi(batch_cfg, n);
                remaining -= (int64_t)n * batch_cfg.batch_size;
                continue;
            }

            TraceConfig tail = batch_cfg;
            tail.batch_size = (int)remaining;
            r.trace_and_draw(tail);
            remaining = 0;
        }
    }

    RenderResult result = develop_result(pp, analyze, t0);
    impl_->has_current_frame = true;
    return result;
}

RenderResult RenderSession::postprocess(const PostProcess& pp, bool analyze) {
    if (!impl_)
        throw std::runtime_error("RenderSession: session is closed");
    if (!impl_->has_current_frame)
        throw std::runtime_error("RenderSession: no frame has been rendered for postprocess replay");

    auto t0 = std::chrono::steady_clock::now();
    return develop_result(pp, analyze, t0);
}

RenderResult RenderSession::develop_result(const PostProcess& pp, bool analyze,
                                           std::chrono::steady_clock::time_point t0) {
    auto& r = impl_->renderer;

    // Read pixels for the render result. The analyzer runs on the GPU display
    // texture first; analyze=false requests luminance only.
    RenderResult result;
    if (analyze) {
        r.read_pixels(result.pixels, pp, (float)impl_->width / (float)impl_->height, nullptr,
                      &result.metrics, &result.analysis);
    } else {
        r.read_pixels(result.pixels, pp, (float)impl_->width / (float)impl_->height, nullptr,
                      &result.metrics, nullptr);
    }
    result.width = impl_->width;
    result.height = impl_->height;
    result.total_rays = r.total_rays();
    result.max_hdr = r.last_max();

    auto t1 = std::chrono::steady_clock::now();
    result.time_ms = std::chrono::duration<double, std::milli>(t1 - t0).count();

    return result;
}

void RenderSession::close() {
    if (!impl_)
        return;

    impl_->renderer.shutdown();
    impl_.reset();
}

void RenderSession::resize(int width, int height) {
    if (!impl_)
        throw std::runtime_error("RenderSession: session is closed");

    const bool dimensions_changed = (width != impl_->width || height != impl_->height);
    if (dimensions_changed)
        impl_->has_current_frame = false;
    impl_->renderer.resize(width, height);
    impl_->width = width;
    impl_->height = height;
}

int RenderSession::width() const {
    if (!impl_)
        throw std::runtime_error("RenderSession: session is closed");
    return impl_->width;
}

int RenderSession::height() const {
    if (!impl_)
        throw std::runtime_error("RenderSession: session is closed");
    return impl_->height;
}
