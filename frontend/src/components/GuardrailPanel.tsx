// Agent detail: effective guardrail + intervention history (issue #17).
import { useCallback, useEffect, useState, type ReactNode } from "react";
import { RefreshCw } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { StatusPill } from "@/components/StatusPill";
import { GuardrailConfigSummary, GuardrailPolicyChips } from "@/components/GuardrailControls";
import { listGuardrailInterventions, refreshGuardrailDetails } from "@/api/agents";
import { useAuth } from "@/contexts/AuthContext";
import { useTimezone } from "@/contexts/TimezoneContext";
import { formatRelativeDateTime, formatTimestamp } from "@/lib/format";
import { guardrailRefLabel, guardrailSummariesFromDetails } from "@/lib/guardrails";
import type {
  AgentResponse,
  GuardrailDetails,
  GuardrailDetailsEntry,
  GuardrailInterventionsResponse,
  GuardrailIoAction,
} from "@/api/types";

function selectionLabel(agent: AgentResponse): string {
  switch (agent.guardrail_selection) {
    case "default": return "inherit default";
    case "custom": return "custom";
    case "none": return "none";
    default: return "not configured";
  }
}

function actionLabel(action: string | null | undefined, enabled: boolean = true): string {
  if (!enabled) return "off";
  switch (action) {
    case "BLOCK": return "block";
    case "ANONYMIZE": return "mask";
    case "NONE": return "detect";
    default: return action ? action.toLowerCase() : "block";
  }
}

function ioLabel(item: GuardrailIoAction): string {
  const input = actionLabel(item.input_action, item.input_enabled);
  const output = actionLabel(item.output_action, item.output_enabled);
  return input === output ? input : `in ${input} · out ${output}`;
}

function DetailSection({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="flex flex-col gap-1">
      <span className="font-mono text-[9.5px] tracking-wide text-muted-foreground uppercase">{title}</span>
      {children}
    </div>
  );
}

function Chip({ children, title }: { children: ReactNode; title?: string }) {
  return (
    <span title={title} className="rounded border px-1.5 py-0.5 font-mono text-[11px]">
      {children}
    </span>
  );
}

