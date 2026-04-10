#pragma once
//
// Thin GL shader compile/link helpers. Shared between `renderer.cpp`
// (which builds the trace/line/fill/postprocess programs) and
// `gpu_image_analysis.cpp` (which builds the single `analysis.comp`
// compute program). Before this header the two files kept byte-identical
// copies of the same three functions, except one copy leaked the shader
// object on link failure.

#include <GL/glew.h>

// Compile a GLSL source string into a shader object. Prints a labelled
// error on failure and returns 0. `label` is injected into the error
// message so callers can tell `trace.comp compile error` apart from
// `analysis.comp compile error`.
GLuint compile_gl_shader(GLenum type, const char* src, const char* label);

// Link a vertex + fragment pair into a program object. Deletes both
// shader objects on success AND on failure so nothing leaks. Returns
// 0 on link failure.
GLuint link_gl_program(GLuint vs, GLuint fs, const char* label);

// Link a single compute shader into a program. Same ownership rules
// as `link_gl_program` — deletes the shader object on both paths.
GLuint link_gl_compute(GLuint cs, const char* label);
