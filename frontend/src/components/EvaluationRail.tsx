import { ExternalLink, Loader2, Play, RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { CopyField } from "@/components/CopyField";
import { StatusPill } from "@/components/StatusPill";
import { useTimezone } from "@/contexts/TimezoneContext";
import { formatRelativeDateTime } from "@/lib/format";
import { evaluatorShortName, agentLogGroupName } from "@/lib/evaluations";
import type { OnlineEvaluationSource } from "@/api/types";
import type { TestCaseRunSummary } from "@/components/EvaluationTestCases";

interface EvaluationRailProps {
  region: string;
  runtimeId: string | null;
  summary: TestCaseRunSummary | null;
  onlineSource: OnlineEvaluationSource | null;
  onRefresh: () => void;
  refreshing: boolean;
  onRunAll?: () => void;
  runningAll?: boolean;
}

const LEGEND: { key: "pass" | "running" | "fail" | "error" | "not_run"; label: string; dot: string; bar: string }[] = [
  { key: "pass", label: "Passed", dot: "bg-success", bar: "bg-success" },
  { key: "running", label: "Running", dot: "bg-primary/45", bar: "bg-primary/45" },
  { key: "fail", label: "Failed", dot: "bg-destructive", bar: "bg-destructive" },
  { key: "error", label: "Couldn't score", dot: "bg-warning", bar: "bg-warning" },
  { key: "not_run", label: "Not run", dot: "border border-foreground/15 bg-muted box-border", bar: "bg-muted" },
];

function LatestTestRunCard({ summary, onRunAll, runningAll }: { summary: TestCaseRunSummary | null; onRunAll?: () => void; runningAll?: boolean }) {
  const { timezone } = useTimezone();
  if (!summary || summary.total === 0) return null;
  const counts = Object.fromEntries(LEGEND.map((l) => [l.key, summary.results.filter((r) => r === l.key).length]));
  const runningCount = counts.running ?? 0;
  return (
    <Card>
      <CardHeader>
        <div className="flex items-center">
          <CardTitle className="text-sm font-medium">Latest test run</CardTitle>
          <span className="ml-auto font-mono text-[11px] text-muted-foreground">
            {summary.latestRunAt ? formatRelativeDateTime(summary.latestRunAt, timezone) : "—"}
          </span>
        </div>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        <div className="flex items-baseline gap-1">
          <span className="font-mono text-2xl font-semibold tracking-tight">{summary.passed}/{summary.total}</span>
          <span className="text-xs text-muted-foreground">
            passed{runningCount > 0 ? ` · ${runningCount} still running` : ""}
          </span>
        </div>
        <div className="flex gap-0.5">
          {summary.results.map((r, i) => {
            const l = LEGEND.find((x) => x.key === r);
            return <div key={i} className={`h-1.5 flex-1 rounded-full ${l?.bar ?? "bg-muted"}`} />;
          })}
        </div>
        <div className="flex flex-col gap-1.5 text-xs">
          {LEGEND.filter((l) => (counts[l.key] ?? 0) > 0).map((l) => (
            <div key={l.key} className="flex items-center gap-1.5">
              <div className={`h-2 w-2 rounded-sm ${l.dot}`} />
              <span className="text-muted-foreground">{l.label}</span>
              <span className="ml-auto font-mono">{counts[l.key] ?? 0}</span>
            </div>
          ))}
        </div>
        {onRunAll && (
          <Button size="sm" variant="outline" disabled={runningAll} onClick={onRunAll} className="gap-1.5">
            {runningAll ? <Loader2 className="h-3 w-3 animate-spin" /> : <Play className="h-3 w-3" />}
            Run all {summary.total}
          </Button>
        )}
      </CardContent>
    </Card>
  );
}

function OnlineEvaluationCard({
  region,
  runtimeId,
  source,
  onRefresh,
  refreshing,
}: {
  region: string;
  runtimeId: string | null;
  source: OnlineEvaluationSource | null;
  onRefresh: () => void;
  refreshing: boolean;
}) {
  // region lands in the host label, so it is encoded: an unencoded value like
  // "evil.com/" would move the host off console.aws.amazon.com. Real region
  // names contain nothing encodeURIComponent touches.
  const safeRegion = encodeURIComponent(region);
  const consoleUrl = `https://${safeRegion}.console.aws.amazon.com/bedrock-agentcore/evaluations?region=${safeRegion}&tab=batch-evaluations`;

  if (!source) {
    return (
      <Card>
        <CardHeader>
          <div className="flex items-center gap-2">
            <CardTitle className="text-sm font-medium">Live traffic scores</CardTitle>
            <StatusPill label="NOT CONNECTED" variant="neutral" />
          </div>
        </CardHeader>
        <CardContent className="flex flex-col gap-2.5">
          <p className="text-xs text-muted-foreground">
            No AgentCore evaluation reads this agent's traces yet. Create an online evaluation pointed at this log group and scores will show here within a few minutes.
          </p>
          {runtimeId && <CopyField label="Trace log group" value={agentLogGroupName(runtimeId)} />}
          <div className="flex items-center gap-2">
            <a href={consoleUrl} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 text-xs text-primary hover:underline">
              View in AWS console <ExternalLink className="h-3 w-3" />
            </a>
            <Button size="sm" variant="outline" onClick={onRefresh} className="ml-auto h-7 gap-1.5 text-xs">
              <RefreshCw className={`h-3 w-3 ${refreshing ? "animate-spin" : ""}`} /> Refresh
            </Button>
          </div>
        </CardContent>
      </Card>
    );
  }
  return (
    <Card>
      <CardHeader>
        <div className="flex items-center gap-2">
          <CardTitle className="text-sm font-medium">Online evaluation</CardTitle>
          <StatusPill label={source.execution_status ?? "UNKNOWN"} variant={source.execution_status === "ENABLED" ? "success" : "neutral"} />
        </div>
      </CardHeader>
      <CardContent className="flex flex-col gap-2">
        <div className="flex flex-col gap-0.5">
          <span className="font-mono text-[9.5px] uppercase tracking-wide text-muted-foreground">Config</span>
          <span className="truncate font-mono text-xs">{source.name ?? source.id}</span>
        </div>
        <div className="flex flex-col gap-0.5">
          <span className="font-mono text-[9.5px] uppercase tracking-wide text-muted-foreground">Sampling</span>
          <span className="text-xs">{source.sampling_percentage !== null ? `${source.sampling_percentage}% of sessions` : "—"}</span>
        </div>
        <div className="flex flex-col gap-0.5">
          <span className="font-mono text-[9.5px] uppercase tracking-wide text-muted-foreground">Evaluators</span>
          <span className="truncate text-xs">{source.evaluators.length} ({source.evaluators.slice(0, 3).map(evaluatorShortName).join(", ")}{source.evaluators.length > 3 ? "…" : ""})</span>
        </div>
        <div className="flex items-center gap-2 pt-1">
          <a href={consoleUrl} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 text-xs text-primary hover:underline">
            Open in AgentCore console <ExternalLink className="h-3 w-3" />
          </a>
          <Button size="sm" variant="outline" onClick={onRefresh} className="ml-auto h-7 gap-1.5 text-xs">
            <RefreshCw className={`h-3 w-3 ${refreshing ? "animate-spin" : ""}`} /> Refresh
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}

export function EvaluationRail({ region, runtimeId, summary, onlineSource, onRefresh, refreshing, onRunAll, runningAll }: EvaluationRailProps) {
  return (
    <div className="flex flex-col gap-3.5">
      <LatestTestRunCard summary={summary} onRunAll={onRunAll} runningAll={runningAll} />
      <OnlineEvaluationCard region={region} runtimeId={runtimeId} source={onlineSource} onRefresh={onRefresh} refreshing={refreshing} />
    </div>
  );
}