/** Policy configuration of one guardrail version, from the stored GetGuardrail snapshot. */
function GuardrailDetailsView({ entry }: { entry: GuardrailDetailsEntry }) {
  if (entry.error) {
    return (
      <p className="rounded-md border border-warning/40 bg-warning-bg px-2 py-1.5 text-[12px] text-warning">
        {entry.error}
      </p>
    );
  }
  const filters = entry.content_filters ?? [];
  const topics = entry.denied_topics ?? [];
  const pii = entry.pii_entities ?? [];
  const regexes = entry.regexes ?? [];
  const managedWords = entry.managed_word_lists ?? [];
  const customWords = entry.custom_word_count ?? 0;
  const grounding = entry.contextual_grounding ?? [];
  const reasoning = entry.automated_reasoning_policy_count ?? 0;
  const empty = !filters.length && !topics.length && !pii.length && !regexes.length
    && !managedWords.length && !customWords && !grounding.length && !reasoning;

  return (
    <div className="flex flex-col gap-2.5">
      {entry.description && <p className="text-[12px] text-muted-foreground">{entry.description}</p>}
      {filters.length > 0 && (
        <DetailSection title={`Content filters${entry.content_tier ? ` · ${entry.content_tier.toLowerCase()} tier` : ""}`}>
          <div className="flex flex-wrap gap-1.5">
            {filters.map((f) => {
              const strength = f.input_strength === f.output_strength || f.type === "PROMPT_ATTACK"
                ? f.input_strength
                : `${f.input_strength}/${f.output_strength}`;
              return (
                <Chip key={f.type} title={`Prompt strength ${f.input_strength}, response strength ${f.output_strength}`}>
                  {f.type} · {strength.toLowerCase()} · {ioLabel(f)}
                </Chip>
              );
            })}
          </div>
        </DetailSection>
      )}
      {topics.length > 0 && (
        <DetailSection title="Denied topics">
          <ul className="flex flex-col gap-1">
            {topics.map((t) => (
              <li key={t.name} className="text-[12px]">
                <span className="font-medium">{t.name}</span>
                <span className="ml-1.5 font-mono text-[10.5px] text-muted-foreground">{ioLabel(t)}</span>
                {t.definition && <span className="block text-muted-foreground">{t.definition}</span>}
              </li>
            ))}
          </ul>
        </DetailSection>
      )}
      {(pii.length > 0 || regexes.length > 0) && (
        <DetailSection title="Sensitive information">
          <div className="flex flex-wrap gap-1.5">
            {pii.map((e) => <Chip key={e.type}>{e.type} · {ioLabel(e)}</Chip>)}
            {regexes.map((r) => <Chip key={`re-${r.name}`} title="Custom regex">regex {r.name} · {ioLabel(r)}</Chip>)}
          </div>
        </DetailSection>
      )}
      {(managedWords.length > 0 || customWords > 0) && (
        <DetailSection title="Word filters">
          <div className="flex flex-wrap gap-1.5">
            {managedWords.map((w) => <Chip key={w.type}>{w.type.toLowerCase()} list · {ioLabel(w)}</Chip>)}
            {customWords > 0 && <Chip>{customWords} custom word{customWords === 1 ? "" : "s"}</Chip>}
          </div>
        </DetailSection>
      )}
      {grounding.length > 0 && (
        <DetailSection title="Contextual grounding">
          <div className="flex flex-wrap gap-1.5">
            {grounding.map((g) => (
              <Chip key={g.type}>
                {g.type.toLowerCase()} ≥ {g.threshold ?? "?"} · {g.enabled ? actionLabel(g.action) : "off"}
              </Chip>
            ))}
          </div>
        </DetailSection>
      )}
      {reasoning > 0 && (
        <DetailSection title="Automated reasoning">
          <span className="text-[12px]">{reasoning} polic{reasoning === 1 ? "y" : "ies"}</span>
        </DetailSection>
      )}
      {empty && <p className="text-[12px] text-muted-foreground">This guardrail version has no policies configured.</p>}
      {(entry.blocked_input_messaging || entry.blocked_outputs_messaging) && (
        <DetailSection title="Blocked messages">
          <div className="flex flex-col gap-0.5 text-[12px]">
            {entry.blocked_input_messaging && <span><span className="text-muted-foreground">Prompt:</span> {entry.blocked_input_messaging}</span>}
            {entry.blocked_outputs_messaging && <span><span className="text-muted-foreground">Response:</span> {entry.blocked_outputs_messaging}</span>}
          </div>
        </DetailSection>
      )}
      <div className="flex flex-wrap gap-x-3 gap-y-0.5 font-mono text-[10.5px] text-muted-foreground">
        {entry.status && <span>status {entry.status.toLowerCase()}</span>}
        {entry.region && <span>{entry.region}</span>}
        {entry.cross_region_profile && <span>cross-region {entry.cross_region_profile}</span>}
        {entry.encrypted_with_cmk && <span>customer-managed KMS key</span>}
      </div>
    </div>
  );
}

