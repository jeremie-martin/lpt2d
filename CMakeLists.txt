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

# Required packages
find_package(OpenGL REQUIRED)
find_package(GLEW REQUIRED)
find_package(glfw3 REQUIRED)
find_library(EGL_LIBRARY EGL REQUIRED)

# ImGui sources (GLFW + OpenGL3 backends)
set(IMGUI_DIR ${CMAKE_SOURCE_DIR}/external/imgui)
set(IMGUI_SOURCES
    ${IMGUI_DIR}/imgui.cpp
    ${IMGUI_DIR}/imgui_draw.cpp
    ${IMGUI_DIR}/imgui_tables.cpp
    ${IMGUI_DIR}/imgui_widgets.cpp
    ${IMGUI_DIR}/backends/imgui_impl_glfw.cpp
    ${IMGUI_DIR}/backends/imgui_impl_opengl3.cpp
)

# Core sources
set(SOURCES
    src/main.cpp
    src/app.cpp
    src/scene.cpp
    src/spectrum.cpp
    src/renderer.cpp
    src/headless.cpp
    src/export.cpp
    ${IMGUI_SOURCES}
)

add_executable(lpt2d ${SOURCES})

target_include_directories(lpt2d PRIVATE
    ${CMAKE_SOURCE_DIR}/src
    ${CMAKE_SOURCE_DIR}/external
    ${CMAKE_SOURCE_DIR}/external/stb
    ${IMGUI_DIR}
    ${IMGUI_DIR}/backends
)

target_link_libraries(lpt2d PRIVATE
    OpenGL::GL
    GLEW::GLEW
    glfw
    ${EGL_LIBRARY}
)

target_compile_options(lpt2d PRIVATE -Wall -Wextra -Wpedantic)
