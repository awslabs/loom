import { apiFetch, getBaseUrl } from "./client";

export interface ProviderCapabilities {
  authorization_code_pkce: boolean;
  refresh_token: boolean;
  password_grant: boolean;
  client_credentials: boolean;
  rfc8693_token_exchange: boolean;
  jwt_bearer_grant: boolean;
  idp_initiated_logout: boolean;
  requires_group_mapping: boolean;
}

export interface AuthConfig {
  provider_type?: string;
  user_pool_id: string;
  region: string;
  // Redirect-based IdP fields (present when a provider is registered)
  authorization_endpoint?: string;
  token_endpoint?: string;
  end_session_endpoint?: string;
  client_id?: string;
  scopes?: string;
  issuer_url?: string;
  redirect_uri?: string;
  group_claim_path?: string;
  group_mappings?: Record<string, string[]>;
  has_client_secret?: boolean;
  client_type?: string; // "public" or "confidential"
  capabilities?: ProviderCapabilities;
  supports_refresh?: boolean;
}

export interface AuthTokens {
  idToken: string;
  accessToken: string;
  refreshToken: string;
}

export interface CognitoAuthResult {
  ChallengeName?: string;
  Session?: string;
  AuthenticationResult?: {
    IdToken: string;
    AccessToken: string;
    RefreshToken: string;
    ExpiresIn: number;
    TokenType: string;
  };
}

export interface OIDCTokenResponse {
  access_token: string;
  id_token: string;
  refresh_token?: string;
  token_type: string;
  expires_in: number;
}

export function fetchAuthConfig(): Promise<AuthConfig> {
  return apiFetch<AuthConfig>("/api/auth/config");
}

export function fetchAuthMe(): Promise<{ username: string; sub: string; groups: string[] }> {
  return apiFetch<{ username: string; sub: string; groups: string[] }>("/api/auth/me");
}

export async function initiateAuth(
  username: string,
  password: string,
  clientId: string,
  region: string,
): Promise<CognitoAuthResult> {
  const response = await fetch(
    `https://cognito-idp.${region}.amazonaws.com/`,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/x-amz-json-1.1",
        "X-Amz-Target": "AWSCognitoIdentityProviderService.InitiateAuth",
      },
      body: JSON.stringify({
        AuthFlow: "USER_PASSWORD_AUTH",
        ClientId: clientId,
        AuthParameters: {
          USERNAME: username,
          PASSWORD: password,
        },
      }),
    },
  );

  if (!response.ok) {
    const error = (await response.json()) as {
      message?: string;
      __type?: string;
    };
    throw new Error(
      error.message || `Authentication failed: ${response.status}`,
    );
  }

  return response.json() as Promise<CognitoAuthResult>;
}

export async function respondToNewPasswordChallenge(
  session: string,
  username: string,
  newPassword: string,
  clientId: string,
  region: string,
): Promise<CognitoAuthResult> {
  const response = await fetch(
    `https://cognito-idp.${region}.amazonaws.com/`,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/x-amz-json-1.1",
        "X-Amz-Target":
          "AWSCognitoIdentityProviderService.RespondToAuthChallenge",
      },
      body: JSON.stringify({
        ChallengeName: "NEW_PASSWORD_REQUIRED",
        ClientId: clientId,
        Session: session,
        ChallengeResponses: {
          USERNAME: username,
          NEW_PASSWORD: newPassword,
        },
      }),
    },
  );

  if (!response.ok) {
    const error = (await response.json()) as {
      message?: string;
      __type?: string;
    };
    throw new Error(
      error.message || `Password change failed: ${response.status}`,
    );
  }

  return response.json() as Promise<CognitoAuthResult>;
}

export async function refreshTokens(
  refreshToken: string,
  clientId: string,
  region: string,
): Promise<CognitoAuthResult> {
  const response = await fetch(
    `https://cognito-idp.${region}.amazonaws.com/`,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/x-amz-json-1.1",
        "X-Amz-Target": "AWSCognitoIdentityProviderService.InitiateAuth",
      },
      body: JSON.stringify({
        AuthFlow: "REFRESH_TOKEN_AUTH",
        ClientId: clientId,
        AuthParameters: {
          REFRESH_TOKEN: refreshToken,
        },
      }),
    },
  );

  if (!response.ok) {
    const error = (await response.json()) as {
      message?: string;
      __type?: string;
    };
    throw new Error(
      error.message || `Token refresh failed: ${response.status}`,
    );
  }

  return response.json() as Promise<CognitoAuthResult>;
}

