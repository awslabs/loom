import type {
  McpHubClient,
  McpServer,
  McpTool,
  ServerAccessRule,
} from "./types";
import { LOOM_PROFILES, PROFILE_PLACEHOLDER } from "./types";
import { serverLabel } from "./grants";

type Props = {
  client: McpHubClient;
  servers: McpServer[];
  selectedProfile: string;
  rules: ServerAccessRule[];
  toolsByServer: Record<number, McpTool[]>;
  canWrite: boolean;
  profileLoaded: boolean;
  loadingProfile: boolean;
  savingGrants: boolean;
  onChangeProfile: (profile: string) => void;
  onUpdateRule: (serverId: number, updates: Partial<ServerAccessRule>) => void;
  onToggleTool: (serverId: number, toolName: string) => void;
  onLoadTools: (serverId: number) => void;
  onSave: () => void;
};

export function ProfileGrantsEditor({
  client,
  servers,
  selectedProfile,
  rules,
  toolsByServer,
  canWrite,
  profileLoaded,
  loadingProfile,
  savingGrants,
  onChangeProfile,
  onUpdateRule,
  onToggleTool,
  onLoadTools,
  onSave,
}: Props) {
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="space-y-2 min-w-0 flex-1">
          <h3 className="text-sm font-medium">
            Profile tools — {client.display_name || client.slug}
          </h3>
          <label className="flex flex-col gap-1 text-xs max-w-sm">
            <span className="text-muted-foreground">IdP profile</span>
            <select
              className="rounded-md border bg-background px-2 py-1.5 text-sm"
              value={selectedProfile}
              onChange={(e) => onChangeProfile(e.target.value)}
            >
              <option value={PROFILE_PLACEHOLDER}>Select a profile…</option>
              {LOOM_PROFILES.map((p) => {
                const configured = (
                  client.granted_profiles ||
                  client.allowed_groups ||
                  []
                ).includes(p);
                return (
                  <option key={p} value={p}>
                    {p}
                    {configured ? " · configured" : ""}
                  </option>
                );
              })}
            </select>
          </label>
          {!selectedProfile ? (
            <p className="text-xs text-muted-foreground">
              Select a profile to load its grants or start registering tools for it.
              The Save button appears after a profile is loaded.
            </p>
          ) : loadingProfile ? (
            <p className="text-xs text-muted-foreground">Loading {selectedProfile}…</p>
          ) : profileLoaded ? (
            <p className="text-xs text-muted-foreground">
              Editing <code className="text-xs">{selectedProfile}</code> only. Save writes
              this profile; other profiles are untouched.
            </p>
          ) : null}
        </div>
        {canWrite && selectedProfile && profileLoaded ? (
          <button
            type="button"
            className="inline-flex items-center rounded-md bg-primary px-3 py-1.5 text-primary-foreground text-xs disabled:opacity-50"
            disabled={savingGrants || loadingProfile}
            onClick={onSave}
          >
            {savingGrants ? "Saving…" : "Save profile grants"}
          </button>
        ) : null}
      </div>

      {selectedProfile && profileLoaded ? (
        servers.length === 0 ? (
          <p className="text-xs text-muted-foreground">No active MCP servers in the catalog.</p>
        ) : (
          <div className="space-y-2">
            {rules.map((rule) => {
              const tools = toolsByServer[rule.server_id] || [];
              return (
                <div key={rule.server_id} className="rounded border bg-background p-3 space-y-2">
                  <label className="flex items-center gap-2 cursor-pointer select-none">
                    <input
                      type="checkbox"
                      checked={rule.enabled}
                      disabled={!canWrite}
                      onChange={(e) => {
                        onUpdateRule(rule.server_id, { enabled: e.target.checked });
                        if (e.target.checked && rule.access_level === "selected_tools") {
                          onLoadTools(rule.server_id);
                        }
                      }}
                      className="h-3.5 w-3.5"
                    />
                    <span className="text-sm font-medium">
                      {serverLabel(servers, rule.server_id)}
                    </span>
                  </label>

                  {rule.enabled ? (
                    <div className="pl-6 space-y-2">
                      <div className="flex items-center gap-4">
                        <label className="flex items-center gap-1.5 text-xs cursor-pointer">
                          <input
                            type="radio"
                            checked={rule.access_level === "all_tools"}
                            disabled={!canWrite}
                            onChange={() =>
                              onUpdateRule(rule.server_id, { access_level: "all_tools" })
                            }
                            className="h-3 w-3"
                          />
                          All Tools
                        </label>
                        <label className="flex items-center gap-1.5 text-xs cursor-pointer">
                          <input
                            type="radio"
                            checked={rule.access_level === "selected_tools"}
                            disabled={!canWrite}
                            onChange={() => {
                              onUpdateRule(rule.server_id, {
                                access_level: "selected_tools",
                              });
                              onLoadTools(rule.server_id);
                            }}
                            className="h-3 w-3"
                          />
                          Selected Tools
                        </label>
                      </div>

                      {rule.access_level === "selected_tools" ? (
                        <div className="flex flex-wrap gap-2">
                          {tools.length === 0 ? (
                            <span className="text-xs text-muted-foreground italic">
                              No tools available. Refresh tools on the server in Integrations
                              first.
                            </span>
                          ) : (
                            tools.map((tool) => (
                              <label
                                key={tool.tool_name}
                                className="flex items-center gap-1.5 text-xs cursor-pointer"
                              >
                                <input
                                  type="checkbox"
                                  checked={rule.allowed_tool_names.includes(tool.tool_name)}
                                  disabled={!canWrite}
                                  onChange={() =>
                                    onToggleTool(rule.server_id, tool.tool_name)
                                  }
                                  className="h-3 w-3"
                                />
                                {tool.tool_name}
                              </label>
                            ))
                          )}
                        </div>
                      ) : null}
                    </div>
                  ) : null}
                </div>
              );
            })}
          </div>
        )
      ) : null}
    </div>
  );
}
