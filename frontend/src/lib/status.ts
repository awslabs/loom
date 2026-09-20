export type BadgeVariant = "default" | "secondary" | "destructive" | "outline" | "neutral" | "warning" | "success";

export function statusVariant(status: string | null): BadgeVariant {
  switch (status) {
    case "ACTIVE":
    case "READY":
      return "success";
    case "CREATING":
    case "UPDATING":
    case "DELETING":
      return "neutral";
    case "FAILED":
    case "CREATE_FAILED":
      return "destructive";
    default:
      return "neutral";
  }
}

export function deploymentStatusVariant(status: string | null): BadgeVariant {
  switch (status) {
    case "deployed":
    case "READY":
      return "success";
    case "initializing":
    case "creating_credentials":
    case "creating_role":
    case "building_artifact":
    case "deploying":
    case "ENDPOINT_CREATING":
      return "warning";
    case "failed":
    case "credential_creation_failed":
      return "destructive";
    case "removing":
      return "neutral";
    default:
      return "neutral";
  }
}

export function registryStatusVariant(status: string | null): BadgeVariant {
  switch (status) {
    case "APPROVED":
      return "success";
    case "PENDING_APPROVAL":
      return "warning";
    case "REJECTED":
      return "destructive";
    case "DRAFT":
    case "DEPRECATED":
      return "neutral";
    default:
      return "neutral";
  }
}

/** Dot color class for a given semantic badge variant, used by StatusDot. */
export function statusDotClass(variant: BadgeVariant): string {
  switch (variant) {
    case "success": return "bg-success";
    case "warning": return "bg-warning";
    case "destructive": return "bg-destructive";
    default: return "bg-status-neutral";
  }
}
