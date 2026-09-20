import { registryStatusVariant, statusDotClass } from "@/lib/status";

type RegistryStatus = "DRAFT" | "PENDING_APPROVAL" | "APPROVED" | "REJECTED" | "DEPRECATED" | null;

function registryLabel(status: RegistryStatus): string {
  switch (status) {
    case "PENDING_APPROVAL": return "PENDING";
    case "APPROVED": return "APPROVED";
    case "REJECTED": return "REJECTED";
    case "DRAFT": return "DRAFT";
    case "DEPRECATED": return "DEPRECATED";
    default: return "UNREGISTERED";
  }
}

interface RegistryStatusBadgeProps {
  status: string | null;
  showUnregistered?: boolean;
  registryEnabled?: boolean;
}

/** Lifecycle status as a dot + label pill, colored by semantic variant (not the interactive accent). */
export function RegistryStatusBadge({ status, showUnregistered = false, registryEnabled = true }: RegistryStatusBadgeProps) {
  if (!registryEnabled) return null;
  if (!status && !showUnregistered) return null;

  const variant = registryStatusVariant(status as RegistryStatus);
  const label = registryLabel(status as RegistryStatus);

  return (
    <span
      className={`inline-flex shrink-0 items-center gap-1 rounded-full border border-transparent px-1.5 py-0.5 text-[10px] font-medium tracking-wide ${
        variant === "success" ? "bg-success-bg text-success"
        : variant === "warning" ? "bg-warning-bg text-warning"
        : variant === "destructive" ? "bg-destructive/10 text-destructive"
        : "bg-status-neutral-bg text-status-neutral"
      }${status === "DEPRECATED" ? " line-through" : ""}`}
    >
      <span className={`h-1.5 w-1.5 shrink-0 rounded-full ${statusDotClass(variant)}`} />
      {label}
    </span>
  );
}
