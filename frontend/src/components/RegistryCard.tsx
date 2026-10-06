import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { RegistryActions } from "@/components/RegistryActions";

/** Sidebar Registry card, shared by the MCP server and A2A agent detail views.
 *
 * Built once and rendered on both so the two pages cannot drift: same padding,
 * border, radius, status pill and left accent, with full-width actions. Only
 * the one-line explanation differs between the two kinds.
 *
 * Lifecycle actions belong here rather than in the page header — the header
 * carries operational actions (edit, refresh, delete) while approval state is
 * the card's whole purpose.
 */

type RegistryKind = "mcp" | "a2a";

interface RegistryCardProps {
  kind: RegistryKind;
  resourceId: number;
  registryRecordId: string | null;
  registryStatus: string | null;
  /** Reason an approver gave, when the record carries one. */
  statusReason?: string | null;
  /** False in read-only mode or when the registry is disabled. */
  canManage: boolean;
  onAction: () => void;
}

const STATUS_LABELS: Record<string, string> = {
  DRAFT: "Draft",
  PENDING_APPROVAL: "Pending review",
  APPROVED: "Approved",
  REJECTED: "Rejected",
  DEPRECATED: "Deprecated",
};

const STATUS_PILL: Record<string, string> = {
  DRAFT: "bg-muted text-muted-foreground border-border",
  PENDING_APPROVAL: "bg-warning-bg text-warning border-warning/40",
  APPROVED: "bg-success-bg text-success border-success/40",
  REJECTED: "bg-destructive/10 text-destructive border-destructive/40",
  DEPRECATED: "bg-muted text-muted-foreground border-border",
};

function explanation(kind: RegistryKind, status: string | null): string {
  switch (status) {
    case "DRAFT":
      return kind === "mcp"
        ? "Only you can use it until it's approved. Submit it so agents can attach this server."
        : "Only you can use it until it's approved. Submit it so other agents can delegate to it.";
    case "PENDING_APPROVAL":
      return kind === "mcp"
        ? "Agents can't attach this server until an admin approves it."
        : "Agents can't delegate to this peer until an admin approves it.";
    case "APPROVED":
      return kind === "mcp"
        ? "Approved — agents can attach this server."
        : "Approved — agents can delegate to this peer.";
    case "REJECTED":
      return "Rejected. Address the feedback and resubmit for approval.";
    case "DEPRECATED":
      return "Deprecated. Existing attachments keep working; new ones are discouraged.";
    default:
      return "Not yet registered in the catalog registry.";
  }
}

export function RegistryCard({
  kind,
  resourceId,
  registryRecordId,
  registryStatus,
  statusReason,
  canManage,
  onAction,
}: RegistryCardProps) {
  return (
    <Card className="gap-2.5 py-4">
      <CardHeader className="px-[18px]">
        <div className="flex items-center gap-2">
          <CardTitle className="text-[13px] font-semibold">Registry</CardTitle>
          {registryStatus && (
            <span
              className={`ml-auto rounded-full border px-2 py-0.5 text-[10px] font-medium tracking-wide uppercase ${
                STATUS_PILL[registryStatus] ?? "bg-muted text-muted-foreground border-border"
              }`}
            >
              {STATUS_LABELS[registryStatus] ?? registryStatus}
            </span>
          )}
        </div>
      </CardHeader>
      <CardContent className="flex flex-col gap-2.5 px-[18px]">
        <p className="text-[12.5px] leading-[1.55] text-muted-foreground">
          {explanation(kind, registryStatus)}
        </p>
        {statusReason && (
          <p className="text-[12.5px] leading-[1.55] text-muted-foreground">{statusReason}</p>
        )}
        {canManage && (
          <RegistryActions
            layout="card"
            resourceType={kind}
            resourceId={resourceId}
            registryRecordId={registryRecordId}
            registryStatus={registryStatus}
            onAction={onAction}
          />
        )}
      </CardContent>
    </Card>
  );
}
