import { apiFetch } from "./client";
import type {
  A2aAgent,
  A2aAgentCreateRequest,
  A2aAgentUpdateRequest,
  A2aAgentSkill,
  A2aAgentAccess,
  A2aAccessUpdateRequest,
  TestConnectionResult,
} from "./types";

export function listA2aAgents(): Promise<A2aAgent[]> {
  return apiFetch<A2aAgent[]>("/api/a2a/agents");
}

export function getA2aAgent(id: number): Promise<A2aAgent> {
  return apiFetch<A2aAgent>(`/api/a2a/agents/${id}`);
}

export function createA2aAgent(request: A2aAgentCreateRequest): Promise<A2aAgent> {
  return apiFetch<A2aAgent>("/api/a2a/agents", {
    method: "POST",
    body: JSON.stringify(request),
  });
}

export function updateA2aAgent(id: number, request: A2aAgentUpdateRequest): Promise<A2aAgent> {
  return apiFetch<A2aAgent>(`/api/a2a/agents/${id}`, {
    method: "PUT",
    body: JSON.stringify(request),
  });
}

export function deleteA2aAgent(id: number): Promise<void> {
  return apiFetch<void>(`/api/a2a/agents/${id}`, {
    method: "DELETE",
  });
}

export function testA2aConnection(agentId: number): Promise<TestConnectionResult> {
  return apiFetch<TestConnectionResult>(`/api/a2a/agents/${agentId}/test-connection`, {
    method: "POST",
  });
}

export function testA2aConnectionPreCreate(config: {
  base_url: string;
  auth_type: string;
  oauth2_well_known_url?: string;
  oauth2_client_id?: string;
  oauth2_client_secret?: string;
  oauth2_scopes?: string;
}): Promise<TestConnectionResult> {
  return apiFetch<TestConnectionResult>("/api/a2a/agents/test-connection", {
    method: "POST",
    body: JSON.stringify(config),
  });
}

export function getAgentCard(agentId: number): Promise<Record<string, unknown>> {
  return apiFetch<Record<string, unknown>>(`/api/a2a/agents/${agentId}/card`);
}

export function refreshAgentCard(agentId: number): Promise<A2aAgent> {
  return apiFetch<A2aAgent>(`/api/a2a/agents/${agentId}/card/refresh`, {
    method: "POST",
  });
}

export function getAgentSkills(agentId: number): Promise<A2aAgentSkill[]> {
  return apiFetch<A2aAgentSkill[]>(`/api/a2a/agents/${agentId}/skills`);
}

export function getAgentAccess(agentId: number): Promise<A2aAgentAccess[]> {
  return apiFetch<A2aAgentAccess[]>(`/api/a2a/agents/${agentId}/access`);
}

export function updateAgentAccess(agentId: number, request: A2aAccessUpdateRequest): Promise<A2aAgentAccess[]> {
  return apiFetch<A2aAgentAccess[]>(`/api/a2a/agents/${agentId}/access`, {
    method: "PUT",
    body: JSON.stringify(request),
  });
}

export function exportA2aAgent(agentId: number): Promise<Record<string, unknown>> {
  return apiFetch<Record<string, unknown>>(`/api/a2a/agents/${agentId}/export`);
}
