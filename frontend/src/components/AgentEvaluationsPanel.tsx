import { Fragment, useCallback, useEffect, useRef, useState } from "react";
import { ChevronDown, ChevronRight, FlaskConical, Radio, RefreshCw } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { StatusPill } from "@/components/StatusPill";
import { useTimezone } from "@/contexts/TimezoneContext";
import { formatTimestamp } from "@/lib/format";
import type { BadgeVariant } from "@/lib/status";
import {
  getAgentEvaluations,
  getEvaluatedExchange,
  getEvaluationResults,
  type EvaluationSourceType,
} from "@/api/evaluations";
import type {
  EvaluatedExchangeResponse,
  EvaluatedTrace,
  EvaluationOverviewResponse,
  EvaluationScore,
} from "@/api/types";

/** Read-only view of the AgentCore Evaluations results for one agent.
 *
 * Two kinds of source score an agent: online evaluation configs sample live
 * sessions, and batch evaluation runs score a chosen set of sessions (test
 * cases). Pick a source to see each evaluated session, its scores, the judge's
 * explanation, and what the user asked and the agent answered.
 */

interface SelectedSource {
  type: EvaluationSourceType;
  id: string;
}

function evaluatorName(id: string | null): string {
  return (id ?? "—").replace(/^Builtin\./, "");
}

/** Built-in evaluators score from 0 to 1. Custom numerical evaluators can use
 * any scale (for example 1 to 5), so only 0-1 scores get a quality colour. */
function scoreVariant(value: number | null): BadgeVariant {
  if (value === null || value < 0 || value > 1) return "neutral";
  if (value >= 0.8) return "success";
  if (value >= 0.5) return "warning";
  return "destructive";
}

function executionVariant(status: string | null): BadgeVariant {
  if (status === "ENABLED" || status === "COMPLETED") return "success";
  if (status === "FAILED" || status === "STOPPED") return "destructive";
  if (status === "DISABLED") return "neutral";
  return "warning";
}

function ScoreChip({ score }: { score: EvaluationScore }) {
  const shown = score.value === null ? (score.label ?? "—") : score.value.toFixed(2);
  return (
    <StatusPill
      label={`${evaluatorName(score.evaluator)} ${shown}`}
      variant={scoreVariant(score.value)}
    />
  );
}

function ExchangeDetail({ agentId, trace }: { agentId: number; trace: EvaluatedTrace }) {
  const [exchange, setExchange] = useState<EvaluatedExchangeResponse | null>(
    trace.trace_id ? null : { prompt: null, answer: null },
  );
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!trace.trace_id) return;
    let cancelled = false;
    getEvaluatedExchange(agentId, trace.trace_id)
      .then((data) => { if (!cancelled) setExchange(data); })
      .catch((e) => { if (!cancelled) setError(e instanceof Error ? e.message : "Failed to load the exchange"); });
    return () => { cancelled = true; };
  }, [agentId, trace.trace_id]);

  return (
    <div className="flex flex-col gap-3 py-2">
      <div className="grid gap-3 md:grid-cols-2">
        <div className="flex flex-col gap-1">
          <span className="font-mono text-[9.5px] tracking-wide text-muted-foreground uppercase">User asked</span>
          {error ? (
            <span className="text-xs text-destructive">{error}</span>
          ) : exchange === null ? (
            <Skeleton className="h-10" />
          ) : (
            <p className="text-xs whitespace-pre-wrap">{exchange.prompt ?? <span className="italic text-muted-foreground">Not found in the runtime logs.</span>}</p>
          )}
        </div>
        <div className="flex flex-col gap-1">
          <span className="font-mono text-[9.5px] tracking-wide text-muted-foreground uppercase">Agent answered</span>
          {exchange === null && !error ? (
            <Skeleton className="h-10" />
          ) : (
            <p className="max-h-40 overflow-y-auto text-xs whitespace-pre-wrap">{exchange?.answer ?? <span className="italic text-muted-foreground">Not found in the runtime logs.</span>}</p>
          )}
        </div>
      </div>
      {trace.scores.map((score, i) => (
        <div key={`${score.evaluator}-${i}`} className="flex flex-col gap-1 border-t pt-2">
          <div className="flex items-center gap-2">
            <ScoreChip score={score} />
            {score.label && <span className="text-xs text-muted-foreground">{score.label}</span>}
          </div>
          {score.explanation && (
            <p className="max-h-32 overflow-y-auto text-xs whitespace-pre-wrap text-muted-foreground">{score.explanation}</p>
          )}
        </div>
      ))}
    </div>
  );
}

