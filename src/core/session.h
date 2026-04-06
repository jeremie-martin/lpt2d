#pragma once

#include "renderer.h"

#include <cstdint>
#include <memory>
#include <vector>

struct Bounds;
struct PostProcess;
struct Scene;
struct Shot;
struct TraceConfig;

struct RenderResult {
    std::vector<uint8_t> pixels; // RGB8, width * height * 3 bytes
    int width = 0;
    int height = 0;
    int64_t total_rays = 0;
    float max_hdr = 0.0f;
    FrameMetrics metrics;
};

class RenderSession {
public:
    RenderSession(int width, int height, bool half_float = false);
    ~RenderSession();

    RenderSession(const RenderSession&) = delete;
    RenderSession& operator=(const RenderSession&) = delete;
    RenderSession(RenderSession&&) noexcept;
    RenderSession& operator=(RenderSession&&) noexcept;

    // Render a complete frame from a Shot.
    // Resolves camera bounds, converts Look → PostProcess, traces rays, post-processes.
    RenderResult render_shot(const Shot& shot);

    // Render with pre-resolved parameters (for animation loops).
    RenderResult render_frame(const Scene& scene, const Bounds& bounds,
                              const TraceConfig& trace_cfg, const PostProcess& pp,
                              int64_t total_rays);

    void resize(int width, int height);
    int width() const;
    int height() const;

private:
    struct Impl;
    std::unique_ptr<Impl> impl_;
};
