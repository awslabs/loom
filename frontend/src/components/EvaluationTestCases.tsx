import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { AlertTriangle, ChevronDown, ChevronRight, Copy, ExternalLink, Loader2, Pencil, Play, Plus, Search, X } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { StatusPill } from "@/components/StatusPill";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { useTimezone } from "@/contexts/TimezoneContext";
import { formatRelativeDateTime } from "@/lib/format";
import { evaluatorShortName, scoreVariant, formatScore, averageScore, classifyResult, hasPartialErrors, cloudWatchLogGroupUrl, agentLogGroupName, runPhaseLabel, type ResultStatus } from "@/lib/evaluations";
import { fetchModels } from "@/api/agents";
import {
  listEvaluators,
  listTestCases,
  createTestCase,
  updateTestCase,
  deleteTestCase,
  runTestCase,
  rescoreTestCase,
  getTestCaseLastRun,
  listTestCaseRuns,
  getTestCaseRun,
} from "@/api/evaluations";
import type { EvaluatorInfo, EvaluationTestCase, EvaluationTestCaseRequest, TestCaseScoreDetail, ModelOption, SessionResponse, TestCaseRunSummary as ApiTestCaseRunSummary } from "@/api/types";

/** Author and run on-demand evaluations for one agent, and review the latest
 * result per test case.
 *
 * Loom saves only the test case itself (prompt, optional expected response,
 * which evaluators to apply, pass threshold, optional model override) —
 * running one invokes the agent for real and hands that session to
 * AgentCore's StartBatchEvaluation, which does the actual judging. Each
 * row's score/result is read back live from that run's result records, not
 * stored.
 */

export interface TestCaseRunSummary {
  total: number;
  scored: number;
  passed: number;
  results: ResultStatus[];
  latestRunAt: string | null;
}

interface EvaluationTestCasesProps {
  agentId: number;
  agentName: string;
  region: string;
  runtimeId: string | null;
  sessions: SessionResponse[];
  onRunStarted?: () => void;
  /** Count of test cases whose latest run failed — bubbled up for the tab's "N failing" badge. */
  onFailingCountChange?: (count: number) => void;
  /** Count of test cases whose latest run errored (couldn't be scored) — "N error" badge. */
  onErrorCountChange?: (count: number) => void;
  /** Count of test cases whose latest run is still in progress — "N running" badge. */
  onRunningCountChange?: (count: number) => void;
  /** Rolled-up pass/fail/error/not-run across all test cases' latest runs — for the rail's "Latest test run" card. */
  onSummaryChange?: (summary: TestCaseRunSummary) => void;
  /** The new/edit test case form replaces the whole tab body (table + rail hidden) while open. */
  onFormOpenChange?: (open: boolean) => void;
  /** Navigate to a session's detail page (for the ERROR panel's "Open session" link). */
  onOpenSession?: (sessionId: string) => void;
}

interface RunState {
  status: string | null;
  scores: TestCaseScoreDetail[];
  loading: boolean;
  error: string | null;
  errors?: string[];
  sessionId?: string | null;
  /** The run this state is for, so a new run (or rescore) that changes
   * last_batch_evaluation_id is detected and refetched instead of showing
   * a stale cached result forever. */
  batchEvaluationId?: string | null;
}

interface RunHistoryState {
  loading: boolean;
  items: ApiTestCaseRunSummary[];
  error: string | null;
}

interface FormState {
  id: number | null;
  name: string;
  prompt: string;
  expectedResponse: string;
  evaluatorIds: string[];
  passThreshold: string;
  modelId: string;
}

/** "36s" / "1m 12s" between two ISO timestamps, or null if either is missing. */
function formatDuration(startIso: string | null | undefined, endIso: string | null | undefined): string | null {
  if (!startIso || !endIso) return null;
  const seconds = Math.max(0, Math.round((new Date(endIso).getTime() - new Date(startIso).getTime()) / 1000));
  if (seconds < 60) return `${seconds}s`;
  return `${Math.floor(seconds / 60)}m ${seconds % 60}s`;
}

/** "Started 3m ago", for a RUNNING row's Last run column. */
function formatStartedAgo(startIso: string | null | undefined): string {
  if (!startIso) return "Started just now";
  const minutes = Math.max(0, Math.round((Date.now() - new Date(startIso).getTime()) / 60_000));
  if (minutes < 1) return "Started just now";
  return `Started ${minutes}m ago`;
}

const EMPTY_FORM: FormState = { id: null, name: "", prompt: "", expectedResponse: "", evaluatorIds: [], passThreshold: "0.70", modelId: "" };
const PRESETS: Record<string, string[]> = {
  Quality: ["Builtin.Correctness", "Builtin.Faithfulness", "Builtin.Helpfulness", "Builtin.ResponseRelevance"],
  Safety: ["Builtin.Refusal", "Builtin.Harmfulness", "Builtin.Stereotyping"],
  "Tool use": ["Builtin.ToolSelectionAccuracy", "Builtin.ToolParameterAccuracy"],
};

