import type { HubInfo } from "./types";

type Props = {
  hubInfo: HubInfo | null;
  canRead: boolean;
  error: string | null;
};

export function HubInfoSection({ hubInfo, canRead, error }: Props) {
  return (
    <section className="rounded-lg border bg-card p-4 space-y-3 text-sm">
      <h2 className="font-medium">MCP Hub (OAuth)</h2>
      <p className="text-muted-foreground">
        No mint. Point the IDE at the Hub URL only — Cursor authenticates via the
        active IdP (Keycloak / Microsoft Entra ID) with Authorization Code + PKCE.
        Use static <code>auth.CLIENT_ID</code> in <code>mcp.json</code>. After
        connect, the channel appears below for profile grants.
      </p>
      {error ? <p className="text-destructive text-xs">{error}</p> : null}
      {hubInfo ? (
        <div className="space-y-2 rounded-md bg-muted/40 p-3 font-mono text-xs break-all">
          <div>
            <div className="text-muted-foreground mb-1">Resource URL (mcp.json)</div>
            <div>{hubInfo.mcp_hub_url}</div>
          </div>
          <pre className="whitespace-pre-wrap text-[11px] leading-relaxed text-muted-foreground">
{`{
  "mcpServers": {
    "loom-hub": {
      "url": "${hubInfo.mcp_hub_url}",
      "auth": {
        "CLIENT_ID": "loom-mcp-hub",
        "scopes": ["openid", "profile"]
      }
    }
  }
}`}
          </pre>
          <div className="text-muted-foreground">
            auth={hubInfo.auth} · {hubInfo.contract_version} · PRM at{" "}
            http://127.0.0.1:8790/.well-known/oauth-protected-resource
          </div>
        </div>
      ) : canRead ? (
        <p className="text-muted-foreground text-xs">Loading Hub info…</p>
      ) : (
        <p className="text-muted-foreground">Requires mcp:read.</p>
      )}
    </section>
  );
}
