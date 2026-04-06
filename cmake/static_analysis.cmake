include_guard(GLOBAL)

add_library(lpt2d-build-options INTERFACE)
add_library(lpt2d-project-warnings INTERFACE)

target_compile_features(lpt2d-build-options INTERFACE cxx_std_23)

if(CMAKE_CXX_COMPILER_ID MATCHES "GNU|Clang|AppleClang")
    target_compile_options(lpt2d-build-options INTERFACE
        $<$<CONFIG:Release>:-march=native>
    )
endif()

function(lpt2d_enable_build_options target)
    target_link_libraries(${target} PRIVATE lpt2d-build-options)
endfunction()

if(CMAKE_CXX_COMPILER_ID MATCHES "GNU|Clang|AppleClang")
    target_compile_options(lpt2d-project-warnings INTERFACE
        -Wall
        -Wextra
        -Wpedantic
    )
elseif(MSVC)
    target_compile_options(lpt2d-project-warnings INTERFACE /W4)
endif()

function(lpt2d_enable_warnings target)
    target_link_libraries(${target} PRIVATE lpt2d-project-warnings)
endfunction()

function(lpt2d_register_analysis_sources target)
    set(options IWYU)
    cmake_parse_arguments(ARG "${options}" "" "" ${ARGN})

    get_target_property(target_sources ${target} SOURCES)
    if(NOT target_sources)
        return()
    endif()

    set(project_src_prefix "${PROJECT_SOURCE_DIR}/src/")
    set(owned_translation_units)
    foreach(source IN LISTS target_sources)
        if(source MATCHES "^\\$<")
            continue()
        endif()

        if(NOT source MATCHES "\\.(c|cc|cpp|cxx)$")
            continue()
        endif()

        if(NOT IS_ABSOLUTE "${source}")
            get_filename_component(source "${source}" ABSOLUTE BASE_DIR "${PROJECT_SOURCE_DIR}")
        endif()

        string(FIND "${source}" "${project_src_prefix}" source_prefix_pos)
        if(NOT source_prefix_pos EQUAL 0)
            continue()
        endif()

        list(APPEND owned_translation_units "${source}")
    endforeach()

    if(NOT owned_translation_units)
        return()
    endif()

    if(ARG_IWYU)
        set_property(GLOBAL APPEND PROPERTY LPT2D_IWYU_SOURCES "${owned_translation_units}")
    endif()
endfunction()

function(lpt2d_add_missing_tool_target target_name tool_name install_hint)
    add_custom_target(${target_name}
        COMMAND ${CMAKE_COMMAND} -E echo "${tool_name} not found. ${install_hint}"
        COMMAND ${CMAKE_COMMAND} -E false
        USES_TERMINAL
        VERBATIM
    )
endfunction()

function(lpt2d_add_static_analysis_targets)
    get_property(iwyu_sources GLOBAL PROPERTY LPT2D_IWYU_SOURCES)
    set(static_analysis_deps
        generate_shaders
        "${PROJECT_BINARY_DIR}/compile_commands.json"
    )

    if(iwyu_sources)
        list(REMOVE_DUPLICATES iwyu_sources)
    endif()

    find_program(LPT2D_CPPCHECK_EXECUTABLE NAMES cppcheck)
    if(LPT2D_CPPCHECK_EXECUTABLE)
        set(cppcheck_args
            "--project=${PROJECT_BINARY_DIR}/compile_commands.json"
            "--cppcheck-build-dir=${PROJECT_BINARY_DIR}/cppcheck"
            "--enable=warning,performance,portability"
            "--inline-suppr"
            "--suppress=missingIncludeSystem"
            "--error-exitcode=1"
            "--file-filter=${PROJECT_SOURCE_DIR}/src/**"
            "--quiet"
            "-i${PROJECT_SOURCE_DIR}/external"
            "-i${PROJECT_BINARY_DIR}"
        )
        if(LPT2D_CPPCHECK_INCONCLUSIVE)
            list(APPEND cppcheck_args "--inconclusive")
        endif()

        add_custom_target(static-analysis-cppcheck
            COMMAND "${LPT2D_CPPCHECK_EXECUTABLE}"
                ${cppcheck_args}
            DEPENDS ${static_analysis_deps}
            USES_TERMINAL
            VERBATIM
            COMMAND_EXPAND_LISTS
        )
    else()
        lpt2d_add_missing_tool_target(
            static-analysis-cppcheck
            "cppcheck"
            "Install cppcheck, then rerun `cmake --build ${PROJECT_BINARY_DIR} --target static-analysis-cppcheck`."
        )
    endif()

    find_program(LPT2D_IWYU_EXECUTABLE NAMES include-what-you-use iwyu)
    find_program(LPT2D_IWYU_TOOL_EXECUTABLE NAMES iwyu_tool iwyu_tool.py)

    if(LPT2D_IWYU_EXECUTABLE AND LPT2D_IWYU_TOOL_EXECUTABLE AND iwyu_sources)
        set(iwyu_args
            -p "${PROJECT_BINARY_DIR}"
            ${iwyu_sources}
        )
        add_custom_target(static-analysis-iwyu
            COMMAND "${LPT2D_IWYU_TOOL_EXECUTABLE}"
                ${iwyu_args}
            DEPENDS ${static_analysis_deps}
            USES_TERMINAL
            VERBATIM
            COMMAND_EXPAND_LISTS
        )
    elseif(NOT LPT2D_IWYU_EXECUTABLE)
        lpt2d_add_missing_tool_target(
            static-analysis-iwyu
            "include-what-you-use"
            "Install include-what-you-use, then rerun `cmake --build ${PROJECT_BINARY_DIR} --target static-analysis-iwyu`."
        )
    elseif(NOT LPT2D_IWYU_TOOL_EXECUTABLE)
        lpt2d_add_missing_tool_target(
            static-analysis-iwyu
            "iwyu_tool"
            "Install the IWYU helper script, then rerun `cmake --build ${PROJECT_BINARY_DIR} --target static-analysis-iwyu`."
        )
    else()
        add_custom_target(static-analysis-iwyu
            COMMAND ${CMAKE_COMMAND} -E echo "No project-owned translation units are registered for IWYU."
            USES_TERMINAL
            VERBATIM
        )
    endif()

    add_custom_target(static-analysis
        DEPENDS
            static-analysis-cppcheck
            static-analysis-iwyu
    )
endfunction()
