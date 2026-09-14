import type { McpClientGrant, McpServer, ServerAccessRule } from "./types";

export function buildRulesFromGrants(
  grants: McpClientGrant[],
  servers: McpServer[],
): ServerAccessRule[] {
  const grantMap = new Map<number, McpClientGrant>();
  for (const g of grants) {
    const sid = Number(g.server_id);
    if (!Number.isFinite(sid)) continue;
    grantMap.set(sid, g);
  }
  const serverIds = new Set(servers.map((s) => s.id));
  const rows: ServerAccessRule[] = servers.map((s) => {
    const existing = grantMap.get(s.id);
    return {
      server_id: s.id,
      enabled: !!existing,
      access_level: existing?.access_level ?? "all_tools",
      allowed_tool_names: existing?.tool_names ?? [],
    };
  });
  for (const [sid, g] of grantMap) {
    if (serverIds.has(sid)) continue;
    rows.push({
      server_id: sid,
      enabled: true,
      access_level: g.access_level ?? "all_tools",
      allowed_tool_names: g.tool_names ?? [],
    });
  }
  return rows;
}

export function serverLabel(servers: McpServer[], serverId: number): string {
  const s = servers.find((x) => x.id === serverId);
  if (!s) return `Server #${serverId}`;
  const suffix = s.template_id ? ` · ${s.template_id}` : "";
  return `${s.name}${suffix}`;
}
