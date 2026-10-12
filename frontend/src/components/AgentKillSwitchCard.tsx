import { useCallback, useEffect, useId, useRef, useState } from "react";
import { OctagonX, Play, RefreshCw } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Skeleton } from "@/components/ui/skeleton";
import { StatusPill } from "@/components/StatusPill";
import { useTimezone } from "@/contexts/TimezoneContext";
import { useAuth } from "@/contexts/AuthContext";
import { trackAction } from "@/api/audit";
import { formatTimestamp } from "@/lib/format";
import type { BadgeVariant } from "@/lib/status";
import { getKillSwitchStatus, resumeAgent, stopAgent } from "@/api/killSwitch";
import type { KillSwitchEvent, KillSwitchState, KillSwitchStatus } from "@/api/types";

/** Kill switch for one agent.
 *
 * Stop adds a deny statement to the AgentCore Runtime's resource policy, so
 * every invocation of this runtime is refused whoever the caller is, and ends
 * the sessions Loom knows about; Resume removes the statement. Loom never
 * writes IAM. Both need a reason, which goes into the audit trail shown below.
 * The card compares Loom's record with the runtime's live policy and says so
 * when they disagree.
 */

const STATE_PILL: Record<KillSwitchState, { label: string; variant: BadgeVariant }> = {
  running: { label: "RUNNING", variant: "success" },
  stopped: { label: "STOPPED", variant: "destructive" },
  stop_not_enforced: { label: "NOT ENFORCED", variant: "warning" },
  stopped_outside_loom: { label: "DENIED OUTSIDE LOOM", variant: "warning" },
  unknown: { label: "UNKNOWN", variant: "neutral" },
  unavailable: { label: "UNAVAILABLE", variant: "neutral" },
};

const POLICY_CHANGE: Record<KillSwitchEvent["policy_change"], string> = {
  deny_added: "deny added",
  already_denied: "deny was already present",
  deny_removed: "deny removed",
  already_removed: "deny was already removed",
};

type Mode = "stop" | "resume";

function runtimeName(runtimeArn: string | null): string {
  return runtimeArn ? runtimeArn.split("/").pop() ?? runtimeArn : "—";
}

function sessionSummary(event: KillSwitchEvent): string | null {
  if (event.sessions.length === 0) return null;
  const count = (r: string) => event.sessions.filter((s) => s.result === r).length;
  const parts = [`${count("stopped")} session(s) stopped`];
  if (count("not_running")) parts.push(`${count("not_running")} already ended`);
  if (count("failed")) parts.push(`${count("failed")} not stopped`);
  return parts.join(", ");
}

interface AgentKillSwitchCardProps {
  agentId: number;
  agentName: string;
  /** agent:write — Stop and Resume are hidden without it. */
  canControl: boolean;
  /** Called after a successful Stop or Resume so the agent list refreshes. */
  onChanged?: () => void;
}

