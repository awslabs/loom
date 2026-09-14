import type { LoomExtensionHost, LoomExtensionRegistration } from "./types";

const extensions: LoomExtensionRegistration[] = [];

export function createExtensionHost(): LoomExtensionHost {
  return {
    addExtension(extension: LoomExtensionRegistration) {
      const exists = extensions.some((item) => item.id === extension.id);
      if (exists) {
        console.warn(`[extensions] duplicate id ignored: ${extension.id}`);
        return;
      }
      extensions.push(extension);
    },
  };
}

export function listExtensions(): readonly LoomExtensionRegistration[] {
  return extensions;
}

export function getExtension(id: string): LoomExtensionRegistration | undefined {
  return extensions.find((item) => item.id === id);
}
