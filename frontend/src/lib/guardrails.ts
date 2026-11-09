// Pure helpers for Bedrock Guardrails (issue #17): support matrix, request /
// manifest (de)serialization, and display labels for stream events. Kept free
// of React and API imports so they can be exercised in isolation.
import type {
  AgentResponse,
  GuardrailConfig,
  GuardrailDefault,
  GuardrailDetails,
  GuardrailMode,
  GuardrailPolicyHit,
  GuardrailRef,
  GuardrailRequest,
  GuardrailSelection,
  GuardrailSummary,
  SSEGuardrail,
} from "@/api/types";

export type GuardrailDeploymentType = "custom" | "managed";

export interface GuardrailAvailability {
  /** False when no guardrail mode at all is supported for this agent. */
  available: boolean;
  enforce: boolean;
  monitor: boolean;
  /**
   * Runtime selection between the primary and `allowed` alternates. Custom
   * agents re-validate it in their runtime; managed agents get it as an
   * InvokeHarness model override carrying the alternate's guardrailConfig.
   */
  alternates: boolean;
  /** Why something is restricted, for inline helper text; null when everything is supported. */
  reason: string | null;
}

export const GUARDRAIL_MODES: GuardrailMode[] = ["enforce", "monitor"];

/**
 * Support matrix (tmp/issues/017, "Support matrix"), evaluated from the
 * wizard's deployment type + provider before an agent exists.
 */
export function guardrailAvailability(deploymentType: GuardrailDeploymentType, provider: string): GuardrailAvailability {
  const bedrock = !provider || provider === "bedrock";
  if (deploymentType === "managed") {
    if (!bedrock) {
      return {
        available: false,
        enforce: false,
        monitor: false,
        alternates: false,
        reason: "Guardrails aren't available for managed agents on a non-Bedrock provider. The harness only attaches guardrails to Bedrock model calls and has no hooks for monitor mode. Use a custom agent instead.",
      };
    }
    return {
      available: true,
      enforce: true,
      monitor: false,
      alternates: true,
      reason: "Managed agents support enforce only (the harness has no hooks for monitor). For log-only behavior, use a guardrail whose policies are set to detect in Bedrock.",
    };
  }
  if (!bedrock) {
    return {
      available: true,
      enforce: false,
      monitor: true,
      alternates: true,
      reason: "Enforce attaches the guardrail to Bedrock model calls, so it needs the Bedrock provider. Non-Bedrock providers support monitor only.",
    };
  }
  return { available: true, enforce: true, monitor: true, alternates: true, reason: null };
}

/** Same shape, derived from an existing agent's backend-computed `guardrail_supported`. */
export function guardrailAvailabilityForAgent(agent: Pick<AgentResponse, "source" | "guardrail_supported">): GuardrailAvailability {
  const enforce = agent.guardrail_supported?.enforce ?? false;
  const monitor = agent.guardrail_supported?.monitor ?? false;
  const available = agent.source !== "register" && (enforce || monitor);
  return {
    available,
    enforce: available && enforce,
    monitor: available && monitor,
    alternates: available,
    reason: agent.source === "register" ? "Guardrails aren't supported for registered agents." : null,
  };
}

export function isModeSupported(availability: GuardrailAvailability, mode: GuardrailMode): boolean {
  return mode === "enforce" ? availability.enforce : availability.monitor;
}

/** First mode the agent supports, preferring enforce. */
export function preferredMode(availability: GuardrailAvailability): GuardrailMode {
  return availability.enforce ? "enforce" : "monitor";
}

export function emptyGuardrailConfig(mode: GuardrailMode = "enforce"): GuardrailConfig {
  return {
    guardrail_id: "",
    guardrail_arn: "",
    guardrail_version: "",
    mode,
    stream_processing_mode: "sync",
    redact_history: true,
    allowed: [],
  };
}

// ---- refs ------------------------------------------------------------------

/** Stable string key for a (guardrail_id, guardrail_version) pair, e.g. for <Select> values. */
export function guardrailRefKey(ref: Pick<GuardrailRef, "guardrail_id" | "guardrail_version">): string {
  return `${ref.guardrail_id}@${ref.guardrail_version}`;
}