// ---------------------------------------------------------------------------
// OIDC Authorization Code + PKCE helpers
// ---------------------------------------------------------------------------

function generateRandomString(length: number): string {
  const array = new Uint8Array(length);
  crypto.getRandomValues(array);
  return Array.from(array, (b) => b.toString(16).padStart(2, "0")).join("").slice(0, length);
}

async function sha256(plain: string): Promise<ArrayBuffer> {
  const encoder = new TextEncoder();
  return crypto.subtle.digest("SHA-256", encoder.encode(plain));
}

function base64urlEncode(buffer: ArrayBuffer): string {
  const bytes = new Uint8Array(buffer);
  let binary = "";
  for (const b of bytes) binary += String.fromCharCode(b);
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

export async function startOIDCLogin(config: AuthConfig): Promise<void> {
  const codeVerifier = generateRandomString(64);
  const codeChallenge = base64urlEncode(await sha256(codeVerifier));

  sessionStorage.setItem("oidc_code_verifier", codeVerifier);

  const redirectUri = config.redirect_uri || `${window.location.origin}/oauth/callback`;
  sessionStorage.setItem("oidc_redirect_uri", redirectUri);

  const params = new URLSearchParams({
    response_type: "code",
    client_id: config.client_id || "",
    redirect_uri: redirectUri,
    scope: config.scopes || "openid profile email",
    code_challenge: codeChallenge,
    code_challenge_method: "S256",
    state: generateRandomString(32),
  });

  // Force fresh login prompt when switching users or after IdP change
  const forcePrompt = sessionStorage.getItem("oidc_force_prompt");
  if (forcePrompt) {
    params.set("prompt", forcePrompt);
    sessionStorage.removeItem("oidc_force_prompt");
  }

  sessionStorage.setItem("oidc_state", params.get("state")!);

  window.location.href = `${config.authorization_endpoint}?${params.toString()}`;
}

/**
 * Renew tokens at the active provider through the backend proxy.
 *
 * The backend attaches the client secret for confidential clients. Providers that rotate
 * refresh tokens return a new one, so callers must store whatever comes back.
 */
export async function refreshOIDCToken(refreshToken: string): Promise<OIDCTokenResponse> {
  const response = await fetch(`${getBaseUrl()}/api/auth/refresh`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ refresh_token: refreshToken }),
  });

  if (!response.ok) {
    throw new Error(`Token refresh failed: ${await response.text()}`);
  }

  return response.json() as Promise<OIDCTokenResponse>;
}

export async function exchangeOIDCCode(
  code: string,
  config: AuthConfig,
): Promise<OIDCTokenResponse> {
  const codeVerifier = sessionStorage.getItem("oidc_code_verifier") || "";
  const redirectUri = sessionStorage.getItem("oidc_redirect_uri") || `${window.location.origin}/oauth/callback`;

  let response: Response;

  if (config.client_type === "confidential") {
    // Confidential client — exchange via backend proxy which attaches the client_secret
    response = await fetch(`${getBaseUrl()}/api/auth/token`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        code,
        code_verifier: codeVerifier,
        redirect_uri: redirectUri,
      }),
    });
  } else {
    // Public client (PKCE only) — exchange directly with the IdP
    response = await fetch(config.token_endpoint!, {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: new URLSearchParams({
        grant_type: "authorization_code",
        client_id: config.client_id || "",
        code,
        code_verifier: codeVerifier,
        redirect_uri: redirectUri,
      }),
    });
  }

  if (!response.ok) {
    const text = await response.text();
    throw new Error(`Token exchange failed: ${text}`);
  }

  // Clean up PKCE state
  sessionStorage.removeItem("oidc_code_verifier");
  sessionStorage.removeItem("oidc_redirect_uri");
  sessionStorage.removeItem("oidc_state");

  return response.json() as Promise<OIDCTokenResponse>;
}
