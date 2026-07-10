import { useState, useEffect, useRef } from "react";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Plug, Unplug, KeyRound, ChevronDown, Send, X, Link2, UserCheck, AlertTriangle } from "lucide-react";
import { listAuthorizerConfigs, listAuthorizerCredentials, checkAuthorizerLinkStatus, getAuthorizerLinkAuthorizeUrl, submitAuthorizerLinkCallback, deleteAuthorizerLink } from "@/api/security";
import { fetchModels, fetchLitellmModels } from "@/api/agents";
import { listConnectors, setUserApiKey, deleteUserApiKey } from "@/api/mcp";
import { groupModels } from "@/lib/models";
import type { SessionResponse, AuthorizerCredential, ModelOption, ConnectorInfo } from "@/api/types";

const NEW_SESSION = "__new__";
const USER_TOKEN = "__user__";
const LINKED_TOKEN = "__linked__";
const NO_CREDENTIAL = "__none__";
const MANUAL_TOKEN = "__manual__";

interface InvokePanelProps {
  agentId: number;
  qualifiers: string[];
  sessions: SessionResponse[];
  isStreaming: boolean;
  modelId?: string | null;
  allowedModelIds?: string[];
  mcpNames?: string[];
  authorizerName?: string;
  authorizerId?: number;
  authorizerPoolId?: string;
  authorizerDiscoveryUrl?: string;
  isExternalIdp?: boolean;
  loginIssuerUrl?: string;
  currentUserId?: string;
  onInvoke: (prompt: string, qualifier: string, sessionId?: string, credentialId?: number, bearerToken?: string, modelId?: string, connectorIds?: number[], useLinkedToken?: boolean) => void;
  onCancel: () => void;
}

function issuerMatchesDiscovery(issuerUrl?: string, discoveryUrl?: string): boolean {
  if (!issuerUrl || !discoveryUrl) return false;
  const entraPattern = /login\.microsoftonline\.com\/([^/]+)/i;
  const issuerMatch = entraPattern.exec(issuerUrl);
  const discoveryMatch = entraPattern.exec(discoveryUrl);
  if (issuerMatch && discoveryMatch) return issuerMatch[1]!.toLowerCase() === discoveryMatch[1]!.toLowerCase();
  const base = discoveryUrl.replace(/\/?\.well-known\/openid-configuration\/?$/, "").replace(/\/+$/, "");
  return base.toLowerCase() === issuerUrl.replace(/\/+$/, "").toLowerCase();
}

