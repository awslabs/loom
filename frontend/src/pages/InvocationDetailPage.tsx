import { useState } from "react";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { StatusPill } from "@/components/StatusPill";
import { MarkdownBlock } from "@/components/MarkdownRenderer";
import { toast } from "sonner";
import { useTimezone } from "@/contexts/TimezoneContext";
import { formatTimestamp } from "@/lib/format";
import type { BadgeVariant } from "@/lib/status";
import type { AgentResponse, SessionResponse, InvocationResponse } from "@/api/types";

interface InvocationDetailPageProps {
  agent: AgentResponse;
  session: SessionResponse;
  invocation: InvocationResponse;
  onOpenLogs?: () => void;
  onRerunPrompt?: () => void;
}

function statusVariant(status: string): BadgeVariant {
  switch (status) {
    case "complete": return "success";
    case "streaming":
    case "pending": return "warning";
    case "error": return "destructive";
    default: return "neutral";
  }
}

function formatSeconds(ms: number | null | undefined): string {
  if (ms == null) return "—";
  return `${(ms / 1000).toFixed(2)} s`;
}

function formatCost(cost: number | null | undefined): string {
  if (cost == null || cost === 0) return "—";
  if (cost < 0.01) return `$${cost.toFixed(6)}`;
  return `$${cost.toFixed(4)}`;
}

function RailCard({ title, meta, children }: { title: string; meta?: React.ReactNode; children: React.ReactNode }) {
  return (
    <Card className="gap-3 py-4">
      <CardContent className="flex flex-col gap-3">
        <div className="flex items-center gap-2">
          <span className="text-[13px] font-semibold">{title}</span>
          {meta}
        </div>
        {children}
      </CardContent>
    </Card>
  );
}

