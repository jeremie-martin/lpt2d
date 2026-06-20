import { defineConfig } from "vite";

// Public assets (the Emscripten lpt2d_web.js/.wasm) are served from web/public
// at the site root and copied verbatim into the build.
export default defineConfig({
  build: { target: "esnext" },
});
