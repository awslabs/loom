import { useState, useEffect, useRef } from "react";
import { Button } from "@/components/ui/button";
import { Loader2 } from "lucide-react";
import { toast } from "sonner";
import * as registryApi from "@/api/registry";
import type { McpNamespace, RegistryRecordCreateRequest } from "@/api/types";

const MCP_NAMESPACES: { value: McpNamespace; label: string }[] = [
  { value: "aws.agentcore", label: "aws.agentcore" },
  { value: "remote.mcp", label: "remote.mcp" },
  { value: "npm", label: "npm" },
  { value: "custom", label: "custom" },
];

interface RegistryActionsProps {
  resourceType: "mcp" | "a2a" | "agent" | "skill";
  resourceId: number;
  registryRecordId: string | null;
  registryStatus: string | null;
  onAction: () => void;  // callback to refresh parent data
}

export function RegistryActions({ resourceType, resourceId, registryRecordId, registryStatus, onAction }: RegistryActionsProps) {
  const [loading, setLoading] = useState(false);
  const [creating, setCreating] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [approving, setApproving] = useState(false);
  const [rejecting, setRejecting] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const [rejectReason, setRejectReason] = useState("");
  const [showRejectInput, setShowRejectInput] = useState(false);
  const [approveReason, setApproveReason] = useState("");
  const [showApproveInput, setShowApproveInput] = useState(false);
  const [namespace, setNamespace] = useState<McpNamespace>("aws.agentcore");

  const timerActive = creating || submitting || approving || rejecting;
  useEffect(() => {
    if (timerActive) {
      setElapsed(0);
      timerRef.current = setInterval(() => setElapsed((s) => s + 1), 1000);
    } else {
      if (timerRef.current) { clearInterval(timerRef.current); timerRef.current = null; }
    }
    return () => { if (timerRef.current) { clearInterval(timerRef.current); timerRef.current = null; } };
  }, [timerActive]);

  useEffect(() => {
    if (creating && (registryRecordId || registryStatus)) {
      setCreating(false);
    }
  }, [creating, registryRecordId, registryStatus]);

  useEffect(() => {
    if (submitting && registryStatus !== "DRAFT") {
      setSubmitting(false);
    }
  }, [submitting, registryStatus]);

  useEffect(() => {
    if ((approving || rejecting) && registryStatus !== "PENDING_APPROVAL") {
      setApproving(false);
      setRejecting(false);
    }
  }, [approving, rejecting, registryStatus]);

  const handleAction = async (action: () => Promise<void>, successMsg: string): Promise<boolean> => {
    setLoading(true);
    try {
      await action();
      toast.success(successMsg);
      onAction();
      return true;
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Registry action failed");
      return false;
    } finally {
      setLoading(false);
    }
  };

  if (!registryRecordId && !registryStatus) {
    // A skill *is* a registry record from the moment it's created (there's
    // no separate Loom resource to "register" it from, unlike mcp/a2a/agent)
    // — this branch should never be reached for one.
    if (resourceType === "skill") return null;
    return (
      <div className="flex items-center gap-1.5" onClick={(e) => e.stopPropagation()}>
        {resourceType === "mcp" && (
          <select
            value={namespace}
            onChange={(e) => setNamespace(e.target.value as McpNamespace)}
            className="h-6 text-xs border rounded px-1 bg-input-bg"
            disabled={loading || creating}
          >
            {MCP_NAMESPACES.map((ns) => (
              <option key={ns.value} value={ns.value}>{ns.label}</option>
            ))}
          </select>
        )}
        <Button
          size="sm"
          variant="outline"
          className="h-6 text-xs w-[5.5rem] justify-center"
          disabled={loading || creating}
          onClick={() => {
            setCreating(true);
            const req: RegistryRecordCreateRequest = {
              resource_type: resourceType,
              resource_id: resourceId,
              ...(resourceType === "mcp" ? { namespace } : {}),
            };
            void handleAction(
              () => registryApi.createRegistryRecord(req).then(() => {}),
              "Registered in registry"
            ).then((ok) => { if (!ok) setCreating(false); });
          }}
        >
          {creating ? <Loader2 className="h-3 w-3 animate-spin" /> : "Register"}
        </Button>
        {creating && (
          <span className="text-[10px] text-muted-foreground tabular-nums">Registering ({elapsed}s)</span>
        )}
      </div>
    );
  }

  if (registryStatus === "DRAFT" && registryRecordId) {
    return (
      <div className="flex items-center gap-1.5">
        <Button
          size="sm"
          variant="outline"
          className="h-6 text-xs w-[8.5rem] justify-center"
          disabled={loading || submitting}
          onClick={(e) => {
            e.stopPropagation();
            setSubmitting(true);
            void handleAction(() => registryApi.submitForApproval(registryRecordId), "Submitted for approval")
              .then((ok) => { if (!ok) setSubmitting(false); });
          }}
        >
          {submitting ? <Loader2 className="h-3 w-3 animate-spin" /> : "Submit for Approval"}
        </Button>
        {submitting && (
          <span className="text-[10px] text-muted-foreground tabular-nums">Submitting ({elapsed}s)</span>
        )}
      </div>
    );
  }

  if (registryStatus === "PENDING_APPROVAL" && registryRecordId) {
    const actionInProgress = approving || rejecting;
    if (actionInProgress) {
      return (
        <div className="flex items-center gap-1.5">
          <Button
            size="sm"
            variant="outline"
            className="h-6 text-xs w-[5rem] justify-center"
            disabled
          >
            <Loader2 className="h-3 w-3 animate-spin" />
          </Button>
          <span className="text-[10px] text-muted-foreground tabular-nums">
            {approving ? "Approving" : "Rejecting"} ({elapsed}s)
          </span>
        </div>
      );
    }
    const showReasonInput = showApproveInput || showRejectInput;
    const reason = showApproveInput ? approveReason : rejectReason;
    const setReason = showApproveInput ? setApproveReason : setRejectReason;
    const cancel = () => {
      setShowApproveInput(false);
      setShowRejectInput(false);
      setApproveReason("");
      setRejectReason("");
    };
    return (
      <div className="flex flex-col gap-1 w-full min-w-0" onClick={(e) => e.stopPropagation()}>
        {showReasonInput && (
          <input
            type="text"
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            placeholder="Reason..."
            className="h-6 text-xs border rounded px-1.5 bg-input-bg w-full"
            autoFocus
          />
        )}
        <div className="flex items-center gap-1 flex-wrap">
          <Button
            size="sm"
            variant="outline"
            className="h-6 text-xs"
            disabled={loading || (showApproveInput && !approveReason.trim())}
            onClick={() => {
              if (!showApproveInput) {
                setShowApproveInput(true);
                setShowRejectInput(false);
                return;
              }
              setApproving(true);
              void handleAction(() => registryApi.approveRecord(registryRecordId, approveReason.trim()), "Record approved")
                .then((ok) => { if (!ok) setApproving(false); });
            }}
          >
            {showApproveInput ? "Confirm" : "Approve"}
          </Button>
          <Button
            size="sm"
            variant="outline"
            className="h-6 text-xs text-destructive"
            disabled={loading || (showRejectInput && !rejectReason.trim())}
            onClick={() => {
              if (!showRejectInput) {
                setShowRejectInput(true);
                setShowApproveInput(false);
                return;
              }
              setRejecting(true);
              void handleAction(() => registryApi.rejectRecord(registryRecordId, rejectReason.trim()), "Record rejected")
                .then((ok) => { if (!ok) setRejecting(false); });
            }}
          >
            {showRejectInput ? "Confirm" : "Reject"}
          </Button>
          {showReasonInput && (
            <Button size="sm" variant="ghost" className="h-6 text-xs" onClick={cancel}>
              Cancel
            </Button>
          )}
        </div>
      </div>
    );
  }

  if (registryStatus === "APPROVED" && registryRecordId) {
    return (
      <Button
        size="sm"
        variant="outline"
        className="h-6 text-xs"
        disabled={loading}
        onClick={(e) => {
          e.stopPropagation();
          handleAction(() => registryApi.rejectRecord(registryRecordId, "Deprecated").then(() => {}), "Record deprecated");
        }}
      >
        Deprecate
      </Button>
    );
  }

  if ((registryStatus === "REJECTED" || registryStatus === "DEPRECATED") && registryRecordId) {
    return (
      <Button
        size="sm"
        variant="outline"
        className="h-6 text-xs"
        disabled={loading}
        onClick={(e) => {
          e.stopPropagation();
          handleAction(() => registryApi.deleteRegistryRecord(registryRecordId), "Removed from registry");
        }}
      >
        Remove from Registry
      </Button>
    );
  }

  return null;
}