/** Effective guardrail baked into the agent at its last deploy, its policy details, and drift against the default. */
export function GuardrailCard({ agent, onUpdated }: { agent: AgentResponse; onUpdated?: () => void }) {
  const { hasScope } = useAuth();
  const { timezone } = useTimezone();
  const [details, setDetails] = useState<GuardrailDetails | null>(agent.guardrail_details ?? null);
  const [refreshing, setRefreshing] = useState(false);
  const [refreshError, setRefreshError] = useState<string | null>(null);
  const [showAlternates, setShowAlternates] = useState(false);
  useEffect(() => { setDetails(agent.guardrail_details ?? null); }, [agent.guardrail_details]);

  const guardrails = guardrailSummariesFromDetails(details);
  const supported = agent.guardrail_supported ?? { enforce: false, monitor: false };
  const supportedModes = [supported.enforce && "enforce", supported.monitor && "monitor"].filter(Boolean).join(", ");
  const config = agent.guardrail;
  const [primary, ...alternates] = details?.guardrails ?? [];

  const refresh = async () => {
    setRefreshing(true);
    setRefreshError(null);
    try {
      const updated = await refreshGuardrailDetails(agent.id);
      setDetails(updated.guardrail_details ?? null);
      onUpdated?.();
    } catch (err) {
      setRefreshError(err instanceof Error ? err.message : "Failed to refresh guardrail details");
    } finally {
      setRefreshing(false);
    }
  };

  return (
    <Card className="gap-0 py-0">
      <CardHeader className="flex-row items-center gap-2.5 border-b py-3.5 px-[18px] [.border-b]:pb-3.5">
        <CardTitle className="text-[13.5px] font-semibold">Guardrail</CardTitle>
        <StatusPill label={selectionLabel(agent)} variant={config ? "info" : "neutral"} />
        {agent.guardrail_drift && (
          <span title="The global default guardrail changed since this agent was last deployed. Edit the agent and update it (or redeploy) to apply the new default.">
            <StatusPill label="Redeploy to apply" variant="warning" />
          </span>
        )}
        <span className="ml-auto font-mono text-[10.5px] text-muted-foreground">
          {supportedModes ? `supports ${supportedModes}` : "not supported for this agent"}
        </span>
      </CardHeader>
      <CardContent className="flex flex-col gap-2.5 px-[18px] py-3.5">
        {config ? (
          <>
            <GuardrailConfigSummary config={config} guardrails={guardrails} />
            {primary ? (
              <GuardrailDetailsView entry={primary} />
            ) : (
              <p className="text-[12px] text-muted-foreground">
                Policy details weren't captured when this agent was deployed. Refresh to read them from Bedrock.
              </p>
            )}
            {config.allowed && config.allowed.length > 0 && (
              <div className="flex flex-col gap-1.5">
                <div className="flex flex-wrap items-center gap-1.5">
                  <span className="font-mono text-[9.5px] tracking-wide text-muted-foreground uppercase">Alternates</span>
                  {config.allowed.map((ref) => (
                    <span key={`${ref.guardrail_id}@${ref.guardrail_version}`} className="rounded border px-1.5 py-0.5 font-mono text-[11px]">
                      {guardrailRefLabel(ref, guardrails)}
                    </span>
                  ))}
                  {alternates.length > 0 && (
                    <button
                      type="button"
                      className="text-[11px] text-primary hover:underline"
                      onClick={() => setShowAlternates((v) => !v)}
                    >
                      {showAlternates ? "Hide policies" : "Show policies"}
                    </button>
                  )}
                </div>
                {showAlternates && alternates.map((entry) => (
                  <div key={`${entry.guardrail_id}@${entry.version}`} className="rounded-md border px-2.5 py-2">
                    <span className="mb-1.5 block font-mono text-[11px]">
                      {guardrailRefLabel({ guardrail_id: entry.guardrail_id, guardrail_version: entry.version }, guardrails)}
                    </span>
                    <GuardrailDetailsView entry={entry} />
                  </div>
                ))}
              </div>
            )}
            <div className="flex items-center gap-2 border-t pt-2 font-mono text-[10.5px] text-muted-foreground">
              <span>
                {details?.fetched_at
                  ? `Details read ${formatRelativeDateTime(details.fetched_at, timezone)} — captured at deploy, not live`
                  : "No details captured"}
              </span>
              {hasScope("agent:write") && (
                <button
                  type="button"
                  onClick={refresh}
                  disabled={refreshing}
                  className="ml-auto inline-flex items-center gap-1 text-primary hover:underline disabled:opacity-50"
                  title="Re-read the guardrail from Bedrock (e.g. after editing a DRAFT version). Doesn't change what the agent enforces."
                >
                  <RefreshCw className={`h-3 w-3 ${refreshing ? "animate-spin" : ""}`} />
                  Refresh details
                </button>
              )}
            </div>
            {refreshError && <p className="text-[11.5px] text-destructive">{refreshError}</p>}
          </>
        ) : (
          <p className="text-[12.5px] text-muted-foreground">
            {agent.guardrail_selection === "none"
              ? "This agent opted out of guardrails."
              : agent.guardrail_selection === "default"
                ? "No default guardrail was set when this agent was last deployed."
                : "No guardrail is attached to this agent."}
          </p>
        )}
      </CardContent>
    </Card>
  );
}

