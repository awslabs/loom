export type BadgeVariant = "default" | "secondary" | "destructive" | "outline";

export function statusVariant(status: string | null): BadgeVariant {
  switch (status) {
    case "ACTIVE":
    case "READY":
      return "default";
    case "CREATING":
    case "UPDATING":
    case "DELETING":
      return "outline";
    case "FAILED":
    case "CREATE_FAILED":
      return "destructive";
    default:
      return "outline";
  }
}

export function deploymentStatusVariant(status: string | null): BadgeVariant {
  switch (status) {
    case "deployed":
    case "READY":
      return "default";
    case "initializing":
    case "creating_credentials":
    case "creating_role":
    case "building_artifact":
    case "deploying":
    case "ENDPOINT_CREATING":
      return "secondary";
    case "failed":
    case "credential_creation_failed":
      return "destructive";
    case "removing":
      return "outline";
    default:
      return "outline";
  }
}

export function registryStatusVariant(status: string | null): BadgeVariant {
  switch (status) {
    case "APPROVED":
      return "default";
    case "PENDING_APPROVAL":
      return "secondary";
    case "REJECTED":
      return "destructive";
    case "DRAFT":
    case "DEPRECATED":
      return "outline";
    default:
      return "outline";
  }
}
