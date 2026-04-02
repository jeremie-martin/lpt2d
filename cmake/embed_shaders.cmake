# embed_shaders.cmake — generates a C++ header from GLSL source files
#
# Usage:
#   embed_shaders(OUTPUT <header_path> SOURCES <shader1> <shader2> ...)
#
# Each shader file becomes an `inline constexpr char name[] = R"(...)";`
# where `name` is the filename with '.' replaced by '_'.

function(embed_shaders)
    cmake_parse_arguments(EMBED "" "OUTPUT" "SOURCES" ${ARGN})

    set(GENERATOR_SCRIPT "${CMAKE_BINARY_DIR}/_generate_shaders.cmake")

    # Write a CMake script that will run at build time
    file(WRITE "${GENERATOR_SCRIPT}" [=[
# Build-time shader embedding script
get_filename_component(OUTPUT_DIR "${OUTPUT_FILE}" DIRECTORY)
file(MAKE_DIRECTORY "${OUTPUT_DIR}")

set(CONTENT "#pragma once\n\n// Auto-generated from src/shaders/ — do not edit\n\n")

foreach(SHADER_FILE ${SHADER_FILES})
    get_filename_component(FNAME "${SHADER_FILE}" NAME)
    string(REPLACE "." "_" VAR_NAME "${FNAME}")
    file(READ "${SHADER_FILE}" SHADER_SRC)
    string(APPEND CONTENT "inline constexpr char ${VAR_NAME}[] = R\"(\n${SHADER_SRC})\";\n\n")
endforeach()

file(WRITE "${OUTPUT_FILE}" "${CONTENT}")
]=])

    add_custom_command(
        OUTPUT "${EMBED_OUTPUT}"
        COMMAND "${CMAKE_COMMAND}"
            "-DOUTPUT_FILE=${EMBED_OUTPUT}"
            "-DSHADER_FILES=${EMBED_SOURCES}"
            -P "${GENERATOR_SCRIPT}"
        DEPENDS ${EMBED_SOURCES}
        COMMENT "Embedding GLSL shaders into shaders.h"
        VERBATIM
    )

    add_custom_target(generate_shaders DEPENDS "${EMBED_OUTPUT}")
endfunction()
