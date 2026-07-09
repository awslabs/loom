import { apiFetch } from "./client";
import type {
  AgentResponse,
  AgentRegisterRequest,
  AgentDeployRequest,
  AgentHarnessDeployRequest,
  ConfigEntry,
  ConfigUpdateRequest,
  IamRole,
  CognitoPool,
  ModelOption,
  IntegrationInfoResponse,
} from "./types";

export function listAgents(): Promise<AgentResponse[]> {
  return apiFetch<AgentResponse[]>("/api/agents");
}

export function getAgent(id: number): Promise<AgentResponse> {
  return apiFetch<AgentResponse>(`/api/agents/${id}`);
}

export function registerAgent(
  request: AgentRegisterRequest,
): Promise<AgentResponse> {
  return apiFetch<AgentResponse>("/api/agents", {
    method: "POST",
    body: JSON.stringify(request),
  });
}

export function deployAgent(
  request: AgentDeployRequest,
): Promise<AgentResponse> {
  return apiFetch<AgentResponse>("/api/agents", {
    method: "POST",
    body: JSON.stringify(request),
  });
}

export function updateDeployAgent(
  id: number,
  request: AgentDeployRequest,
): Promise<AgentResponse> {
  return apiFetch<AgentResponse>(`/api/agents/${id}/redeploy-deploy`, {
    method: "PUT",
    body: JSON.stringify(request),
  });
}

export function deployHarnessAgent(
  request: AgentHarnessDeployRequest,
): Promise<AgentResponse> {
  return apiFetch<AgentResponse>("/api/agents", {
    method: "POST",
    body: JSON.stringify(request),
  });
}

export function updateHarnessAgent(
  id: number,
  request: AgentHarnessDeployRequest,
): Promise<AgentResponse> {
  return apiFetch<AgentResponse>(`/api/agents/${id}/redeploy-harness`, {
    method: "PUT",
    body: JSON.stringify(request),
  });
}

export function redeployAgent(id: number): Promise<AgentResponse> {
  return apiFetch<AgentResponse>(`/api/agents/${id}/redeploy`, {
    method: "POST",
  });
}

export function refreshAgent(id: number): Promise<AgentResponse> {
  return apiFetch<AgentResponse>(`/api/agents/${id}/refresh`, {
    method: "POST",
  });
}

export function deleteAgent(id: number, cleanupAws: boolean = false): Promise<AgentResponse> {
  const params = cleanupAws ? "?cleanup_aws=true" : "";
  return apiFetch<AgentResponse>(`/api/agents/${id}${params}`, {
    method: "DELETE",
  });
}

export function purgeAgent(id: number): Promise<void> {
  return apiFetch<void>(`/api/agents/${id}/purge`, {
    method: "DELETE",
  });
}

export function fetchAgentStatus(id: number): Promise<AgentResponse> {
  return apiFetch<AgentResponse>(`/api/agents/${id}/status`);
}

export function getAgentConfig(id: number): Promise<ConfigEntry[]> {
  return apiFetch<ConfigEntry[]>(`/api/agents/${id}/config`);
}

export function updateAgentConfig(
  id: number,
  request: ConfigUpdateRequest,
): Promise<ConfigEntry[]> {
  return apiFetch<ConfigEntry[]>(`/api/agents/${id}/config`, {
    method: "PUT",
    body: JSON.stringify(request),
  });
}

export function patchAgent(
  id: number,
  updates: { description?: string | null; model_id?: string; allowed_model_ids?: string[] },
): Promise<AgentResponse> {
  return apiFetch<AgentResponse>(`/api/agents/${id}`, {
    method: "PATCH",
    body: JSON.stringify(updates),
  });
}

export function fetchRoles(): Promise<IamRole[]> {
  return apiFetch<IamRole[]>("/api/agents/roles");
}

export function fetchCognitoPools(): Promise<CognitoPool[]> {
  return apiFetch<CognitoPool[]>("/api/agents/cognito-pools");
}

export function fetchModels(): Promise<ModelOption[]> {
  return apiFetch<ModelOption[]>("/api/agents/models");
}

export interface LoomDefaults {
  idle_timeout_seconds: number;
  max_lifetime_seconds: number;
  region: string;
}

export function fetchDefaults(): Promise<LoomDefaults> {
  return apiFetch<LoomDefaults>("/api/agents/defaults");
}

export function getAgentIntegration(id: number): Promise<IntegrationInfoResponse> {
  return apiFetch<IntegrationInfoResponse>(`/api/agents/${id}/integration`);
}

export function exportAgent(id: number): Promise<Record<string, unknown>> {
  return apiFetch<Record<string, unknown>>(`/api/agents/${id}/export`);
}