export function parseGuardrailRefKey(key: string): GuardrailRef | null {
  const at = key.lastIndexOf("@");
  if (at <= 0 || at === key.length - 1) return null;
  return { guardrail_id: key.slice(0, at), guardrail_version: key.slice(at + 1) };
}

export function sameGuardrailRef(a: Pick<GuardrailRef, "guardrail_id" | "guardrail_version">, b: Pick<GuardrailRef, "guardrail_id" | "guardrail_version">): boolean {
  return a.guardrail_id === b.guardrail_id && a.guardrail_version === b.guardrail_version;
}

export function guardrailName(id: string, list: GuardrailSummary[]): string | null {
  return list.find((g) => g.guardrail_id === id)?.name ?? null;
}

/** "pii-strict v2" / "abc123 vDRAFT" — falls back to the ID when the name isn't known. */
export function guardrailRefLabel(ref: Pick<GuardrailRef, "guardrail_id" | "guardrail_version">, list: GuardrailSummary[]): string {
  const name = guardrailName(ref.guardrail_id, list) ?? ref.guardrail_id;
  const version = ref.guardrail_version === "DRAFT" ? "DRAFT" : `v${ref.guardrail_version}`;
  return `${name} · ${version}`;
}

/**
 * Name lookups from an agent's stored `guardrail_details` snapshot (captured
 * at deploy/update time), so agent, invoke and chat views label guardrails
 * without calling ListGuardrails on every page load.
 */
export function guardrailSummariesFromDetails(details: GuardrailDetails | null | undefined): GuardrailSummary[] {
  return (details?.guardrails ?? [])
    .filter((g) => !g.error && g.name)
    .map((g) => ({
      guardrail_id: g.guardrail_id,
      guardrail_arn: g.guardrail_arn ?? "",
      name: g.name ?? "",
      description: g.description ?? "",
      status: g.status ?? "",
      versions: [g.version],
    }));
}

/** Primary first, then `allowed` alternates (deduped, primary excluded). */
export function invokableGuardrails(config: GuardrailConfig | null | undefined): GuardrailRef[] {
  if (!config || !config.guardrail_id) return [];
  const primary: GuardrailRef = { guardrail_id: config.guardrail_id, guardrail_arn: config.guardrail_arn, guardrail_version: config.guardrail_version };
  return [primary, ...normalizeAllowed(config.allowed ?? [], primary)];
}

function normalizeAllowed(allowed: GuardrailRef[], primary: GuardrailRef): GuardrailRef[] {
  const seen = new Set<string>([guardrailRefKey(primary)]);
  const out: GuardrailRef[] = [];
  for (const ref of allowed) {
    if (!ref.guardrail_id || !ref.guardrail_version) continue;
    const key = guardrailRefKey(ref);
    if (seen.has(key)) continue;
    seen.add(key);
    out.push(ref.guardrail_arn ? ref : { guardrail_id: ref.guardrail_id, guardrail_version: ref.guardrail_version });
  }
  return out;
}

// ---- validation + request ----------------------------------------------------

function defaultIsLocked(def: GuardrailDefault | null | undefined): boolean {
  return !!def && def.enabled && def.locked;
}

/** True when inheriting the global default would actually attach a guardrail. */
export function hasUsableDefault(def: GuardrailDefault | null | undefined): boolean {
  return !!def && def.enabled && !!def.config;
}

export interface GuardrailSelectionOptions {
  /** "Inherit default" can't be chosen: no default is configured. */
  inheritDisabled: boolean;
  inheritTitle?: string;
  /** "None" is offered: hidden under a locked default, since agents can't opt out. */
  showNone: boolean;
}

/**
 * Which selection options the wizard offers. `def` is null while the default
 * is loading or if it couldn't be read; that's treated as unknown, so nothing
 * is disabled. The current selection always stays visible, so editing an
 * agent saved as "inherit" (or "none" before a lock) doesn't hide its value.
 */
export function guardrailSelectionOptions(
  def: GuardrailDefault | null | undefined,
  current: GuardrailSelection,
): GuardrailSelectionOptions {
  const noDefault = !!def && !hasUsableDefault(def);
  return {
    inheritDisabled: noDefault && current !== "default",
    inheritTitle: noDefault ? "No default guardrail is configured" : undefined,
    showNone: !defaultIsLocked(def) || current === "none",
  };
}