function ResultsTable({ agentId, source }: { agentId: number; source: SelectedSource }) {
  const { timezone } = useTimezone();
  const [days, setDays] = useState(7);
  const [results, setResults] = useState<EvaluatedTrace[] | null>(null);
  const [truncated, setTruncated] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setResults(null);
    setError(null);
    setExpanded(null);
    getEvaluationResults(agentId, source.type, source.id, days)
      .then((r) => { if (!cancelled) { setResults(r.results); setTruncated(r.truncated); } })
      .catch((e) => { if (!cancelled) setError(e instanceof Error ? e.message : "Failed to load results"); });
    return () => { cancelled = true; };
  }, [agentId, source.type, source.id, days]);

  return (
    <Card className="gap-3 py-4">
      <CardHeader className="flex flex-row items-center justify-between gap-2">
        <CardTitle className="text-sm font-medium">
          {source.type === "batch" ? "Evaluated test cases" : "Evaluated sessions"}
        </CardTitle>
        {source.type === "online" && (
          <div className="flex items-center gap-1" role="group" aria-label="Look-back window">
            {[7, 30].map((d) => (
              <Button key={d} size="sm" variant={days === d ? "secondary" : "ghost"} className="h-6 text-xs" onClick={() => setDays(d)}>
                Last {d} days
              </Button>
            ))}
          </div>
        )}
      </CardHeader>
      <CardContent>
        {error && <p className="text-sm text-destructive">{error}</p>}
        {!error && results === null && <Skeleton className="h-24" />}
        {!error && results !== null && results.length === 0 && (
          <p className="py-6 text-center text-sm text-muted-foreground">
            {source.type === "online" ? `No sessions were evaluated in the last ${days} days.` : "This run produced no results."}
          </p>
        )}
        {!error && results !== null && results.length > 0 && (
          <div className="rounded-md border overflow-hidden">
            <Table>
              <TableHeader>
                <TableRow className="bg-card hover:bg-card">
                  <TableHead className="w-8" />
                  <TableHead className="w-44">Evaluated</TableHead>
                  <TableHead className="w-64">Session</TableHead>
                  <TableHead>Scores</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {results.map((trace) => {
                  const key = `${trace.session_id}-${trace.trace_id}`;
                  const open = expanded === key;
                  return (
                    <Fragment key={key}>
                      <TableRow
                        className="cursor-pointer bg-input-bg hover:bg-input-bg/80 focus-visible:outline-2 focus-visible:outline-primary"
                        onClick={() => setExpanded(open ? null : key)}
                        onKeyDown={(e) => {
                          if (e.key === "Enter" || e.key === " ") { e.preventDefault(); setExpanded(open ? null : key); }
                        }}
                        tabIndex={0}
                        aria-expanded={open}
                        aria-label={`${open ? "Collapse" : "Expand"} evaluation of session ${trace.session_id ?? "unknown"}`}
                      >
                        <TableCell>{open ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}</TableCell>
                        <TableCell className="text-xs text-muted-foreground">{formatTimestamp(trace.evaluated_at, timezone)}</TableCell>
                        <TableCell className="truncate font-mono text-xs" title={trace.session_id ?? ""}>{trace.session_id ?? "—"}</TableCell>
                        <TableCell>
                          <div className="flex flex-wrap gap-1">
                            {trace.scores.map((s, i) => <ScoreChip key={`${s.evaluator}-${i}`} score={s} />)}
                          </div>
                        </TableCell>
                      </TableRow>
                      {open && (
                        <TableRow className="hover:bg-transparent">
                          <TableCell />
                          <TableCell colSpan={3}><ExchangeDetail agentId={agentId} trace={trace} /></TableCell>
                        </TableRow>
                      )}
                    </Fragment>
                  );
                })}
              </TableBody>
            </Table>
          </div>
        )}
        {truncated && (
          <p className="pt-2 text-[11px] text-muted-foreground">Showing the first 1,000 result records.</p>
        )}
      </CardContent>
    </Card>
  );
}

