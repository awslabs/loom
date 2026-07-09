import { useState } from "react";
import { useAuth } from "@/contexts/AuthContext";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import type { CognitoAuthResult } from "@/api/auth";

const PROVIDER_LABELS: Record<string, string> = {
  entra_id: "Microsoft Entra ID",
  okta: "Okta",
  auth0: "Auth0",
  generic_oidc: "Single Sign-On",
};

export function LoginPage() {
  const { login, loginWithOIDC, completeNewPassword, authConfig, logoutIdP } = useAuth();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const [challenge, setChallenge] = useState<{
    session: string;
    username: string;
  } | null>(null);
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");

  const isExternalOIDC = authConfig?.provider_type && authConfig.provider_type !== "cognito";
  const providerLabel = PROVIDER_LABELS[authConfig?.provider_type ?? ""] ?? "Single Sign-On";
  const hasBothProviders = isExternalOIDC && authConfig?.user_pool_id;
  const lastOidcProvider = isExternalOIDC ? localStorage.getItem("loom_last_oidc_provider") : null;
  const lastOidcUser = isExternalOIDC && lastOidcProvider === authConfig?.provider_type
    ? localStorage.getItem("loom_last_oidc_user")
    : null;

  const [selectedProvider, setSelectedProvider] = useState<"external" | "cognito">(
    isExternalOIDC ? "external" : "cognito",
  );

  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setLoading(true);

    try {
      const result: CognitoAuthResult = await login(username, password);

      if (result.ChallengeName === "NEW_PASSWORD_REQUIRED") {
        setChallenge({
          session: result.Session || "",
          username,
        });
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Login failed");
    } finally {
      setLoading(false);
    }
  };

  const handleOIDCLogin = async () => {
    setError(null);
    setLoading(true);
    try {
      await loginWithOIDC();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Login redirect failed");
      setLoading(false);
    }
  };

  const handleNewPassword = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);

    if (newPassword !== confirmPassword) {
      setError("Passwords do not match");
      return;
    }

    if (newPassword.length < 8) {
      setError("Password must be at least 8 characters");
      return;
    }

    setLoading(true);
    try {
      await completeNewPassword(
        challenge!.session,
        challenge!.username,
        newPassword,
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "Password change failed");
    } finally {
      setLoading(false);
    }
  };

  const showCognitoForm = !isExternalOIDC || selectedProvider === "cognito";
  const showOIDCButton = isExternalOIDC && selectedProvider === "external";

  return (
    <div className="min-h-screen bg-background flex items-center justify-center pb-[25vh]">
      <div className="w-full max-w-sm space-y-6">
        <div className="text-center">
          <img
            src="/assets/loom_dark_alt.png"
            alt="Loom"
            className="h-16 mx-auto dark:block hidden"
          />
          <img
            src="/assets/loom_light_alt.png"
            alt="Loom"
            className="h-16 mx-auto dark:hidden block"
          />
        </div>

        <div className="rounded-lg border bg-card p-6 shadow-sm space-y-4">
          {hasBothProviders && !challenge && (
            <div className="flex rounded-md border text-sm w-full" role="tablist">
              <button
                type="button"
                role="tab"
                aria-selected={selectedProvider === "external"}
                className={`flex-1 px-3 py-1.5 transition-colors rounded-l-md text-xs ${
                  selectedProvider === "external"
                    ? "bg-primary text-primary-foreground"
                    : "hover:bg-accent"
                }`}
                onClick={() => { setSelectedProvider("external"); setError(null); }}
              >
                {providerLabel}
              </button>
              <button
                type="button"
                role="tab"
                aria-selected={selectedProvider === "cognito"}
                className={`flex-1 px-3 py-1.5 transition-colors rounded-r-md text-xs ${
                  selectedProvider === "cognito"
                    ? "bg-primary text-primary-foreground"
                    : "hover:bg-accent"
                }`}
                onClick={() => { setSelectedProvider("cognito"); setError(null); }}
              >
                Username / Password
              </button>
            </div>
          )}

          {showOIDCButton && !challenge && (
            <div className="space-y-4">
              <Button
                className="w-full"
                disabled={loading}
                onClick={() => void handleOIDCLogin()}
              >
                {loading ? "Redirecting..." : `Sign in with ${providerLabel}`}
              </Button>
              {lastOidcUser ? (
                <p className="text-xs text-muted-foreground text-center">
                  Currently logged in as <span className="font-medium text-foreground">{lastOidcUser}</span>
                </p>
              ) : (
                <p className="text-xs text-muted-foreground text-center">
                  You may be signed in automatically if you have an active {providerLabel} session.
                </p>
              )}
              {lastOidcUser && (
                <button
                  type="button"
                  className="text-xs text-muted-foreground hover:text-foreground underline w-full text-center"
                  onClick={() => { try { localStorage.removeItem("loom_last_oidc_user"); localStorage.removeItem("loom_last_oidc_provider"); } catch { /* ignore */ } logoutIdP(); }}
                >
                  Sign in as a different user
                </button>
              )}
              {error && (
                <p className="text-sm text-destructive">{error}</p>
              )}
            </div>
          )}

          {showCognitoForm && !challenge && (
            <form onSubmit={handleLogin} className="space-y-4">
              <div className="space-y-2">
                <Label htmlFor="username">Username</Label>
                <Input
                  id="username"
                  type="text"
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  placeholder="Enter your username"
                  required
                  autoFocus
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="password">Password</Label>
                <Input
                  id="password"
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="Enter your password"
                  required
                />
              </div>
              {error && (
                <p className="text-sm text-destructive">{error}</p>
              )}
              <Button type="submit" className="w-full" disabled={loading}>
                {loading ? "Signing in..." : "Sign in"}
              </Button>
            </form>
          )}

          {challenge && (
            <form onSubmit={handleNewPassword} className="space-y-4">
              <p className="text-sm text-muted-foreground">
                You must set a new password to continue.
              </p>
              <div className="space-y-2">
                <Label htmlFor="newPassword">New Password</Label>
                <Input
                  id="newPassword"
                  type="password"
                  value={newPassword}
                  onChange={(e) => setNewPassword(e.target.value)}
                  placeholder="Enter new password"
                  required
                  autoFocus
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="confirmPassword">Confirm Password</Label>
                <Input
                  id="confirmPassword"
                  type="password"
                  value={confirmPassword}
                  onChange={(e) => setConfirmPassword(e.target.value)}
                  placeholder="Confirm new password"
                  required
                />
              </div>
              {error && (
                <p className="text-sm text-destructive">{error}</p>
              )}
              <Button type="submit" className="w-full" disabled={loading}>
                {loading ? "Setting password..." : "Set Password"}
              </Button>
            </form>
          )}
        </div>
      </div>
    </div>
  );
}
