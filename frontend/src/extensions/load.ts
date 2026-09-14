import { createExtensionHost, listExtensions } from "./registry";
import type { LoomExtensionRegistration } from "./types";

type RegisterFn = (host: ReturnType<typeof createExtensionHost>) => void;

/**
 * Discover and register UI plugins (ADR 0006).
 * Failures are logged; the Loom shell still boots.
 */
export async function loadExtensions(): Promise<readonly LoomExtensionRegistration[]> {
  const host = createExtensionHost();

  try {
    const mod = await import("@loom-ext/local-runtime");
    const register = (mod.register ?? mod.default) as RegisterFn | undefined;
    if (typeof register === "function") {
      register(host);
    } else {
      console.warn("[extensions] @loom-ext/local-runtime has no register()");
    }
  } catch (err) {
    console.warn("[extensions] local-runtime plugin not loaded:", err);
  }

  return listExtensions();
}
