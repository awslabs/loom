import type { ModelOption } from "@/api/types";

/** Pulls the first version-shaped number out of a display name (e.g.
 * "Claude Opus 4.8" -> 4.8, "Kimi K3" -> 3, "Nova Lite" -> null). Used as a
 * recency proxy so newer versions sort first without needing a release
 * date on every catalog entry. */
function extractVersion(displayName: string): number | null {
  const match = displayName.match(/(\d+(?:\.\d+)?)/);
  if (!match?.[1]) return null;
  const value = parseFloat(match[1]);
  return Number.isNaN(value) ? null : value;
}

/** Pulls the model "tier" out of a display name by stripping every version
 * number (e.g. "Claude Opus 4.8" -> "Claude Opus", "Nova 2 Lite" and
 * "Nova Lite" both -> "Nova Lite"). Models in the same tier are versions of
 * the same line and should stay adjacent, sorted newest first, rather than
 * interleaving with other tiers that happen to share a version number. */
function extractTier(displayName: string): string {
  return displayName.replace(/\d+(?:\.\d+)?/g, "").replace(/\s+/g, " ").trim();
}

/** Sorts models by tier recency, then by version within a tier: each tier's
 * most recent version sets the tier's rank (so "Fable 5.1" outranks the
 * "Opus" tier, whose latest is "Opus 5"), ties between tiers break
 * alphabetically, and within a tier newer versions come first. Falls back to
 * alphabetical for names with no version at all (which sort after every
 * versioned entry in the same tier — there's no recency signal to rank them
 * by). */
export function sortModelsByRecency(models: ModelOption[]): ModelOption[] {
  const tierOf = (m: ModelOption) => extractTier(m.display_name);
  const tierMaxVersion = new Map<string, number>();
  for (const m of models) {
    const tier = tierOf(m);
    const version = extractVersion(m.display_name) ?? -Infinity;
    const current = tierMaxVersion.get(tier);
    if (current === undefined || version > current) tierMaxVersion.set(tier, version);
  }

  return [...models].sort((a, b) => {
    const tierA = tierOf(a);
    const tierB = tierOf(b);
    if (tierA !== tierB) {
      const maxA = tierMaxVersion.get(tierA) ?? -Infinity;
      const maxB = tierMaxVersion.get(tierB) ?? -Infinity;
      if (maxA !== maxB) return maxB - maxA;
      return tierA.localeCompare(tierB);
    }
    const va = extractVersion(a.display_name);
    const vb = extractVersion(b.display_name);
    if (va !== null && vb !== null && va !== vb) return vb - va;
    if (va !== null && vb === null) return -1;
    if (va === null && vb !== null) return 1;
    return a.display_name.localeCompare(b.display_name);
  });
}

export function groupModels(models: ModelOption[]): [string, ModelOption[]][] {
  const groups = new Map<string, ModelOption[]>();
  for (const m of models) {
    const key = m.group ?? "Other";
    const list = groups.get(key);
    if (list) list.push(m);
    else groups.set(key, [m]);
  }
  return Array.from(groups.entries())
    .sort((a, b) => a[0].localeCompare(b[0]))
    .map(([group, groupModels]) => [group, sortModelsByRecency(groupModels)]);
}

const PROVIDER_ORDER = ["bedrock", "litellm"];

export function groupModelsByProvider(models: ModelOption[]): [string, [string, ModelOption[]][]][] {
  const byProvider = new Map<string, ModelOption[]>();
  for (const m of models) {
    const key = m.provider ?? "bedrock";
    const list = byProvider.get(key);
    if (list) list.push(m);
    else byProvider.set(key, [m]);
  }
  return Array.from(byProvider.entries())
    .sort((a, b) => {
      const ai = PROVIDER_ORDER.indexOf(a[0]);
      const bi = PROVIDER_ORDER.indexOf(b[0]);
      if (ai !== bi) return (ai === -1 ? 99 : ai) - (bi === -1 ? 99 : bi);
      return a[0].localeCompare(b[0]);
    })
    .map(([provider, providerModels]) => [provider, groupModels(providerModels)]);
}
