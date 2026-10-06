import { useEffect, useMemo, useState } from "react";
import { RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { getEvaluationResults } from "@/api/evaluations";
import { evaluatorShortName, formatScore } from "@/lib/evaluations";
import type { EvaluatedTrace, OnlineEvaluationSource } from "@/api/types";

/** Progress-bar-per-evaluator view of an online evaluation config's recent
 * scores, with a delta against the equal-length period immediately before —
 * computed client-side by splitting one days-window fetch at its midpoint,
 * since there's no backend endpoint for an arbitrary offset window. 30d is
 * shown without a delta: the results endpoint caps at 30 days, so there's no
 * room left to also fetch the preceding 30-day comparison period. */

interface LiveTrafficScoresProps {
  agentId: number;
  source: OnlineEvaluationSource | null;
  loading: boolean;
}

const PERIODS = [
  { label: "24h", days: 1 },
  { label: "7d", days: 7 },
  { label: "30d", days: 30 },
];

function average(values: number[]): number | null {
  return values.length === 0 ? null : values.reduce((a, b) => a + b, 0) / values.length;
}

export function LiveTrafficScores({ agentId, source, loading }: LiveTrafficScoresProps) {
  const [periodDays, setPeriodDays] = useState(7);
  const [traces, setTraces] = useState<EvaluatedTrace[] | null>(null);
  const [fetchedDays, setFetchedDays] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);

  const load = async () => {
    if (!source) return;
    setRefreshing(true);
    setError(null);
    const fetchDays = Math.min(periodDays * 2, 30);
    try {
      const r = await getEvaluationResults(agentId, "online", source.id, fetchDays);
      setTraces(r.results);
      setFetchedDays(fetchDays);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load scores");
    } finally {
      setRefreshing(false);
    }
  };

  useEffect(() => {
    setTraces(null);
    if (source) void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [agentId, source?.id, periodDays]);

  const rows = useMemo(() => {
    if (!traces || !source) return [];
    const canSplit = fetchedDays >= periodDays * 2;
    const cutoffMs = Date.now() - periodDays * 86_400_000;
    const current: Record<string, number[]> = {};
    const previous: Record<string, number[]> = {};
    for (const trace of traces) {
      const ts = trace.evaluated_at ? new Date(trace.evaluated_at).getTime() : null;
      const bucket = canSplit && ts !== null && ts < cutoffMs ? previous : current;
      for (const score of trace.scores) {
        if (score.value === null) continue;
        const id = score.evaluator ?? "unknown";
        (bucket[id] ??= []).push(score.value);
      }
    }
    return source.evaluators.map((id) => {
      const currentAvg = average(current[id] ?? []);
      const previousAvg = canSplit ? average(previous[id] ?? []) : null;
      const delta = currentAvg !== null && previousAvg !== null ? currentAvg - previousAvg : null;
      return { id, score: currentAvg, delta };
    });
  }, [traces, source, periodDays, fetchedDays]);

  // The NOT CONNECTED explanation lives in the rail's merged card (EvaluationRail)
  // so it isn't shown twice; this card only renders once a source exists.
  if (loading || !source) return null;

  return (
    <Card>
      <CardHeader>
        <div className="flex items-start justify-between gap-2">
          <div>
            <CardTitle className="text-sm font-medium">Live traffic scores</CardTitle>
            <p className="text-[12.5px] text-muted-foreground">
              AgentCore online evaluation
              {source.sampling_percentage !== null && ` · ${source.sampling_percentage}% of sessions sampled`}
            </p>
          </div>
          <div className="flex items-center gap-1.5">
            <div className="flex items-center rounded-md border p-0.5" role="group" aria-label="Period">
              {PERIODS.map((p) => (
                <button
                  key={p.label}
                  type="button"
                  onClick={() => setPeriodDays(p.days)}
                  className={`rounded px-2 py-0.5 text-[11px] ${periodDays === p.days ? "bg-secondary" : "hover:bg-accent"}`}
                >
                  {p.label}
                </button>
              ))}
            </div>
            <Button size="sm" variant="outline" onClick={() => void load()} className="h-7 gap-1.5 text-xs">
              <RefreshCw className={`h-3 w-3 ${refreshing ? "animate-spin" : ""}`} /> Refresh
            </Button>
          </div>
        </div>
      </CardHeader>
      <CardContent className="flex flex-col gap-2.5">
        {error && <p className="text-xs text-destructive">{error}</p>}
        {!error && traces === null && <Skeleton className="h-24" />}
        {!error && traces !== null && rows.length === 0 && (
          <p className="py-4 text-center text-xs text-muted-foreground">No sessions evaluated in this period.</p>
        )}
        {!error && traces !== null && rows.map((row) => (
          <div key={row.id} className="flex items-center gap-3">
            <span className="w-40 shrink-0 truncate text-xs">{evaluatorShortName(row.id)}</span>
            <div className="h-2 flex-1 overflow-hidden rounded-full bg-muted">
              <div
                className={`h-full rounded-full ${row.score !== null && row.score >= 0.8 ? "bg-success" : row.score !== null && row.score >= 0.7 ? "bg-warning" : "bg-destructive"}`}
                style={{ width: `${Math.max(0, Math.min(100, (row.score ?? 0) * 100))}%` }}
              />
            </div>
            <span className="w-12 shrink-0 text-right font-mono text-xs">{formatScore(row.score)}</span>
            <span className={`w-14 shrink-0 text-right text-[11px] ${row.delta === null ? "text-muted-foreground" : row.delta >= 0 ? "text-success" : "text-destructive"}`}>
              {row.delta === null ? "—" : `${row.delta >= 0 ? "+" : ""}${row.delta.toFixed(2)}`}
            </span>
          </div>
        ))}
        {traces !== null && rows.length > 0 && (
          <p className="pt-1 text-[11px] text-muted-foreground">
            {fetchedDays >= periodDays * 2
              ? `Delta compares against the previous ${periodDays} day${periodDays === 1 ? "" : "s"}.`
              : "Delta unavailable — the comparison period would exceed the 30-day results window."}
          </p>
        )}
      </CardContent>
    </Card>
  );
}
