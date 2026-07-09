import { apiFetch } from "./client";

export interface IdentityProviderResponse {
  id: number;
  name: string;
  provider_type: string;
  issuer_url: string;
  client_id: string;
  has_client_secret: boolean;
  client_type: string;
  scopes: string | null;
  audience: string | null;
  group_claim_path: string | null;
  group_mappings: Record<string, string[]>;
  status: string;
  jwks_uri: string | null;
  authorization_endpoint: string | null;
  token_endpoint: string | null;
  discovery_scopes: string[];
  created_at: string | null;
  updated_at: string | null;
}

export interface CreateIdentityProviderRequest {
  name: string;
  provider_type: string;
  issuer_url: string;
  client_id: string;
  client_secret?: string;
  client_type?: string;
  scopes?: string;
  audience?: string;
  group_claim_path?: string;
  group_mappings?: Record<string, string[]>;
  status?: string;
}

export interface UpdateIdentityProviderRequest {
  name?: string;
  provider_type?: string;
  issuer_url?: string;
  client_id?: string;
  client_secret?: string;
  client_type?: string;
  scopes?: string;
  audience?: string;
  group_claim_path?: string;
  group_mappings?: Record<string, string[]>;
  status?: string;
}

export function listIdentityProviders(): Promise<IdentityProviderResponse[]> {
  return apiFetch<IdentityProviderResponse[]>("/api/settings/identity-providers");
}

export function getIdentityProvider(id: number): Promise<IdentityProviderResponse> {
  return apiFetch<IdentityProviderResponse>(`/api/settings/identity-providers/${id}`);
}

export function createIdentityProvider(data: CreateIdentityProviderRequest): Promise<IdentityProviderResponse> {
  return apiFetch<IdentityProviderResponse>("/api/settings/identity-providers", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
}

export function updateIdentityProvider(id: number, data: UpdateIdentityProviderRequest): Promise<IdentityProviderResponse> {
  return apiFetch<IdentityProviderResponse>(`/api/settings/identity-providers/${id}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
}

export function deleteIdentityProvider(id: number): Promise<void> {
  return apiFetch(`/api/settings/identity-providers/${id}`, { method: "DELETE" });
}

export function discoverIdentityProvider(id: number): Promise<IdentityProviderResponse> {
  return apiFetch<IdentityProviderResponse>(`/api/settings/identity-providers/${id}/discover`);
}

export function testDiscovery(issuerUrl: string): Promise<{ status: string; detail?: string; jwks_uri?: string; authorization_endpoint?: string; token_endpoint?: string }> {
  return apiFetch("/api/settings/identity-providers/test-discovery", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ issuer_url: issuerUrl }),
  });
}
