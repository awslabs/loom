import { useState } from "react";
import { apiFetch, ApiError } from "@/api/client";

type Props = {
  canRead: boolean;
  canWrite: boolean;
};

type HubMint = {
  hub_session_token: string;
  hub_session_id: string;
  mcp_hub_url: string;
  expires_at: string;
  contract_version: string;
};

/**
 * Ops surface for local-runtime backends.
 * MCP stdio catalog CRUD still uses Loom Integrations until forms move here.
 */
export function LocalRuntimePage({ canRead, canWrite }: Props) {
  const [mint, setMint] = useState<HubMint | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function mintHubSession() {
    setBusy(true);
    setError(null);
    try {
      const data = await apiFetch<HubMint>("/api/mcp/hub/sessions", {
        method: "POST",
        body: JSON.stringify({ client_label: "local-runtime-ui" }),
      });
      setMint(data);
    } catch (err) {
      if (err instanceof ApiError) {
        setError(`Mint failed (${err.status}): ${err.detail.slice(0, 200)}`);
      } else {
        setError(err instanceof Error ? err.message : "Mint failed");
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-6 max-w-3xl">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Local runtime</h1>
        <p className="text-sm text-muted-foreground mt-1">
          Extension plugin (ADR 0006). UI runs inside the Loom shell; compute runs in
          separate backends under <code className="text-xs">local-runtime/services/</code>.
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
            <strong className="text-foreground">mcp-hub</strong> — user-facing MCP
            (:8790) with Hub session (ADR 0007). Tools only in phase 1.
          </li>
          <li>
            <strong className="text-foreground">cursor-adapter</strong> — LiteLLM CustomLLM
            (:8765).
          </li>
          <li>
            <strong className="text-foreground">agent-runtime</strong> — tool loop
            (:8766). <code className="text-xs">cursor-local</code> = planner
            (devolve <code className="text-xs">tool_calls</code>); MCP executa aqui,
            não no Cursor SDK.
          </li>
        </ul>
      </section>

      <section className="rounded-lg border bg-card p-4 space-y-3 text-sm">
        <h2 className="font-medium">MCP Hub</h2>
        <p className="text-muted-foreground">
          Mint a Hub session after IdP login. Configure your IDE MCP client with the
          URL and Bearer token below. Tools are filtered by Loom RBAC
          (<code className="text-xs">McpServerAccess</code> via invocável agents).
        </p>
        {canRead ? (
          <button
            type="button"
            className="inline-flex items-center rounded-md bg-primary px-3 py-1.5 text-primary-foreground text-sm disabled:opacity-50"
            disabled={busy}
            onClick={() => void mintHubSession()}
          >
            {busy ? "Minting…" : "Mint Hub session"}
          </button>
        ) : (
          <p className="text-muted-foreground">Requires mcp:read.</p>
        )}
        {error ? <p className="text-destructive text-xs">{error}</p> : null}
        {mint ? (
          <div className="space-y-2 rounded-md bg-muted/40 p-3 font-mono text-xs break-all">
            <div>
              <div className="text-muted-foreground mb-1">URL</div>
              <div>{mint.mcp_hub_url}</div>
            </div>
            <div>
              <div className="text-muted-foreground mb-1">Bearer (Hub session)</div>
              <div>{mint.hub_session_token}</div>
            </div>
            <div className="text-muted-foreground">
              expires {mint.expires_at} · {mint.contract_version}
            </div>
          </div>
        ) : null}
        <p className="text-muted-foreground text-xs">
          Access: {canRead ? "mcp:read" : "no mcp:read"}
          {canWrite ? " · mcp:write" : ""}.
        </p>
      </section>

      <section className="rounded-lg border bg-card p-4 space-y-2 text-sm">
        <h2 className="font-medium">What to use where</h2>
        <p className="text-muted-foreground">
          Register and refresh Azure DevOps / Grafana / Rancher (stdio) under{" "}
          <strong className="text-foreground">Integrations → MCP</strong>, grant{" "}
          <code className="text-xs">McpServerAccess</code> to your agents, then use Chat
          or the MCP Hub from an IDE.
        </p>
      </section>
    </div>
  );
}

