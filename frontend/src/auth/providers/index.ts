import type { AuthConfig } from "@/api/auth";

/**
 * Provider descriptors: the frontend half of the identity provider abstraction.
 *
 * Adding a provider means adding one descriptor here and one adapter in
 * `backend/app/idp`. No component should compare `provider_type` to a literal —
 * ask the descriptor a capability question instead.
 */

export type LoginMode = "password" | "redirect";
export type RefreshStrategy = "cognito-direct" | "backend-proxy" | "none";

export interface ProviderDescriptor {
  type: string;
  label: string;
  /** `password` renders a username/password form; `redirect` sends the browser to the IdP. */
  loginMode: LoginMode;
  refreshStrategy: RefreshStrategy;
  /** Default claim to read groups from, used as a form hint. */
  groupClaimHint: string;
  /** Offered in the Identity Providers admin form. */
  registrable: boolean;
  /** Show the external-group-to-Loom-group mapping editor. */
  groupMappingUi: boolean;
  logoutUrl?: (cfg: AuthConfig, returnTo: string, idToken: string) => string | null;
  /** Whether a login issuer and an authorizer discovery URL belong to the same IdP. */
  issuerMatches?: (issuerUrl: string, discoveryUrl: string) => boolean;
}

function stripTrailingSlashes(value: string): string {
  return value.replace(/\/+$/, "");
}

function discoveryBase(discoveryUrl: string): string {
  return stripTrailingSlashes(
    discoveryUrl.replace(/\/?\.well-known\/openid-configuration\/?$/, ""),
  );
}

function baseUrlMatches(issuerUrl: string, discoveryUrl: string): boolean {
  return (
    discoveryBase(discoveryUrl).toLowerCase() ===
    stripTrailingSlashes(issuerUrl).toLowerCase()
  );
}

const ENTRA_TENANT = /login\.microsoftonline\.com\/([^/]+)/i;

function endSessionLogoutUrl(cfg: AuthConfig, returnTo: string, idToken: string): string | null {
  if (!cfg.end_session_endpoint) return null;
  const params = new URLSearchParams({ post_logout_redirect_uri: returnTo });
  if (cfg.client_id) params.set("client_id", cfg.client_id);
  if (idToken) params.set("id_token_hint", idToken);
  return `${cfg.end_session_endpoint}?${params.toString()}`;
}

const cognito: ProviderDescriptor = {
  type: "cognito",
  label: "Amazon Cognito",
  loginMode: "password",
  refreshStrategy: "cognito-direct",
  groupClaimHint: "cognito:groups",
  registrable: false,
  groupMappingUi: false,
  issuerMatches: baseUrlMatches,
};

const keycloak: ProviderDescriptor = {
  type: "keycloak",
  label: "Keycloak",
  loginMode: "redirect",
  refreshStrategy: "backend-proxy",
  groupClaimHint: "groups",
  registrable: true,
  groupMappingUi: true,
  logoutUrl: endSessionLogoutUrl,
  issuerMatches: baseUrlMatches,
};

const entraId: ProviderDescriptor = {
  type: "entra_id",
  label: "Microsoft Entra ID",
  loginMode: "redirect",
  refreshStrategy: "backend-proxy",
  groupClaimHint: "roles",
  registrable: true,
  groupMappingUi: true,
  logoutUrl: (cfg, returnTo) => {
    if (!cfg.issuer_url) return null;
    const authority = stripTrailingSlashes(cfg.issuer_url).replace(/\/v2\.0$/i, "");
    const params = new URLSearchParams({ post_logout_redirect_uri: returnTo });
    return `${authority}/oauth2/v2.0/logout?${params.toString()}`;
  },
  issuerMatches: (issuerUrl, discoveryUrl) => {
    const issuerMatch = ENTRA_TENANT.exec(issuerUrl);
    const discoveryMatch = ENTRA_TENANT.exec(discoveryUrl);
    if (issuerMatch && discoveryMatch) {
      return issuerMatch[1]!.toLowerCase() === discoveryMatch[1]!.toLowerCase();
    }
    return baseUrlMatches(issuerUrl, discoveryUrl);
  },
};