/**
 * Starting selection for a brand-new agent once the default has loaded:
 * inherit when a default exists, otherwise an explicit "none" so the wizard
 * doesn't suggest an inherited guardrail that isn't there. Returns null while
 * the default is unknown (leave the selection alone).
 */
export function initialGuardrailSelection(def: GuardrailDefault | null | undefined): GuardrailSelection | null {
  if (!def) return null;
  return hasUsableDefault(def) ? "default" : "none";
}

/**
 * Blocking validation for the wizard's guardrail section. Returns a message
 * when the choice would be rejected (422) by the backend, else null.
 */
export function validateGuardrailChoice(
  selection: GuardrailSelection,
  config: GuardrailConfig,
  availability: GuardrailAvailability,
  def: GuardrailDefault | null | undefined,
): string | null {
  if (!availability.available) {
    return defaultIsLocked(def)
      ? "The global default guardrail is locked, but guardrails aren't supported for this agent configuration."
      : null;
  }
  if (selection === "none") {
    return defaultIsLocked(def) ? "The global default guardrail is locked, so agents can't opt out." : null;
  }
  if (selection === "custom") {
    if (!config.guardrail_id) return "Select a guardrail.";
    if (!config.guardrail_version) return "Select a guardrail version.";
    if (!isModeSupported(availability, config.mode)) return `${config.mode} mode isn't supported for this agent.`;
    if (defaultIsLocked(def) && def?.config?.mode === "enforce" && config.mode === "monitor") {
      return "The locked default enforces its guardrail, so a custom guardrail can't use monitor mode.";
    }
  }
  return null;
}

/** Non-blocking warning for "Inherit default" when the default can't apply to this agent as-is. */
export function inheritWarning(availability: GuardrailAvailability, def: GuardrailDefault | null | undefined): string | null {
  if (!def || !def.enabled || !def.config || !availability.available) return null;
  if (!isModeSupported(availability, def.config.mode)) {
    return `The default guardrail uses ${def.config.mode} mode, which isn't supported for this agent. Choose a custom guardrail${def.locked ? "" : " or none"}.`;
  }
  return null;
}

/** Normalizes a config before sending: drops the primary/duplicates from `allowed`, clears alternates when unsupported. */
export function normalizeGuardrailConfig(config: GuardrailConfig, availability: GuardrailAvailability): GuardrailConfig {
  const primary: GuardrailRef = { guardrail_id: config.guardrail_id, guardrail_version: config.guardrail_version };
  const out: GuardrailConfig = {
    guardrail_id: config.guardrail_id,
    guardrail_version: config.guardrail_version,
    mode: config.mode,
    stream_processing_mode: config.stream_processing_mode,
    redact_history: config.redact_history,
    allowed: availability.alternates ? normalizeAllowed(config.allowed, primary) : [],
  };
  if (config.guardrail_arn) out.guardrail_arn = config.guardrail_arn;
  return out;
}

/**
 * The create/redeploy `guardrail` request field. Returns undefined to omit it
 * (backend treats that as "default").
 */
export function buildGuardrailRequest(
  selection: GuardrailSelection,
  config: GuardrailConfig,
  availability: GuardrailAvailability,
  def: GuardrailDefault | null | undefined,
): GuardrailRequest | undefined {
  if (!availability.available) {
    // Nothing can be attached; opt out explicitly unless the default is locked
    // (in which case validation already blocks the deploy).
    return defaultIsLocked(def) ? undefined : { selection: "none", config: null };
  }
  if (selection === "custom") return { selection: "custom", config: normalizeGuardrailConfig(config, availability) };
  return { selection, config: null };
}

// ---- manifest ----------------------------------------------------------------

/** Manifest `guardrail` block. Absent = inherit the default. */
export interface ManifestGuardrail {
  selection: GuardrailSelection;
  config?: GuardrailConfig;
}

