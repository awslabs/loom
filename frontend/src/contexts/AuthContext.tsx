import {
  createContext,
  useContext,
  useState,
  useEffect,
  useCallback,
  useRef,
  type ReactNode,
} from "react";
import {
  fetchAuthConfig,
  initiateAuth,
  respondToNewPasswordChallenge,
  refreshTokens,
  exchangeOIDCCode,
  startOIDCLogin,
  type AuthConfig,
  type AuthTokens,
  type CognitoAuthResult,
} from "@/api/auth";
import { setAuthToken, setOnUnauthorized } from "@/api/client";
import { recordLogin } from "@/api/audit";

interface CognitoUser {
  sub: string;
  email?: string;
  username?: string;
  groups?: string[];
  [key: string]: unknown;
}

export type Scope =
  | "catalog:read" | "catalog:write"
  | "agent:read" | "agent:write"
  | "memory:read" | "memory:write"
  | "security:read" | "security:write"
  | "settings:read" | "settings:write"
  | "tagging:read" | "tagging:write"
  | "costs:read" | "costs:write"
  | "mcp:read" | "mcp:write"
  | "a2a:read" | "a2a:write"
  | "registry:read" | "registry:write"
  | "admin:read" | "admin:write"
  | "invoke";

const GROUP_SCOPES: Record<string, Scope[]> = {
  // Type groups (for UI routing - don't grant scopes directly)
  "t-admin": [],
  "t-user": [],

  // Admin groups (t-admin users - single group only)
  "g-admins-super": [
    "catalog:read", "catalog:write", "agent:read", "agent:write",
    "memory:read", "memory:write", "security:read", "security:write",
    "settings:read", "settings:write", "tagging:read", "tagging:write",
    "costs:read", "costs:write",
    "mcp:read", "mcp:write", "a2a:read", "a2a:write",
    "registry:read", "registry:write",
    "invoke", "admin:read", "admin:write",
  ],
  "g-admins-demo": [
    "catalog:read", "agent:read", "agent:write", "memory:read", "memory:write",
    "security:read", "settings:read", "settings:write", "tagging:read", "costs:read", "costs:write",
    "mcp:read", "mcp:write", "a2a:read", "a2a:write",
    "registry:read", "registry:write",
    "invoke",
  ],
  "g-admins-security": [
    "security:read", "security:write", "settings:read", "settings:write", "tagging:read",
  ],
  "g-admins-memory": [
    "memory:read", "memory:write", "settings:read", "settings:write", "tagging:read",
  ],
  "g-admins-mcp": [
    "mcp:read", "mcp:write", "settings:read", "settings:write", "tagging:read",
  ],
  "g-admins-a2a": [
    "a2a:read", "a2a:write", "settings:read", "settings:write", "tagging:read",
  ],
  "g-admins-registry": [
    "mcp:read", "a2a:read", "registry:read", "registry:write", "settings:read", "settings:write", "tagging:read",
  ],

  // User groups (t-user users - can have multiple)
  "g-users-demo": ["agent:read", "memory:read", "mcp:read", "invoke"],
  "g-users-test": ["agent:read", "memory:read", "mcp:read", "invoke"],
  "g-users-strategics": ["agent:read", "memory:read", "mcp:read", "invoke"],
};

function deriveScopes(groups: string[]): Set<Scope> {
  const scopes = new Set<Scope>();
  for (const group of groups) {
    const groupScopes = GROUP_SCOPES[group];
    if (groupScopes) {
      for (const scope of groupScopes) {
        scopes.add(scope);
      }
    }
  }
  return scopes;
}

interface AuthContextValue {
  isAuthenticated: boolean;
  isLoading: boolean;
  user: CognitoUser | null;
  accessToken: string | null;
  scopes: Set<Scope>;
  hasScope: (scope: Scope) => boolean;
  authConfig: AuthConfig | null;
  login: (username: string, password: string) => Promise<CognitoAuthResult>;
  loginWithOIDC: () => Promise<void>;
  completeNewPassword: (
    session: string,
    username: string,
    newPassword: string,
  ) => Promise<void>;
  logout: () => void;
  logoutIdP: () => void;
  browserSessionId: string | null;
}