const okta: ProviderDescriptor = {
  type: "okta",
  label: "Okta",
  loginMode: "redirect",
  refreshStrategy: "backend-proxy",
  groupClaimHint: "groups",
  registrable: true,
  groupMappingUi: false,
  logoutUrl: (cfg, returnTo, idToken) => {
    if (!cfg.issuer_url || !idToken) return null;
    const params = new URLSearchParams({
      post_logout_redirect_uri: returnTo,
      id_token_hint: idToken,
    });
    return `${stripTrailingSlashes(cfg.issuer_url)}/v1/logout?${params.toString()}`;
  },
  issuerMatches: baseUrlMatches,
};

const auth0: ProviderDescriptor = {
  type: "auth0",
  label: "Auth0",
  loginMode: "redirect",
  refreshStrategy: "backend-proxy",
  groupClaimHint: "https://your-namespace/roles",
  registrable: true,
  groupMappingUi: true,
  logoutUrl: endSessionLogoutUrl,
  issuerMatches: baseUrlMatches,
};

const genericOidc: ProviderDescriptor = {
  type: "generic_oidc",
  label: "Single Sign-On",
  loginMode: "redirect",
  refreshStrategy: "backend-proxy",
  groupClaimHint: "groups",
  registrable: true,
  groupMappingUi: true,
  logoutUrl: endSessionLogoutUrl,
  issuerMatches: baseUrlMatches,
};

export const PROVIDER_DESCRIPTORS: Record<string, ProviderDescriptor> = {
  [cognito.type]: cognito,
  [keycloak.type]: keycloak,
  [entraId.type]: entraId,
  [okta.type]: okta,
  [auth0.type]: auth0,
  [genericOidc.type]: genericOidc,
};

/** Providers that can be registered through the admin UI. */
export const REGISTRABLE_PROVIDERS: ProviderDescriptor[] = Object.values(PROVIDER_DESCRIPTORS)
  .filter((d) => d.registrable);

export function getDescriptor(providerType?: string | null): ProviderDescriptor {
  if (!providerType) return genericOidc;
  return PROVIDER_DESCRIPTORS[providerType] ?? genericOidc;
}

export function descriptorFor(cfg: AuthConfig | null | undefined): ProviderDescriptor | null {
  if (!cfg?.provider_type) return null;
  return getDescriptor(cfg.provider_type);
}

/** True when login happens by redirecting to the provider rather than posting credentials. */
export function usesRedirectLogin(cfg: AuthConfig | null | undefined): boolean {
  return descriptorFor(cfg)?.loginMode === "redirect";
}

export function providerLabel(cfg: AuthConfig | null | undefined): string {
  return descriptorFor(cfg)?.label ?? genericOidc.label;
}

/**
 * How to renew an access token for this provider. The backend may veto refresh for a
 * specific registration via `supports_refresh`.
 */
export function refreshStrategyFor(cfg: AuthConfig | null | undefined): RefreshStrategy {
  const descriptor = descriptorFor(cfg);
  if (!descriptor) return "none";
  if (descriptor.refreshStrategy === "backend-proxy" && cfg?.supports_refresh === false) {
    return "none";
  }
  return descriptor.refreshStrategy;
}

export function idpLogoutUrl(
  cfg: AuthConfig | null | undefined,
  returnTo: string,
  idToken: string,
): string | null {
  if (!cfg) return null;
  return descriptorFor(cfg)?.logoutUrl?.(cfg, returnTo, idToken) ?? null;
}

/** Same-IdP detection between the login provider and an agent authorizer. */
export function issuerMatchesDiscovery(
  providerType: string | null | undefined,
  issuerUrl?: string,
  discoveryUrl?: string,
): boolean {
  if (!issuerUrl || !discoveryUrl) return false;
  const matcher = getDescriptor(providerType).issuerMatches ?? baseUrlMatches;
  return matcher(issuerUrl, discoveryUrl);
}
