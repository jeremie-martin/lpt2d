cmake_minimum_required(VERSION 3.20)
project(lpt2d VERSION 0.1.0 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 23)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)

if(NOT CMAKE_BUILD_TYPE)
    set(CMAKE_BUILD_TYPE Release)
endif()

set(CMAKE_CXX_FLAGS_RELEASE "-O3 -march=native -DNDEBUG")
set(CMAKE_CXX_FLAGS_DEBUG "-g -O0 -DDEBUG")

# ── Shader embedding ──────────────────────────────────────────────
include(cmake/embed_shaders.cmake)

set(SHADER_DIR ${CMAKE_SOURCE_DIR}/src/shaders)
set(SHADER_FILES
    ${SHADER_DIR}/trace.comp
    ${SHADER_DIR}/line.vert
    ${SHADER_DIR}/line.frag
    ${SHADER_DIR}/postprocess.vert
    ${SHADER_DIR}/postprocess.frag
    ${SHADER_DIR}/max_reduce.comp
)
set(GENERATED_SHADER_HEADER ${CMAKE_BINARY_DIR}/generated/shaders.h)

embed_shaders(
    OUTPUT ${GENERATED_SHADER_HEADER}
    SOURCES ${SHADER_FILES}
)

# ── Dependencies ──────────────────────────────────────────────────
find_package(OpenGL REQUIRED)
find_package(GLEW REQUIRED)

# ── Core library ──────────────────────────────────────────────────
add_library(lpt2d-core STATIC
    src/core/scene.cpp
    src/core/renderer.cpp
    src/core/spectrum.cpp
    src/core/export.cpp
    src/core/serialize.cpp
)

target_include_directories(lpt2d-core PUBLIC
    ${CMAKE_SOURCE_DIR}/src/core
    ${CMAKE_BINARY_DIR}/generated
)
target_include_directories(lpt2d-core PRIVATE
    ${CMAKE_SOURCE_DIR}/external/stb
)
target_link_libraries(lpt2d-core PUBLIC
    OpenGL::GL
    GLEW::GLEW
)
target_compile_options(lpt2d-core PRIVATE -Wall -Wextra -Wpedantic)

add_dependencies(lpt2d-core generate_shaders)

# ── Interactive GUI executable ────────────────────────────────────
find_package(glfw3 REQUIRED)

set(IMGUI_DIR ${CMAKE_SOURCE_DIR}/external/imgui)
set(IMGUI_SOURCES
    ${IMGUI_DIR}/imgui.cpp
    ${IMGUI_DIR}/imgui_draw.cpp
    ${IMGUI_DIR}/imgui_tables.cpp
    ${IMGUI_DIR}/imgui_widgets.cpp
    ${IMGUI_DIR}/backends/imgui_impl_glfw.cpp
    ${IMGUI_DIR}/backends/imgui_impl_opengl3.cpp
)

add_executable(lpt2d
    src/app/main.cpp
    src/app/app.cpp
    src/app/editor.cpp
    src/app/ui.cpp
    ${IMGUI_SOURCES}
)

target_include_directories(lpt2d PRIVATE
    ${CMAKE_SOURCE_DIR}/src/app
    ${IMGUI_DIR}
    ${IMGUI_DIR}/backends
)
target_link_libraries(lpt2d PRIVATE
    lpt2d-core
    glfw
)
target_compile_definitions(lpt2d PRIVATE
    LPT2D_FONT_PATH="${CMAKE_SOURCE_DIR}/external/imgui/misc/fonts/Roboto-Medium.ttf"
)
target_compile_options(lpt2d PRIVATE -Wall -Wextra -Wpedantic)

# ── Headless CLI executable ───────────────────────────────────────
find_library(EGL_LIBRARY EGL REQUIRED)

add_executable(lpt2d-cli
    src/cli/main.cpp
    src/cli/headless.cpp
)

target_include_directories(lpt2d-cli PRIVATE
    ${CMAKE_SOURCE_DIR}/src/cli
)
target_link_libraries(lpt2d-cli PRIVATE
    lpt2d-core
    ${EGL_LIBRARY}
)
target_compile_options(lpt2d-cli PRIVATE -Wall -Wextra -Wpedantic)
