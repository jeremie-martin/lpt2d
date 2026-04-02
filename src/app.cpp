#include "app.h"

#include "export.h"
#include "renderer.h"
#include "scenes.h"
#include "spectrum.h"

#include <GL/glew.h>
#include <GLFW/glfw3.h>
#include <imgui.h>
#include <imgui_impl_glfw.h>
#include <imgui_impl_opengl3.h>

#include <iostream>

int App::run(const std::vector<SceneFactory>& scenes, const AppConfig& config) {
    if (!glfwInit()) {
        std::cerr << "GLFW: failed to initialize\n";
        return 1;
    }

    glfwWindowHint(GLFW_CONTEXT_VERSION_MAJOR, 4);
    glfwWindowHint(GLFW_CONTEXT_VERSION_MINOR, 3);
    glfwWindowHint(GLFW_OPENGL_PROFILE, GLFW_OPENGL_CORE_PROFILE);

    GLFWwindow* window = glfwCreateWindow(config.width, config.height, "lpt2d", nullptr, nullptr);
    if (!window) {
        // Fall back to GL 3.3
        glfwWindowHint(GLFW_CONTEXT_VERSION_MAJOR, 3);
        glfwWindowHint(GLFW_CONTEXT_VERSION_MINOR, 3);
        window = glfwCreateWindow(config.width, config.height, "lpt2d", nullptr, nullptr);
        if (!window) {
            std::cerr << "GLFW: failed to create window\n";
            glfwTerminate();
            return 1;
        }
    }

    glfwMakeContextCurrent(window);
    glfwSwapInterval(1);

    Renderer renderer;
    if (!renderer.init(config.width, config.height)) {
        glfwTerminate();
        return 1;
    }

    // ImGui setup
    IMGUI_CHECKVERSION();
    ImGui::CreateContext();
    ImGui_ImplGlfw_InitForOpenGL(window, true);
    ImGui_ImplOpenGL3_Init("#version 330");
    ImGui::StyleColorsDark();

    // State
    int current_scene = 0;
    if (!config.initial_scene.empty()) {
        for (int i = 0; i < (int)scenes.size(); ++i) {
            if (scenes[i].first == config.initial_scene) {
                current_scene = i;
                break;
            }
        }
    }

    Scene scene = scenes[current_scene].second();
    Bounds bounds = compute_bounds(scene);
    Tracer tracer;
    Tracer::Config tcfg;
    PostProcess pp;
    pp.tone_map = ToneMap::ACES;
    int batches_done = 0;
    bool paused = false;

    renderer.clear();

    while (!glfwWindowShouldClose(window)) {
        glfwPollEvents();

        // Trace a batch
        if (!paused) {
            auto segments = tracer.trace_batch(scene, tcfg);

            // Convert world coords to pixel coords
            Vec2 size = bounds.max - bounds.min;
            float scale_x = (float)config.width / size.x;
            float scale_y = (float)config.height / size.y;
            float scale = std::min(scale_x, scale_y);
            Vec2 offset = {(config.width - size.x * scale) * 0.5f, (config.height - size.y * scale) * 0.5f};

            for (auto& s : segments) {
                s.x0 = (s.x0 - bounds.min.x) * scale + offset.x;
                s.y0 = (s.y0 - bounds.min.y) * scale + offset.y;
                s.x1 = (s.x1 - bounds.min.x) * scale + offset.x;
                s.y1 = (s.y1 - bounds.min.y) * scale + offset.y;
            }

            renderer.draw_lines(segments);
            renderer.flush();
            batches_done++;
        }

        // Post-process and display
        renderer.update_display(pp);

        // Render ImGui on top
        ImGui_ImplOpenGL3_NewFrame();
        ImGui_ImplGlfw_NewFrame();
        ImGui::NewFrame();

        // Render display texture to screen
        glBindFramebuffer(GL_FRAMEBUFFER, 0);
        glViewport(0, 0, config.width, config.height);
        glClearColor(0, 0, 0, 1);
        glClear(GL_COLOR_BUFFER_BIT);

        // Draw the rendered image as a fullscreen quad via ImGui
        ImGui::SetNextWindowPos(ImVec2(0, 0));
        ImGui::SetNextWindowSize(ImVec2((float)config.width, (float)config.height));
        ImGui::PushStyleVar(ImGuiStyleVar_WindowPadding, ImVec2(0, 0));
        ImGui::Begin("Viewport", nullptr,
                     ImGuiWindowFlags_NoTitleBar | ImGuiWindowFlags_NoResize | ImGuiWindowFlags_NoMove |
                         ImGuiWindowFlags_NoScrollbar | ImGuiWindowFlags_NoBringToFrontOnFocus);
        ImGui::Image((ImTextureID)(intptr_t)renderer.display_texture(),
                     ImVec2((float)config.width, (float)config.height));
        ImGui::End();
        ImGui::PopStyleVar();

        // Control panel
        ImGui::Begin("Controls");

        // Scene selection
        if (ImGui::BeginCombo("Scene", scenes[current_scene].first.c_str())) {
            for (int i = 0; i < (int)scenes.size(); ++i) {
                bool selected = (i == current_scene);
                if (ImGui::Selectable(scenes[i].first.c_str(), selected)) {
                    current_scene = i;
                    scene = scenes[current_scene].second();
                    bounds = compute_bounds(scene);
                    renderer.clear();
                    tracer = Tracer{};
                    batches_done = 0;
                }
            }
            ImGui::EndCombo();
        }

        ImGui::Separator();
        ImGui::Text("Tracer");
        ImGui::SliderInt("Batch size", &tcfg.batch_size, 1000, 200000);
        ImGui::SliderInt("Max depth", &tcfg.max_depth, 1, 30);
        ImGui::SliderFloat("Intensity", &tcfg.intensity, 0.001f, 10.0f, "%.3f", ImGuiSliderFlags_Logarithmic);
        ImGui::Checkbox("Paused", &paused);

        ImGui::Separator();
        ImGui::Text("Post-processing");
        ImGui::SliderFloat("Exposure", &pp.exposure, -5.0f, 5.0f);
        ImGui::SliderFloat("Contrast", &pp.contrast, 0.1f, 3.0f);
        ImGui::SliderFloat("Gamma", &pp.gamma, 0.5f, 4.0f);
        ImGui::SliderFloat("White point", &pp.white_point, 0.1f, 10.0f);

        const char* tone_names[] = {"None", "Reinhard", "Reinhard Ext", "ACES", "Logarithmic"};
        int tm = (int)pp.tone_map;
        if (ImGui::Combo("Tone map", &tm, tone_names, 5))
            pp.tone_map = (ToneMap)tm;

        ImGui::Separator();
        ImGui::Text("Stats");
        ImGui::Text("Rays: %d", tracer.total_rays());
        ImGui::Text("Batches: %d", batches_done);
        ImGui::Text("Max HDR: %.2f", renderer.last_max());

        if (ImGui::Button("Clear")) {
            renderer.clear();
            tracer = Tracer{};
            batches_done = 0;
        }

        ImGui::SameLine();
        if (ImGui::Button("Export PNG")) {
            std::vector<uint8_t> pixels;
            renderer.read_pixels(pixels, pp);
            std::string filename = scene.name + ".png";
            if (export_png(filename, pixels.data(), config.width, config.height)) {
                std::cerr << "Exported: " << filename << "\n";
            }
        }

        ImGui::End();

        ImGui::Render();
        ImGui_ImplOpenGL3_RenderDrawData(ImGui::GetDrawData());

        glfwSwapBuffers(window);
    }

    ImGui_ImplOpenGL3_Shutdown();
    ImGui_ImplGlfw_Shutdown();
    ImGui::DestroyContext();
    renderer.shutdown();
    glfwDestroyWindow(window);
    glfwTerminate();
    return 0;
}
