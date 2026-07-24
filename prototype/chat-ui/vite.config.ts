import path from "node:path";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  base: "./",
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  build: {
    // Keep the legacy React build packaged for `/app`. The zero-build
    // browse.html console remains the default `/` surface.
    outDir: "../../loom/assets/ui",
    assetsDir: "assets",
    emptyOutDir: true,
    sourcemap: false,
  },
  preview: {
    headers: {
      // 模拟 Tauri WebView 的严格 CSP（与 tauri.conf.json 一致）
      "Content-Security-Policy":
        "default-src 'self'; style-src 'self' 'unsafe-inline'",
    },
  },
});
