import { apiFetch } from "./client";
import type {
  AgentIntegration,
  IntegrationCreateRequest,
  IntegrationUpdateRequest,
} from "./types";

export function listIntegrations(agentId: number): Promise<AgentIntegration[]> {
  return apiFetch<AgentIntegration[]>(`/api/agents/${agentId}/integrations`);
}

export function createIntegration(
  agentId: number,
  request: IntegrationCreateRequest,
): Promise<AgentIntegration> {
  return apiFetch<AgentIntegration>(`/api/agents/${agentId}/integrations`, {
    method: "POST",
    body: JSON.stringify(request),
  });
}

export function updateIntegration(
  agentId: number,
  integrationId: number,
  request: IntegrationUpdateRequest,
): Promise<AgentIntegration> {
  return apiFetch<AgentIntegration>(
    `/api/agents/${agentId}/integrations/${integrationId}`,
    {
      method: "PUT",
      body: JSON.stringify(request),
    },
  );
}

export function deleteIntegration(
  agentId: number,
  integrationId: number,
): Promise<void> {
  return apiFetch<void>(`/api/agents/${agentId}/integrations/${integrationId}`, {
    method: "DELETE",
  });
}
