import { apiFetch } from "./client";
import { assertHttpsUrl } from "@/lib/navigation";
import type {
  ManagedRole,
  ManagedRoleCreateRequest,
  ManagedRoleUpdateRequest,
  CognitoPool,
  AuthorizerCredential,
  AuthorizerConfigResponse,
  AuthorizerConfigCreateRequest,
  AuthorizerConfigUpdateRequest,
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

export type AuthorizerLinkAuthorize = {
  authorize_url: string;
  code_verifier: string;
  state: string;
  redirect_uri: string;
};

/**
 * The returned `authorize_url` is assigned to `window.location.href` by every
 * caller, and it is built from an OIDC discovery document served by whatever
 * host an authorizer's `discovery_url` points at. A `javascript:` URL there
 * would execute in Loom's own origin, where the session tokens live in
 * sessionStorage.
 *
 * The backend validates the scheme at discovery-persist time and again before
 * returning it. This is the third check, placed in the shared fetcher rather
 * than in each caller so a new navigation site cannot miss it: the browser is
 * where the consequence lands, so the browser refuses too.
 */
export async function getAuthorizerLinkAuthorizeUrl(authId: number): Promise<AuthorizerLinkAuthorize> {
  const result = await apiFetch<AuthorizerLinkAuthorize>(
    `/api/security/authorizers/${authId}/link/authorize`,
  );
  assertHttpsUrl(result.authorize_url, "authorizer sign-in URL");
  return result;
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


