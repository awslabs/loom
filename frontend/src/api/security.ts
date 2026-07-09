import { apiFetch } from "./client";
import type {
  ManagedRole,
  ManagedRoleCreateRequest,
  ManagedRoleUpdateRequest,
  CognitoPool,
  AuthorizerCredential,
  AuthorizerConfigResponse,
  AuthorizerConfigCreateRequest,
  AuthorizerConfigUpdateRequest,
  PermissionRequestResponse,
  PermissionRequestCreateRequest,
  PermissionRequestReviewRequest,
} from "./types";

// Managed Roles
export function listManagedRoles(): Promise<ManagedRole[]> {
  return apiFetch<ManagedRole[]>("/api/security/roles");
}

export function getManagedRole(id: number): Promise<ManagedRole> {
  return apiFetch<ManagedRole>(`/api/security/roles/${id}`);
}

export function createManagedRole(request: ManagedRoleCreateRequest): Promise<ManagedRole> {
  return apiFetch<ManagedRole>("/api/security/roles", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });
}

export function updateManagedRole(id: number, request: ManagedRoleUpdateRequest): Promise<ManagedRole> {
  return apiFetch<ManagedRole>(`/api/security/roles/${id}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });
}

export function deleteManagedRole(id: number): Promise<void> {
  return apiFetch<void>(`/api/security/roles/${id}`, { method: "DELETE" });
}

// Cognito Pools
export function listCognitoPools(): Promise<CognitoPool[]> {
  return apiFetch<CognitoPool[]>("/api/security/cognito-pools");
}

// Authorizer Configs
export function listAuthorizerConfigs(): Promise<AuthorizerConfigResponse[]> {
  return apiFetch<AuthorizerConfigResponse[]>("/api/security/authorizers");
}

export function getAuthorizerConfig(id: number): Promise<AuthorizerConfigResponse> {
  return apiFetch<AuthorizerConfigResponse>(`/api/security/authorizers/${id}`);
}

export function createAuthorizerConfig(request: AuthorizerConfigCreateRequest): Promise<AuthorizerConfigResponse> {
  return apiFetch<AuthorizerConfigResponse>("/api/security/authorizers", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });
}

export function updateAuthorizerConfig(id: number, request: AuthorizerConfigUpdateRequest): Promise<AuthorizerConfigResponse> {
  return apiFetch<AuthorizerConfigResponse>(`/api/security/authorizers/${id}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });
}

export function deleteAuthorizerConfig(id: number): Promise<void> {
  return apiFetch<void>(`/api/security/authorizers/${id}`, { method: "DELETE" });
}

// Authorizer Credentials
export function listAuthorizerCredentials(authId: number): Promise<AuthorizerCredential[]> {
  return apiFetch<AuthorizerCredential[]>(`/api/security/authorizers/${authId}/credentials`);
}

export function createAuthorizerCredential(
  authId: number,
  request: { label: string; client_id: string; client_secret?: string },
): Promise<AuthorizerCredential> {
  return apiFetch<AuthorizerCredential>(`/api/security/authorizers/${authId}/credentials`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });
}

export function deleteAuthorizerCredential(authId: number, credId: number): Promise<void> {
  return apiFetch<void>(`/api/security/authorizers/${authId}/credentials/${credId}`, { method: "DELETE" });
}

export function getCredentialToken(authId: number, credId: number): Promise<{ access_token: string; token_type: string; expires_in: number }> {
  return apiFetch(`/api/security/authorizers/${authId}/credentials/${credId}/token`, { method: "POST" });
}

// Authorizer Linking
export function checkAuthorizerLinkStatus(authId: number): Promise<{ linked: boolean; linkable: boolean }> {
  return apiFetch<{ linked: boolean; linkable: boolean }>(`/api/security/authorizers/${authId}/link/status`);
}

export function getAuthorizerLinkAuthorizeUrl(authId: number): Promise<{ authorize_url: string; code_verifier: string; state: string; redirect_uri: string }> {
  return apiFetch(`/api/security/authorizers/${authId}/link/authorize`);
}

export function submitAuthorizerLinkCallback(
  authId: number,
  code: string,
  codeVerifier: string,
  redirectUri: string,
): Promise<{ linked: boolean }> {
  return apiFetch<{ linked: boolean }>(`/api/security/authorizers/${authId}/link/callback`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ code, code_verifier: codeVerifier, redirect_uri: redirectUri }),
  });
}

export function deleteAuthorizerLink(authId: number): Promise<void> {
  return apiFetch<void>(`/api/security/authorizers/${authId}/link`, { method: "DELETE" });
}

// Permission Requests
export function listPermissionRequests(status?: string): Promise<PermissionRequestResponse[]> {
  const query = status ? `?status=${status}` : "";
  return apiFetch<PermissionRequestResponse[]>(`/api/security/permission-requests${query}`);
}

export function createPermissionRequest(request: PermissionRequestCreateRequest): Promise<PermissionRequestResponse> {
  return apiFetch<PermissionRequestResponse>("/api/security/permission-requests", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });
}

export function reviewPermissionRequest(id: number, request: PermissionRequestReviewRequest): Promise<PermissionRequestResponse> {
  return apiFetch<PermissionRequestResponse>(`/api/security/permission-requests/${id}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });
}
