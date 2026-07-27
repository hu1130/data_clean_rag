import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";

export default defineConfig({
  plugins: [vue()],
  server: {
    host: "127.0.0.1",
    port: 5173,
    proxy: {
      "/api": "http://127.0.0.1:8131",
      "/health": "http://127.0.0.1:8131"
    }
  },
  build: {
    outDir: "dist",
    sourcemap: false,
    chunkSizeWarningLimit: 1200,
    rollupOptions: {
      output: {
        manualChunks: {
          vue: ["vue"],
          element: ["element-plus", "@element-plus/icons-vue"],
          charts: ["echarts"],
          http: ["axios"]
        }
      }
    }
  }
});
