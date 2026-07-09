import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { useTimezone } from "@/contexts/TimezoneContext";
import { formatTimestamp, formatMs } from "@/lib/format";
import type { AgentResponse, SessionResponse, InvocationResponse } from "@/api/types";
import ReactMarkdown from "react-markdown";
import { CollapsibleJsonBlock } from "@/components/CollapsibleJsonBlock";
import remarkGfm from "remark-gfm";

interface InvocationDetailPageProps {
  agent: AgentResponse;
  session: SessionResponse;
  invocation: InvocationResponse;
}

function statusVariant(status: string): "default" | "secondary" | "destructive" | "outline" {
  switch (status) {
    case "complete":
      return "default";
    case "streaming":
    case "pending":
      return "secondary";
    case "error":
      return "destructive";
    default:
      return "outline";
  }
}

function formatCost(cost: number | null | undefined): string {
  if (cost == null) return "—";
  if (cost === 0) return "~$0.00";
  if (cost < 0.01) return `~$${cost.toFixed(6)}`;
  if (cost < 1) return `~$${cost.toFixed(4)}`;
  return `~$${cost.toFixed(2)}`;
}

function CostRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-baseline py-1 gap-1.5">
      <span className="text-xs text-muted-foreground shrink-0">{label}</span>
      <span className="flex-1 overflow-hidden text-muted-foreground/30 text-xs leading-none tracking-[0.15em] select-none" aria-hidden="true">
        {"." .repeat(200)}
      </span>
      <span className="font-mono text-sm shrink-0">{value}</span>
    </div>
  );
}

