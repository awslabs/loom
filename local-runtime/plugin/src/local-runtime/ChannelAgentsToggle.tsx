import type { McpHubClient } from "./types";

type Props = {
  client: McpHubClient;
  canWrite: boolean;
  busy: boolean;
  onToggle: (slug: string, agentsEnabled: boolean) => void;
};

export function ChannelAgentsToggle({ client, canWrite, busy, onToggle }: Props) {
  return (
    <div className="rounded-md border bg-background p-3 space-y-2">
      <h3 className="text-sm font-medium">Channel settings</h3>
      <p className="text-xs text-muted-foreground">
        Applies immediately on toggle — no profile and no Save button. Agent
        visibility still follows <code>loom:group</code> RBAC.
      </p>
      <label className="flex items-center gap-2 text-xs">
        <input
          type="checkbox"
          checked={Boolean(client.agents_enabled)}
          disabled={busy || !canWrite}
          onChange={(e) => onToggle(client.slug, e.target.checked)}
        />
        <span>
          Expose Loom agents (<code>agents_enabled</code>)
          {busy ? " · saving…" : client.agents_enabled ? " · on" : " · off"}
        </span>
      </label>
    </div>
  );
}
