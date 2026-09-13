import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import path from "path";
import pkg from "./package.json" with { type: "json" };

export default defineConfig({
  plugins: [react(), tailwindcss()],
  define: {
    __APP_VERSION__: JSON.stringify(pkg.version),
  },
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  server: {
    // Bind-mounted source (Docker on a Windows or macOS host) does not deliver change
    // events into the container, so hot reload only works when the watcher polls.
    watch:
      process.env.VITE_USE_POLLING === "true"
        ? { usePolling: true, interval: 300 }
        : undefined,
  },
});