export function AgentKillSwitchCard({ agentId, agentName, canControl, onChanged }: AgentKillSwitchCardProps) {
  const { timezone } = useTimezone();
  const { user, browserSessionId } = useAuth();
  const reasonId = useId();
  const [status, setStatus] = useState<KillSwitchStatus | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [mode, setMode] = useState<Mode | null>(null);
  const [reason, setReason] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  // Only the latest request may update the card (agent switches, refresh races).
  const requestRef = useRef(0);

  const load = useCallback(async () => {
    const id = ++requestRef.current;
    try {
      const next = await getKillSwitchStatus(agentId);
      if (id === requestRef.current) {
        setStatus(next);
        setLoadError(null);
      }
    } catch (e) {
      if (id === requestRef.current) setLoadError(e instanceof Error ? e.message : "Failed to load the kill switch.");
    }
  }, [agentId]);

  useEffect(() => {
    setStatus(null);
    setLoadError(null);
    setMode(null);
    setReason("");
    setActionError(null);
    setNotice(null);
    void load();
  }, [load]);

  const openForm = (next: Mode) => {
    setMode(next);
    setReason("");
    setActionError(null);
    setNotice(null);
  };

  const submit = async () => {
    if (!mode || !reason.trim()) return;
    setSubmitting(true);
    setActionError(null);
    const action = mode;
    try {
      const call = action === "stop" ? stopAgent : resumeAgent;
      const result = await call(agentId, reason.trim());
      requestRef.current++; // a load still in flight is now stale
      setStatus(result.status);
      setNotice(result.message);
      setMode(null);
      setReason("");
      if (result.changed && user && browserSessionId) {
        trackAction(user.username ?? user.sub, browserSessionId, "agent", action, agentName);
      }
      onChanged?.();
    } catch (e) {
      setActionError(e instanceof Error ? e.message : "The request failed.");
    } finally {
      setSubmitting(false);
    }
  };

  const state = status?.state ?? null;
  const pill = state ? STATE_PILL[state] : null;
  const runtime = runtimeName(status?.runtime_arn ?? null);
  const canStop = state === "running" || state === "stop_not_enforced" || state === "stopped_outside_loom";
  const canResume = state === "stopped" || state === "stop_not_enforced" || state === "stopped_outside_loom";
  const showActions = canControl && mode === null;

  return (
    <Card className="gap-2.5 py-4">
      <CardHeader className="px-[18px]">
        <div className="flex items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            <CardTitle className="text-[13px] font-semibold">Kill switch</CardTitle>
            {pill && <StatusPill label={pill.label} variant={pill.variant} />}
          </div>
          <button
            type="button"
            onClick={() => void load()}
            className="text-muted-foreground/70 transition-colors hover:text-foreground"
            aria-label="Refresh the kill-switch state"
            title="Refresh"
          >
            <RefreshCw className="h-3.5 w-3.5" />
          </button>
        </div>
      </CardHeader>
      <CardContent className="flex flex-col gap-2.5 px-[18px]">
        {!status && !loadError && (
          <div className="flex flex-col gap-1.5" aria-busy="true">
            <Skeleton className="h-3 w-full" />
            <Skeleton className="h-3 w-2/3" />
          </div>
        )}
        {loadError && <p role="alert" className="text-[12.5px] text-destructive">{loadError}</p>}

        {status && state === "unavailable" && (
          <p className="text-[12.5px] leading-[1.55] text-muted-foreground">{status.unavailable_reason}</p>
        )}
        {status && state === "running" && (
          <p className="text-[12.5px] leading-[1.55] text-muted-foreground">
            Stopping adds a deny to runtime <span className="font-mono text-foreground">{runtime}</span>'s resource
            policy, so nobody can invoke it, through Loom or directly, and ends its active sessions. Nothing is
            deleted; Resume restores it without a redeploy.
          </p>
        )}
        {status && (state === "stopped" || state === "stop_not_enforced") && (
          <div className="flex flex-col gap-1 rounded-md border border-destructive/30 bg-destructive/10 px-2.5 py-2">
            <span className="font-mono text-[10.5px] text-muted-foreground">
              Stopped by {status.stopped_by ?? "an operator"} · {formatTimestamp(status.stopped_at, timezone)}
            </span>
            <p className="text-[12.5px] leading-snug">{status.stop_reason}</p>
          </div>
        )}
        {status && state === "stopped" && (
          <p className="text-[12.5px] leading-[1.55] text-muted-foreground">
            Runtime <span className="font-mono text-foreground">{runtime}</span>'s resource policy denies every
            invocation, from any caller, until it is resumed.
          </p>
        )}
        {status && state === "stop_not_enforced" && (
          <p className="text-[12.5px] leading-[1.55] text-warning">
            The deny is no longer in <span className="font-mono">{runtime}</span>'s resource policy: the agent can be
            invoked. Stop again to re-apply it, or Resume to clear the record.
          </p>
        )}
        {status && state === "stopped_outside_loom" && (
          <p className="text-[12.5px] leading-[1.55] text-warning">
            Loom's deny is in <span className="font-mono">{runtime}</span>'s resource policy but Loom recorded no
            stop, so nobody can invoke the agent. Resume to remove it, or Stop to record it.
          </p>
        )}
        {status && state === "unknown" && (
          <p className="text-[12.5px] leading-[1.55] text-warning">
            Could not read <span className="font-mono">{runtime}</span>'s resource policy: {status.policy_error}
          </p>
        )}

        {notice && <p role="status" className="text-[12px] leading-[1.5] text-foreground">{notice}</p>}

        {status && showActions && (canStop || canResume) && (
          <div className="flex flex-wrap gap-2">
            {canStop && (
              <Button size="sm" variant="destructive" className="h-7 text-xs" onClick={() => openForm("stop")}>
                <OctagonX className="h-3.5 w-3.5" />
                Stop agent…
              </Button>
            )}
            {canResume && (
              <Button size="sm" variant="outline" className="h-7 text-xs" onClick={() => openForm("resume")}>
                <Play className="h-3.5 w-3.5" />
                Resume agent…
              </Button>
            )}
          </div>
        )}

        {mode && (
          <form
            className="flex flex-col gap-2 rounded-md border px-2.5 py-2.5"
            onSubmit={(e) => {
              e.preventDefault();
              void submit();
            }}
          >
            <label htmlFor={reasonId} className="text-[11.5px] font-medium">
              {mode === "stop" ? "Why are you stopping this agent?" : "Why is it safe to resume?"}
              <span className="font-normal text-muted-foreground"> (required, kept in the audit trail)</span>
            </label>
            <Textarea
              id={reasonId}
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              rows={3}
              maxLength={500}
              required
              autoFocus
              className="resize-none text-xs"
              placeholder={mode === "stop" ? "e.g. answers leak customer data, under investigation" : "e.g. prompt fixed and re-tested"}
            />
            {actionError && <p role="alert" className="text-[11.5px] text-destructive">{actionError}</p>}
            <div className="flex gap-2">
              <Button
                type="submit"
                size="sm"
                variant={mode === "stop" ? "destructive" : "default"}
                className="h-7 text-xs"
                disabled={submitting || !reason.trim()}
              >
                {submitting ? (mode === "stop" ? "Stopping…" : "Resuming…") : mode === "stop" ? "Stop agent" : "Resume agent"}
              </Button>
              <Button type="button" size="sm" variant="ghost" className="h-7 text-xs" onClick={() => setMode(null)} disabled={submitting}>
                Cancel
              </Button>
            </div>
          </form>
        )}

        {status && status.events.length > 0 && (
          <div className="flex flex-col gap-1.5">
            <span className="font-mono text-[9.5px] tracking-wide text-muted-foreground uppercase">History</span>
            <ul className="flex flex-col gap-2">
              {status.events.slice(0, 5).map((event) => (
                <li
                  key={event.id}
                  className={`flex flex-col gap-0.5 border-l-2 pl-2 ${event.action === "stop" ? "border-destructive/60" : "border-success/60"}`}
                >
                  <div className="flex items-center justify-between gap-2 font-mono text-[10.5px] text-muted-foreground">
                    <span>{event.action === "stop" ? "Stopped" : "Resumed"} · {event.actor}</span>
                    <span>{formatTimestamp(event.created_at, timezone)}</span>
                  </div>
                  <p className="text-[12px] leading-snug">{event.reason}</p>
                  <p
                    className="truncate font-mono text-[10px] text-muted-foreground"
                    title={`AgentCore request ${event.request_id ?? "—"}`}
                  >
                    {POLICY_CHANGE[event.policy_change] ?? event.policy_change}
                    {event.request_id ? ` · request ${event.request_id}` : ""}
                    {sessionSummary(event) ? ` · ${sessionSummary(event)}` : ""}
                  </p>
                </li>
              ))}
            </ul>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
