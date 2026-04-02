#include "headless.h"

#include <iostream>

HeadlessGL::~HeadlessGL() { shutdown(); }

bool HeadlessGL::init() {
    display_ = eglGetDisplay(EGL_DEFAULT_DISPLAY);
    if (display_ == EGL_NO_DISPLAY) {
        std::cerr << "EGL: failed to get display\n";
        return false;
    }

    EGLint major, minor;
    if (!eglInitialize(display_, &major, &minor)) {
        std::cerr << "EGL: failed to initialize\n";
        return false;
    }

    EGLint config_attribs[] = {EGL_SURFACE_TYPE,    EGL_PBUFFER_BIT, EGL_RENDERABLE_TYPE, EGL_OPENGL_BIT,
                               EGL_RED_SIZE,         8,                EGL_GREEN_SIZE,      8,
                               EGL_BLUE_SIZE,        8,                EGL_ALPHA_SIZE,      8,
                               EGL_DEPTH_SIZE,       0,                EGL_NONE};

    EGLConfig config;
    EGLint num_configs;
    if (!eglChooseConfig(display_, config_attribs, &config, 1, &num_configs) || num_configs == 0) {
        std::cerr << "EGL: failed to choose config\n";
        eglTerminate(display_);
        return false;
    }

    if (!eglBindAPI(EGL_OPENGL_API)) {
        std::cerr << "EGL: failed to bind OpenGL API\n";
        eglTerminate(display_);
        return false;
    }

    // Require GL 4.3+ (compute shaders)
    EGLint ctx_attribs[] = {EGL_CONTEXT_MAJOR_VERSION,
                            4,
                            EGL_CONTEXT_MINOR_VERSION,
                            3,
                            EGL_CONTEXT_OPENGL_PROFILE_MASK,
                            EGL_CONTEXT_OPENGL_CORE_PROFILE_BIT,
                            EGL_NONE};

    context_ = eglCreateContext(display_, config, EGL_NO_CONTEXT, ctx_attribs);
    if (context_ == EGL_NO_CONTEXT) {
        std::cerr << "EGL: failed to create GL 4.3 context\n";
        eglTerminate(display_);
        return false;
    }

    EGLint pbuf[] = {EGL_WIDTH, 1, EGL_HEIGHT, 1, EGL_NONE};
    surface_ = eglCreatePbufferSurface(display_, config, pbuf);
    if (surface_ == EGL_NO_SURFACE) {
        std::cerr << "EGL: failed to create pbuffer surface\n";
        eglDestroyContext(display_, context_);
        eglTerminate(display_);
        return false;
    }

    if (!make_current()) {
        std::cerr << "EGL: failed to make context current\n";
        shutdown();
        return false;
    }

    return true;
}

void HeadlessGL::shutdown() {
    if (display_ != EGL_NO_DISPLAY) {
        eglMakeCurrent(display_, EGL_NO_SURFACE, EGL_NO_SURFACE, EGL_NO_CONTEXT);
        if (surface_ != EGL_NO_SURFACE) {
            eglDestroySurface(display_, surface_);
            surface_ = EGL_NO_SURFACE;
        }
        if (context_ != EGL_NO_CONTEXT) {
            eglDestroyContext(display_, context_);
            context_ = EGL_NO_CONTEXT;
        }
        eglTerminate(display_);
        display_ = EGL_NO_DISPLAY;
    }
}

bool HeadlessGL::make_current() { return eglMakeCurrent(display_, surface_, surface_, context_) == EGL_TRUE; }
