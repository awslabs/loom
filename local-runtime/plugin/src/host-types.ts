import type { ComponentType, ReactNode } from "react";

/** Scopes mirror Loom AuthContext Scope strings. */
export type ExtensionScope = string;

export type ExtensionNavSection = "home" | "build" | "operate" | "system";

export interface ExtensionNavItem {
  section: ExtensionNavSection;
  label: string;
  icon?: ComponentType<{ className?: string }>;
  requiredScopes?: ExtensionScope[];
}

export interface ExtensionRenderContext {
  hasScope: (scope: ExtensionScope) => boolean;
}

export interface LoomExtensionRegistration {
  id: string;
  nav: ExtensionNavItem;
  render: (ctx: ExtensionRenderContext) => ReactNode;
}

/**
 * Minimal host API injected by Loom's Extension Host.
 * Plugins must not bundle their own React.
 */
export interface LoomExtensionHost {
  addExtension: (extension: LoomExtensionRegistration) => void;
}
