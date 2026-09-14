import { apiFetch } from "@/api/client";
import type {
  HubInfo,
  McpClientGrant,
  McpHubClient,
  McpServer,
  McpTool,
} from "./types";

export async function fetchHubInfo(): Promise<HubInfo> {
  return apiFetch<HubInfo>("/api/mcp/hub/info");
}

export async function fetchMcpClients(): Promise<McpHubClient[]> {
  const data = await apiFetch<{ clients: McpHubClient[] }>(
    "/api/ext/local-runtime/mcp-clients",
  );
  return data.clients || [];
}

export async function fetchActiveMcpServers(): Promise<McpServer[]> {
  const list = await apiFetch<McpServer[]>("/api/mcp/servers");
  return (list || []).filter((s) => s.status === "active");
}

export async function fetchServerTools(serverId: number): Promise<McpTool[]> {
  const tools = await apiFetch<McpTool[]>(`/api/mcp/servers/${serverId}/tools`);
  return tools || [];
}

export async function fetchProfileGrants(
  slug: string,
  group: string,
): Promise<{ group: string; grants: McpClientGrant[] }> {
  return apiFetch<{ group: string; grants: McpClientGrant[] }>(
    `/api/ext/local-runtime/mcp-clients/${encodeURIComponent(slug)}/profile-grants?group=${encodeURIComponent(group)}`,
  );
}

export async function putProfileGrants(
  slug: string,
  group: string,
  grants: McpClientGrant[],
): Promise<void> {
  await apiFetch(
    `/api/ext/local-runtime/mcp-clients/${encodeURIComponent(slug)}/profile-grants`,
    {
      method: "PUT",
      body: JSON.stringify({ group, grants }),
    },
  );
}

export async function patchMcpClient(
  slug: string,
  body: {
    status?: "enabled" | "disabled";
    agents_enabled?: boolean;
  },
): Promise<void> {
  await apiFetch(`/api/ext/local-runtime/mcp-clients/${encodeURIComponent(slug)}`, {
    method: "PATCH",
    body: JSON.stringify(body),
  });
}

export async function deleteMcpClient(slug: string): Promise<void> {
  await apiFetch(`/api/ext/local-runtime/mcp-clients/${encodeURIComponent(slug)}`, {
    method: "DELETE",
  });
}