export function AgentEvaluationsPanel({ agentId }: { agentId: number }) {
  const { timezone } = useTimezone();
  const [overview, setOverview] = useState<EvaluationOverviewResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState<SelectedSource | null>(null);
  const requestRef = useRef(0);

  const load = useCallback(async () => {
    const request = ++requestRef.current;
    setLoading(true);
    setError(null);
    try {
      const data = await getAgentEvaluations(agentId);
      if (request !== requestRef.current) return; // a newer load superseded this one
      setOverview(data);
      setSelected((current) => {
        const stillThere = current !== null && (
          current.type === "online"
            ? data.online.some((c) => c.id === current.id)
            : data.batch.some((b) => b.id === current.id)
        );
        if (stillThere) return current;
        if (data.online[0]) return { type: "online", id: data.online[0].id };
        if (data.batch[0]) return { type: "batch", id: data.batch[0].id };
        return null;
      });
    } catch (e) {
      if (request === requestRef.current) setError(e instanceof Error ? e.message : "Failed to load evaluations");
    } finally {
      if (request === requestRef.current) setLoading(false);
    }
  }, [agentId]);

  useEffect(() => {
    // A different agent: forget the previous agent's sources and selection.
    setOverview(null);
    setSelected(null);
    void load();
  }, [load]);

  const empty = overview !== null && overview.online.length === 0 && overview.batch.length === 0;

  return (
    <div className="flex flex-col gap-4 pt-4">
      <div className="flex items-start justify-between gap-2">
        <div>
          <h2 className="text-base font-semibold">Evaluations</h2>
          <p className="text-[13px] text-muted-foreground">
            Quality scores from AgentCore Evaluations, for live traffic and for test runs.
          </p>
        </div>
        <Button variant="outline" size="sm" onClick={() => void load()} className="gap-1.5">
          <RefreshCw className={`h-3 w-3 ${loading ? "animate-spin" : ""}`} /> Refresh
        </Button>
      </div>

      {error && <p className="text-sm text-destructive">{error}</p>}
      {loading && overview === null && <Skeleton className="h-28" />}

      {empty && (
        <Card>
          <CardContent className="py-10 text-center">
            <p className="text-sm font-medium">Not evaluated</p>
            <p className="mx-auto mt-1 max-w-md text-xs text-muted-foreground">
              No AgentCore online evaluation or batch evaluation reads this agent's traces yet.
              Create one in the AgentCore console to start scoring its sessions.
            </p>
          </CardContent>
        </Card>
      )}

      {overview !== null && !empty && (
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          {overview.online.map((c) => (
            <button
              key={`online-${c.id}`}
              type="button"
              onClick={() => setSelected({ type: "online", id: c.id })}
              aria-pressed={selected?.type === "online" && selected.id === c.id}
              className={`rounded-lg border bg-card p-4 text-left transition-colors hover:bg-accent/50 ${selected?.type === "online" && selected.id === c.id ? "border-primary" : ""}`}
            >
              <div className="flex items-center justify-between gap-2">
                <span className="flex min-w-0 items-center gap-1.5">
                  <Radio className="h-3.5 w-3.5 shrink-0 text-muted-foreground" aria-hidden />
                  <span className="truncate font-mono text-sm font-medium">{c.name ?? c.id}</span>
                </span>
                <StatusPill label={c.execution_status ?? c.status ?? "UNKNOWN"} variant={executionVariant(c.execution_status)} />
              </div>
              <p className="mt-2 text-xs text-muted-foreground">
                Live traffic{c.sampling_percentage !== null ? ` · ${c.sampling_percentage}% of sessions sampled` : ""}
                {c.shared ? " · shared with other agents, showing this agent only" : ""}
              </p>
              <p className="mt-1 text-xs">
                Last evaluated: <span className="font-medium">{formatTimestamp(c.last_evaluated_at, timezone)}</span>
              </p>
              <p className="mt-1 truncate text-[11px] text-muted-foreground">{c.evaluators.map(evaluatorName).join(" · ")}</p>
            </button>
          ))}
          {overview.batch.map((b) => (
            <button
              key={`batch-${b.id}`}
              type="button"
              onClick={() => setSelected({ type: "batch", id: b.id })}
              aria-pressed={selected?.type === "batch" && selected.id === b.id}
              className={`rounded-lg border bg-card p-4 text-left transition-colors hover:bg-accent/50 ${selected?.type === "batch" && selected.id === b.id ? "border-primary" : ""}`}
            >
              <div className="flex items-center justify-between gap-2">
                <span className="flex min-w-0 items-center gap-1.5">
                  <FlaskConical className="h-3.5 w-3.5 shrink-0 text-muted-foreground" aria-hidden />
                  <span className="truncate font-mono text-sm font-medium">{b.name ?? b.id}</span>
                </span>
                <StatusPill label={b.status ?? "UNKNOWN"} variant={executionVariant(b.status)} />
              </div>
              <p className="mt-2 text-xs text-muted-foreground">
                Test run · {b.sessions_completed ?? 0} of {b.sessions_total ?? b.targeted_session_count} test cases scored
              </p>
              <p className="mt-1 text-xs">
                Ran: <span className="font-medium">{formatTimestamp(b.created_at, timezone)}</span>
              </p>
              <div className="mt-2 flex flex-wrap gap-1">
                {b.evaluator_summaries.map((s) => (
                  <StatusPill
                    key={s.evaluator_id ?? ""}
                    label={`${evaluatorName(s.evaluator_id)} avg ${s.average_score === null ? "—" : s.average_score.toFixed(2)}`}
                    variant={scoreVariant(s.average_score)}
                  />
                ))}
              </div>
            </button>
          ))}
        </div>
      )}

      {selected && <ResultsTable agentId={agentId} source={selected} />}
    </div>
  );
}
