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
    // Build straight into the loom package so `loom serve` serves it by default
    // (serve.py _ui_dir() looks for loom/assets/ui/index.html). browse.html is
    // the zero-build fallback when this directory is absent.
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
