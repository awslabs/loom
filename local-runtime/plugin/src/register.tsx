import type { LoomExtensionHost } from "./host-types";
import { LocalRuntimePage } from "./pages/LocalRuntimePage";
import { Server } from "lucide-react";

/**
 * Loom Extension Host entry (ADR 0006).
 * Only UI — backends live under local-runtime/services/.
 */
export function register(host: LoomExtensionHost): void {
  host.addExtension({
    id: "local-runtime",
    nav: {
      section: "build",
      label: "Local runtime",
      icon: Server,
      requiredScopes: ["mcp:read"],
    },
    render: ({ hasScope }) => (
      <LocalRuntimePage
        canWrite={hasScope("mcp:write")}
        canRead={hasScope("mcp:read")}
      />
    ),
  });
}

export default register;