const ALL_SCOPES = new Set<Scope>([
  "catalog:read", "catalog:write", "agent:read", "agent:write",
  "memory:read", "memory:write", "security:read", "security:write",
  "settings:read", "settings:write", "tagging:read", "tagging:write",
  "costs:read", "costs:write",
  "mcp:read", "mcp:write", "a2a:read", "a2a:write", "invoke",
]);
const EMPTY_SCOPES = new Set<Scope>();

const AuthContext = createContext<AuthContextValue>({
  isAuthenticated: false,
  isLoading: true,
  user: null,
  accessToken: null,
  scopes: EMPTY_SCOPES,
  hasScope: () => false,
  authConfig: null,
  login: async () => ({}),
  loginWithOIDC: async () => {},
  completeNewPassword: async () => {},
  logout: () => {},
  logoutIdP: () => {},
  browserSessionId: null,
});

function decodeJwtPayload(token: string): Record<string, unknown> {
  const parts = token.split(".");
  if (parts.length !== 3) throw new Error("Invalid JWT");
  const payload = parts[1]!;
  const decoded = atob(payload.replace(/-/g, "+").replace(/_/g, "/"));
  return JSON.parse(decoded) as Record<string, unknown>;
}

function isExternalOIDC(cfg: AuthConfig | null): boolean {
  return !!cfg?.provider_type && cfg.provider_type !== "cognito";
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [tokens, setTokens] = useState<AuthTokens | null>(() => {
    try {
      const stored = sessionStorage.getItem("loom_auth_tokens");
      if (stored) {
        const parsed = JSON.parse(stored) as AuthTokens;
        // Check if the access token is expired before restoring
        try {
          const claims = JSON.parse(atob(parsed.accessToken.split(".")[1] ?? ""));
          if (claims.exp && claims.exp < Date.now() / 1000) {
            sessionStorage.removeItem("loom_auth_tokens");
            sessionStorage.removeItem("loom_auth_user");
            return null;
          }
        } catch { /* if we can't decode, let validation handle it */ }
        setAuthToken(parsed.accessToken);
        return parsed;
      }
      return null;
    } catch { return null; }
  });
  const [user, setUser] = useState<CognitoUser | null>(() => {
    try {
      const stored = sessionStorage.getItem("loom_auth_user");
      return stored ? JSON.parse(stored) as CognitoUser : null;
    } catch { return null; }
  });
  const [config, setConfig] = useState<AuthConfig | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  // Persist tokens and user to sessionStorage
  useEffect(() => {
    if (tokens) {
      sessionStorage.setItem("loom_auth_tokens", JSON.stringify(tokens));
      setAuthToken(tokens.accessToken);
    } else {
      sessionStorage.removeItem("loom_auth_tokens");
    }
  }, [tokens]);

  useEffect(() => {
    if (user) {
      sessionStorage.setItem("loom_auth_user", JSON.stringify(user));
    } else {
      sessionStorage.removeItem("loom_auth_user");
    }
  }, [user]);
  const [browserSessionId, setBrowserSessionId] = useState<string | null>(null);
  const refreshTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const tokensRef = useRef<AuthTokens | null>(null);
  tokensRef.current = tokens;
  const configRef = useRef<AuthConfig | null>(null);
  configRef.current = config;

  // Process OIDC callback code
  const handleOIDCCallback = useCallback(async (code: string, cfg: AuthConfig) => {
    try {
      const tokenResponse = await exchangeOIDCCode(code, cfg);
      const newTokens: AuthTokens = {
        idToken: tokenResponse.id_token,
        accessToken: tokenResponse.access_token,
        refreshToken: tokenResponse.refresh_token || "",
      };
      setTokens(newTokens);
      setAuthToken(newTokens.accessToken);

      // Decode id_token for user info
      try {
        const claims = decodeJwtPayload(newTokens.idToken);
        const claimPath = cfg.group_claim_path ?? "groups";
        const rawGroups = (claims[claimPath] as string[] | undefined)
          ?? (claims.groups as string[] | undefined)
          ?? (claims.roles as string[] | undefined)
          ?? (claims["cognito:groups"] as string[] | undefined)
          ?? [];
        const mappings = cfg.group_mappings;
        const hasMappings = mappings && Object.keys(mappings).length > 0;
        const groups = hasMappings
          ? rawGroups.flatMap((g) => mappings[g] ?? [])
          : rawGroups;
        const oidcUsername =
            (claims.preferred_username as string)
            || (claims.email as string)
            || (claims.name as string)
            || (claims.sub as string);
        setUser({
          sub: claims.sub as string,
          email: (claims.email as string | undefined) ?? (claims.preferred_username as string | undefined),
          username: oidcUsername,
          groups,
        });
        try {
          localStorage.setItem("loom_last_oidc_user", oidcUsername);
          localStorage.setItem("loom_last_oidc_provider", cfg.provider_type ?? "");
        } catch { /* ignore */ }
      } catch {
        setUser({ sub: "unknown" });
      }

      const sessionId = crypto.randomUUID();
      setBrowserSessionId(sessionId);
      try {
        const claims = decodeJwtPayload(newTokens.idToken);
        const username = (claims.preferred_username as string) || (claims.email as string) || (claims.sub as string);
        recordLogin(username, sessionId).catch(() => {});
      } catch { /* ignore */ }

      // Clean up URL — if we're on /oauth/callback, navigate to the saved return path
      if (window.location.pathname === "/oauth/callback") {
        const returnPath = sessionStorage.getItem("loom_link_return_url") || "/";
        window.location.replace(returnPath);
        return;
      }
      window.history.replaceState({}, "", window.location.pathname);
    } catch (e) {
      console.error("OIDC callback failed:", e);
    }
  }, []);

  // Fetch auth config on mount
  useEffect(() => {
    fetchAuthConfig()
      .then((cfg) => {
        setConfig(cfg);

        // Invalidate cached tokens if the IdP changed (e.g., switched from Okta to Entra).
        // Use the id_token's aud claim which always matches the client_id, unlike access
        // tokens which may have a different audience (e.g., Entra ID API resource URIs).
        if (isExternalOIDC(cfg) && tokensRef.current?.idToken) {
          try {
            const claims = decodeJwtPayload(tokensRef.current.idToken);
            const tokenAud = (claims.aud as string) || "";
            const configClientId = cfg.client_id || "";
            if (configClientId && tokenAud && tokenAud !== configClientId) {
              setTokens(null);
              setUser(null);
              setAuthToken(null);
            }
          } catch { /* ignore decode errors */ }
        }

        // Check for OIDC callback code in URL (skip link-callback — that's handled separately)
        const params = new URLSearchParams(window.location.search);
        const code = params.get("code");
        if (code && isExternalOIDC(cfg) && window.location.pathname !== "/oauth/link-callback") {
          void handleOIDCCallback(code, cfg).finally(() => setIsLoading(false));
          return;
        }

        // If no Cognito pool and no external IdP, skip auth
        if (!isExternalOIDC(cfg) && (!cfg.user_pool_id || !import.meta.env.VITE_COGNITO_USER_CLIENT_ID)) {
          setIsLoading(false);
        }
      })
      .catch(() => {
        setIsLoading(false);
      });
  }, [handleOIDCCallback]);

  // Mark loading done once config is loaded (if pool is configured, user must log in)
  useEffect(() => {
    if (config) {
      if (isExternalOIDC(config)) {
        // For external IdP, loading is done after callback handling or immediately if no code
        const params = new URLSearchParams(window.location.search);
        if (!params.get("code") || window.location.pathname === "/oauth/link-callback") {
          setIsLoading(false);
        }
      } else if (config.user_pool_id && import.meta.env.VITE_COGNITO_USER_CLIENT_ID) {
        setIsLoading(false);
      }
    }
  }, [config]);

  const scheduleRefresh = useCallback(
    (accessToken: string, refreshToken: string) => {
      if (refreshTimerRef.current) {
        clearTimeout(refreshTimerRef.current);
      }

      try {
        const claims = decodeJwtPayload(accessToken);
        const exp = claims.exp as number;
        const refreshIn = Math.max((exp - Date.now() / 1000 - 60) * 1000, 0);

        refreshTimerRef.current = setTimeout(async () => {
          if (!config) return;
          // Only Cognito supports REFRESH_TOKEN_AUTH via direct API
          if (isExternalOIDC(config)) {
            // For external IdPs, force re-login when token expires
            setTokens(null);
            setUser(null);
            setAuthToken(null);
            return;
          }
          try {
            const result = await refreshTokens(
              refreshToken,
              import.meta.env.VITE_COGNITO_USER_CLIENT_ID,
              config.region,
            );
            if (result.AuthenticationResult) {
              const newTokens: AuthTokens = {
                idToken: result.AuthenticationResult.IdToken,
                accessToken: result.AuthenticationResult.AccessToken,
                refreshToken: refreshToken,
              };
              setTokens(newTokens);
              setAuthToken(newTokens.accessToken);
              scheduleRefresh(newTokens.accessToken, newTokens.refreshToken);
            }
          } catch {
            setTokens(null);
            setUser(null);
            setAuthToken(null);
          }
        }, refreshIn);
      } catch {
        // Cannot decode token
      }
    },
    [config],
  );

  // Register 401 interceptor
  useEffect(() => {
    setOnUnauthorized(async () => {
      const currentTokens = tokensRef.current;
      const currentConfig = configRef.current;
      if (!currentTokens?.refreshToken || !currentConfig) return null;
      if (isExternalOIDC(currentConfig)) {
        // Only clear session if the token is actually expired — a 401 on a
        // scope-restricted endpoint shouldn't nuke the entire session.
        try {
          const payload = currentTokens.accessToken.split(".")[1] ?? "";
          const claims = JSON.parse(atob(payload));
          if (claims.exp && claims.exp > Date.now() / 1000) {
            return null;
          }
        } catch { /* can't verify — clear to be safe */ }
        setTokens(null);
        setUser(null);
        setAuthToken(null);
        return null;
      }
      try {
        const result = await refreshTokens(
          currentTokens.refreshToken,
          import.meta.env.VITE_COGNITO_USER_CLIENT_ID,
          currentConfig.region,
        );
        if (result.AuthenticationResult) {
          const newTokens: AuthTokens = {
            idToken: result.AuthenticationResult.IdToken,
            accessToken: result.AuthenticationResult.AccessToken,
            refreshToken: currentTokens.refreshToken,
          };
          setTokens(newTokens);
          setAuthToken(newTokens.accessToken);
          scheduleRefresh(newTokens.accessToken, newTokens.refreshToken);
          return newTokens.accessToken;
        }
      } catch {
        setTokens(null);
        setUser(null);
        setAuthToken(null);
      }
      return null;
    });
    return () => setOnUnauthorized(null);
  }, [scheduleRefresh]);

  // Schedule refresh for restored session tokens
  useEffect(() => {
    if (tokens?.refreshToken && tokens?.accessToken && !refreshTimerRef.current) {
      scheduleRefresh(tokens.accessToken, tokens.refreshToken);
    }
  }, [tokens, scheduleRefresh]);

  const processAuthResult = useCallback(
    (result: CognitoAuthResult) => {
      if (result.AuthenticationResult) {
        const newTokens: AuthTokens = {
          idToken: result.AuthenticationResult.IdToken,
          accessToken: result.AuthenticationResult.AccessToken,
          refreshToken: result.AuthenticationResult.RefreshToken,
        };
        setTokens(newTokens);
        setAuthToken(newTokens.accessToken);

        try {
          const claims = decodeJwtPayload(newTokens.idToken);
          const groups = (claims["cognito:groups"] as string[] | undefined) ?? [];
          setUser({
            sub: claims.sub as string,
            email: claims.email as string | undefined,
            username:
              (claims["cognito:username"] as string) || (claims.sub as string),
            groups,
          });
        } catch {
          setUser({ sub: "unknown" });
        }

        const sessionId = crypto.randomUUID();
        setBrowserSessionId(sessionId);
        try {
          const claims = decodeJwtPayload(newTokens.idToken);
          const username = (claims["cognito:username"] as string) || (claims.sub as string);
          recordLogin(username, sessionId).catch(() => {});
        } catch { /* ignore */ }

        scheduleRefresh(newTokens.accessToken, newTokens.refreshToken);
      }
    },
    [scheduleRefresh],
  );

  const login = useCallback(
    async (username: string, password: string): Promise<CognitoAuthResult> => {
      if (!config) throw new Error("Auth not configured");
      const result = await initiateAuth(
        username,
        password,
        import.meta.env.VITE_COGNITO_USER_CLIENT_ID,
        config.region,
      );
      processAuthResult(result);
      return result;
    },
    [config, processAuthResult],
  );

  const loginWithOIDC = useCallback(async () => {
    if (!config) throw new Error("Auth not configured");
    await startOIDCLogin(config);
  }, [config]);

  const completeNewPassword = useCallback(
    async (session: string, username: string, newPassword: string) => {
      if (!config) throw new Error("Auth not configured");
      const result = await respondToNewPasswordChallenge(
        session,
        username,
        newPassword,
        import.meta.env.VITE_COGNITO_USER_CLIENT_ID,
        config.region,
      );
      processAuthResult(result);
    },
    [config, processAuthResult],
  );

  const logout = useCallback(() => {
    setTokens(null);
    setUser(null);
    setAuthToken(null);
    setBrowserSessionId(null);
    sessionStorage.removeItem("loom_auth_tokens");
    sessionStorage.removeItem("loom_auth_user");
    if (refreshTimerRef.current) {
      clearTimeout(refreshTimerRef.current);
    }
    Object.keys(sessionStorage)
      .filter((k) => k.startsWith("loom:invokePrompt:"))
      .forEach((k) => sessionStorage.removeItem(k));
    setIsLoading(true);
    fetchAuthConfig().then((cfg) => {
      setConfig(cfg);
      setIsLoading(false);
    }).catch(() => { setIsLoading(false); });
  }, []);

  const logoutIdP = useCallback(() => {
    const currentConfig = configRef.current;
    const idToken = tokens?.idToken;
    logout();
    // Mark that next login should force a fresh prompt
    sessionStorage.setItem("oidc_force_prompt", "login");
    if (currentConfig && isExternalOIDC(currentConfig) && currentConfig.issuer_url && idToken) {
      // Only redirect to IdP logout if we have a valid id_token_hint — otherwise the
      // IdP may reject the request (e.g. after authorization server change).
      const issuer = currentConfig.issuer_url.replace(/\/+$/, "");
      const returnUrl = window.location.origin;
      if (currentConfig.provider_type === "okta") {
        const params = new URLSearchParams({ post_logout_redirect_uri: returnUrl, id_token_hint: idToken });
        window.location.href = `${issuer}/v1/logout?${params.toString()}`;
      } else if (currentConfig.provider_type === "entra_id") {
        const params = new URLSearchParams({ post_logout_redirect_uri: returnUrl });
        window.location.href = `${issuer}/oauth2/v2.0/logout?${params.toString()}`;
      }
    }
  }, [tokens, logout]);


  useEffect(() => {
    return () => {
      if (refreshTimerRef.current) {
        clearTimeout(refreshTimerRef.current);
      }
    };
  }, []);

  const isCognitoConfigured = Boolean(
    config?.user_pool_id && import.meta.env.VITE_COGNITO_USER_CLIENT_ID,
  );
  const isExternalConfigured = isExternalOIDC(config);
  const isConfigured = isCognitoConfigured || isExternalConfigured;

  const scopes = !isConfigured
    ? ALL_SCOPES
    : user?.groups
      ? deriveScopes(user.groups)
      : EMPTY_SCOPES;

  const hasScope = useCallback(
    (scope: Scope) => scopes.has(scope),
    [scopes],
  );

  return (
    <AuthContext.Provider
      value={{
        isAuthenticated: isLoading ? false : isConfigured ? tokens !== null : true,
        isLoading,
        user,
        accessToken: tokens?.accessToken ?? null,
        scopes,
        hasScope,
        authConfig: config,
        login,
        loginWithOIDC,
        completeNewPassword,
        logout,
        logoutIdP,
        browserSessionId,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  return useContext(AuthContext);
}
