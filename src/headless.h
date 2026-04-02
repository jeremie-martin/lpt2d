#pragma once

#include <EGL/egl.h>

class HeadlessGL {
public:
    ~HeadlessGL();

    bool init();
    void shutdown();
    bool make_current();

private:
    EGLDisplay display_ = EGL_NO_DISPLAY;
    EGLContext context_ = EGL_NO_CONTEXT;
    EGLSurface surface_ = EGL_NO_SURFACE;
};
