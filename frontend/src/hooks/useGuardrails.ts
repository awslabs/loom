import { useCallback, useEffect, useState } from "react";
import { getGuardrailDefault, listGuardrails } from "@/api/settings";
import type { GuardrailDefault, GuardrailSummary } from "@/api/types";

export interface GuardrailCatalog {
  guardrails: GuardrailSummary[];
  /** Error detail from GET /api/settings/guardrails (e.g. the 502 when Bedrock can't be reached). */
  listError: string | null;
  listLoading: boolean;
  guardrailDefault: GuardrailDefault | null;
  defaultLoading: boolean;
  setGuardrailDefault: (value: GuardrailDefault) => void;
  reload: () => void;
}

/**
 * Loads the account's guardrails and the global default together. Both are
 * `agent:read`, so any page that can see agents can call this.
 */
export function useGuardrailCatalog(options: { enabled?: boolean; loadDefault?: boolean } = {}): GuardrailCatalog {
  const { enabled = true, loadDefault = true } = options;
  const [guardrails, setGuardrails] = useState<GuardrailSummary[]>([]);
  const [listError, setListError] = useState<string | null>(null);
  const [listLoading, setListLoading] = useState(false);
  const [guardrailDefault, setGuardrailDefault] = useState<GuardrailDefault | null>(null);
  const [defaultLoading, setDefaultLoading] = useState(false);
  const [nonce, setNonce] = useState(0);

  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;
    setListLoading(true);
    setListError(null);
    listGuardrails()
      .then((list) => { if (!cancelled) setGuardrails(list); })
      .catch((err: unknown) => {
        if (!cancelled) setListError(err instanceof Error ? err.message : "Failed to list guardrails");
      })
      .finally(() => { if (!cancelled) setListLoading(false); });
    if (loadDefault) {
      setDefaultLoading(true);
      getGuardrailDefault()
        .then((d) => { if (!cancelled) setGuardrailDefault(d); })
        .catch(() => { if (!cancelled) setGuardrailDefault(null); })
        .finally(() => { if (!cancelled) setDefaultLoading(false); });
    }
    return () => { cancelled = true; };
  }, [enabled, loadDefault, nonce]);

  const reload = useCallback(() => setNonce((n) => n + 1), []);

  return { guardrails, listError, listLoading, guardrailDefault, defaultLoading, setGuardrailDefault, reload };
}
