// Pure check for the external OIDC sign-in callback. An authorization code is
// only redeemed if it answers a sign-in this browser tab started: the `state`
// echoed back by the IdP must equal the one startOIDCLogin stored, and the
// matching PKCE verifier must still be present. Otherwise anyone could hand a
// victim a callback URL carrying their own code and sign the victim into the
// wrong account (login CSRF). Kept free of browser and API imports so it can
// be exercised in isolation.

export type OIDCCallbackCheck =
  | { ok: true; codeVerifier: string }
  | { ok: false; reason: string };

export function checkOIDCCallback(
  returnedState: string | null,
  storedState: string | null,
  storedVerifier: string | null,
): OIDCCallbackCheck {
  if (!storedState || !storedVerifier) {
    return { ok: false, reason: "no sign-in is pending in this tab" };
  }
  if (!returnedState) {
    return { ok: false, reason: "state parameter missing" };
  }
  if (returnedState !== storedState) {
    return { ok: false, reason: "state mismatch" };
  }
  return { ok: true, codeVerifier: storedVerifier };
}
