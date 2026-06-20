#!/usr/bin/env bash
# Build the GL-free lpt2d core + web glue to WebAssembly (Emscripten).
# Output: web/public/lpt2d_web.{js,wasm} — an ES module exporting resolve_scene.
#
# Requires emcc on PATH. If absent, source the emsdk env first, e.g.:
#   source ~/emsdk/emsdk_env.sh
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO"

if ! command -v emcc >/dev/null 2>&1; then
    if [ -f "$HOME/emsdk/emsdk_env.sh" ]; then
        # shellcheck disable=SC1091
        source "$HOME/emsdk/emsdk_env.sh" >/dev/null 2>&1
    fi
fi
if ! command -v emcc >/dev/null 2>&1; then
    echo "ERROR: emcc not found. Install Emscripten and/or source emsdk_env.sh." >&2
    exit 1
fi

OUT_DIR="$REPO/web/public"
mkdir -p "$OUT_DIR"

# GL-free core translation units (verified: none include GL/EGL/GLEW).
CORE_SRCS=(
    src/core/scene.cpp
    src/core/geometry.cpp
    src/core/serialize_json.cpp
    src/core/spectrum.cpp
    src/core/color.cpp
)

emcc \
    -std=c++20 -O2 \
    -I src/core \
    -I external/nlohmann/single_include \
    -I external/stb \
    web/wasm/lpt2d_web.cpp \
    "${CORE_SRCS[@]}" \
    -lembind \
    -sMODULARIZE=1 \
    -sEXPORT_ES6=1 \
    -sENVIRONMENT=web,node \
    -sALLOW_MEMORY_GROWTH=1 \
    -sEXPORT_NAME=createLpt2dModule \
    -o "$OUT_DIR/lpt2d_web.js"

echo "WASM build OK -> $OUT_DIR/lpt2d_web.js ($(du -h "$OUT_DIR/lpt2d_web.wasm" | cut -f1))"
