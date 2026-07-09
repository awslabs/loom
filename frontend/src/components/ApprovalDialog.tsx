import { useState, useEffect } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ShieldCheck, ShieldX, Clock, CheckCircle, XCircle } from "lucide-react";
import { submitApprovalDecision } from "@/api/approvals";
import type { SSEApprovalRequest, SSEApprovalResolved } from "@/api/types";

export function ApprovalRequestBubble({
  data,
  onDecided,
  resolved,
}: {
  data: SSEApprovalRequest;
  onDecided?: (requestId: string, decision: string) => void;
  resolved?: boolean;
}) {
  const [decision, setDecision] = useState<string | null>(resolved ? "approved" : null);
  const [reason, setReason] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showReason, setShowReason] = useState(false);
  const [elapsed, setElapsed] = useState(0);

  useEffect(() => {
    if (decision) return;
    const start = Date.now();
    const id = setInterval(() => setElapsed(Math.floor((Date.now() - start) / 1000)), 1000);
    return () => clearInterval(id);
  }, [decision]);

  const isNotifyOnly = data.approval_mode === "notify_only";

  const handleDecision = async (d: "approved" | "rejected") => {
    setSubmitting(true);
    setError(null);
    try {
      await submitApprovalDecision(data.request_id, d, reason || undefined);
      setDecision(d);
      onDecided?.(data.request_id, d);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to submit decision. Try again.");
    } finally {
      setSubmitting(false);
    }
  };

  if (isNotifyOnly) {
    return (
      <div className="flex justify-start">
        <div className="max-w-full rounded-2xl px-4 py-3 text-sm bg-blue-50 dark:bg-blue-950/30 border border-blue-200 dark:border-blue-800">
          <div className="flex items-center gap-2 text-blue-700 dark:text-blue-300 mb-1">
            <ShieldCheck className="h-4 w-4 shrink-0" />
            <span className="font-medium text-xs uppercase tracking-wide">Tool Notification</span>
          </div>
          <p className="text-xs">
            <span className="font-medium">{data.tool_name}</span>
            {data.policy_name && (
              <span className="text-muted-foreground ml-1">({data.policy_name})</span>
            )}
          </p>
          {data.tool_input_summary && (
            <p className="text-xs text-muted-foreground mt-1 font-mono break-all line-clamp-3">
              {data.tool_input_summary}
            </p>
          )}
        </div>
      </div>
    );
  }

  return (
    <div className="flex justify-start">
      <div className="max-w-full rounded-2xl px-4 py-3 text-sm bg-amber-50 dark:bg-amber-950/30 border border-amber-200 dark:border-amber-800">
        <div className="flex items-center gap-2 text-amber-700 dark:text-amber-300 mb-1">
          <ShieldCheck className="h-4 w-4 shrink-0" />
          <span className="font-medium text-xs uppercase tracking-wide">Approval Required</span>
          {!decision && (
            <span className="text-xs text-muted-foreground ml-auto flex items-center gap-1">
              <Clock className="h-3 w-3" />
              {elapsed}s / {data.timeout_seconds}s
            </span>
          )}
        </div>
        <p className="text-xs">
          <span className="font-medium">{data.tool_name}</span>
          {data.policy_name && (
            <span className="text-muted-foreground ml-1">({data.policy_name})</span>
          )}
        </p>
        {data.tool_input_summary && (
          <p className="text-xs text-muted-foreground mt-1 font-mono break-all line-clamp-3">
            {data.tool_input_summary}
          </p>
        )}

        {error && (
          <p className="mt-1 text-xs text-red-600 dark:text-red-400">{error}</p>
        )}

        {decision ? (
          <div className={`mt-2 flex items-center gap-1.5 text-xs font-medium ${
            decision === "approved"
              ? "text-green-700 dark:text-green-400"
              : "text-red-700 dark:text-red-400"
          }`}>
            {decision === "approved" ? (
              <CheckCircle className="h-3.5 w-3.5" />
            ) : (
              <XCircle className="h-3.5 w-3.5" />
            )}
            {decision === "approved" ? "Approved" : "Rejected"}
          </div>
        ) : (
          <div className="mt-2 space-y-2">
            {showReason && (
              <Input
                placeholder="Reason (optional)"
                value={reason}
                onChange={(e) => setReason(e.target.value)}
                className="text-xs h-7"
              />
            )}
            <div className="flex items-center gap-2">
              <Button
                size="sm"
                variant="outline"
                className="h-7 text-xs border-green-300 dark:border-green-700 text-green-700 dark:text-green-400 hover:bg-green-50 dark:hover:bg-green-900/30"
                onClick={() => void handleDecision("approved")}
                disabled={submitting}
              >
                <CheckCircle className="h-3 w-3 mr-1" />
                Approve
              </Button>
              <Button
                size="sm"
                variant="outline"
                className="h-7 text-xs border-red-300 dark:border-red-700 text-red-700 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-900/30"
                onClick={() => {
                  if (!showReason) {
                    setShowReason(true);
                  } else {
                    void handleDecision("rejected");
                  }
                }}
                disabled={submitting}
              >
                <XCircle className="h-3 w-3 mr-1" />
                Reject
              </Button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

export function ApprovalResolvedBubble({ data }: { data: SSEApprovalResolved }) {
  const isApproved = data.status === "approved";
  return (
    <div className="flex justify-start">
      <div className={`rounded-2xl px-4 py-2 text-xs border ${
        isApproved
          ? "bg-green-50 dark:bg-green-950/30 border-green-200 dark:border-green-800"
          : "bg-red-50 dark:bg-red-950/30 border-red-200 dark:border-red-800"
      }`}>
        <div className="flex items-center gap-1.5">
          {isApproved ? (
            <CheckCircle className="h-3.5 w-3.5 text-green-600 dark:text-green-400" />
          ) : (
            <ShieldX className="h-3.5 w-3.5 text-red-600 dark:text-red-400" />
          )}
          <span className={`font-medium ${
            isApproved
              ? "text-green-700 dark:text-green-400"
              : "text-red-700 dark:text-red-400"
          }`}>
            {isApproved ? "Approved" : data.status === "timeout" ? "Timed out" : "Rejected"}
          </span>
          {data.decided_by && (
            <span className="text-muted-foreground">by {data.decided_by}</span>
          )}
        </div>
        {data.reason && (
          <p className="text-muted-foreground mt-0.5">{data.reason}</p>
        )}
      </div>
    </div>
  );
}
