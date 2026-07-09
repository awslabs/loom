import { apiFetch } from "./client";
import type { CredentialProvider, CredentialProviderCreateRequest } from "./types";

export function listCredentialProviders(agentId: number): Promise<CredentialProvider[]> {
  return apiFetch<CredentialProvider[]>(`/api/agents/${agentId}/credentials`);
}

export function createCredentialProvider(
  agentId: number,
  request: CredentialProviderCreateRequest,
): Promise<CredentialProvider> {
  return apiFetch<CredentialProvider>(`/api/agents/${agentId}/credentials`, {
    method: "POST",
    body: JSON.stringify(request),
  });
}

export function deleteCredentialProvider(
  agentId: number,
  providerId: number,
): Promise<void> {
  return apiFetch<void>(`/api/agents/${agentId}/credentials/${providerId}`, {
    method: "DELETE",
  });
}