export function InvocationDetailPage({ agent, session, invocation, onOpenLogs, onRerunPrompt }: InvocationDetailPageProps) {
  const { timezone } = useTimezone();
  const [responseRaw, setResponseRaw] = useState(false);

  const rtCpu = invocation.compute_cpu_cost ?? 0;
  const rtMem = (invocation.compute_memory_cost ?? 0) + (invocation.idle_memory_cost ?? 0);
  const rtTotal = rtCpu + rtMem;
  const stm = invocation.stm_cost ?? 0;
  const ltm = invocation.ltm_cost ?? 0;
  const memTotal = stm + ltm;
  const modelCost = invocation.estimated_cost ?? 0;
  const grandTotal = modelCost + rtTotal + memTotal;

  const durationMs = invocation.client_duration_ms;
  const coldStartMs = invocation.cold_start_latency_ms;
  const generationMs = durationMs != null ? Math.max(0, durationMs - (coldStartMs ?? 0)) : null;
  const coldStartPct = durationMs && coldStartMs ? (coldStartMs / durationMs) * 100 : 0;
  const generationPct = durationMs && generationMs != null ? (generationMs / durationMs) * 100 : 0;

  const handleCopyId = () => {
    navigator.clipboard.writeText(invocation.invocation_id);
    toast.success("Copied invocation id");
  };

  const handleCopyRequestJson = () => {
    const payload = {
      invocation_id: invocation.invocation_id,
      request_id: invocation.request_id,
      session_id: session.session_id,
      qualifier: session.qualifier,
      prompt: invocation.prompt_text,
      created_at: invocation.created_at,
    };
    navigator.clipboard.writeText(JSON.stringify(payload, null, 2));
    toast.success("Copied request JSON");
  };

  const handleCopyText = (text: string | null, label: string) => {
    if (!text) return;
    navigator.clipboard.writeText(text);
    toast.success(`Copied ${label}`);
  };

  const metrics: [string, string][] = [
    ["Request ID", invocation.request_id ? invocation.request_id.slice(0, 13) : "—"],
    ["Duration", formatSeconds(durationMs)],
    ["Cold start", formatSeconds(coldStartMs)],
    ["Tokens", invocation.input_tokens != null || invocation.output_tokens != null ? `${invocation.input_tokens ?? 0} in · ${invocation.output_tokens ?? 0} out` : "—"],
    ["Model", agent.model_id ?? "—"],
    ["Created", formatTimestamp(invocation.created_at, timezone)],
  ];

  return (
    <div className="flex flex-col gap-4">
      {/* header */}
      <div className="flex flex-col gap-4 rounded-t-xl border bg-card px-6 pt-5 pb-4">
        <div className="flex flex-wrap items-center gap-2.5">
          <h1 className="truncate font-mono text-xl font-semibold tracking-tight">{invocation.invocation_id}</h1>
          <button type="button" onClick={handleCopyId} className="rounded-md border bg-muted px-1.5 py-0.5 font-mono text-[10.5px] text-muted-foreground hover:text-foreground">
            copy
          </button>
          <StatusPill label={invocation.status} variant={statusVariant(invocation.status)} />
          <div className="ml-auto flex items-center gap-2">
            {onOpenLogs && <Button variant="outline" size="sm" onClick={onOpenLogs}>Open logs</Button>}
            <Button variant="outline" size="sm" className="font-mono" onClick={handleCopyRequestJson}>Copy request JSON</Button>
            {onRerunPrompt && invocation.prompt_text && <Button size="sm" onClick={onRerunPrompt}>Rerun prompt</Button>}
          </div>
        </div>

        <div className="grid grid-cols-2 overflow-hidden rounded-[10px] border bg-muted sm:grid-cols-3 lg:grid-cols-6">
          {metrics.map(([label, value], i) => (
            <div key={label} className={`flex flex-col gap-1 px-3.5 py-2.5 ${i < metrics.length - 1 ? "border-r" : ""}`}>
              <span className="font-mono text-[9.5px] tracking-wide text-muted-foreground uppercase">{label}</span>
              <span className="truncate font-mono text-[12.5px] tabular-nums">{value}</span>
            </div>
          ))}
        </div>
      </div>

      {/* body: document + receipt rail */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[1fr_320px]">
        <div className="flex min-w-0 flex-col gap-4">
          {/* prompt */}
          <Card className="gap-0 py-0">
            <div className="flex items-center gap-2.5 border-b px-[18px] py-3.5">
              <span className="text-[13.5px] font-semibold">Prompt</span>
              {invocation.input_tokens != null && (
                <span className="rounded-[5px] border bg-muted px-1.5 py-0.5 font-mono text-[10px] tracking-wide text-muted-foreground">{invocation.input_tokens} TOKENS</span>
              )}
              {invocation.prompt_text && (
                <button type="button" onClick={() => handleCopyText(invocation.prompt_text, "prompt")} className="ml-auto font-mono text-[10.5px] text-muted-foreground hover:text-foreground">copy</button>
              )}
            </div>
            <CardContent className="px-[18px] py-4">
              {invocation.prompt_text ? (
                <div className="rounded-r-md border-l-2 border-primary bg-muted px-4 py-3.5 text-[14.5px] leading-[1.6] whitespace-pre-wrap">
                  {invocation.prompt_text}
                </div>
              ) : (
                <p className="text-sm text-muted-foreground italic">Not captured</p>
              )}
            </CardContent>
          </Card>

          {/* thinking */}
          {invocation.thinking_text != null && (
            <Card className="gap-0 py-0">
              <div className="flex items-center gap-2.5 border-b px-[18px] py-3.5">
                <span className="text-[13.5px] font-semibold">Thinking</span>
                <button type="button" onClick={() => handleCopyText(invocation.thinking_text, "thinking")} className="ml-auto font-mono text-[10.5px] text-muted-foreground hover:text-foreground">copy</button>
              </div>
              <CardContent className="px-[18px] py-4">
                <pre className="overflow-x-auto rounded-md border bg-muted p-3.5 font-mono text-xs leading-[1.6] whitespace-pre-wrap">{invocation.thinking_text}</pre>
              </CardContent>
            </Card>
          )}

          {/* response */}
          <Card className="gap-0 py-0">
            <div className="flex items-center gap-2.5 border-b px-[18px] py-3.5">
              <span className="text-[13.5px] font-semibold">Response</span>
              {(invocation.output_tokens != null || durationMs != null) && (
                <span className="rounded-[5px] border bg-muted px-1.5 py-0.5 font-mono text-[10px] tracking-wide text-muted-foreground">
                  {invocation.output_tokens != null ? `${invocation.output_tokens} TOKENS` : ""}
                  {invocation.output_tokens != null && generationMs != null ? " · " : ""}
                  {generationMs != null ? `${(generationMs / 1000).toFixed(1)} S` : ""}
                </span>
              )}
              <div className="ml-auto flex items-center gap-2.5">
                {invocation.response_text && (
                  <div className="flex items-center gap-0.5 rounded-md border bg-muted p-[3px]">
                    <button type="button" onClick={() => setResponseRaw(false)} className={`rounded-[4px] px-2 py-0.5 font-mono text-[10.5px] ${!responseRaw ? "bg-card" : "text-muted-foreground"}`}>rendered</button>
                    <button type="button" onClick={() => setResponseRaw(true)} className={`rounded-[4px] px-2 py-0.5 font-mono text-[10.5px] ${responseRaw ? "bg-card" : "text-muted-foreground"}`}>raw</button>
                  </div>
                )}
                {invocation.response_text && (
                  <button type="button" onClick={() => handleCopyText(invocation.response_text, "response")} className="font-mono text-[10.5px] text-muted-foreground hover:text-foreground">copy</button>
                )}
              </div>
            </div>
            <CardContent className="max-w-[820px] px-[18px] py-4">
              {invocation.response_text ? (
                responseRaw ? (
                  <pre className="overflow-x-auto rounded-md border bg-muted p-3.5 font-mono text-xs leading-[1.6] whitespace-pre-wrap">{invocation.response_text}</pre>
                ) : (
                  <MarkdownBlock text={invocation.response_text} className="text-sm leading-[1.65]" />
                )
              ) : (
                <p className="text-sm text-muted-foreground italic">Not captured</p>
              )}
            </CardContent>
          </Card>
        </div>

        {/* receipt rail */}
        <div className="flex flex-col gap-3.5">
          <RailCard title="Cost" meta={<span className="rounded-[4px] border bg-muted px-1.5 py-0.5 font-mono text-[9.5px] tracking-wide text-muted-foreground">{invocation.cost_source === "usage_logs" ? "ACTUAL" : "ESTIMATED"}</span>}>
            <div className="flex items-baseline gap-1.5">
              <span className="font-mono text-2xl font-semibold tracking-tight tabular-nums">{formatCost(grandTotal)}</span>
              <span className="text-[11.5px] text-muted-foreground">total</span>
            </div>
            {grandTotal > 0 && (
              <div className="flex h-[5px] overflow-hidden rounded-[3px] bg-input-bg">
                <div className="bg-chart-1" style={{ width: `${(modelCost / grandTotal) * 100}%` }} />
                <div className="bg-chart-2" style={{ width: `${(rtTotal / grandTotal) * 100}%` }} />
                <div className="bg-chart-3" style={{ width: `${(memTotal / grandTotal) * 100}%` }} />
              </div>
            )}
            <div className="flex flex-col gap-2.5">
              <div className="flex items-center gap-2">
                <span className="h-1.5 w-1.5 shrink-0 rounded-[2px] bg-chart-1" />
                <span className="font-mono text-[9.5px] tracking-wide text-muted-foreground uppercase">Model</span>
                <span className="ml-auto font-mono text-[11.5px] tabular-nums">{formatCost(modelCost)}</span>
              </div>
              <div className="flex items-center gap-2 pl-[14px] text-[12px] text-muted-foreground">
                <span>Tokens ({invocation.input_tokens ?? 0} in + {invocation.output_tokens ?? 0} out)</span>
                <span className="ml-auto font-mono text-[11px] tabular-nums">{formatCost(modelCost)}</span>
              </div>

              <div className="h-px bg-border" />

              <div className="flex items-center gap-2">
                <span className="h-1.5 w-1.5 shrink-0 rounded-[2px] bg-chart-2" />
                <span className="font-mono text-[9.5px] tracking-wide text-muted-foreground uppercase">Runtime</span>
                <span className="ml-auto font-mono text-[11.5px] tabular-nums">{formatCost(rtTotal)}</span>
              </div>
              <div className="flex items-center gap-2 pl-[14px] text-[12px] text-muted-foreground">
                <span>CPU (active invocation)</span>
                <span className="ml-auto font-mono text-[11px] tabular-nums">{rtCpu > 0 ? formatCost(rtCpu) : "not used"}</span>
              </div>
              <div className="flex items-center gap-2 pl-[14px] text-[12px] text-muted-foreground">
                <span>Memory (RAM + idle)</span>
                <span className="ml-auto font-mono text-[11px] tabular-nums">{rtMem > 0 ? formatCost(rtMem) : "not used"}</span>
              </div>

              <div className="h-px bg-border" />

              <div className="flex items-center gap-2">
                <span className="h-1.5 w-1.5 shrink-0 rounded-[2px] bg-chart-3" />
                <span className="font-mono text-[9.5px] tracking-wide text-muted-foreground uppercase">Memory store</span>
                <span className="ml-auto font-mono text-[11.5px] tabular-nums">{formatCost(memTotal)}</span>
              </div>
              <div className="flex items-center gap-2 pl-[14px] text-[12px] text-muted-foreground">
                <span>Create events (STM)</span>
                <span className="ml-auto font-mono text-[11px] tabular-nums">{stm > 0 ? formatCost(stm) : "not used"}</span>
              </div>
              <div className="flex items-center gap-2 pl-[14px] text-[12px] text-muted-foreground">
                <span>Retrieve records (LTM)</span>
                <span className="ml-auto font-mono text-[11px] tabular-nums">{ltm > 0 ? formatCost(ltm) : "not used"}</span>
              </div>
            </div>
          </RailCard>

          {durationMs != null && (
            <RailCard title="Timing" meta={<span className="ml-auto font-mono text-[11px] tabular-nums text-muted-foreground">{formatSeconds(durationMs)}</span>}>
              <div className="flex h-[6px] overflow-hidden rounded-[3px] bg-input-bg">
                {coldStartMs != null && <div className="bg-warning" style={{ width: `${coldStartPct}%` }} />}
                {generationMs != null && <div className="bg-primary" style={{ width: `${generationPct}%` }} />}
              </div>
              <div className="flex flex-col gap-2">
                {coldStartMs != null && (
                  <div className="flex items-center gap-2">
                    <span className="h-1.5 w-1.5 shrink-0 rounded-[2px] bg-warning" />
                    <span className="text-[12px]">Cold start</span>
                    <span className="ml-auto font-mono text-[11.5px] tabular-nums">{formatSeconds(coldStartMs)}</span>
                  </div>
                )}
                {generationMs != null && (
                  <div className="flex items-center gap-2">
                    <span className="h-1.5 w-1.5 shrink-0 rounded-[2px] bg-primary" />
                    <span className="text-[12px]">Model generation</span>
                    <span className="ml-auto font-mono text-[11.5px] tabular-nums">{formatSeconds(generationMs)}</span>
                  </div>
                )}
              </div>
              {coldStartPct >= 10 && (
                <p className="text-[11.5px] leading-[1.5] text-muted-foreground">
                  Cold start is {Math.round(coldStartPct)}% of wall time.
                </p>
              )}
            </RailCard>
          )}

          <RailCard title="Context">
            <div className="flex flex-col gap-2.5">
              <div className="flex items-center justify-between gap-2.5">
                <span className="font-mono text-[9.5px] tracking-wide text-muted-foreground uppercase">Session</span>
                <span className="truncate font-mono text-[11.5px]">{session.session_id.slice(0, 13)}</span>
              </div>
              {session.user_id && (
                <div className="flex items-center justify-between gap-2.5">
                  <span className="font-mono text-[9.5px] tracking-wide text-muted-foreground uppercase">Invoked by</span>
                  <span className="truncate font-mono text-[11.5px]">{session.user_id}</span>
                </div>
              )}
              <div className="flex items-center justify-between gap-2.5">
                <span className="font-mono text-[9.5px] tracking-wide text-muted-foreground uppercase">Qualifier</span>
                <span className="font-mono text-[11.5px]">{session.qualifier}</span>
              </div>
              {onOpenLogs && (
                <div className="flex items-center justify-between gap-2.5">
                  <span className="font-mono text-[9.5px] tracking-wide text-muted-foreground uppercase">Logs</span>
                  <button type="button" onClick={onOpenLogs} className="font-mono text-[11.5px] text-primary hover:underline">open →</button>
                </div>
              )}
            </div>
          </RailCard>
        </div>
      </div>
    </div>
  );
}
