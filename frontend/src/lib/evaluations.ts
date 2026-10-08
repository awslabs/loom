import type { BadgeVariant } from "@/lib/status";

/** Last dotted segment of an evaluator ID, e.g. "Helpfulness" for "Builtin.Helpfulness". */
export function evaluatorShortName(id: string | null): string {
  if (!id) return "—";
  return id.split(".").pop() ?? id;
}

/** Built-in evaluators score 0-1. Custom numerical evaluators can use any
 * scale, so only 0-1 scores get a quality colour — matching AgentCore's own
 * ≥0.80 good / 0.70-0.79 borderline / <0.70 poor convention. */
export function scoreVariant(value: number | null): BadgeVariant {
  if (value === null || value < 0 || value > 1) return "neutral";
  if (value >= 0.8) return "success";
  if (value >= 0.7) return "warning";
  return "destructive";
}

export function formatScore(value: number | null): string {
  return value === null ? "—" : value.toFixed(2);
}

/** Average of the numeric scores in a set of evaluator verdicts (null if none are numeric). */
export function averageScore(scores: { value: number | null }[]): number | null {
  const values = scores.map((s) => s.value).filter((v): v is number => v !== null);
  if (values.length === 0) return null;
  return values.reduce((a, b) => a + b, 0) / values.length;
}

/** The four meanings a test case's latest run can carry. PASS/FAIL mean the
 * run finished and scored; ERROR means it never got far enough to be scored
 * (no trace spans, timeout, evaluator failure) — a pipeline problem, not a
 * verdict on the agent. NOT_RUN means it has never been run. */
export type ResultStatus = "pass" | "fail" | "error" | "not_run" | "running";

export interface RunLike {
  status: string | null;
  errors?: string[];
  scores: { value: number | null }[];
}

const RUNNING_STATUSES = new Set([
  "PENDING",
  "IN_PROGRESS",
  "RUNNING",
  "INVOKING",
  "WAITING_FOR_LOGS",
  "EVALUATING",
]);

/** Human-readable label for an in-progress run's current phase, so the
 * frontend can show *what* is happening instead of a single opaque
 * "running" state for however long the whole invoke+wait+evaluate chain
 * takes (an on-demand run can take anywhere from a few seconds to a few
 * minutes, mostly spent waiting for CloudWatch to make spans queryable). */
export function runPhaseLabel(status: string | null): string {
  switch (status) {
    case "INVOKING":
      return "Invoking agent";
    case "WAITING_FOR_LOGS":
      return "Waiting for logs";
    case "EVALUATING":
      return "Scoring";
    default:
      return "Running";
  }
}

/** Classify a test case's latest run. `run` is undefined while its status
 * hasn't been fetched yet (also reported as "running" so callers show a
 * spinner rather than a stale result). A run with some scores *and* errors
 * (one evaluator failed, another didn't) is a PASS/FAIL with a partial-
 * failure warning (see hasPartialErrors), not a hard ERROR — ERROR means no
 * evaluator produced anything to judge by. */
export function classifyResult(hasRun: boolean, run: RunLike | undefined, passThreshold: number): ResultStatus {
  if (!hasRun) return "not_run";
  if (!run) return "running";
  if (run.status !== null && RUNNING_STATUSES.has(run.status)) return "running";
  if (run.status === "FAILED") return "error";
  const overall = averageScore(run.scores);
  if (overall === null) return "error";
  return overall >= passThreshold ? "pass" : "fail";
}

/** True when a run has at least one real score but also at least one
 * evaluator error — some evaluators scored, others silently failed. Worth
 * a visible warning even though the run isn't a hard ERROR. */
export function hasPartialErrors(run: RunLike | undefined): boolean {
  return !!run && run.scores.length > 0 && !!run.errors && run.errors.length > 0;
}

/** CloudWatch log group name for one runtime qualifier, mirroring the
 * backend's `derive_log_group` (app/routers/agents.py) — the runtime ID
 * alone is NOT the log group; AgentCore appends the qualifier (e.g.
 * "-DEFAULT") to it. */
export function agentLogGroupName(runtimeId: string, qualifier = "DEFAULT"): string {
  return `/aws/bedrock-agentcore/runtimes/${runtimeId}-${qualifier}`;
}

/** Console deep link to one CloudWatch log group.
 *
 * The console's client-side router keeps the log group name in the URL
 * fragment (after `#`) and expects it *double*-encoded there — a literal
 * `/` must become `$252F` (the `%2F` you'd normally get from encoding a
 * `/`, with its own `%` re-encoded to `%25`), not the single-encoded
 * `%2F` a plain `encodeURIComponent` produces. A single-encoded link
 * loads the console but can't resolve the group and shows "invalid log
 * group" / 404. */
export function cloudWatchLogGroupUrl(region: string, logGroupName: string): string {
  const fragmentEncoded = logGroupName.split("/").map(encodeURIComponent).join("$252F");
  // region is the leading host label, so encode it too — otherwise a crafted
  // value moves the link off console.aws.amazon.com.
  const safeRegion = encodeURIComponent(region);
  return `https://${safeRegion}.console.aws.amazon.com/cloudwatch/home?region=${safeRegion}#logsV2:log-groups/log-group/${fragmentEncoded}`;
}
