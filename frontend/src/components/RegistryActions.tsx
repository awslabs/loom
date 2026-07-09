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
  resourceType: "mcp" | "a2a" | "agent";
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
    return (
      <div className="flex items-center gap-1" onClick={(e) => e.stopPropagation()}>
        {!showApproveInput ? (
          <Button
            size="sm"
            variant="outline"
            className="h-6 text-xs"
            disabled={loading}
            onClick={() => { setShowApproveInput(true); setShowRejectInput(false); }}
          >
            Approve
          </Button>
        ) : (
          <div className="flex items-center gap-1">
            <input
              type="text"
              value={approveReason}
              onChange={(e) => setApproveReason(e.target.value)}
              placeholder="Reason..."
              className="h-6 text-xs border rounded px-1.5 bg-input-bg w-[30rem]"
            />
            <Button
              size="sm"
              variant="outline"
              className="h-6 text-xs"
              disabled={loading || !approveReason.trim()}
              onClick={() => {
                setApproving(true);
                void handleAction(() => registryApi.approveRecord(registryRecordId, approveReason.trim()), "Record approved")
                  .then((ok) => { if (!ok) setApproving(false); });
              }}
            >
              Confirm
            </Button>
            <Button
              size="sm"
              variant="ghost"
              className="h-6 text-xs"
              onClick={() => { setShowApproveInput(false); setApproveReason(""); }}
            >
              Cancel
            </Button>
          </div>
        )}
        {!showRejectInput ? (
          <Button
            size="sm"
            variant="outline"
            className="h-6 text-xs text-destructive"
            disabled={loading}
            onClick={() => { setShowRejectInput(true); setShowApproveInput(false); }}
          >
            Reject
          </Button>
        ) : (
          <div className="flex items-center gap-1">
            <input
              type="text"
              value={rejectReason}
              onChange={(e) => setRejectReason(e.target.value)}
              placeholder="Reason..."
              className="h-6 text-xs border rounded px-1.5 bg-input-bg w-[30rem]"
            />
            <Button
              size="sm"
              variant="destructive"
              className="h-6 text-xs"
              disabled={loading || !rejectReason.trim()}
              onClick={() => {
                setRejecting(true);
                void handleAction(() => registryApi.rejectRecord(registryRecordId, rejectReason.trim()), "Record rejected")
                  .then((ok) => { if (!ok) setRejecting(false); });
              }}
            >
              Confirm
            </Button>
            <Button
              size="sm"
              variant="ghost"
              className="h-6 text-xs"
              onClick={() => { setShowRejectInput(false); setRejectReason(""); }}
            >
              Cancel
            </Button>
          </div>
        )}
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