export function InvocationDetailPage({ invocation }: InvocationDetailPageProps) {
  const { timezone } = useTimezone();

  const rtCpu = invocation.compute_cpu_cost ?? 0;
  const rtMem = (invocation.compute_memory_cost ?? 0) + (invocation.idle_memory_cost ?? 0);
  const rtTotal = rtCpu + rtMem;
  const memTotal = (invocation.stm_cost ?? 0) + (invocation.ltm_cost ?? 0);
  const modelCost = invocation.estimated_cost ?? 0;
  const grandTotal = modelCost + rtTotal + memTotal;

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6 items-start">
        <div className="space-y-6">
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-medium">Invocation Details</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="flex gap-6 text-sm flex-wrap">
                <div>
                  <div className="text-xs text-muted-foreground">Request ID</div>
                  <div className="font-mono text-sm mt-0.5 break-all">{invocation.request_id ?? "—"}</div>
                </div>
                <div>
                  <div className="text-xs text-muted-foreground">Status</div>
                  <Badge className="mt-0.5" variant={statusVariant(invocation.status)}>
                    {invocation.status}
                  </Badge>
                </div>
                <div>
                  <div className="text-xs text-muted-foreground">Cold Start</div>
                  <div className="font-mono text-sm mt-0.5">{formatMs(invocation.cold_start_latency_ms)}</div>
                </div>
                <div>
                  <div className="text-xs text-muted-foreground">Duration</div>
                  <div className="font-mono text-sm mt-0.5">{formatMs(invocation.client_duration_ms)}</div>
                </div>
                <div>
                  <div className="text-xs text-muted-foreground">Created</div>
                  <div className="text-sm mt-0.5">{formatTimestamp(invocation.created_at, timezone)}</div>
                </div>
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-medium">Prompt</CardTitle>
            </CardHeader>
            <CardContent>
              {invocation.prompt_text ? (
                <div className="rounded border bg-input-bg p-4 text-sm">
                  <ReactMarkdown
                    remarkPlugins={[remarkGfm]}
                    components={{
                      p: ({ children }) => <p className="mb-2 last:mb-0">{children}</p>,
                      h1: ({ children }) => <h1 className="text-base font-bold mb-2 mt-3 first:mt-0">{children}</h1>,
                      h2: ({ children }) => <h2 className="text-sm font-bold mb-2 mt-3 first:mt-0">{children}</h2>,
                      h3: ({ children }) => <h3 className="text-sm font-semibold mb-1 mt-2 first:mt-0">{children}</h3>,
                      ul: ({ children }) => <ul className="list-disc pl-4 mb-2 space-y-0.5">{children}</ul>,
                      ol: ({ children }) => <ol className="list-decimal pl-4 mb-2 space-y-0.5">{children}</ol>,
                      li: ({ children }) => <li className="leading-snug">{children}</li>,
                      pre: ({ children }) => {
                        const codeClass = (children as { props?: { className?: string } } | null)?.props?.className ?? '';
                        if (codeClass.includes('language-json')) {
                          return <CollapsibleJsonBlock>{children}</CollapsibleJsonBlock>;
                        }
                        return (
                          <pre className="mb-2 overflow-x-auto rounded bg-black/10 dark:bg-white/10 p-3 text-xs font-mono">{children}</pre>
                        );
                      },
                      code: ({ className, children }) =>
                        className?.startsWith("language-") ? (
                          <code className={className}>{children}</code>
                        ) : (
                          <code className="rounded bg-black/10 dark:bg-white/10 px-1 py-0.5 text-xs font-mono">{children}</code>
                        ),
                      blockquote: ({ children }) => (
                        <blockquote className="border-l-2 border-muted-foreground/30 pl-3 italic text-muted-foreground mb-2">{children}</blockquote>
                      ),
                      table: ({ children }) => (
                        <div className="overflow-x-auto mb-2">
                          <table className="border-collapse text-xs w-full">{children}</table>
                        </div>
                      ),
                      thead: ({ children }) => <thead>{children}</thead>,
                      tbody: ({ children }) => <tbody>{children}</tbody>,
                      tr: ({ children }) => <tr>{children}</tr>,
                      th: ({ children }) => (
                        <th className="border border-border px-2 py-1 text-left font-semibold bg-muted/50">{children}</th>
                      ),
                      td: ({ children }) => (
                        <td className="border border-border px-2 py-1">{children}</td>
                      ),
                      strong: ({ children }) => <strong className="font-semibold">{children}</strong>,
                      a: ({ href, children }) => (
                        <a href={href} className="underline underline-offset-2 hover:opacity-80" target="_blank" rel="noopener noreferrer">{children}</a>
                      ),
                    }}
                  >
                    {invocation.prompt_text}
                  </ReactMarkdown>
                </div>
              ) : (
                <pre className="bg-input-bg rounded-md p-4 text-sm font-mono whitespace-pre-wrap overflow-x-auto text-muted-foreground">
                  Not captured
                </pre>
              )}
            </CardContent>
          </Card>
        </div>

        <Card>
          <CardHeader className="pb-2">
            <div className="flex items-center gap-2">
              <CardTitle className="text-sm font-medium">Cost Breakdown</CardTitle>
              {invocation.cost_source && (
                <Badge variant={invocation.cost_source === "usage_logs" ? "default" : "outline"} className="text-[10px] px-1.5 py-0">
                  {invocation.cost_source === "usage_logs" ? "actual" : "estimated"}
                </Badge>
              )}
            </div>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="rounded-md border bg-background p-3 space-y-0.5">
              <div className="text-[10px] text-muted-foreground uppercase tracking-wider pb-1">Model</div>
              <CostRow
                label={invocation.input_tokens != null && invocation.output_tokens != null
                  ? `Token Cost (${invocation.input_tokens.toLocaleString()} in + ${invocation.output_tokens.toLocaleString()} out)`
                  : "Token Cost"}
                value={formatCost(invocation.estimated_cost)}
              />

              <div className="text-[10px] text-muted-foreground uppercase tracking-wider pt-3 pb-1">Runtime</div>
              <CostRow label="CPU (active invocation)" value={formatCost(rtCpu > 0 ? rtCpu : null)} />
              <CostRow label="Memory (RAM + idle timeout)" value={formatCost(rtMem > 0 ? rtMem : null)} />

              <div className="text-[10px] text-muted-foreground uppercase tracking-wider pt-3 pb-1">Memory</div>
              <CostRow label="Create Events (STM)" value={formatCost(invocation.stm_cost || null)} />
              <CostRow label="Retrieve Records (LTM)" value={formatCost(invocation.ltm_cost || null)} />
            </div>

            <div className="rounded-md border bg-background p-3">
              <div className="flex items-baseline gap-1.5">
                <span className="text-xs font-medium shrink-0">Total Estimated Cost</span>
                <span className="flex-1 overflow-hidden text-muted-foreground/30 text-xs leading-none tracking-[0.15em] select-none" aria-hidden="true">
                  {"." .repeat(200)}
                </span>
                <span className="font-mono text-sm font-semibold shrink-0">{formatCost(grandTotal > 0 ? grandTotal : null)}</span>
              </div>
            </div>
          </CardContent>
        </Card>
      </div>

      {invocation.thinking_text != null && (
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium">Thinking</CardTitle>
          </CardHeader>
          <CardContent>
            <pre className="bg-muted rounded-md p-4 text-sm font-mono whitespace-pre-wrap overflow-x-auto">
              {invocation.thinking_text}
            </pre>
          </CardContent>
        </Card>
      )}

      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm font-medium">Response</CardTitle>
        </CardHeader>
        <CardContent>
          {invocation.response_text ? (
            <div className="rounded border bg-input-bg p-4 text-sm">
              <ReactMarkdown
                remarkPlugins={[remarkGfm]}
                components={{
                  p: ({ children }) => <p className="mb-2 last:mb-0">{children}</p>,
                  h1: ({ children }) => <h1 className="text-base font-bold mb-2 mt-3 first:mt-0">{children}</h1>,
                  h2: ({ children }) => <h2 className="text-sm font-bold mb-2 mt-3 first:mt-0">{children}</h2>,
                  h3: ({ children }) => <h3 className="text-sm font-semibold mb-1 mt-2 first:mt-0">{children}</h3>,
                  ul: ({ children }) => <ul className="list-disc pl-4 mb-2 space-y-0.5">{children}</ul>,
                  ol: ({ children }) => <ol className="list-decimal pl-4 mb-2 space-y-0.5">{children}</ol>,
                  li: ({ children }) => <li className="leading-snug">{children}</li>,
                  pre: ({ children }) => (
                    <pre className="mb-2 overflow-x-auto rounded bg-black/10 dark:bg-white/10 p-3 text-xs font-mono">{children}</pre>
                  ),
                  code: ({ className, children }) =>
                    className?.startsWith("language-") ? (
                      <code className={className}>{children}</code>
                    ) : (
                      <code className="rounded bg-black/10 dark:bg-white/10 px-1 py-0.5 text-xs font-mono">{children}</code>
                    ),
                  blockquote: ({ children }) => (
                    <blockquote className="border-l-2 border-muted-foreground/30 pl-3 italic text-muted-foreground mb-2">{children}</blockquote>
                  ),
                  table: ({ children }) => (
                    <div className="overflow-x-auto mb-2">
                      <table className="border-collapse text-xs w-full">{children}</table>
                    </div>
                  ),
                  thead: ({ children }) => <thead>{children}</thead>,
                  tbody: ({ children }) => <tbody>{children}</tbody>,
                  tr: ({ children }) => <tr>{children}</tr>,
                  th: ({ children }) => (
                    <th className="border border-border px-2 py-1 text-left font-semibold bg-muted/50">{children}</th>
                  ),
                  td: ({ children }) => (
                    <td className="border border-border px-2 py-1">{children}</td>
                  ),
                  strong: ({ children }) => <strong className="font-semibold">{children}</strong>,
                  a: ({ href, children }) => (
                    <a href={href} className="underline underline-offset-2 hover:opacity-80" target="_blank" rel="noopener noreferrer">{children}</a>
                  ),
                }}
              >
                {invocation.response_text}
              </ReactMarkdown>
            </div>
          ) : (
            <pre className="bg-input-bg rounded-md p-4 text-sm font-mono whitespace-pre-wrap overflow-x-auto text-muted-foreground">
              Not captured
            </pre>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
