const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

export function getBaseUrl(): string {
  return BASE_URL;
}

let _authToken: string | null = null;
let _onUnauthorized: (() => Promise<string | null>) | null = null;

export function setAuthToken(token: string | null): void {
  _authToken = token;
}

export function getAuthToken(): string | null {
  return _authToken;
}

/** Register a callback that attempts to refresh the token on 401. */
export function setOnUnauthorized(cb: (() => Promise<string | null>) | null): void {
  _onUnauthorized = cb;
}

/** Try to refresh the auth token via the registered callback. Returns new token or null. */
export async function tryRefreshToken(): Promise<string | null> {
  if (!_onUnauthorized) return null;
  return _onUnauthorized();
}

export class ApiError extends Error {
  constructor(
    public status: number,
    public detail: string,
  ) {
    super(detail);
    this.name = "ApiError";
  }
}

export async function apiFetch<T>(
  path: string,
  options?: RequestInit,
): Promise<T> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(options?.headers as Record<string, string>),
  };

  if (_authToken) {
    headers["Authorization"] = `Bearer ${_authToken}`;
  }

  let response = await fetch(`${BASE_URL}${path}`, {
    ...options,
    headers,
  });

  // On 401, attempt a token refresh and retry once
  if (response.status === 401 && _onUnauthorized) {
    const newToken = await _onUnauthorized();
    if (newToken) {
      headers["Authorization"] = `Bearer ${newToken}`;
      const retryResponse = await fetch(`${BASE_URL}${path}`, {
        ...options,
        headers,
      });
      if (retryResponse.ok) {
        if (retryResponse.status === 204) return undefined as T;
        return retryResponse.json() as Promise<T>;
      }
      // Retry also failed — fall through to error handling with retryResponse
      response = retryResponse;
    }
  }

  if (!response.ok) {
    let detail = `HTTP ${response.status}`;
    try {
      const body = (await response.json()) as { detail?: string | unknown[] };
      if (typeof body.detail === "string") {
        detail = body.detail;
      } else if (Array.isArray(body.detail)) {
        detail = body.detail.map((e) => {
          const err = e as { msg?: string; loc?: string[] };
          return err.msg ?? String(e);
        }).join("; ");
      }
    } catch {
      // use default detail
    }
    throw new ApiError(response.status, detail);
  }

  if (response.status === 204) {
    return undefined as T;
  }

  return response.json() as Promise<T>;
}

export { BASE_URL };