function EvaluatorPicker({
  evaluators,
  selected,
  onChange,
}: {
  evaluators: EvaluatorInfo[];
  selected: string[];
  onChange: (ids: string[]) => void;
}) {
  const [search, setSearch] = useState("");

  const groups = useMemo(() => {
    const byGroup = new Map<string, EvaluatorInfo[]>();
    for (const ev of evaluators) {
      if (search && !evaluatorShortName(ev.id).toLowerCase().includes(search.toLowerCase())) continue;
      const list = byGroup.get(ev.group) ?? [];
      list.push(ev);
      byGroup.set(ev.group, list);
    }
    return Array.from(byGroup.entries());
  }, [evaluators, search]);

  const toggle = (id: string) => {
    onChange(selected.includes(id) ? selected.filter((x) => x !== id) : [...selected, id]);
  };

  return (
    <div className="flex flex-col gap-3 rounded-lg bg-muted/40 p-3">
      <div className="flex items-center justify-between gap-2">
        <span className="text-xs font-medium">Evaluators · {selected.length} of {evaluators.length}</span>
        {selected.length > 0 && (
          <button type="button" className="text-[11px] text-primary hover:underline" onClick={() => onChange([])}>Clear</button>
        )}
      </div>
      <div className="relative">
        <Search className="absolute left-2 top-1/2 h-3 w-3 -translate-y-1/2 text-muted-foreground" />
        <Input
          placeholder="Search evaluators..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="h-7 pl-7 text-xs"
        />
      </div>
      <div className="flex flex-col gap-1.5">
        <span className="text-[10px] font-medium uppercase tracking-wide text-muted-foreground">Presets</span>
        <div className="flex flex-wrap gap-1.5">
          {Object.entries(PRESETS).map(([label, ids]) => (
            <button
              key={label}
              type="button"
              className="rounded-full border px-2 py-0.5 text-[11px] hover:bg-accent"
              onClick={() => onChange(Array.from(new Set([...selected, ...ids])))}
            >
              {label}
            </button>
          ))}
        </div>
      </div>
      <div className="flex flex-col gap-3">
        {groups.map(([group, items]) => {
          const allOn = items.every((ev) => selected.includes(ev.id));
          return (
            <div key={group} className="flex flex-col gap-1.5">
              <div className="flex items-center justify-between">
                <span className="text-[10px] font-medium uppercase tracking-wide text-muted-foreground">{group} ({items.length})</span>
                <button
                  type="button"
                  className="text-[10px] text-primary hover:underline"
                  onClick={() => onChange(
                    allOn
                      ? selected.filter((id) => !items.some((ev) => ev.id === id))
                      : Array.from(new Set([...selected, ...items.map((ev) => ev.id)])),
                  )}
                >
                  {allOn ? "Deselect all" : "Select all"}
                </button>
              </div>
              <div className="flex flex-wrap gap-1.5">
                {items.map((ev) => {
                  const on = selected.includes(ev.id);
                  return (
                    <button
                      key={ev.id}
                      type="button"
                      title={ev.description ? `${ev.id} — ${ev.description}` : ev.id}
                      onClick={() => toggle(ev.id)}
                      className={`rounded-full px-2 py-0.5 text-[11px] transition-colors ${
                        on ? "bg-primary text-primary-foreground" : "border hover:bg-accent"
                      }`}
                    >
                      {on ? "✓ " : ""}{evaluatorShortName(ev.id)}
                    </button>
                  );
                })}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function RecentSessionPicker({ sessions, onSelect, onClose }: {
  sessions: SessionResponse[];
  onSelect: (prompt: string) => void;
  onClose: () => void;
}) {
  const recentPrompts = useMemo(() => {
    const prompts: { text: string; at: number }[] = [];
    for (const session of sessions) {
      for (const inv of session.invocations) {
        if (inv.prompt_text) prompts.push({ text: inv.prompt_text, at: inv.client_invoke_time ?? 0 });
      }
    }
    return prompts.sort((a, b) => b.at - a.at).slice(0, 8);
  }, [sessions]);

  if (recentPrompts.length === 0) {
    return <p className="rounded-md border bg-muted/40 p-2 text-[11px] text-muted-foreground">No recent invocations to pick from.</p>;
  }

  return (
    <div className="flex flex-col gap-1 rounded-md border bg-muted/40 p-1.5">
      {recentPrompts.map((p, i) => (
        <button
          key={i}
          type="button"
          className="truncate rounded px-2 py-1 text-left text-[11px] hover:bg-accent"
          title={p.text}
          onClick={() => { onSelect(p.text); onClose(); }}
        >
          {p.text}
        </button>
      ))}
    </div>
  );
}

function TestCaseForm({
  form,
  evaluators,
  models,
  sessions,
  onChange,
  onSave,
  onSaveAndRun,
  onCancel,
  saving,
}: {
  form: FormState;
  evaluators: EvaluatorInfo[];
  models: ModelOption[];
  sessions: SessionResponse[];
  onChange: (form: FormState) => void;
  onSave: () => void;
  onSaveAndRun: () => void;
  onCancel: () => void;
  saving: boolean;
}) {
  const [showRecentSessions, setShowRecentSessions] = useState(false);
  const canSave = form.name.trim() !== "" && form.prompt.trim() !== "" && form.evaluatorIds.length > 0;
  return (
    <Card className="border-primary/40">
      <CardHeader>
        <CardTitle className="text-sm font-medium">{form.id === null ? "New test case" : "Edit test case"}</CardTitle>
      </CardHeader>
      <CardContent className="grid grid-cols-1 lg:grid-cols-2 gap-5">
        <div className="flex flex-col gap-3">
          <div className="flex flex-col gap-1">
            <label className="text-xs text-muted-foreground">Name</label>
            <Input
              placeholder="handles_missing_file"
              value={form.name}
              onChange={(e) => onChange({ ...form, name: e.target.value })}
              className="font-mono text-sm"
            />
            <span className="text-[11px] text-muted-foreground">snake_case, unique per agent</span>
          </div>
          <div className="flex flex-col gap-1">
            <div className="flex items-center justify-between">
              <label className="text-xs text-muted-foreground">Prompt</label>
              <button
                type="button"
                className="text-[11px] text-primary hover:underline"
                onClick={() => setShowRecentSessions((v) => !v)}
              >
                Use a recent session
              </button>
            </div>
            {showRecentSessions && (
              <RecentSessionPicker
                sessions={sessions}
                onSelect={(prompt) => onChange({ ...form, prompt })}
                onClose={() => setShowRecentSessions(false)}
              />
            )}
            <Textarea
              placeholder="Load data.csv and give me the mean of the price column"
              value={form.prompt}
              onChange={(e) => onChange({ ...form, prompt: e.target.value })}
              rows={4}
              className="text-sm"
            />
            <span className="text-[11px] text-muted-foreground">Prompt to send to the agent</span>
          </div>
          <div className="flex flex-col gap-1">
            <div className="flex items-center gap-1.5">
              <label className="text-xs text-muted-foreground">Expected response</label>
              <span className="rounded border px-1 py-0 text-[9px] uppercase tracking-wide text-muted-foreground">Optional</span>
            </div>
            <Textarea
              placeholder="data.csv was not found. Upload it or give a path."
              value={form.expectedResponse}
              onChange={(e) => onChange({ ...form, expectedResponse: e.target.value })}
              rows={2}
              className="text-sm"
            />
            <span className="text-[11px] text-muted-foreground">Adds a ground-truth score on top of the evaluators you pick.</span>
          </div>
          <div className="flex items-end gap-3">
            <div className="flex flex-col gap-1 w-32">
              <label className="text-xs text-muted-foreground">Pass threshold</label>
              <Input
                type="number"
                min={0}
                max={1}
                step={0.05}
                value={form.passThreshold}
                onChange={(e) => onChange({ ...form, passThreshold: e.target.value })}
                className="font-mono text-sm"
              />
            </div>
            <div className="flex flex-col gap-1 flex-1 min-w-0">
              <label className="text-xs text-muted-foreground">Model</label>
              <Select value={form.modelId || "__default__"} onValueChange={(v) => onChange({ ...form, modelId: v === "__default__" ? "" : v })}>
                <SelectTrigger className="w-full text-sm"><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="__default__">Agent default</SelectItem>
                  {models.map((m) => (
                    <SelectItem key={m.model_id} value={m.model_id}>{m.display_name}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>
        </div>
        <EvaluatorPicker
          evaluators={evaluators}
          selected={form.evaluatorIds}
          onChange={(ids) => onChange({ ...form, evaluatorIds: ids })}
        />
      </CardContent>
      <div className="flex items-center gap-2 px-6 pb-4">
        <span className="text-xs text-muted-foreground flex-1">
          {form.evaluatorIds.length} evaluator{form.evaluatorIds.length === 1 ? "" : "s"} selected
        </span>
        <Button size="sm" variant="ghost" onClick={onCancel} disabled={saving}>Cancel</Button>
        <Button size="sm" variant="outline" disabled={!canSave || saving} onClick={onSave}>
          {saving ? <Loader2 className="h-3 w-3 animate-spin" /> : "Save"}
        </Button>
        <Button size="sm" disabled={!canSave || saving} onClick={onSaveAndRun} className="gap-1.5">
          {saving ? <Loader2 className="h-3 w-3 animate-spin" /> : <Play className="h-3 w-3" />}
          Save and run
        </Button>
      </div>
    </Card>
  );
}

/** First sentence of an evaluator's explanation, capped to ~90 chars — the
 * one-line verdict shown in the collapsed row. Prefers the evaluator's own
 * label when AgentCore provides one. */
function evaluatorVerdict(s: TestCaseScoreDetail, maxLen = 90): string {
  if (s.label) return s.label;
  if (!s.explanation) return "—";
  const sentence = s.explanation.match(/^.*?[.!?](?=\s|$)/)?.[0] ?? s.explanation;
  return sentence.length > maxLen ? `${sentence.slice(0, maxLen - 1)}…` : sentence;
}

// ~2 lines of 13px text at a 72ch max-width — past this, assume it won't
// fit in 2 lines and offer "Show more" rather than guessing from a DOM measurement.
const LONG_EXPLANATION_CHARS = 150;

function EvaluatorExplanation({ text }: { text: string }) {
  const [showFull, setShowFull] = useState(false);
  const isLong = text.length > LONG_EXPLANATION_CHARS;
  return (
    <div className="flex flex-col gap-1.5">
      <p
        className="whitespace-normal text-[13px] leading-relaxed text-foreground"
        style={!showFull && isLong ? { display: "-webkit-box", WebkitLineClamp: 2, WebkitBoxOrient: "vertical", overflow: "hidden" } : undefined}
      >
        {text}
      </p>
      {isLong && (
        <button type="button" className="self-start text-[11.5px] text-primary hover:underline" onClick={() => setShowFull((v) => !v)}>
          {showFull ? "Show less" : "Show more"}
        </button>
      )}
    </div>
  );
}

/** One evaluator per row: a one-line verdict + score, click to expand the
 * full reasoning in place. A 300px tooltip turned 100-200 words of
 * evaluator reasoning into ~15 lines covering the rows underneath it —
 * expanding in place at the card's full width fits the same text in ~5. */
function EvaluatorRows({
  scores,
  passThreshold,
  sessionId,
  onOpenSession,
  footer = true,
  bordered = true,
}: {
  scores: TestCaseScoreDetail[];
  passThreshold: number;
  sessionId?: string | null;
  onOpenSession?: (sessionId: string) => void;
  footer?: boolean;
  /** False when the caller already provides the surrounding card border
   * (e.g. the "Latest run" card, which also has a header above these rows). */
  bordered?: boolean;
}) {
  const [expanded, setExpanded] = useState<Set<number>>(new Set());
  const autoExpandKey = useRef<string | null>(null);

  // Re-derive the default expansion (open anything below threshold, leave
  // passing rows collapsed) whenever this is actually a new set of scores —
  // not on every re-render, which would stomp on rows the user toggled by hand.
  useEffect(() => {
    const key = scores.map((s) => `${s.evaluator}:${s.value}`).join("|");
    if (key === autoExpandKey.current) return;
    autoExpandKey.current = key;
    setExpanded(new Set(scores.flatMap((s, i) => (s.value !== null && s.value < passThreshold ? [i] : []))));
  }, [scores, passThreshold]);

  const toggle = (i: number) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(i)) next.delete(i); else next.add(i);
      return next;
    });
  };

  const allOpen = scores.length > 0 && expanded.size === scores.length;
  const overall = averageScore(scores);

  return (
    <div className={`flex flex-col ${bordered ? "rounded-md border" : ""}`}>
      {scores.map((s, i) => {
        const variant = scoreVariant(s.value);
        const color = variant === "success" ? "var(--success)" : variant === "warning" ? "var(--warning)" : variant === "destructive" ? "var(--destructive)" : "var(--muted-foreground)";
        const widthPct = s.value === null ? 0 : Math.max(0, Math.min(100, s.value * 100));
        const isOpen = expanded.has(i);
        return (
          <div key={`${s.evaluator}-${i}`} className={`${i > 0 ? "border-t" : ""} ${isOpen ? "bg-muted/40" : ""}`}>
            <div
              role="button"
              tabIndex={0}
              onClick={() => toggle(i)}
              onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); toggle(i); } }}
              className="grid cursor-pointer grid-cols-[14px_220px_minmax(0,1fr)_330px] items-center gap-3.5 px-3.5 py-2.5 hover:bg-accent/30"
            >
              {isOpen ? <ChevronDown className="h-3 w-3 shrink-0 text-muted-foreground" /> : <ChevronRight className="h-3 w-3 shrink-0 text-muted-foreground" />}
              <span className="truncate font-mono text-xs font-medium">{evaluatorShortName(s.evaluator)}</span>
              <span className="truncate text-[13px] text-muted-foreground">{evaluatorVerdict(s)}</span>
              <div className="flex min-w-0 items-center gap-2">
                <div className="h-[5px] flex-1 overflow-hidden rounded-full bg-muted">
                  <div className="h-full rounded-full" style={{ width: `${widthPct}%`, backgroundColor: color }} />
                </div>
                <span className="shrink-0 font-mono text-[12.5px] font-semibold" style={{ color }}>{formatScore(s.value)}</span>
              </div>
            </div>
            {isOpen && (
              <div className="flex flex-col gap-2.5 pb-3.5 pl-[42px] pr-[42px]">
                <EvaluatorExplanation text={s.explanation ?? "No reasoning was returned for this evaluator."} />
                <div className="flex items-center gap-3.5 text-[12px] text-primary">
                  <button
                    type="button"
                    className="hover:underline"
                    onClick={(e) => {
                      e.stopPropagation();
                      void navigator.clipboard.writeText(s.explanation ?? "");
                      toast.success("Explanation copied");
                    }}
                  >
                    Copy
                  </button>
                  {sessionId && onOpenSession && (
                    <button type="button" className="hover:underline" onClick={(e) => { e.stopPropagation(); onOpenSession(sessionId); }}>
                      View in session trace
                    </button>
                  )}
                </div>
              </div>
            )}
          </div>
        );
      })}
      {footer && scores.length > 0 && (
        <div className="flex items-center border-t px-3.5 py-2 text-[12px] text-muted-foreground">
          <span>Average {overall === null ? "—" : overall.toFixed(2)} · pass threshold {passThreshold.toFixed(2)}</span>
          <button
            type="button"
            className="ml-auto text-primary hover:underline"
            onClick={() => setExpanded(allOpen ? new Set() : new Set(scores.map((_, i) => i)))}
          >
            {allOpen ? "Collapse all" : "Expand all"}
          </button>
        </div>
      )}
    </div>
  );
}

/** One-line collapsed rows for every run except the latest (which has its
 * own card above) — expanding a row reuses the same evaluator-rows list. */
function EarlierRunsList({
  tc,
  history,
  expandedRunId,
  onToggleRun,
  historyRunStates,
  onOpenSession,
}: {
  tc: EvaluationTestCase;
  history: RunHistoryState | undefined;
  expandedRunId: string | null;
  onToggleRun: (batchEvaluationId: string) => void;
  historyRunStates: Record<string, RunState>;
  onOpenSession?: (sessionId: string) => void;
}) {
  const { timezone } = useTimezone();

  if (history === undefined || history.loading) {
    return <Skeleton className="h-10" />;
  }
  if (history.error) {
    return <p className="text-xs text-destructive">{history.error}</p>;
  }
  const earlier = history.items.filter((run) => run.batch_evaluation_id !== tc.last_batch_evaluation_id);
  if (earlier.length === 0) {
    return <p className="text-xs text-muted-foreground italic">No earlier runs.</p>;
  }

  return (
    <div className="flex flex-col gap-1.5">
      {earlier.map((run) => {
        const isOpen = expandedRunId === run.batch_evaluation_id;
        const runDetail = historyRunStates[run.batch_evaluation_id];
        const isRunning = run.status === "PENDING" || run.status === "IN_PROGRESS" || run.status === "RUNNING";
        const isError = !isRunning && (run.status === "FAILED" || run.errors.length > 0);
        // Status pills everywhere use the same short, fixed vocabulary
        // (PASS/FAIL/ERROR/RUNNING) — showing the raw backend status
        // ("IN_PROGRESS", "COMPLETED") here both breaks that consistency and
        // overflows this row's narrow fixed-width pill column.
        const label = isRunning ? "RUNNING" : isError ? "ERROR" : run.status === "COMPLETED" ? "PASS" : "UNKNOWN";
        const variant = isRunning ? "info" : isError ? "warning" : run.status === "COMPLETED" ? "success" : "neutral";
        const summary = isError
          ? `Couldn't score${run.errors[0] ? `: ${run.errors[0]}` : ""}`
          : null;
        const score = runDetail && !runDetail.loading ? averageScore(runDetail.scores) : null;
        return (
          <div key={run.batch_evaluation_id} className="rounded-md border">
            <button
              type="button"
              onClick={() => onToggleRun(run.batch_evaluation_id)}
              className="grid w-full grid-cols-[14px_76px_130px_48px_minmax(0,1fr)_44px] items-center gap-3 px-3 py-2 text-left hover:bg-accent/40"
            >
              {isOpen ? <ChevronDown className="h-3 w-3 shrink-0" /> : <ChevronRight className="h-3 w-3 shrink-0" />}
              <StatusPill label={label} variant={variant} pulse={isRunning} />
              <span className="truncate text-[11.5px] text-muted-foreground">
                {run.created_at ? formatRelativeDateTime(run.created_at, timezone) : "—"}
              </span>
              <span className="truncate text-[11.5px] text-muted-foreground">{formatDuration(run.created_at, run.updated_at) ?? "—"}</span>
              <span className="truncate text-[12.5px] text-muted-foreground">{summary}</span>
              <span className="truncate text-right font-mono text-xs text-muted-foreground">{score === null ? "—" : score.toFixed(2)}</span>
            </button>
            {isOpen && (
              <div className="border-t p-2.5">
                {runDetail === undefined || runDetail.loading ? (
                  <Skeleton className="h-10" />
                ) : runDetail.error ? (
                  <p className="text-xs text-destructive">{runDetail.error}</p>
                ) : runDetail.scores.length === 0 ? (
                  <p className="text-xs text-muted-foreground italic">
                    {runDetail.errors && runDetail.errors.length > 0 ? runDetail.errors[0] : "No scores for this run."}
                  </p>
                ) : (
                  <EvaluatorRows
                    scores={runDetail.scores}
                    passThreshold={tc.pass_threshold}
                    sessionId={runDetail.sessionId}
                    onOpenSession={onOpenSession}
                  />
                )}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

function ErrorPanel({
  runState,
  onRescore,
  rescoring,
  onOpenSession,
  logGroupUrl,
}: {
  runState: RunState;
  onRescore: () => void;
  rescoring: boolean;
  onOpenSession?: (sessionId: string) => void;
  logGroupUrl: string | null;
}) {
  const [showRaw, setShowRaw] = useState(false);
  const sessionId = runState.sessionId ?? null;
  const cause = runState.errors && runState.errors.length > 0
    ? runState.errors[0]
    : "AgentCore found no trace spans for this session. Spans can take up to 5 minutes to arrive, so this is usually fixed by scoring again.";

  return (
    <div className="flex flex-col gap-2.5 rounded-md border border-warning/40 bg-warning-bg/40 p-3">
      <div className="flex flex-col gap-0.5">
        <span className="text-[13px] font-semibold">The run finished but couldn't be scored</span>
        <p className="whitespace-normal text-xs leading-relaxed text-muted-foreground">{cause}</p>
      </div>
      {sessionId && (
        <div className="flex items-center gap-2 rounded-md border bg-background px-2.5 py-1.5">
          <span className="font-mono text-[9.5px] uppercase tracking-wide text-muted-foreground">Session</span>
          <span className="min-w-0 truncate font-mono text-xs">{sessionId}</span>
          <button
            type="button"
            className="ml-auto shrink-0 rounded border px-1.5 py-0.5 text-[10px] text-muted-foreground hover:bg-accent"
            onClick={() => { void navigator.clipboard.writeText(sessionId); toast.success("Session ID copied"); }}
          >
            <Copy className="h-3 w-3" />
          </button>
        </div>
      )}
      <div className="flex items-center gap-2">
        <Button size="sm" disabled={rescoring} onClick={onRescore} className="h-7 gap-1.5 text-xs">
          {rescoring ? <Loader2 className="h-3 w-3 animate-spin" /> : null}
          Score again
        </Button>
        {sessionId && onOpenSession && (
          <Button size="sm" variant="outline" onClick={() => onOpenSession(sessionId)} className="h-7 text-xs">
            Open session
          </Button>
        )}
        {logGroupUrl && (
          <a href={logGroupUrl} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 text-xs text-primary hover:underline">
            View log group <ExternalLink className="h-3 w-3" />
          </a>
        )}
        {runState.errors && runState.errors.length > 0 && (
          <button type="button" className="ml-auto text-[11px] text-muted-foreground hover:underline" onClick={() => setShowRaw((v) => !v)}>
            Raw error · {showRaw ? "Hide" : "Show"}
          </button>
        )}
      </div>
      {showRaw && runState.errors && (
        <ul className="list-disc space-y-0.5 whitespace-normal pl-4 text-[11px] text-muted-foreground">
          {runState.errors.map((e, i) => <li key={i}>{e}</li>)}
        </ul>
      )}
    </div>
  );
}

function TestCaseRow({
  tc,
  expanded,
  onToggle,
  onEdit,
  onDelete,
  onRun,
  onRescore,
  running,
  rescoring,
  deleting,
  runState,
  history,
  expandedRunId,
  onToggleRun,
  historyRunStates,
  onOpenSession,
  logGroupUrl,
}: {
  tc: EvaluationTestCase;
  expanded: boolean;
  onToggle: () => void;
  onEdit: () => void;
  onDelete: () => void;
  onRun: () => void;
  onRescore: () => void;
  running: boolean;
  rescoring: boolean;
  deleting: boolean;
  runState: RunState | undefined;
  history: RunHistoryState | undefined;
  expandedRunId: string | null;
  onToggleRun: (batchEvaluationId: string) => void;
  historyRunStates: Record<string, RunState>;
  onOpenSession?: (sessionId: string) => void;
  logGroupUrl: string | null;
}) {
  const { timezone } = useTimezone();
  const overall = runState ? averageScore(runState.scores) : null;
  const resultStatus = classifyResult(!!tc.last_batch_evaluation_id, runState?.loading ? undefined : runState, tc.pass_threshold);
  const resultLabel = resultStatus === "pass" ? "PASS"
    : resultStatus === "fail" ? "FAIL"
    : resultStatus === "error" ? "ERROR"
    : resultStatus === "running" ? "RUNNING"
    : "NOT RUN";
  const resultVariant = resultStatus === "pass" ? "success"
    : resultStatus === "fail" ? "destructive"
    : resultStatus === "error" ? "warning"
    : resultStatus === "running" ? "info"
    : "neutral";
  const rowTint = resultStatus === "error" ? "bg-warning-bg/20" : resultStatus === "fail" ? "bg-destructive/5" : "";
  const latestHistoryEntry = history?.items.find((r) => r.batch_evaluation_id === tc.last_batch_evaluation_id);
  const earlierCount = history ? history.items.filter((r) => r.batch_evaluation_id !== tc.last_batch_evaluation_id).length : null;

  const actions = (
    <div className="ml-auto flex items-center gap-3 text-[11.5px]">
      {runState?.sessionId && onOpenSession && (
        <button type="button" className="text-primary hover:underline" onClick={() => onOpenSession(runState.sessionId!)}>Open session</button>
      )}
      <button type="button" className="text-primary hover:underline disabled:opacity-50" onClick={onRun} disabled={running}>Run now</button>
      <button type="button" className="inline-flex items-center gap-1 text-primary hover:underline" onClick={onEdit}>
        <Pencil className="h-3 w-3" /> Edit test
      </button>
      <button type="button" className="inline-flex items-center gap-1 text-destructive hover:underline disabled:opacity-50" disabled={deleting} onClick={onDelete}>
        {deleting ? <Loader2 className="h-3 w-3 animate-spin" /> : <X className="h-3 w-3" />} Delete
      </button>
    </div>
  );

  return (
    <>
      <TableRow
        className={`cursor-pointer hover:bg-accent/40 ${rowTint}`}
        onClick={onToggle}
        onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onToggle(); } }}
        tabIndex={0}
        aria-expanded={expanded}
      >
        <TableCell>{expanded ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}</TableCell>
        <TableCell className="min-w-0 max-w-0">
          <div className="truncate font-mono text-xs font-medium">{tc.name}</div>
          <div className="truncate text-[11px] text-muted-foreground">{tc.prompt}</div>
        </TableCell>
        <TableCell className="truncate text-xs text-muted-foreground">
          {hasPartialErrors(runState) ? (
            <span className="inline-flex items-center gap-1 text-warning" title={`Only ${runState!.scores.length} of ${tc.evaluator_ids.length} evaluators returned a score`}>
              <AlertTriangle className="h-3 w-3" />
              {runState!.scores.length}/{tc.evaluator_ids.length}
            </span>
          ) : tc.evaluator_ids.length}
        </TableCell>
        <TableCell className={`truncate text-xs ${resultStatus === "running" ? "text-primary" : "text-muted-foreground"}`}>
          {resultStatus === "running" ? `${formatStartedAgo(tc.last_run_at)} · ${runPhaseLabel(runState?.status ?? null)}`
            : tc.last_run_at ? formatRelativeDateTime(tc.last_run_at, timezone)
            : "Never run"}
        </TableCell>
        <TableCell className="truncate font-mono text-xs">
          {runState?.loading ? <Loader2 className="h-3 w-3 animate-spin" /> : formatScore(overall)}
        </TableCell>
        <TableCell onClick={(e) => e.stopPropagation()} className="text-right">
          {resultStatus === "not_run" ? (
            <Button size="sm" variant="outline" disabled={running} onClick={onRun} className="h-6 gap-1 text-[11px]">
              {running ? <Loader2 className="h-3 w-3 animate-spin" /> : <Play className="h-3 w-3" />}
              Run
            </Button>
          ) : (
            <StatusPill label={resultLabel} variant={resultVariant} pulse={resultStatus === "running"} />
          )}
        </TableCell>
      </TableRow>
      {expanded && (
        <TableRow className="hover:bg-transparent">
          <TableCell />
          <TableCell colSpan={5} className="space-y-4 pb-4">
            <div className="flex flex-col rounded-md border">
              <div className="flex items-center gap-3 border-b px-3.5 py-2.5">
                {tc.last_batch_evaluation_id ? (
                  <>
                    <span className="font-mono text-[9.5px] uppercase tracking-wide text-muted-foreground">Latest run</span>
                    <span className={`text-[11.5px] ${resultStatus === "running" ? "text-primary" : "text-muted-foreground"}`}>
                      {resultStatus === "running"
                        ? runPhaseLabel(runState?.status ?? null)
                        : formatRelativeDateTime(tc.last_run_at, timezone)}
                      {latestHistoryEntry && formatDuration(latestHistoryEntry.created_at, latestHistoryEntry.updated_at) && ` · ${formatDuration(latestHistoryEntry.created_at, latestHistoryEntry.updated_at)}`}
                      {resultStatus !== "running" && " · manual"}
                    </span>
                  </>
                ) : (
                  <span className="text-[11.5px] italic text-muted-foreground">Not run yet.</span>
                )}
                {actions}
              </div>
              {!tc.last_batch_evaluation_id ? (
                <p className="p-3.5 text-xs text-muted-foreground italic">Pick evaluators and run it to see results here.</p>
              ) : runState?.error ? (
                <p className="whitespace-normal p-3.5 text-xs text-destructive">{runState.error}</p>
              ) : runState === undefined || runState.loading ? (
                <Skeleton className="m-3.5 h-16" />
              ) : resultStatus === "error" ? (
                <div className="p-3.5">
                  <ErrorPanel
                    runState={runState}
                    onRescore={onRescore}
                    rescoring={rescoring}
                    onOpenSession={onOpenSession}
                    logGroupUrl={logGroupUrl}
                  />
                </div>
              ) : runState.scores.length === 0 ? (
                <p className="p-3.5 text-xs text-muted-foreground italic">{runPhaseLabel(runState.status)} — no scores yet.</p>
              ) : (
                <div className="flex flex-col">
                  {hasPartialErrors(runState) && (
                    <div className="flex items-start gap-2 border-b border-warning/40 bg-warning-bg/40 px-3.5 py-2.5">
                      <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-warning" />
                      <div className="flex flex-col gap-0.5">
                        <span className="text-[12.5px] font-medium">
                          {runState.scores.length} of {tc.evaluator_ids.length} evaluators returned a score
                        </span>
                        <ul className="list-disc space-y-0.5 pl-4 text-[11px] text-muted-foreground">
                          {runState.errors!.map((e, i) => <li key={i}>{e}</li>)}
                        </ul>
                      </div>
                    </div>
                  )}
                  <EvaluatorRows
                    scores={runState.scores}
                    passThreshold={tc.pass_threshold}
                    sessionId={runState.sessionId}
                    onOpenSession={onOpenSession}
                    bordered={false}
                  />
                </div>
              )}
            </div>
            <div>
              <div className="mb-1.5 flex items-center gap-2">
                <span className="font-mono text-[9.5px] uppercase tracking-wide text-muted-foreground">Earlier runs</span>
                <span className="font-mono text-[10px] text-muted-foreground">{earlierCount ?? ""}</span>
              </div>
              <EarlierRunsList
                tc={tc}
                history={history}
                expandedRunId={expandedRunId}
                onToggleRun={onToggleRun}
                historyRunStates={historyRunStates}
                onOpenSession={onOpenSession}
              />
            </div>
          </TableCell>
        </TableRow>
      )}
    </>
  );
}

/** "JSON ▾" dropdown beside Run all, replacing the old always-visible
 * Import/Export disclosure link. */
function JsonMenu({ onImport, onExport }: { onImport: () => void; onExport: () => void }) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  return (
    <div ref={ref} className="relative">
      <Button size="sm" variant="outline" onClick={() => setOpen((v) => !v)} className="gap-1">
        JSON <ChevronDown className="h-3 w-3 text-muted-foreground" />
      </Button>
      {open && (
        <div className="absolute right-0 z-50 mt-1 w-32 rounded-md border bg-popover p-1 shadow-md">
          <button
            type="button"
            className="block w-full rounded-sm px-2 py-1.5 text-left text-xs hover:bg-accent"
            onClick={() => { setOpen(false); onImport(); }}
          >
            Import
          </button>
          <button
            type="button"
            className="block w-full rounded-sm px-2 py-1.5 text-left text-xs hover:bg-accent"
            onClick={() => { setOpen(false); onExport(); }}
          >
            Export
          </button>
        </div>
      )}
    </div>
  );
}

/** Inline Import panel opened from the JSON dropdown — a plain textarea +
 * Apply/Cancel, no disclosure chrome needed since the dropdown already
 * gates visibility. */
function ImportJsonPanel({
  onApply,
  onCancel,
}: {
  onApply: (json: string) => Promise<string | null>;
  onCancel: () => void;
}) {
  const [value, setValue] = useState("");
  const [applying, setApplying] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleApply = async () => {
    setApplying(true);
    const err = await onApply(value);
    setApplying(false);
    if (err) setError(err);
  };

  return (
    <div className="flex flex-col gap-2 rounded-md border bg-muted/30 p-3">
      <Textarea
        autoFocus
        placeholder='{"test_cases": [{"name": "...", "prompt": "...", "evaluator_ids": ["Builtin.Correctness"]}]}'
        value={value}
        onChange={(e) => { setValue(e.target.value); setError(null); }}
        rows={4}
        className="text-sm font-mono"
      />
      {error && <p className="text-xs text-destructive">{error}</p>}
      <div className="flex gap-2">
        <Button size="sm" variant="outline" disabled={!value.trim() || applying} onClick={() => void handleApply()}>
          {applying ? <Loader2 className="h-3 w-3 animate-spin" /> : "Apply"}
        </Button>
        <Button size="sm" variant="ghost" onClick={onCancel}>Cancel</Button>
      </div>
    </div>
  );
}

export function EvaluationTestCases({ agentId, agentName, region, runtimeId, sessions, onRunStarted, onFailingCountChange, onErrorCountChange, onRunningCountChange, onSummaryChange, onFormOpenChange, onOpenSession }: EvaluationTestCasesProps) {
  const [testCases, setTestCases] = useState<EvaluationTestCase[]>([]);
  const [evaluators, setEvaluators] = useState<EvaluatorInfo[]>([]);
  const [models, setModels] = useState<ModelOption[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [form, setForm] = useState<FormState | null>(null);
  const [saving, setSaving] = useState(false);
  const [runningId, setRunningId] = useState<number | null>(null);
  const [rescoringId, setRescoringId] = useState<number | null>(null);
  const [runningAll, setRunningAll] = useState(false);
  const [deletingId, setDeletingId] = useState<number | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<EvaluationTestCase | null>(null);
  const [importOpen, setImportOpen] = useState(false);
  const [expandedId, setExpandedId] = useState<number | null>(null);
  const [runStates, setRunStates] = useState<Record<number, RunState>>({});

  useEffect(() => { onFormOpenChange?.(form !== null); }, [form, onFormOpenChange]);

  // `silent` skips the loading-skeleton swap: refreshing after a run/rescore
  // (now near-instant, since the actual work moved to a background task)
  // was replacing the whole table with a Skeleton on every single refresh,
  // which is what showed up as the dashboard "blinking" during "Run all".
  // Only the very first load — nothing on screen yet — needs the skeleton.
  const load = useCallback(async (silent = false) => {
    if (!silent) setLoading(true);
    setError(null);
    try {
      const [cases, evals, modelList] = await Promise.all([listTestCases(agentId), listEvaluators(agentId), fetchModels()]);
      setTestCases(cases);
      setEvaluators(evals);
      setModels(modelList);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load test cases");
    } finally {
      if (!silent) setLoading(false);
    }
  }, [agentId]);

  useEffect(() => { void load(); }, [load]);

  const fetchRunState = useCallback(async (tc: EvaluationTestCase) => {
    if (!tc.last_batch_evaluation_id) return;
    const batchEvaluationId = tc.last_batch_evaluation_id;
    // Only blank the row to "loading" the first time this batch evaluation
    // id is seen. A RUNNING row gets re-polled every 2s by the effect below
    // as it moves through phases — re-entering "loading" on every tick blew
    // away the expanded panel's content (Skeleton) each time, which is what
    // showed up as the detail view "blinking" while a run was in progress.
    setRunStates((prev) => {
      const existing = prev[tc.id];
      const isNewRun = existing?.batchEvaluationId !== batchEvaluationId;
      return { ...prev, [tc.id]: isNewRun || !existing
        ? { status: null, scores: [], loading: true, error: null, batchEvaluationId }
        : { ...existing, batchEvaluationId } };
    });
    try {
      const detail = await getTestCaseLastRun(agentId, tc.id);
      setRunStates((prev) => ({ ...prev, [tc.id]: { status: detail.status, scores: detail.scores, loading: false, error: null, errors: detail.errors, sessionId: detail.session_id, batchEvaluationId } }));
    } catch (e) {
      setRunStates((prev) => ({ ...prev, [tc.id]: { status: null, scores: [], loading: false, error: e instanceof Error ? e.message : "Failed to load results", batchEvaluationId } }));
    }
  }, [agentId]);

  const [runHistory, setRunHistory] = useState<Record<number, RunHistoryState>>({});
  const [historyRunStates, setHistoryRunStates] = useState<Record<string, RunState>>({});
  const [expandedRunId, setExpandedRunId] = useState<string | null>(null);

  const fetchRunHistory = useCallback(async (tc: EvaluationTestCase) => {
    setRunHistory((prev) => ({ ...prev, [tc.id]: { loading: true, items: [], error: null } }));
    try {
      const items = await listTestCaseRuns(agentId, tc.id);
      setRunHistory((prev) => ({ ...prev, [tc.id]: { loading: false, items, error: null } }));
    } catch (e) {
      setRunHistory((prev) => ({ ...prev, [tc.id]: { loading: false, items: [], error: e instanceof Error ? e.message : "Failed to load run history" } }));
    }
  }, [agentId]);

  const fetchHistoryRunDetail = useCallback(async (tc: EvaluationTestCase, batchEvaluationId: string) => {
    setHistoryRunStates((prev) => ({ ...prev, [batchEvaluationId]: { status: null, scores: [], loading: true, error: null } }));
    try {
      const detail = await getTestCaseRun(agentId, tc.id, batchEvaluationId);
      setHistoryRunStates((prev) => ({ ...prev, [batchEvaluationId]: { status: detail.status, scores: detail.scores, loading: false, error: null, errors: detail.errors, sessionId: detail.session_id } }));
    } catch (e) {
      setHistoryRunStates((prev) => ({ ...prev, [batchEvaluationId]: { status: null, scores: [], loading: false, error: e instanceof Error ? e.message : "Failed to load run" } }));
    }
  }, [agentId]);

  // Fetch each test case's latest-run summary (for the SCORE/RESULT columns)
  // as soon as the list loads, and whenever a run or rescore gives it a new
  // batch evaluation id. Keyed on that id (not just "have we fetched before")
  // so a cached result isn't mistaken for the outcome of a newer run — and,
  // just as importantly, so merely expanding/collapsing a row (which doesn't
  // change testCases) never re-triggers this fetch and flickers the result.
  useEffect(() => {
    for (const tc of testCases) {
      if (tc.last_batch_evaluation_id && runStates[tc.id]?.batchEvaluationId !== tc.last_batch_evaluation_id) {
        void fetchRunState(tc);
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [testCases]);

  // A RUNNING test case keeps the same batch evaluation id while in
  // progress, so the effect above (keyed on that id changing) won't refetch
  // it again on its own — poll until it settles into PASS/FAIL/ERROR.
  useEffect(() => {
    const running = testCases.filter((tc) => {
      const rs = runStates[tc.id];
      return rs && !rs.loading && classifyResult(true, rs, tc.pass_threshold) === "running";
    });
    if (running.length === 0) return;
    const interval = setInterval(() => {
      for (const tc of running) void fetchRunState(tc);
    }, 2000);
    return () => clearInterval(interval);
  }, [testCases, runStates, fetchRunState]);

  useEffect(() => {
    const results: ResultStatus[] = testCases.map((tc) => {
      const rs = runStates[tc.id];
      return classifyResult(!!tc.last_batch_evaluation_id, rs?.loading ? undefined : rs, tc.pass_threshold);
    });
    onFailingCountChange?.(results.filter((r) => r === "fail").length);
    onErrorCountChange?.(results.filter((r) => r === "error").length);
    onRunningCountChange?.(results.filter((r) => r === "running").length);
    const latestRunAt = testCases.reduce<string | null>((latest, tc) => {
      if (!tc.last_run_at) return latest;
      return !latest || tc.last_run_at > latest ? tc.last_run_at : latest;
    }, null);
    onSummaryChange?.({
      total: testCases.length,
      scored: results.filter((r) => r === "pass" || r === "fail" || r === "error").length,
      passed: results.filter((r) => r === "pass").length,
      results,
      latestRunAt,
    });
  }, [testCases, runStates, onFailingCountChange, onErrorCountChange, onRunningCountChange, onSummaryChange]);

  const handleSave = async (andRun: boolean) => {
    if (!form) return;
    setSaving(true);
    const request: EvaluationTestCaseRequest = {
      name: form.name.trim(),
      prompt: form.prompt,
      expected_response: form.expectedResponse.trim() || null,
      evaluator_ids: form.evaluatorIds,
      pass_threshold: Number(form.passThreshold) || 0.7,
      model_id: form.modelId || null,
    };
    try {
      const saved = form.id === null
        ? await createTestCase(agentId, request)
        : await updateTestCase(agentId, form.id, request);
      toast.success(form.id === null ? "Test case created" : "Test case updated");
      setForm(null);
      await load(true);
      if (andRun) await handleRun(saved);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Failed to save test case");
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (tc: EvaluationTestCase) => {
    setDeletingId(tc.id);
    try {
      await deleteTestCase(agentId, tc.id);
      toast.success("Test case deleted");
      await load(true);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Failed to delete test case");
    } finally {
      setDeletingId(null);
    }
  };

  const handleRun = async (tc: EvaluationTestCase) => {
    setRunningId(tc.id);
    try {
      await runTestCase(agentId, tc.id);
      toast.success(`Started evaluation for "${tc.name}"`);
      await load(true);
      onRunStarted?.();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Failed to run test case");
    } finally {
      setRunningId(null);
    }
  };

  const handleRescore = async (tc: EvaluationTestCase) => {
    setRescoringId(tc.id);
    try {
      await rescoreTestCase(agentId, tc.id);
      toast.success(`Rescoring "${tc.name}"`);
      await load(true);
      onRunStarted?.();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Failed to rescore test case");
    } finally {
      setRescoringId(null);
    }
  };

  const handleRunAll = async () => {
    setRunningAll(true);
    try {
      // Each call now just creates a PENDING run row and schedules a
      // background task — the actual invoke+wait+evaluate work (what used
      // to make this slow) happens after the response, not before it. So
      // these can be fired concurrently and still return almost instantly;
      // the old sequential-with-a-full-reload-per-iteration loop here (built
      // around batch evaluation's internal timeout, which on-demand
      // evaluation no longer has) was adding delay and causing the table to
      // flash on every iteration for no benefit.
      const results = await Promise.allSettled(
        testCases.map((tc) => runTestCase(agentId, tc.id).catch(() => { throw new Error(tc.name); })),
      );
      for (const r of results) {
        if (r.status === "rejected") toast.error(`Failed to run "${(r.reason as Error).message}"`);
      }
      await load(true);
      onRunStarted?.();
      toast.success("Started all test cases");
    } finally {
      setRunningAll(false);
    }
  };

  const handleExportJson = (): string => {
    const manifest = {
      test_cases: testCases.map((tc) => ({
        name: tc.name,
        prompt: tc.prompt,
        expected_response: tc.expected_response,
        evaluator_ids: tc.evaluator_ids,
        pass_threshold: tc.pass_threshold,
        model_id: tc.model_id,
      })),
    };
    return JSON.stringify(manifest, null, 2);
  };

  const handleImportJson = async (json: string): Promise<string | null> => {
    let parsed: unknown;
    try {
      parsed = JSON.parse(json);
    } catch {
      return "Invalid JSON.";
    }
    const list = Array.isArray(parsed) ? parsed : (parsed as { test_cases?: unknown }).test_cases;
    if (!Array.isArray(list) || list.length === 0) {
      return 'Expected {"test_cases": [...]} (or a bare array of test cases).';
    }
    for (const [i, entry] of list.entries()) {
      if (typeof entry !== "object" || entry === null) return `Entry ${i + 1} is not an object.`;
      const e = entry as Record<string, unknown>;
      if (typeof e.name !== "string" || !e.name.trim()) return `Entry ${i + 1} is missing "name".`;
      if (typeof e.prompt !== "string" || !e.prompt.trim()) return `Entry ${i + 1} ("${e.name}") is missing "prompt".`;
      if (!Array.isArray(e.evaluator_ids) || e.evaluator_ids.length === 0) {
        return `Entry ${i + 1} ("${e.name}") needs a non-empty "evaluator_ids" array.`;
      }
    }

    let imported = 0;
    let failed = 0;
    for (const entry of list as Record<string, unknown>[]) {
      try {
        await createTestCase(agentId, {
          name: String(entry.name),
          prompt: String(entry.prompt),
          expected_response: typeof entry.expected_response === "string" ? entry.expected_response : null,
          evaluator_ids: entry.evaluator_ids as string[],
          pass_threshold: typeof entry.pass_threshold === "number" ? entry.pass_threshold : 0.7,
          model_id: typeof entry.model_id === "string" ? entry.model_id : null,
        });
        imported++;
      } catch (e) {
        failed++;
        toast.error(`Failed to import "${entry.name}": ${e instanceof Error ? e.message : "unknown error"}`);
      }
    }
    await load(true);
    toast.success(`Imported ${imported} test case${imported === 1 ? "" : "s"}${failed > 0 ? ` (${failed} failed)` : ""}`);
    return null;
  };

  // The form replaces the whole tab body (table, live traffic, rail) while open.
  if (form) {
    return (
      <div className="flex flex-col gap-3">
        <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
          <span>Agents</span>
          <span>/</span>
          <span className="text-foreground">{agentName}</span>
        </div>
        <TestCaseForm
          form={form}
          evaluators={evaluators}
          models={models}
          sessions={sessions}
          onChange={setForm}
          onSave={() => void handleSave(false)}
          onSaveAndRun={() => void handleSave(true)}
          onCancel={() => setForm(null)}
          saving={saving}
        />
      </div>
    );
  }

  return (
    <Card>
      <CardHeader>
        <div className="flex items-start justify-between gap-2">
          <div className="flex items-center gap-2">
            <CardTitle className="text-sm font-medium">Test cases</CardTitle>
            <span className="rounded-full bg-muted px-1.5 py-0.5 text-[10px] font-medium text-muted-foreground">{testCases.length}</span>
          </div>
          <div className="flex items-center gap-1.5">
            <JsonMenu
              onImport={() => setImportOpen(true)}
              onExport={() => {
                void navigator.clipboard.writeText(handleExportJson());
                toast.success(`Copied ${testCases.length} test case${testCases.length === 1 ? "" : "s"} as JSON`);
              }}
            />
            <Button size="sm" variant="outline" disabled={runningAll || testCases.length === 0} onClick={() => void handleRunAll()} className="gap-1.5">
              {runningAll ? <Loader2 className="h-3 w-3 animate-spin" /> : <Play className="h-3 w-3" />}
              Run all
            </Button>
            <Button size="sm" onClick={() => setForm(EMPTY_FORM)} className="gap-1.5">
              <Plus className="h-3.5 w-3.5" /> New test case
            </Button>
          </div>
        </div>
        <p className="text-[12.5px] text-muted-foreground">Prompts run against this agent and scored by AgentCore evaluators.</p>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        {importOpen && (
          <ImportJsonPanel
            onApply={async (json) => {
              const err = await handleImportJson(json);
              if (!err) setImportOpen(false);
              return err;
            }}
            onCancel={() => setImportOpen(false)}
          />
        )}

        {error && <p className="text-sm text-destructive">{error}</p>}
        {loading && <Skeleton className="h-24" />}

        {!loading && testCases.length === 0 && (
          <div className="flex flex-col gap-3 py-6 text-center">
            <p className="text-sm text-muted-foreground">No test cases yet.</p>
            <ol className="mx-auto flex max-w-sm flex-col gap-1.5 text-left text-xs text-muted-foreground">
              <li>1. Write a prompt you expect the agent to handle well.</li>
              <li>2. Pick evaluators, or start from a preset.</li>
              <li>3. Run it now, or re-run all tests after each deploy.</li>
            </ol>
          </div>
        )}

        {!loading && testCases.length > 0 && (
          <div className="rounded-md border overflow-hidden">
            <Table className="table-fixed">
              <colgroup>
                <col style={{ width: 16 }} />
                <col />
                <col style={{ width: 84 }} />
                <col style={{ width: 110 }} />
                <col style={{ width: 56 }} />
                <col style={{ width: 92 }} />
              </colgroup>
              <TableHeader>
                <TableRow className="bg-card hover:bg-card">
                  <TableHead />
                  <TableHead>Test case</TableHead>
                  <TableHead>Evaluators</TableHead>
                  <TableHead>Last run</TableHead>
                  <TableHead>Score</TableHead>
                  <TableHead className="text-right">Result</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {testCases.map((tc) => (
                  <TestCaseRow
                    key={tc.id}
                    tc={tc}
                    expanded={expandedId === tc.id}
                    onToggle={() => {
                      // Expanding only loads run history — the latest-run
                      // state (and its ERROR/PASS/FAIL result) is already
                      // kept current by the effect above, keyed on the test
                      // case's batch evaluation id. Re-fetching it here too
                      // would flash the row to "running" and back on every
                      // expand even though nothing changed.
                      const next = expandedId === tc.id ? null : tc.id;
                      setExpandedId(next);
                      if (next !== null) void fetchRunHistory(tc);
                    }}
                    history={runHistory[tc.id]}
                    expandedRunId={expandedRunId}
                    onToggleRun={(batchEvaluationId) => {
                      const next = expandedRunId === batchEvaluationId ? null : batchEvaluationId;
                      setExpandedRunId(next);
                      if (next !== null && !historyRunStates[batchEvaluationId]) void fetchHistoryRunDetail(tc, batchEvaluationId);
                    }}
                    historyRunStates={historyRunStates}
                    onEdit={() => setForm({
                      id: tc.id,
                      name: tc.name,
                      prompt: tc.prompt,
                      expectedResponse: tc.expected_response ?? "",
                      evaluatorIds: tc.evaluator_ids,
                      passThreshold: String(tc.pass_threshold),
                      modelId: tc.model_id ?? "",
                    })}
                    onDelete={() => setDeleteTarget(tc)}
                    onRun={() => void handleRun(tc)}
                    onRescore={() => void handleRescore(tc)}
                    running={runningId === tc.id}
                    rescoring={rescoringId === tc.id}
                    deleting={deletingId === tc.id}
                    runState={runStates[tc.id]}
                    onOpenSession={onOpenSession}
                    logGroupUrl={runtimeId ? cloudWatchLogGroupUrl(region, agentLogGroupName(runtimeId)) : null}
                  />
                ))}
              </TableBody>
            </Table>
          </div>
        )}
        {!loading && testCases.length > 0 && (
          <p className="text-[12px] text-muted-foreground">
            Scores of 0.70 or higher pass by default. Click a row for evaluator details and run history.
          </p>
        )}
      </CardContent>
      <ConfirmDialog
        open={deleteTarget !== null}
        onOpenChange={(open) => { if (!open) setDeleteTarget(null); }}
        title="Delete test case"
        description={deleteTarget ? `Delete test case "${deleteTarget.name}"? This cannot be undone.` : ""}
        confirmLabel="Delete"
        onConfirm={() => {
          if (deleteTarget) void handleDelete(deleteTarget);
          setDeleteTarget(null);
        }}
      />
    </Card>
  );
}
