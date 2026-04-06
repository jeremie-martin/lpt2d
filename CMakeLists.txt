cmake_minimum_required(VERSION 3.20)
project(lpt2d VERSION 0.1.0 LANGUAGES CXX)

set(CMAKE_EXPORT_COMPILE_COMMANDS ON)

if(NOT CMAKE_CONFIGURATION_TYPES AND NOT CMAKE_BUILD_TYPE)
    set(CMAKE_BUILD_TYPE Release CACHE STRING "Build type" FORCE)
endif()

option(LPT2D_BUILD_PYTHON "Build Python bindings" ON)
option(LPT2D_CPPCHECK_INCONCLUSIVE "Enable inconclusive cppcheck diagnostics" OFF)

# ── Shader embedding ──────────────────────────────────────────────
include(cmake/embed_shaders.cmake)
include(cmake/static_analysis.cmake)

set(SHADER_DIR ${PROJECT_SOURCE_DIR}/src/shaders)
set(SHADER_FILES
    ${SHADER_DIR}/trace.comp
    ${SHADER_DIR}/line.vert
    ${SHADER_DIR}/line.frag
    ${SHADER_DIR}/fill.vert
    ${SHADER_DIR}/fill.frag
    ${SHADER_DIR}/postprocess.vert
    ${SHADER_DIR}/postprocess.frag
    ${SHADER_DIR}/max_reduce.comp
)
set(GENERATED_SHADER_HEADER ${PROJECT_BINARY_DIR}/generated/shaders.h)

embed_shaders(
    OUTPUT ${GENERATED_SHADER_HEADER}
    SOURCES ${SHADER_FILES}
)

# ── Dependencies ──────────────────────────────────────────────────
find_package(OpenGL REQUIRED)
find_package(GLEW REQUIRED)
find_library(EGL_LIBRARY EGL REQUIRED)

# ── Core library ──────────────────────────────────────────────────
add_library(lpt2d-core STATIC
    src/core/scene.cpp
    src/core/geometry.cpp
    src/core/scenes.cpp
    src/core/renderer.cpp
    src/core/spectrum.cpp
    src/core/color.cpp
    src/core/export.cpp
    src/core/serialize.cpp
    src/core/serialize_json.cpp
    src/core/headless.cpp
    src/core/session.cpp
)

target_include_directories(lpt2d-core PUBLIC
    ${PROJECT_SOURCE_DIR}/src/core
    ${PROJECT_BINARY_DIR}/generated
)
target_include_directories(lpt2d-core SYSTEM PUBLIC
    ${PROJECT_SOURCE_DIR}/external/nlohmann/single_include
)
target_include_directories(lpt2d-core SYSTEM PRIVATE
    ${PROJECT_SOURCE_DIR}/external/stb
)
target_link_libraries(lpt2d-core PUBLIC
    OpenGL::GL
    GLEW::GLEW
    ${EGL_LIBRARY}
)
target_compile_definitions(lpt2d-core PUBLIC
    LPT2D_SCENES_DIR="${PROJECT_SOURCE_DIR}/scenes"
)
lpt2d_enable_build_options(lpt2d-core)
lpt2d_enable_warnings(lpt2d-core)
set_property(TARGET lpt2d-core PROPERTY POSITION_INDEPENDENT_CODE ON)

add_dependencies(lpt2d-core generate_shaders)
lpt2d_register_analysis_sources(lpt2d-core IWYU)

# ── Interactive GUI executable ────────────────────────────────────
find_package(glfw3 REQUIRED)

set(IMGUI_DIR ${PROJECT_SOURCE_DIR}/external/imgui)
set(IMGUI_SOURCES
    ${IMGUI_DIR}/imgui.cpp
    ${IMGUI_DIR}/imgui_draw.cpp
    ${IMGUI_DIR}/imgui_tables.cpp
    ${IMGUI_DIR}/imgui_widgets.cpp
    ${IMGUI_DIR}/backends/imgui_impl_glfw.cpp
    ${IMGUI_DIR}/backends/imgui_impl_opengl3.cpp
)

add_library(lpt2d-imgui STATIC
    ${IMGUI_SOURCES}
)

target_include_directories(lpt2d-imgui SYSTEM PUBLIC
    ${IMGUI_DIR}
    ${IMGUI_DIR}/backends
)
target_link_libraries(lpt2d-imgui PUBLIC
    glfw
)
lpt2d_enable_build_options(lpt2d-imgui)

add_executable(lpt2d
    src/app/main.cpp
    src/app/app.cpp
    src/app/app_actions.cpp
    src/app/app_panels.cpp
    src/app/editor.cpp
    src/app/ui.cpp
)

target_include_directories(lpt2d PRIVATE
    ${PROJECT_SOURCE_DIR}/src/app
)
target_link_libraries(lpt2d PRIVATE
    lpt2d-core
    lpt2d-imgui
    glfw
)
target_compile_definitions(lpt2d PRIVATE
    LPT2D_FONT_PATH="${PROJECT_SOURCE_DIR}/external/imgui/misc/fonts/Roboto-Medium.ttf"
)
lpt2d_enable_build_options(lpt2d)
lpt2d_enable_warnings(lpt2d)
lpt2d_register_analysis_sources(lpt2d IWYU)

# ── Headless CLI executable ───────────────────────────────────────
add_executable(lpt2d-cli
    src/cli/main.cpp
)

target_link_libraries(lpt2d-cli PRIVATE
    lpt2d-core
)
lpt2d_enable_build_options(lpt2d-cli)
lpt2d_enable_warnings(lpt2d-cli)
lpt2d_register_analysis_sources(lpt2d-cli IWYU)

# ── Python extension module (nanobind) ───────────────────────────
if(LPT2D_BUILD_PYTHON)
    find_package(Python3 COMPONENTS Interpreter Development.Module)
    if(Python3_FOUND)
        # nanobind uses find_package(Python), not find_package(Python3).
        # Bridge the variables so nanobind finds the same Python.
        set(Python_EXECUTABLE ${Python3_EXECUTABLE})
        set(Python_INCLUDE_DIRS ${Python3_INCLUDE_DIRS})
        set(Python_LIBRARIES ${Python3_LIBRARIES})
        set(Python_FOUND TRUE)

        add_subdirectory(${PROJECT_SOURCE_DIR}/external/nanobind)
        nanobind_add_module(_lpt2d
            src/bindings/lpt2d_bindings.cpp
        )
        target_link_libraries(_lpt2d PRIVATE lpt2d-core)
        lpt2d_enable_build_options(_lpt2d)
        lpt2d_enable_warnings(_lpt2d)
        lpt2d_register_analysis_sources(_lpt2d)
        install(TARGETS _lpt2d LIBRARY DESTINATION .)
    else()
        message(STATUS "Python3 development components not found; skipping _lpt2d module")
    endif()
endif()

lpt2d_add_static_analysis_targets()
