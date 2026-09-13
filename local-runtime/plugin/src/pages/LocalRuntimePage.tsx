type Props = {
  canRead: boolean;
  canWrite: boolean;
};

/**
 * Ops surface for local-runtime backends.
 * MCP stdio catalog CRUD still uses Loom Integrations until forms move here.
 */
export function LocalRuntimePage({ canRead, canWrite }: Props) {
  return (
    <div className="space-y-6 max-w-3xl">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Local runtime</h1>
        <p className="text-sm text-muted-foreground mt-1">
          Extension plugin (ADR 0006). UI runs inside the Loom shell; compute runs in
          apart backends under <code className="text-xs">local-runtime/services/</code>.
        </p>
      </div>

      <section className="rounded-lg border bg-card p-4 space-y-2 text-sm">
        <h2 className="font-medium">Backends</h2>
        <ul className="list-disc pl-5 space-y-1 text-muted-foreground">
          <li>
            <strong className="text-foreground">mcp-runtime</strong> — stdio MCP facade
            (:8787). Templates in <code className="text-xs">local-runtime/templates/</code>.
          </li>
          <li>
            <strong className="text-foreground">cursor-adapter</strong> — LiteLLM CustomLLM
            (:8765).
          </li>
          <li>
            <strong className="text-foreground">agent-runtime</strong> — deferred (ADR 0005).
            Local invoke still uses the Loom LiteLLM shortcut until this ships.
          </li>
        </ul>
      </section>

      <section className="rounded-lg border bg-card p-4 space-y-2 text-sm">
        <h2 className="font-medium">What to use where</h2>
        <p className="text-muted-foreground">
          Register and refresh Azure DevOps (and other stdio) MCP servers under{" "}
          <strong className="text-foreground">Integrations → MCP</strong>. That catalog
          still lives in Loom for now; this page is the extension home and will grow
          ops/forms as they move out of core.
        </p>
        <p className="text-muted-foreground">
          Access: {canRead ? "mcp:read" : "no mcp:read"}
          {canWrite ? " · mcp:write" : ""}.
        </p>
      </section>
    </div>
  );
}
