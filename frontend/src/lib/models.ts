import type { ModelOption } from "@/api/types";

export function groupModels(models: ModelOption[]): [string, ModelOption[]][] {
  const groups = new Map<string, ModelOption[]>();
  for (const m of models) {
    const key = m.group ?? "Other";
    const list = groups.get(key);
    if (list) list.push(m);
    else groups.set(key, [m]);
  }
  return Array.from(groups.entries()).sort((a, b) => a[0].localeCompare(b[0]));
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
