import type { McpHubClient } from "./types";

type Props = {
  clients: McpHubClient[];
  selectedSlug: string | null;
  canRead: boolean;
  canWrite: boolean;
  busy: boolean;
  onRefresh: () => void;
  onSelect: (client: McpHubClient) => void;
  onSetStatus: (slug: string, next: "enabled" | "disabled") => void;
  onDelete: (slug: string) => void;
};

export function ClientsList({
  clients,
  selectedSlug,
  canRead,
  canWrite,
  busy,
  onRefresh,
  onSelect,
  onSetStatus,
  onDelete,
}: Props) {
  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between gap-2">
        <h2 className="font-medium">MCP Clients (channels)</h2>
        <button
          type="button"
          className="text-xs text-muted-foreground underline disabled:opacity-50"
          disabled={busy || !canRead}
          onClick={onRefresh}
        >
          Refresh
        </button>
      </div>
      <p className="text-muted-foreground text-xs">
        Discovered on IDE <code className="text-xs">initialize</code>. Select a channel,
        then choose an IdP profile to load or register its tool grants.
      </p>
      {clients.length === 0 ? (
        <p className="text-muted-foreground text-xs">No clients discovered yet.</p>
      ) : (
        <ul className="space-y-2">
          {clients.map((c) => (
            <li
              key={c.slug}
              className={`rounded-md border px-3 py-2 space-y-1 ${
                selectedSlug === c.slug ? "border-primary bg-muted/30" : ""
              }`}
            >
              <button type="button" className="text-left w-full" onClick={() => onSelect(c)}>
                <div className="font-medium">
                  {c.display_name || c.slug}{" "}
                  <span className="text-muted-foreground font-normal">({c.slug})</span>
                </div>
                <div className="text-xs text-muted-foreground">
                  status={c.status} · family={c.declared_family} · agents=
                  {c.agents_enabled ? "on" : "off"} · grant rows=
                  {c.grant_count ?? 0}
                  {(c.granted_profiles || c.allowed_groups || []).length > 0
                    ? ` · profiles=${(c.granted_profiles || c.allowed_groups || []).join(",")}`
                    : ""}
                </div>
              </button>
              {canWrite ? (
                <div className="flex flex-wrap gap-3 pt-1 text-xs">
                  <button
                    type="button"
                    className="underline disabled:opacity-50"
                    disabled={busy || c.status === "enabled"}
                    onClick={() => onSetStatus(c.slug, "enabled")}
                  >
                    Enable
                  </button>
                  <button
                    type="button"
                    className="underline disabled:opacity-50"
                    disabled={busy || c.status === "disabled"}
                    onClick={() => onSetStatus(c.slug, "disabled")}
                  >
                    Disable
                  </button>
                  <button
                    type="button"
                    className="underline text-destructive disabled:opacity-50"
                    disabled={busy}
                    onClick={() => onDelete(c.slug)}
                  >
                    Delete
                  </button>
                </div>
              ) : null}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