const HOUR_OPTIONS = [
  { value: "1", label: "Last hour" },
  { value: "24", label: "Last 24 hours" },
  { value: "168", label: "Last 7 days" },
];

/** GET /api/agents/{id}/guardrails/interventions — Logs Insights over the agent's runtime log group. */
export function GuardrailInterventionsCard({ agentId, onOpenSession }: { agentId: number; onOpenSession?: (sessionId: string) => void }) {
  const { timezone } = useTimezone();
  const [hours, setHours] = useState("24");
  const [data, setData] = useState<GuardrailInterventionsResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    setLoading(true);
    setError(null);
    listGuardrailInterventions(agentId, { hours: Number(hours), limit: 100 })
      .then(setData)
      .catch((err: unknown) => setError(err instanceof Error ? err.message : "Failed to load interventions"))
      .finally(() => setLoading(false));
  }, [agentId, hours]);

  useEffect(() => { load(); }, [load]);

  const rows = data?.interventions ?? [];

  return (
    <Card className="gap-0 py-0">
      <CardHeader className="flex-row items-center gap-2.5 border-b py-3.5 px-[18px] [.border-b]:pb-3.5">
        <CardTitle className="text-[13.5px] font-semibold">Guardrail interventions</CardTitle>
        {data?.supported && <span className="rounded-md border px-1.5 py-0 font-mono text-[11px]">{rows.length}</span>}
        <div className="ml-auto flex items-center gap-2">
          <Select value={hours} onValueChange={setHours}>
            <SelectTrigger size="sm" className="h-7 w-36 text-xs">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {HOUR_OPTIONS.map((o) => <SelectItem key={o.value} value={o.value}>{o.label}</SelectItem>)}
            </SelectContent>
          </Select>
          <button type="button" onClick={load} disabled={loading} className="text-muted-foreground hover:text-foreground disabled:opacity-50" title="Refresh">
            <RefreshCw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} />
          </button>
        </div>
      </CardHeader>
      <CardContent className="px-[18px] py-3">
        {error ? (
          <p className="text-[12.5px] text-destructive">{error}</p>
        ) : data && !data.supported ? (
          <p className="text-[12.5px] text-muted-foreground">{data.note ?? "Intervention history isn't available for this agent."}</p>
        ) : loading && !data ? (
          <p className="text-[12.5px] text-muted-foreground">Loading…</p>
        ) : rows.length === 0 ? (
          <p className="text-[12.5px] text-muted-foreground">No guardrail interventions in this period.</p>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="text-xs">Time</TableHead>
                <TableHead className="text-xs">Session</TableHead>
                <TableHead className="text-xs">Source</TableHead>
                <TableHead className="text-xs">Action</TableHead>
                <TableHead className="text-xs">Mode</TableHead>
                <TableHead className="text-xs">Policies</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((r, i) => (
                <TableRow key={`${r.timestamp}-${i}`}>
                  <TableCell className="whitespace-nowrap font-mono text-[11.5px]" title={formatTimestamp(r.timestamp, timezone)}>
                    {formatRelativeDateTime(r.timestamp, timezone)}
                  </TableCell>
                  <TableCell className="font-mono text-[11.5px]">
                    {r.session_id ? (
                      onOpenSession ? (
                        <button type="button" onClick={() => onOpenSession(r.session_id)} className="text-primary hover:underline" title={r.session_id}>
                          {r.session_id.slice(0, 12)}…
                        </button>
                      ) : (
                        <span title={r.session_id}>{r.session_id.slice(0, 12)}…</span>
                      )
                    ) : "—"}
                  </TableCell>
                  <TableCell className="font-mono text-[11.5px] lowercase">{r.source}</TableCell>
                  <TableCell>
                    <StatusPill label={r.action} variant={r.action === "detected" ? "warning" : "destructive"} />
                  </TableCell>
                  <TableCell className="font-mono text-[11.5px]" title={`${r.guardrail_id} · ${r.guardrail_version}`}>{r.mode}</TableCell>
                  <TableCell className="whitespace-normal"><GuardrailPolicyChips event={r} /></TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </CardContent>
    </Card>
  );
}
