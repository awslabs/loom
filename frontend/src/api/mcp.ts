import { apiFetch } from "./client";
import type {
  McpServer,
  McpServerCreateRequest,
  McpServerUpdateRequest,
  McpTool,
  McpServerAccess,
  McpAccessUpdateRequest,
  ToolInvokeRequest,
  ToolInvokeResult,
  TestConnectionResult,
  ConnectorInfo,
} from "./types";

export function listMcpServers(): Promise<McpServer[]> {
  return apiFetch<McpServer[]>("/api/mcp/servers");
}

export function listConnectors(): Promise<ConnectorInfo[]> {
  return apiFetch<ConnectorInfo[]>("/api/mcp/servers/connectors");
}

export function getMcpServer(id: number): Promise<McpServer> {
  return apiFetch<McpServer>(`/api/mcp/servers/${id}`);
}

export function createMcpServer(request: McpServerCreateRequest): Promise<McpServer> {
  return apiFetch<McpServer>("/api/mcp/servers", {
    method: "POST",
    body: JSON.stringify(request),
  });
}

export function updateMcpServer(id: number, request: McpServerUpdateRequest): Promise<McpServer> {
  return apiFetch<McpServer>(`/api/mcp/servers/${id}`, {
    method: "PUT",
    body: JSON.stringify(request),
  });
}

export function deleteMcpServer(id: number): Promise<void> {
  return apiFetch<void>(`/api/mcp/servers/${id}`, {
    method: "DELETE",
  });
}

export function testConnection(serverId: number): Promise<TestConnectionResult> {
  return apiFetch<TestConnectionResult>(`/api/mcp/servers/${serverId}/test-connection`, {
    method: "POST",
  });
}

export function testConnectionPreCreate(config: {
  endpoint_url: string;
  transport_type: string;
  auth_type: string;
  oauth2_well_known_url?: string;
  oauth2_client_id?: string;
  oauth2_client_secret?: string;
  oauth2_scopes?: string;
  delegation_mode?: string;
  oauth2_audience?: string;
}): Promise<TestConnectionResult> {
  return apiFetch<TestConnectionResult>("/api/mcp/servers/test-connection", {
    method: "POST",
    body: JSON.stringify(config),
  });
}

export function getServerTools(serverId: number): Promise<McpTool[]> {
  return apiFetch<McpTool[]>(`/api/mcp/servers/${serverId}/tools`);
}

export function refreshServerTools(serverId: number): Promise<McpTool[]> {
  return apiFetch<McpTool[]>(`/api/mcp/servers/${serverId}/tools/refresh`, {
    method: "POST",
  });
}

export function invokeServerTool(serverId: number, request: ToolInvokeRequest): Promise<ToolInvokeResult> {
  return apiFetch<ToolInvokeResult>(`/api/mcp/servers/${serverId}/tools/invoke`, {
    method: "POST",
    body: JSON.stringify(request),
  });
}

export function exportMcpServer(serverId: number): Promise<Record<string, unknown>> {
  return apiFetch<Record<string, unknown>>(`/api/mcp/servers/${serverId}/export`);
}

export function getServerAccess(serverId: number): Promise<McpServerAccess[]> {
  return apiFetch<McpServerAccess[]>(`/api/mcp/servers/${serverId}/access`);
}

export function updateServerAccess(serverId: number, request: McpAccessUpdateRequest): Promise<McpServerAccess[]> {
  return apiFetch<McpServerAccess[]>(`/api/mcp/servers/${serverId}/access`, {
    method: "PUT",
    body: JSON.stringify(request),
  });
}

export function setUserApiKey(serverId: number, apiKey: string): Promise<{ has_user_api_key: boolean }> {
  return apiFetch(`/api/mcp/servers/${serverId}/api-key`, {
    method: "PUT",
    body: JSON.stringify({ api_key: apiKey }),
  });
}

export function getUserApiKeyStatus(serverId: number): Promise<{ has_user_api_key: boolean }> {
  return apiFetch(`/api/mcp/servers/${serverId}/api-key/status`);
}

export function deleteUserApiKey(serverId: number): Promise<{ has_user_api_key: boolean }> {
  return apiFetch(`/api/mcp/servers/${serverId}/api-key`, { method: "DELETE" });
}
