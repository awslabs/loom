import { Badge } from "@/components/ui/badge";

type RegistryStatus = "DRAFT" | "PENDING_APPROVAL" | "APPROVED" | "REJECTED" | "DEPRECATED" | null;

function registryVariant(status: RegistryStatus): "default" | "secondary" | "destructive" | "outline" {
  switch (status) {
    case "APPROVED": return "default";
    case "PENDING_APPROVAL": return "default";
    case "REJECTED": return "destructive";
    case "DRAFT": return "default";
    case "DEPRECATED": return "outline";
    default: return "outline";
  }
}

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

export function RegistryStatusBadge({ status, showUnregistered = false, registryEnabled = true }: RegistryStatusBadgeProps) {
  if (!registryEnabled) return null;
  if (!status && !showUnregistered) return null;

  const variant = registryVariant(status as RegistryStatus);
  const label = registryLabel(status as RegistryStatus);

  return (
    <Badge variant={variant} className={`text-[10px] px-1.5 py-0 shrink-0${status === "DEPRECATED" ? " line-through" : ""}`}>
      {label}
    </Badge>
  );
}
