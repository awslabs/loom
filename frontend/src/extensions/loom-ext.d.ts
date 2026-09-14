/// <reference types="vite/client" />

declare module "@loom-ext/local-runtime" {
  import type { LoomExtensionHost } from "@/extensions/types";

  export function register(host: LoomExtensionHost): void;
  export default register;
}