export function guardrailToManifest(selection: GuardrailSelection, config: GuardrailConfig): ManifestGuardrail | undefined {
  if (selection === "default") return undefined;
  if (selection === "none") return { selection: "none" };
  const out: GuardrailConfig = {
    guardrail_id: config.guardrail_id,
    guardrail_version: config.guardrail_version,
    mode: config.mode,
    stream_processing_mode: config.stream_processing_mode,
    redact_history: config.redact_history,
    allowed: normalizeAllowed(config.allowed, config),
  };
  if (config.guardrail_arn) out.guardrail_arn = config.guardrail_arn;
  return { selection: "custom", config: out };
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function parseRef(value: unknown): GuardrailRef | null {
  if (!isRecord(value)) return null;
  const id = value.guardrail_id;
  const version = value.guardrail_version;
  if (typeof id !== "string" || !id) return null;
  const ref: GuardrailRef = { guardrail_id: id, guardrail_version: typeof version === "string" && version ? version : "DRAFT" };
  if (typeof value.guardrail_arn === "string" && value.guardrail_arn) ref.guardrail_arn = value.guardrail_arn;
  return ref;
}

/** Parses a GuardrailConfig-shaped object, filling contract defaults for missing optional fields. */
export function parseGuardrailConfig(value: unknown): GuardrailConfig | null {
  const ref = parseRef(value);
  if (!ref || !isRecord(value)) return null;
  const mode: GuardrailMode = value.mode === "monitor" ? "monitor" : "enforce";
  const allowed = Array.isArray(value.allowed)
    ? value.allowed.map(parseRef).filter((r): r is GuardrailRef => r !== null)
    : [];
  return {
    ...ref,
    mode,
    stream_processing_mode: value.stream_processing_mode === "async" ? "async" : "sync",
    redact_history: typeof value.redact_history === "boolean" ? value.redact_history : true,
    allowed: normalizeAllowed(allowed, ref),
  };
}

export type ParsedManifestGuardrail =
  | { ok: true; selection: GuardrailSelection; config: GuardrailConfig | null }
  | { ok: false; error: string };

/**
 * Accepts: absent/null (→ default), a selection string ("default" | "none"),
 * `{selection, config}` (the request shape), or a bare GuardrailConfig (→ custom).
 */
export function guardrailFromManifest(value: unknown): ParsedManifestGuardrail {
  if (value === undefined || value === null) return { ok: true, selection: "default", config: null };
  if (value === "default" || value === "none") return { ok: true, selection: value, config: null };
  if (!isRecord(value)) return { ok: false, error: "Invalid guardrail block in manifest." };
  if ("selection" in value) {
    const selection = value.selection;
    if (selection === "default" || selection === "none") return { ok: true, selection, config: null };
    if (selection === "custom") {
      const config = parseGuardrailConfig(value.config);
      return config
        ? { ok: true, selection: "custom", config }
        : { ok: false, error: "Manifest guardrail selection \"custom\" requires a config with guardrail_id." };
    }
    return { ok: false, error: `Unknown guardrail selection "${String(selection)}" in manifest.` };
  }
  const config = parseGuardrailConfig(value);
  return config ? { ok: true, selection: "custom", config } : { ok: false, error: "Invalid guardrail block in manifest." };
}

// ---- stream events -----------------------------------------------------------

export function policyLabel(p: GuardrailPolicyHit): string {
  const detail = p.type ?? p.name;
  return detail ? `${p.policy} ${detail}` : p.policy;
}

/** e.g. "Guardrail intervened · input · contentPolicy HATE" / "Guardrail detected (monitor) · output". */
export function guardrailEventLabel(e: SSEGuardrail): string {
  const head = e.action === "detected" ? "Guardrail detected (monitor)" : "Guardrail intervened";
  const parts = [head];
  if (e.source && e.source !== "UNKNOWN") parts.push(e.source.toLowerCase());
  const policies = (e.policies ?? []).map(policyLabel);
  if (policies.length > 0) parts.push(policies.join(", "));
  return parts.join(" · ");
}

/** Newest published (numeric) version, else DRAFT. Versions arrive as e.g. ["DRAFT", "2", "1"]. */
export function pickDefaultVersion(versions: string[]): string {
  const numeric = versions.filter((v) => /^\d+$/.test(v)).sort((a, b) => Number(b) - Number(a));
  return numeric[0] ?? (versions.includes("DRAFT") ? "DRAFT" : versions[0] ?? "DRAFT");
}
