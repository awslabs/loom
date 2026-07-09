import { useEffect, useState } from "react";

export function OAuthLinkCallbackPage() {
  const [error, setError] = useState("");

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const code = params.get("code");
    const state = params.get("state");
    const savedState = sessionStorage.getItem("loom_link_state");
    const returnUrl = sessionStorage.getItem("loom_link_return_url") || "/";

    if (!code) {
      setError(params.get("error_description") || params.get("error") || "No authorization code received");
      return;
    }

    if (state && savedState && state !== savedState) {
      setError("State mismatch — possible CSRF");
      return;
    }

    sessionStorage.setItem("loom_link_code", code);
    window.location.href = returnUrl;
  }, []);

  if (error) {
    return (
      <div className="min-h-screen bg-background flex items-center justify-center">
        <div className="text-center space-y-2">
          <p className="text-destructive font-medium">Linking failed</p>
          <p className="text-xs text-muted-foreground">{error}</p>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-background flex items-center justify-center">
      <p className="text-muted-foreground">Completing account linking...</p>
    </div>
  );
}