export function InvokePanel({ agentId, qualifiers, sessions, isStreaming, modelId, allowedModelIds = [], mcpNames = [], authorizerName, authorizerId, authorizerPoolId, authorizerDiscoveryUrl, isExternalIdp, loginIssuerUrl, currentUserId, onInvoke, onCancel }: InvokePanelProps) {
  const promptKey = `loom:invokePrompt:${agentId}`;
  const [prompt, setPrompt] = useState(() => sessionStorage.getItem(promptKey) ?? "");

  useEffect(() => {
    if (prompt) {
      sessionStorage.setItem(promptKey, prompt);
    } else {
      sessionStorage.removeItem(promptKey);
    }
  }, [prompt, promptKey]);
  const [qualifier, setQualifier] = useState(qualifiers[0] ?? "DEFAULT");
  const [selectedSession, setSelectedSession] = useState(NEW_SESSION);
  const [selectedCredential, setSelectedCredential] = useState(
    authorizerName && !isExternalIdp ? USER_TOKEN : NO_CREDENTIAL,
  );
  const [bearerToken, setBearerToken] = useState("");
  const [allCredentials, setAllCredentials] = useState<(AuthorizerCredential & { authorizer_name: string })[]>([]);
  const [credentialsLoaded, setCredentialsLoaded] = useState(false);
  const [resolvedAuthorizerId, setResolvedAuthorizerId] = useState<number | undefined>(authorizerId);
  const [selectedModel, setSelectedModel] = useState(modelId ?? "");
  const [modelOptions, setModelOptions] = useState<ModelOption[]>([]);

  // Connector state
  const connectorStorageKey = `loom:enabledConnectors:${agentId}:${currentUserId ?? "anonymous"}`;
  const [connectors, setConnectors] = useState<ConnectorInfo[]>([]);
  const [enabledConnectors, setEnabledConnectors] = useState<Set<number>>(new Set());
  const [showConnectors, setShowConnectors] = useState(false);
  const [showModelPicker, setShowModelPicker] = useState(false);
  const [apiKeyDialog, setApiKeyDialog] = useState<{ serverId: number; serverName: string } | null>(null);
  const [apiKeyInput, setApiKeyInput] = useState("");
  const [savingApiKey, setSavingApiKey] = useState(false);
  const connectorsRef = useRef<HTMLDivElement>(null);
  const modelPickerRef = useRef<HTMLDivElement>(null);

  // Authorizer linking state (cross-IdP)
  const [linkStatus, setLinkStatus] = useState<"unknown" | "linked" | "unlinked" | "linking" | "not-configured" | "same-idp">("unknown");

  const sameIdp = isExternalIdp && issuerMatchesDiscovery(loginIssuerUrl, authorizerDiscoveryUrl);

  useEffect(() => {
    if (sameIdp) {
      setLinkStatus("same-idp");
      setSelectedCredential(USER_TOKEN);
      return;
    }
    if (!resolvedAuthorizerId) return;
    checkAuthorizerLinkStatus(resolvedAuthorizerId)
      .then((r) => {
        if (r.linkable === false) setLinkStatus("not-configured");
        else setLinkStatus(r.linked ? "linked" : "unlinked");
      })
      .catch(() => setLinkStatus("unknown"));
  }, [resolvedAuthorizerId, sameIdp]);

  // Auto-select credential based on link status
  useEffect(() => {
    if (linkStatus === "linked") {
      setSelectedCredential(LINKED_TOKEN);
    } else if (linkStatus === "unlinked" && credentialsLoaded && allCredentials.length > 0) {
      setSelectedCredential(String(allCredentials[0]!.id));
    }
  }, [linkStatus, credentialsLoaded, allCredentials]);

  // Complete pending link exchange after redirect
  useEffect(() => {
    const code = sessionStorage.getItem("loom_link_code");
    if (!code || !resolvedAuthorizerId) return;
    const codeVerifier = sessionStorage.getItem("loom_link_code_verifier") || "";
    const redirectUri = sessionStorage.getItem("loom_link_redirect_uri") || "";
    sessionStorage.removeItem("loom_link_code");
    sessionStorage.removeItem("loom_link_code_verifier");
    sessionStorage.removeItem("loom_link_state");
    sessionStorage.removeItem("loom_link_redirect_uri");
    sessionStorage.removeItem("loom_link_auth_id");
    sessionStorage.removeItem("loom_link_return_url");
    setLinkStatus("linking");
    submitAuthorizerLinkCallback(resolvedAuthorizerId, code, codeVerifier, redirectUri)
      .then(() => setLinkStatus("linked"))
      .catch(() => setLinkStatus("unlinked"));
  }, [resolvedAuthorizerId]);

  const handleLinkAccount = async () => {
    if (!resolvedAuthorizerId) return;
    setLinkStatus("linking");
    try {
      const { authorize_url, code_verifier, state, redirect_uri } = await getAuthorizerLinkAuthorizeUrl(resolvedAuthorizerId);
      sessionStorage.setItem("loom_link_code_verifier", code_verifier);
      sessionStorage.setItem("loom_link_state", state);
      sessionStorage.setItem("loom_link_redirect_uri", redirect_uri);
      sessionStorage.setItem("loom_link_auth_id", String(resolvedAuthorizerId));
      sessionStorage.setItem("loom_link_return_url", window.location.pathname);
      localStorage.setItem("loom_link_return_agent_id", String(agentId));
      window.location.href = authorize_url;
    } catch {
      setLinkStatus("unlinked");
    }
  };

  const handleUnlinkAccount = async () => {
    if (!resolvedAuthorizerId) return;
    try {
      await deleteAuthorizerLink(resolvedAuthorizerId);
      setLinkStatus("unlinked");
      setSelectedCredential(authorizerName && !isExternalIdp ? USER_TOKEN : NO_CREDENTIAL);
    } catch {
      // Unlink failed silently
    }
  };

  useEffect(() => {
    setSelectedModel(modelId ?? "");
  }, [modelId, agentId]);

  useEffect(() => {
    if (!modelId) return;
    let cancelled = false;
    // /api/agents/models is Bedrock-only; LiteLLM's catalog is a separate
    // on-demand endpoint. Merge both so a LiteLLM agent's allowed_model_ids
    // resolve here — otherwise filteredModels is empty and the picker hides.
    Promise.all([
      fetchModels().catch(() => []),
      fetchLitellmModels().catch(() => []),
    ]).then(([bedrockModels, litellmModels]) => {
      if (!cancelled) setModelOptions([...bedrockModels, ...litellmModels]);
    });
    return () => { cancelled = true; };
  }, [modelId]);

  const filteredModels = allowedModelIds.length > 0
    ? modelOptions.filter((m) => allowedModelIds.includes(m.model_id))
    : modelId
      ? modelOptions.filter((m) => m.model_id === modelId)
      : [];

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const configs = await listAuthorizerConfigs();
        const matchingConfig = configs.find((c) =>
          (authorizerName && c.name === authorizerName) ||
          (authorizerPoolId && c.pool_id === authorizerPoolId) ||
          (authorizerDiscoveryUrl && c.discovery_url === authorizerDiscoveryUrl)
        );
        const results: (AuthorizerCredential & { authorizer_name: string })[] = [];
        const targetConfigs = matchingConfig ? [matchingConfig] : configs;
        for (const config of targetConfigs) {
          const creds = await listAuthorizerCredentials(config.id);
          for (const cred of creds) {
            if (cred.has_secret) {
              results.push({ ...cred, authorizer_name: config.name });
            }
          }
        }
        if (!cancelled) {
          setAllCredentials(results);
          setCredentialsLoaded(true);
          if (isExternalIdp && authorizerName && results.length > 0) {
            setSelectedCredential(String(results[0]!.id));
          }
          if (!authorizerId) {
            const match = configs.find((c) =>
              (authorizerName && c.name === authorizerName) ||
              (authorizerPoolId && c.pool_id === authorizerPoolId) ||
              (authorizerDiscoveryUrl && c.discovery_url === authorizerDiscoveryUrl)
            );
            if (match) setResolvedAuthorizerId(match.id);
          }
        }
      } catch {
        // Silently fail — credentials are optional
      }
    })();
    return () => { cancelled = true; };
  }, []);

  // Load connectors
  useEffect(() => {
    listConnectors().then(setConnectors).catch(() => {});
  }, []);

  // Restore enabled connectors from localStorage (only invoke-time connectors)
  useEffect(() => {
    const stored = localStorage.getItem(connectorStorageKey);
    if (stored) {
      try {
        setEnabledConnectors(new Set(JSON.parse(stored) as number[]));
      } catch { setEnabledConnectors(new Set()); }
    } else {
      setEnabledConnectors(new Set());
    }
  }, [connectorStorageKey]);

  // Close connector popover on outside click
  useEffect(() => {
    if (!showConnectors) return;
    function handleClickOutside(e: MouseEvent) {
      if (connectorsRef.current && !connectorsRef.current.contains(e.target as Node)) {
        setShowConnectors(false);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, [showConnectors]);

  // Close model picker on outside click
  useEffect(() => {
    if (!showModelPicker) return;
    function handleClickOutside(e: MouseEvent) {
      if (modelPickerRef.current && !modelPickerRef.current.contains(e.target as Node)) {
        setShowModelPicker(false);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, [showModelPicker]);

  const toggleConnector = (c: ConnectorInfo) => {
    const isEnabled = enabledConnectors.has(c.id);
    if (isEnabled) {
      setEnabledConnectors((prev) => {
        const next = new Set(prev);
        next.delete(c.id);
        localStorage.setItem(connectorStorageKey, JSON.stringify([...next]));
        return next;
      });
    } else if (c.auth_type === "api_key" && !c.has_user_api_key) {
      setApiKeyDialog({ serverId: c.id, serverName: c.name });
      setShowConnectors(false);
    } else {
      setEnabledConnectors((prev) => {
        const next = new Set(prev);
        next.add(c.id);
        localStorage.setItem(connectorStorageKey, JSON.stringify([...next]));
        return next;
      });
    }
  };

  const handleSaveApiKey = async () => {
    if (!apiKeyDialog || !apiKeyInput.trim()) return;
    setSavingApiKey(true);
    try {
      await setUserApiKey(apiKeyDialog.serverId, apiKeyInput.trim());
      setConnectors((prev) =>
        prev.map((c) => (c.id === apiKeyDialog.serverId ? { ...c, has_user_api_key: true } : c)),
      );
      setEnabledConnectors((prev) => {
        const next = new Set(prev);
        next.add(apiKeyDialog.serverId);
        localStorage.setItem(connectorStorageKey, JSON.stringify([...next]));
        return next;
      });
      setApiKeyDialog(null);
      setApiKeyInput("");
    } catch {
      // API key save failed silently
    } finally {
      setSavingApiKey(false);
    }
  };

  const disconnectConnector = async (c: ConnectorInfo) => {
    try {
      if (c.auth_type === "api_key" && c.has_user_api_key) {
        await deleteUserApiKey(c.id);
      }
      setConnectors((prev) =>
        prev.map((item) => (item.id === c.id ? { ...item, has_user_api_key: false } : item)),
      );
      setEnabledConnectors((prev) => {
        const next = new Set(prev);
        next.delete(c.id);
        localStorage.setItem(connectorStorageKey, JSON.stringify([...next]));
        return next;
      });
    } catch {
      // Disconnect failed silently
    }
  };

  // Filter sessions that match the selected qualifier, are not expired,
  // and belong to the current user (or have no owner recorded yet)
  const matchingSessions = sessions.filter(
    (s) => s.live_status !== "expired"
  );

  // Track whether the user has manually changed the session selector
  const userPickedRef = useRef(false);

  // Reset when agent changes
  useEffect(() => {
    setSelectedSession(NEW_SESSION);
    userPickedRef.current = false;
  }, [agentId]);

  // Auto-select the most recent session when sessions load or a new one appears,
  // unless the user has manually picked a session in this mount cycle.
  useEffect(() => {
    if (userPickedRef.current) {
      // User made a deliberate choice — only reset if their selection disappeared
      if (
        selectedSession !== NEW_SESSION &&
        !matchingSessions.some((s) => s.session_id === selectedSession)
      ) {
        setSelectedSession(NEW_SESSION);
        userPickedRef.current = false;
      }
      return;
    }
    if (matchingSessions.length > 0) {
      const sorted = [...matchingSessions].sort((a, b) =>
        (b.created_at ?? "").localeCompare(a.created_at ?? ""),
      );
      setSelectedSession(sorted[0]!.session_id);
    }
  }, [matchingSessions, selectedSession]);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!prompt.trim() || isStreaming) return;
    const sessionId = selectedSession === NEW_SESSION ? undefined : selectedSession;
    const credentialId = selectedCredential === USER_TOKEN || selectedCredential === LINKED_TOKEN || selectedCredential === NO_CREDENTIAL || selectedCredential === MANUAL_TOKEN
      ? undefined : Number(selectedCredential);
    const token = selectedCredential === MANUAL_TOKEN && bearerToken.trim()
      ? bearerToken.trim() : undefined;
    const runtimeModelId = selectedModel && selectedModel !== modelId ? selectedModel : undefined;
    const invokeOnlyIds = [...enabledConnectors].filter((id) => {
      const c = connectors.find((cn) => cn.id === id);
      return c && !mcpNames.includes(c.name);
    });
    const activeConnectorIds = invokeOnlyIds.length > 0 ? invokeOnlyIds : undefined;
    const useLinkedToken = selectedCredential === LINKED_TOKEN ? true : undefined;
    onInvoke(prompt.trim(), qualifier, sessionId, credentialId, token, runtimeModelId, activeConnectorIds, useLinkedToken);
  };

  const handleQualifierChange = (value: string) => {
    setQualifier(value);
    // Reset session selection when qualifier changes
    setSelectedSession(NEW_SESSION);
  };

  // OBO delegation detection: any MCP connector on this agent using OBO mode
  const oboConnectorNames = connectors
    .filter((c) => c.delegation_mode === "obo" && mcpNames.includes(c.name))
    .map((c) => c.name);
  const hasObo = oboConnectorNames.length > 0;
  const userTokenAvailable = (linkStatus === "linked" || linkStatus === "same-idp") ||
    selectedCredential === USER_TOKEN ||
    selectedCredential === LINKED_TOKEN ||
    (selectedCredential === MANUAL_TOKEN && bearerToken.trim().length > 0) ||
    allCredentials.some((c) => String(c.id) === selectedCredential);
  const oboWarning = hasObo && !userTokenAvailable;

  const groupedModels = groupModels(filteredModels);

  const currentModelName = selectedModel
    ? (filteredModels.find((m) => m.model_id === selectedModel)?.display_name ?? selectedModel)
    : (filteredModels.find((m) => m.model_id === modelId)?.display_name ?? modelId ?? "Model");

  return (
    <Card>
      <CardContent className="pt-2">
        <form onSubmit={handleSubmit} className="space-y-4">
          {/* Config selects row */}
          <div className="flex gap-4 flex-wrap">
            {qualifiers.length > 0 && (
              <div className="space-y-1.5">
                <Label className="text-xs text-muted-foreground">Endpoint</Label>
                <Select value={qualifier} onValueChange={handleQualifierChange}>
                  <SelectTrigger className="w-48">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {qualifiers.map((q) => (
                      <SelectItem key={q} value={q}>
                        {q}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            )}
            <div className="space-y-1.5">
              <Label className="text-xs text-muted-foreground">Session Identifier</Label>
              <Select value={selectedSession} onValueChange={(v) => { userPickedRef.current = true; setSelectedSession(v); }}>
                <SelectTrigger className="w-80">
                  <SelectValue placeholder="New session" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={NEW_SESSION}>New session</SelectItem>
                  {matchingSessions.map((s) => (
                    <SelectItem key={s.session_id} value={s.session_id}>
                      <span className="font-mono text-xs">{s.session_id}</span>
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1.5">
              <div className="flex items-center gap-1.5">
                <Label className="text-xs text-muted-foreground">Credential</Label>
                {(linkStatus === "linked" || linkStatus === "same-idp") && (
                  <>
                    <span className="inline-block h-1.5 w-1.5 rounded-full bg-green-500" title={linkStatus === "same-idp" ? "Same identity provider" : "Account linked"} />
                    {linkStatus === "linked" && (
                      <button
                        type="button"
                        onClick={() => void handleUnlinkAccount()}
                        className="text-muted-foreground/50 hover:text-destructive transition-colors"
                        title="Unlink account"
                      >
                        <Unplug className="h-3 w-3" />
                      </button>
                    )}
                  </>
                )}
              </div>
              <div className="flex items-center gap-4">
              <Select value={selectedCredential} onValueChange={(v) => { setSelectedCredential(v); if (v !== MANUAL_TOKEN) setBearerToken(""); }}>
                <SelectTrigger className="w-96">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {authorizerName ? (
                    <>
                      {linkStatus === "linked" && (
                        <SelectItem value={LINKED_TOKEN}>{authorizerName} / linked user token</SelectItem>
                      )}
                      {linkStatus === "same-idp" && (
                        <SelectItem value={USER_TOKEN}>{authorizerName} / current user&apos;s token</SelectItem>
                      )}
                      {!isExternalIdp && (
                        <SelectItem value={USER_TOKEN}>{authorizerName} / current user&apos;s token</SelectItem>
                      )}
                      {allCredentials.map((c) => (
                        <SelectItem key={c.id} value={String(c.id)}>
                          {c.authorizer_name} / {c.label}
                        </SelectItem>
                      ))}
                      <SelectItem value={MANUAL_TOKEN}>{authorizerName} / manual token</SelectItem>
                      {isExternalIdp && !credentialsLoaded && allCredentials.length === 0 && (
                        <SelectItem value={NO_CREDENTIAL} disabled>Loading credentials...</SelectItem>
                      )}
                    </>
                  ) : (
                    <SelectItem value={NO_CREDENTIAL}>No credentials (SigV4)</SelectItem>
                  )}
                </SelectContent>
              </Select>
              {resolvedAuthorizerId && linkStatus === "unlinked" && (
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  className="flex items-center gap-1.5 h-9"
                  onClick={() => void handleLinkAccount()}
                >
                  <Link2 className="h-3.5 w-3.5" />
                  Link Account
                </Button>
              )}
              {resolvedAuthorizerId && linkStatus === "linking" && (
                <span className="text-xs text-muted-foreground">Linking...</span>
              )}
              </div>
            </div>
            {selectedCredential === MANUAL_TOKEN && (
              <div className="space-y-1.5">
                <Label className="text-xs text-muted-foreground">Bearer Token</Label>
                <Input
                  type="password"
                  placeholder="Paste bearer token..."
                  value={bearerToken}
                  onChange={(e) => setBearerToken(e.target.value)}
                  className="w-80"
                />
              </div>
            )}
          </div>

          {/* Chat-style input box */}
      <div className="rounded-xl border bg-background shadow-sm">
        <Textarea
          placeholder="Enter your prompt..."
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              if (prompt.trim() && !isStreaming) handleSubmit(e);
            }
          }}
          rows={3}
          className="resize-none border-0 shadow-none focus-visible:ring-0 rounded-none rounded-t-xl"
        />
        <div className="flex items-center justify-between px-3 py-2 bg-background rounded-b-xl">
          {/* Left: Connectors */}
          <div className="relative flex items-center gap-2" ref={connectorsRef}>
            {connectors.length > 0 && (
              <button
                type="button"
                onClick={() => setShowConnectors((v) => !v)}
                className="flex items-center gap-1 text-xs text-muted-foreground rounded-md border px-2 py-1 hover:text-foreground hover:border-foreground/30 cursor-pointer"
                title="Connectors"
              >
                <Plug className="h-3 w-3" />
                <span>Connectors</span>
                {enabledConnectors.size > 0 && (
                  <span className="ml-0.5 text-[10px] text-green-600 dark:text-green-400">{enabledConnectors.size}</span>
                )}
              </button>
            )}
            {hasObo && !oboWarning && (
              <span
                className="flex items-center gap-1 text-[10px] text-blue-700 dark:text-blue-300 bg-blue-50 dark:bg-blue-950 border border-blue-200 dark:border-blue-900 rounded-md px-1.5 py-1"
                title={`User identity will be delegated to: ${oboConnectorNames.join(", ")}`}
              >
                <UserCheck className="h-3 w-3" />
                User identity delegated
              </span>
            )}
            {oboWarning && (
              <span
                className="flex items-center gap-1 text-[10px] text-amber-700 dark:text-amber-300 bg-amber-50 dark:bg-amber-950 border border-amber-200 dark:border-amber-900 rounded-md px-1.5 py-1"
                title="OBO delegation requires a user token — select a user credential to invoke."
              >
                <AlertTriangle className="h-3 w-3" />
                OBO requires authentication
              </span>
            )}
            {showConnectors && (() => {
              const deployTimeConnectors = connectors.filter((c) => mcpNames.includes(c.name));
              const invokeTimeConnectors = connectors.filter((c) => !mcpNames.includes(c.name));
              return (
              <div className="absolute bottom-8 left-0 z-50 w-72 rounded-lg border bg-background shadow-md py-1">
                {invokeTimeConnectors.length > 0 && (
                  <>
                    <div className="px-3 py-1.5 text-[10px] font-medium text-muted-foreground uppercase tracking-wider">
                      Additional Available Tools
                    </div>
                    {invokeTimeConnectors.map((c) => {
                      const isEnabled = enabledConnectors.has(c.id);
                      const needsKey = c.auth_type === "api_key" && !c.has_user_api_key;
                      const isConnected = c.auth_type === "none" || (c.auth_type === "api_key" && c.has_user_api_key);
                      return (
                        <div
                          key={c.id}
                          className="flex items-center justify-between px-3 py-2 text-xs hover:bg-accent transition-colors"
                        >
                          <button
                            type="button"
                            onClick={() => toggleConnector(c)}
                            className="flex items-center gap-2 min-w-0 flex-1"
                          >
                            <span className="truncate" title={c.name}>{c.name}</span>
                            {needsKey && (
                              <span className="flex items-center gap-0.5 text-amber-500 shrink-0">
                                <KeyRound className="h-3 w-3" />
                              </span>
                            )}
                            {c.auth_type === "oauth2" && !isEnabled && (
                              <span className="text-[10px] text-muted-foreground shrink-0">OAuth2</span>
                            )}
                          </button>
                          <div className="flex items-center gap-1.5 shrink-0">
                            {isConnected && c.auth_type !== "none" && (
                              <button
                                type="button"
                                onClick={(e) => { e.stopPropagation(); void disconnectConnector(c); }}
                                className="text-muted-foreground/50 hover:text-destructive transition-colors"
                                title={`Disconnect ${c.name}`}
                              >
                                <Unplug className="h-3 w-3" />
                              </button>
                            )}
                            <button type="button" onClick={() => toggleConnector(c)}>
                              <div
                                className={`relative w-7 h-4 rounded-full transition-colors ${
                                  isEnabled ? "bg-green-500" : "bg-muted-foreground/30"
                                }`}
                              >
                                <div
                                  className={`absolute top-0.5 h-3 w-3 rounded-full bg-white shadow-sm transition-transform ${
                                    isEnabled ? "translate-x-3.5" : "translate-x-0.5"
                                  }`}
                                />
                              </div>
                            </button>
                          </div>
                        </div>
                      );
                    })}
                  </>
                )}
                {deployTimeConnectors.length > 0 && (
                  <>
                    <div className="px-3 py-1.5 text-[10px] font-medium text-muted-foreground uppercase tracking-wider border-t mt-1 pt-1.5">
                      Built-in Tools
                    </div>
                    {deployTimeConnectors.map((c) => (
                      <div
                        key={c.id}
                        className="flex items-center justify-between px-3 py-2 text-xs opacity-70"
                      >
                        <span className="flex items-center gap-2 min-w-0 flex-1">
                          <span className="truncate" title={c.name}>{c.name}</span>
                        </span>
                        <div
                          className="relative w-7 h-4 rounded-full bg-green-500/60 cursor-not-allowed"
                          title="Attached at deploy time"
                        >
                          <div className="absolute top-0.5 h-3 w-3 rounded-full bg-white shadow-sm translate-x-3.5" />
                        </div>
                      </div>
                    ))}
                  </>
                )}
              </div>
              );
            })()}
            {apiKeyDialog && (
              <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
                <div className="w-96 rounded-lg border bg-background shadow-lg p-4 space-y-3">
                  <div className="text-sm font-medium">
                    API Key for {apiKeyDialog.serverName}
                  </div>
                  <p className="text-xs text-muted-foreground">
                    Enter your personal API key to connect to this MCP server.
                  </p>
                  <Input
                    type="password"
                    value={apiKeyInput}
                    onChange={(e) => setApiKeyInput(e.target.value)}
                    placeholder="Enter your API key"
                    onKeyDown={(e) => { if (e.key === "Enter") void handleSaveApiKey(); }}
                  />
                  <div className="flex justify-end gap-2">
                    <Button
                      type="button"
                      size="sm"
                      variant="ghost"
                      onClick={() => { setApiKeyDialog(null); setApiKeyInput(""); }}
                    >
                      Cancel
                    </Button>
                    <Button
                      type="button"
                      size="sm"
                      onClick={() => void handleSaveApiKey()}
                      disabled={!apiKeyInput.trim() || savingApiKey}
                    >
                      {savingApiKey ? "Saving..." : "Save"}
                    </Button>
                  </div>
                </div>
              </div>
            )}
          </div>

          {/* Right: Model picker + Send/Cancel */}
          <div className="flex items-center gap-2">
            {filteredModels.length > 0 && (
              <div className="relative" ref={modelPickerRef}>
                <button
                  type="button"
                  onClick={() => { if (filteredModels.length > 1) setShowModelPicker((v) => !v); }}
                  className={`flex items-center gap-1 text-xs text-muted-foreground rounded-md border px-2 py-1 ${
                    filteredModels.length > 1 ? "hover:text-foreground hover:border-foreground/30 cursor-pointer" : "cursor-default"
                  }`}
                >
                  <span>{currentModelName}</span>
                  {filteredModels.length > 1 && <ChevronDown className="h-3 w-3" />}
                </button>
                {showModelPicker && (
                  <div className="absolute bottom-7 right-0 z-50 w-56 rounded-lg border bg-background shadow-md py-1 max-h-64 overflow-y-auto">
                    {groupedModels.map(([group, models]) => (
                      <div key={group}>
                        <div className="px-3 py-1 text-[10px] font-medium text-muted-foreground uppercase tracking-wider">
                          {group}
                        </div>
                        {models.map((m) => {
                          const isDefault = m.model_id === modelId;
                          const isSelected = selectedModel ? m.model_id === selectedModel : isDefault;
                          return (
                            <button
                              type="button"
                              key={m.model_id}
                              onClick={() => {
                                setSelectedModel(isDefault ? (modelId ?? "") : m.model_id);
                                setShowModelPicker(false);
                              }}
                              className={`w-full text-left px-3 py-1.5 text-xs transition-colors hover:bg-accent ${
                                isSelected ? "font-semibold text-foreground" : "text-muted-foreground"
                              }`}
                            >
                              {m.display_name}
                              {isDefault && <span className="text-[10px] opacity-60 ml-1">(default)</span>}
                              {isSelected && !isDefault && <span className="text-[10px] opacity-60 ml-1">(selected)</span>}
                            </button>
                          );
                        })}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}
            <Button
              type="submit"
              size="icon"
              variant="ghost"
              className="h-7 w-7"
              disabled={isStreaming || !prompt.trim()}
              title={isStreaming ? "Streaming..." : "Send"}
            >
              <Send className="h-4 w-4" />
            </Button>
            {isStreaming && (
              <Button type="button" variant="ghost" size="icon" className="h-7 w-7" onClick={onCancel} title="Cancel stream">
                <X className="h-4 w-4" />
              </Button>
            )}
          </div>
        </div>
      </div>
        </form>
      </CardContent>
    </Card>
  );
}
