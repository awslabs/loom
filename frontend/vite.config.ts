import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import path from "path";
import fs from "fs";
import pkg from "./package.json" with { type: "json" };

function localRuntimePluginRoot(): string {
  const fromEnv = process.env.LOOM_EXT_LOCAL_RUNTIME;
  if (fromEnv && fs.existsSync(fromEnv)) {
    return path.resolve(fromEnv);
  }
  const sibling = path.resolve(__dirname, "../local-runtime/plugin");
  if (fs.existsSync(sibling)) {
    return sibling;
  }
  // Docker mount fallback
  const mounted = path.resolve(__dirname, "extensions/local-runtime");
  return mounted;
}

export default defineConfig({
  plugins: [react(), tailwindcss()],
  define: {
    __APP_VERSION__: JSON.stringify(pkg.version),
  },
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
      "@loom-ext/local-runtime": path.resolve(localRuntimePluginRoot(), "src/register.tsx"),
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
  optimizeDeps: {
    exclude: ["@loom-ext/local-runtime"],
  },
});
