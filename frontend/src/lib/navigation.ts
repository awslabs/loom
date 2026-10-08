/**
 * Guarded navigation to a URL that came from the server.
 *
 * Several redirect targets originate in an OIDC discovery document — the
 * login `authorization_endpoint`, the Link Account `authorize_url`, the
 * logout `issuer_url`. A discovery document is served by whatever host an
 * administrator pointed Loom at, so its contents are attacker-influenced. A
 * `javascript:` URL assigned to `window.location.href` executes in Loom's own
 * origin, where the session tokens live in sessionStorage.
 *
 * The backend rejects non-https endpoints at discovery time and again before
 * serving them. This is the last layer, and it lives here rather than in each
 * caller so a new redirect site cannot miss it: the browser is where the
 * consequence lands, so the browser refuses too.
 */
export class UnsafeNavigationError extends Error {}

/** Throw unless `url` is an absolute https:// URL. Returns it unchanged. */
export function assertHttpsUrl(url: string | null | undefined, what: string): string {
  if (!url) {
    throw new UnsafeNavigationError(`No ${what} was provided; navigation aborted.`);
  }
  let parsed: URL;
  try {
    parsed = new URL(url);
  } catch {
    throw new UnsafeNavigationError(`The ${what} is not a valid absolute URL; navigation aborted.`);
  }
  if (parsed.protocol !== "https:") {
    throw new UnsafeNavigationError(
      `The ${what} uses the unsupported scheme "${parsed.protocol}"; navigation aborted.`,
    );
  }
  return url;
}

/** Navigate to a server-supplied URL, refusing anything but https. */
export function navigateToExternal(url: string | null | undefined, what: string): void {
  window.location.href = assertHttpsUrl(url, what);
}

/**
 * Whether `url` is safe to put in an `href` the user can click.
 *
 * Use this for links whose target came from the server — a registry record's
 * repository/website URL, for instance — where the right behaviour is to
 * render the value as plain text rather than throw. Clicking a `javascript:`
 * href runs in Loom's origin, where the session tokens live, so an unchecked
 * server-supplied href is a one-click XSS.
 *
 * react-markdown's `defaultUrlTransform` already does this for links inside
 * rendered markdown; this is for hrefs built in JSX by hand.
 */
export function isSafeExternalUrl(url: string | null | undefined): boolean {
  if (!url) return false;
  try {
    return new URL(url).protocol === "https:";
  } catch {
    return false;
  }
}
