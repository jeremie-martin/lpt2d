#include "session.h"

#include "geometry.h"
#include "headless.h"
#include "renderer.h"
#include "scene.h"

#include <algorithm>
#include <stdexcept>

struct RenderSession::Impl {
    HeadlessGL gl;
    Renderer renderer;
    int width;
    int height;
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

RenderSession::~RenderSession() {
    if (impl_)
        impl_->renderer.shutdown();
}

RenderSession::RenderSession(RenderSession&&) noexcept = default;
RenderSession& RenderSession::operator=(RenderSession&&) noexcept = default;

RenderResult RenderSession::render_shot(const Shot& shot) {
    // Resize if canvas dimensions changed
    if (shot.canvas.width != impl_->width || shot.canvas.height != impl_->height)
        resize(shot.canvas.width, shot.canvas.height);

    // Resolve camera bounds
    Bounds scene_bounds = compute_bounds(shot.scene);
    Bounds bounds = shot.camera.resolve(shot.canvas.aspect(), scene_bounds);

    // Convert authored types to runtime types
    TraceConfig tcfg = shot.trace.to_trace_config();
    PostProcess pp = shot.look.to_post_process();
    int64_t total_rays = shot.trace.rays;

    return render_frame(shot.scene, bounds, tcfg, pp, total_rays);
}

RenderResult RenderSession::render_frame(const Scene& scene, const Bounds& bounds,
                                          const TraceConfig& trace_cfg, const PostProcess& pp,
                                          int64_t total_rays) {
    auto& r = impl_->renderer;

    r.upload_scene(scene, bounds);
    r.clear();

    // Trace rays in batched dispatches (skip if no lights)
    if (r.num_lights() > 0) {
        int64_t num_batches = (total_rays + trace_cfg.batch_size - 1) / trace_cfg.batch_size;
        constexpr int dispatches_per_draw = 4;
        int64_t b = 0;
        while (b < num_batches) {
            int n = (int)std::min((int64_t)dispatches_per_draw, num_batches - b);
            r.trace_and_draw_multi(trace_cfg, n);
            b += n;
        }
    }

    // Read pixels and compute metrics
    RenderResult result;
    r.read_pixels(result.pixels, pp, (float)impl_->width / (float)impl_->height);
    result.width = impl_->width;
    result.height = impl_->height;
    result.total_rays = r.total_rays();
    result.max_hdr = r.last_max();
    result.metrics = r.compute_frame_metrics();

    return result;
}

void RenderSession::resize(int width, int height) {
    impl_->renderer.resize(width, height);
    impl_->width = width;
    impl_->height = height;
}

int RenderSession::width() const { return impl_->width; }
int RenderSession::height() const { return impl_->height; }
