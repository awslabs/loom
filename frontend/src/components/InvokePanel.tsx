import { useState, useEffect, useRef } from "react";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectLabel,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Plug, Unplug, KeyRound, Send, Square, Link2, UserCheck, AlertTriangle, Copy } from "lucide-react";
import { toast } from "sonner";
import { MarkdownBlock } from "@/components/MarkdownRenderer";
import { ApprovalRequestBubble } from "@/components/ApprovalDialog";
import { ElicitationRequestBubble } from "@/components/ElicitationDialog";
import { statusVariant, statusDotClass } from "@/lib/status";
import { useTimezone } from "@/contexts/TimezoneContext";
import { formatTimestamp } from "@/lib/format";
import { listAuthorizerConfigs, listAuthorizerCredentials, checkAuthorizerLinkStatus, getAuthorizerLinkAuthorizeUrl, submitAuthorizerLinkCallback, deleteAuthorizerLink } from "@/api/security";
import { fetchModels, fetchLitellmModels } from "@/api/agents";
import { listConnectors, setUserApiKey, deleteUserApiKey } from "@/api/mcp";
import { sendElicitationResponse, type StreamSegment } from "@/hooks/useInvoke";
import { groupModels } from "@/lib/models";
import type { SessionResponse, AuthorizerCredential, ModelOption, ConnectorInfo, SSESessionStart, SSESessionEnd } from "@/api/types";

const NEW_SESSION = "__new__";
const USER_TOKEN = "__user__";
const LINKED_TOKEN = "__linked__";
const NO_CREDENTIAL = "__none__";
const MANUAL_TOKEN = "__manual__";
const RAIL_SESSION_COUNT = 4;

interface InvokePanelProps {
  agentId: number;
  agentName: string;
  qualifiers: string[];
  sessions: SessionResponse[];
  isStreaming: boolean;
  modelId?: string | null;
  allowedModelIds?: string[];
  memoryNames?: string[];
  mcpNames?: string[];
  authorizerName?: string;
  authorizerId?: number;
  authorizerPoolId?: string;
  authorizerDiscoveryUrl?: string;
  isExternalIdp?: boolean;
  loginIssuerUrl?: string;
  currentUserId?: string;
  streamedText: string;
  segments: StreamSegment[];
  sessionStart: SSESessionStart | null;
  sessionEnd: SSESessionEnd | null;
  error: string | null;
  rawError: string | null;
  onInvoke: (prompt: string, qualifier: string, sessionId?: string, credentialId?: number, bearerToken?: string, modelId?: string, connectorIds?: number[], useLinkedToken?: boolean) => void;
  onCancel: () => void;
  onOpenSessionDetail?: (sessionId: string) => void;
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

function formatToolName(raw: string): string {
  const parts = raw.split("___");
  return parts.length > 1 ? parts.slice(1).join(" / ") : raw;
}

function formatLatencyMs(ms: number | null | undefined): string {
  if (ms == null) return "—";
  return ms >= 1000 ? `${(ms / 1000).toFixed(1)}s` : `${Math.round(ms)}ms`;
}

function formatCost(cost: number | null | undefined): string {
  if (cost == null || cost === 0) return "—";
  if (cost < 0.01) return `$${cost.toFixed(6)}`;
  return `$${cost.toFixed(4)}`;
}


function ElapsedTimer({ since }: { since: number }) {
  const [elapsed, setElapsed] = useState(0);
  useEffect(() => {
    setElapsed(Math.floor((Date.now() - since) / 1000));
    const id = setInterval(() => setElapsed(Math.floor((Date.now() - since) / 1000)), 1000);
    return () => clearInterval(id);
  }, [since]);
  return <span className="tabular-nums">({elapsed}s)</span>;
}

function ToolCallRow({ tool, isActive }: { tool: { name: string; index: number; total: number; timestamp: number }; isActive: boolean }) {
  return (
    <div className="flex items-center gap-2.5 border-b bg-muted px-3 py-1.5 text-xs last:border-b-0">
      <span className={`h-1.5 w-1.5 shrink-0 rounded-full ${isActive ? "animate-pulse bg-primary" : "bg-success"}`} />
      <span className="truncate font-mono">tool · {formatToolName(tool.name)}</span>
      {isActive ? (
        <ElapsedTimer since={tool.timestamp} />
      ) : (
        <span className="ml-auto shrink-0 font-mono text-[10.5px] text-muted-foreground">done</span>
      )}
    </div>
  );
}

/** Renders the live segment stream (text / tool calls / approvals / elicitations) for the in-flight turn. */
function LiveTurnBody({ agentId, segments, isStreaming }: { agentId: number; segments: StreamSegment[]; isStreaming: boolean }) {
  const blocks: React.ReactNode[] = [];
  let toolGroup: { name: string; index: number; total: number; timestamp: number }[] = [];
  let toolGroupStart = 0;
  const flushTools = () => {
    if (toolGroup.length > 0) {
      const lastIdx = toolGroupStart + toolGroup.length - 1;
      blocks.push(
        <div key={`tools-${toolGroupStart}`} className="flex flex-col overflow-hidden rounded-[9px] border">
          {toolGroup.map((t, i) => (
            <ToolCallRow key={i} tool={t} isActive={isStreaming && toolGroupStart + i === lastIdx && toolGroupStart + i === segments.length - 1} />
          ))}
        </div>,
      );
      toolGroup = [];
    }
  };
  segments.forEach((seg, i) => {
    if (seg.type === "tool_use") {
      if (toolGroup.length === 0) toolGroupStart = i;
      toolGroup.push({ name: seg.name, index: seg.index, total: seg.total, timestamp: seg.timestamp });
    } else if (seg.type === "approval_request") {
      flushTools();
      blocks.push(<ApprovalRequestBubble key={`approval-${i}`} data={seg.data} />);
    } else if (seg.type === "approval_resolved") {
      flushTools();
    } else if (seg.type === "elicitation_request") {
      flushTools();
      blocks.push(<ElicitationRequestBubble key={`elicit-${i}`} data={seg.data} onRespond={(id, action, content) => sendElicitationResponse(agentId, id, action, content)} />);
    } else {
      flushTools();
      blocks.push(<MarkdownBlock key={i} text={seg.content} />);
    }
  });
  flushTools();
  return (
    <>
      {isStreaming && blocks.length === 0 && (
        <div className="flex items-center gap-2 text-muted-foreground">
          <span className="flex gap-0.5">
            <span className="h-1.5 w-1.5 rounded-full bg-muted-foreground/50 animate-bounce [animation-delay:0ms]" />
            <span className="h-1.5 w-1.5 rounded-full bg-muted-foreground/50 animate-bounce [animation-delay:150ms]" />
            <span className="h-1.5 w-1.5 rounded-full bg-muted-foreground/50 animate-bounce [animation-delay:300ms]" />
          </span>
          <span className="text-xs">Thinking…</span>
        </div>
      )}
      {blocks}
      {isStreaming && blocks.length > 0 && <span className="inline-block w-1.5 h-4 bg-foreground/70 animate-pulse ml-0.5 align-text-bottom" />}
    </>
  );
}

function UserBubble({ text, timestamp, currentUserId }: { text: string; timestamp?: string; currentUserId?: string }) {
  return (
    <div className="flex flex-col items-end gap-1.5">
      <div className="max-w-[600px] rounded-2xl rounded-br-md bg-primary px-3.5 py-2.5 text-[13.5px] leading-[1.55] whitespace-pre-wrap text-primary-foreground">
        {text}
      </div>
      {timestamp && (
        <span className="font-mono text-[10px] text-muted-foreground">{currentUserId ? `${currentUserId} · ` : ""}{timestamp}</span>
      )}
    </div>
  );
}

function AgentAttribution({ agentName, modelLabel }: { agentName: string; modelLabel?: string }) {
  return (
    <div className="flex items-center gap-2">
      <span className="font-mono text-[10px] tracking-wide text-muted-foreground uppercase">{agentName}</span>
      {modelLabel && (
        <span className="rounded-[4px] border bg-muted px-1.5 py-0.5 font-mono text-[9.5px] text-muted-foreground uppercase">{modelLabel}</span>
      )}
    </div>
  );
}

// Per-turn latency/tokens/cost live in the run strip at the top (aggregated across the session) —
// no need to repeat them under every turn. This just keeps the copy action.
function TurnFooter({ text }: { text?: string }) {
  const handleCopy = () => {
    if (!text) return;
    navigator.clipboard.writeText(text);
    toast.success("Copied to clipboard");
  };
  if (!text) return null;
  return (
    <div className="flex items-center pt-0.5">
      <button type="button" onClick={handleCopy} className="ml-auto flex items-center gap-1 text-[10.5px] text-muted-foreground hover:text-foreground">
        <Copy className="h-3 w-3" />copy
      </button>
    </div>
  );
}

function EmptyState({ agentName, onSeed }: { agentName: string; onSeed: (text: string) => void }) {
  const seeds = ["What can you help me with?", "Summarize your capabilities and tools", "Walk me through an example task"];
  return (
    <div className="flex flex-1 flex-col items-center justify-center gap-3.5 px-6 py-11 text-center">
      <div className="h-8 w-8 rounded-[9px] border bg-muted" />
      <div className="flex flex-col items-center gap-1">
        <div className="text-sm font-medium">Invoke {agentName}</div>
        <p className="max-w-[340px] text-[12.5px] leading-[1.55] text-muted-foreground">
          A session is created on your first message.
        </p>
      </div>
      <div className="flex max-w-[520px] flex-wrap justify-center gap-1.5">
        {seeds.map((s) => (
          <button
            key={s}
            type="button"
            onClick={() => onSeed(s)}
            className="rounded-md border bg-muted px-2.5 py-1.5 text-xs hover:bg-accent"
          >
            {s}
          </button>
        ))}
      </div>
    </div>
  );
}

export function InvokePanel({
  agentId, agentName, qualifiers, sessions, isStreaming, modelId, allowedModelIds = [], memoryNames = [], mcpNames = [],
  authorizerName, authorizerId, authorizerPoolId, authorizerDiscoveryUrl, isExternalIdp, loginIssuerUrl, currentUserId,
  streamedText, segments, sessionStart, sessionEnd, error, rawError, onInvoke, onCancel, onOpenSessionDetail,
}: InvokePanelProps) {
  const { timezone } = useTimezone();
  const promptKey = `loom:invokePrompt:${agentId}`;
  const [prompt, setPrompt] = useState(() => sessionStorage.getItem(promptKey) ?? "");
  const [lastPrompt, setLastPrompt] = useState<string | null>(null);
  const [showAllSessions, setShowAllSessions] = useState(false);

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
  const [apiKeyDialog, setApiKeyDialog] = useState<{ serverId: number; serverName: string } | null>(null);
  const [apiKeyInput, setApiKeyInput] = useState("");
  const [savingApiKey, setSavingApiKey] = useState(false);
  const connectorsRef = useRef<HTMLDivElement>(null);

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

  useEffect(() => {
    if (linkStatus === "linked") {
      setSelectedCredential(LINKED_TOKEN);
    } else if (linkStatus === "unlinked" && credentialsLoaded && allCredentials.length > 0) {
      setSelectedCredential(String(allCredentials[0]!.id));
    }
  }, [linkStatus, credentialsLoaded, allCredentials]);

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

  useEffect(() => {
    listConnectors().then(setConnectors).catch(() => {});
  }, []);

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

  const matchingSessions = sessions.filter((s) => s.live_status !== "expired");
  const sortedSessions = [...sessions].sort((a, b) => (b.created_at ?? "").localeCompare(a.created_at ?? ""));

  const userPickedRef = useRef(false);

  useEffect(() => {
    setSelectedSession(NEW_SESSION);
    setLastPrompt(null);
    userPickedRef.current = false;
  }, [agentId]);

  useEffect(() => {
    if (userPickedRef.current) {
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
    const trimmed = prompt.trim();
    const targetRecord = sessions.find((s) => s.session_id === selectedSession);
    const sessionId = selectedSession === NEW_SESSION || !targetRecord || targetRecord.live_status === "expired"
      ? undefined : selectedSession;
    const credentialId = selectedCredential === USER_TOKEN || selectedCredential === LINKED_TOKEN || selectedCredential === NO_CREDENTIAL || selectedCredential === MANUAL_TOKEN
      ? undefined : Number(selectedCredential);
    const token = selectedCredential === MANUAL_TOKEN && bearerToken.trim()
      ? bearerToken.trim() : undefined;
    const runtimeModelId = selectedModel && selectedModel !== modelId ? selectedModel : undefined;
    const invokeOnlyIds = [...enabledConnectors].filter((id) => {
      const c = connectors.find((cn) => cn.id === id);
      return c && (!mcpNames.includes(c.name) || c.auth_type === "api_key");
    });
    const activeConnectorIds = invokeOnlyIds.length > 0 ? invokeOnlyIds : undefined;
    const useLinkedToken = selectedCredential === LINKED_TOKEN ? true : undefined;
    setLastPrompt(trimmed);
    onInvoke(trimmed, qualifier, sessionId, credentialId, token, runtimeModelId, activeConnectorIds, useLinkedToken);
  };

  const handleQualifierChange = (value: string) => {
    setQualifier(value);
    setSelectedSession(NEW_SESSION);
  };

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
    : (filteredModels.find((m) => m.model_id === modelId)?.display_name ?? modelId ?? "");

  // ---- transcript assembly -------------------------------------------------
  const activeSessionId = sessionStart?.session_id ?? (selectedSession !== NEW_SESSION ? selectedSession : null);
  const activeSessionRecord = sessions.find((s) => s.session_id === activeSessionId) ?? null;
  // Exclude the invocation that's currently rendered by the live turn below — sessionStart/sessionEnd
  // persist after a request finishes, so once `sessions` refetches and includes this same invocation,
  // it would otherwise render twice.
  const historicalInvocations = (activeSessionRecord?.invocations ?? []).filter(
    (inv) => inv.invocation_id !== sessionEnd?.invocation_id,
  );
  const hasLiveTurn = Boolean(sessionStart);
  const hasTranscript = historicalInvocations.length > 0 || hasLiveTurn;

  const histTokens = historicalInvocations.reduce((sum, inv) => sum + (inv.input_tokens ?? 0) + (inv.output_tokens ?? 0), 0);
  const liveTokens = (sessionEnd?.input_tokens ?? 0) + (sessionEnd?.output_tokens ?? 0);
  const totalTokens = histTokens + liveTokens;
  const histCost = historicalInvocations.reduce((sum, inv) => sum + (inv.estimated_cost ?? 0), 0);
  const totalCost = histCost + (sessionEnd?.estimated_cost ?? 0);
  const totalTurns = historicalInvocations.length + (hasLiveTurn ? 1 : 0);
  const lastInvocation = historicalInvocations[historicalInvocations.length - 1];
  const lastLatencyMs = sessionEnd?.client_duration_ms ?? lastInvocation?.client_duration_ms ?? null;

  const railSessions = showAllSessions ? sortedSessions : sortedSessions.slice(0, RAIL_SESSION_COUNT);

  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-[1fr_300px]">
      {/* console */}
      <Card className="flex flex-col gap-0 overflow-hidden py-0">
        {activeSessionId && (
          <div className="flex flex-wrap items-center gap-3.5 border-b bg-muted px-4 py-2.5">
            <div className="flex items-center gap-1.5">
              <span className={`h-1.5 w-1.5 rounded-full ${isStreaming ? "animate-pulse bg-primary" : "bg-success"}`} />
              <button
                type="button"
                onClick={() => { navigator.clipboard.writeText(activeSessionId); toast.success("Copied session id"); }}
                className="font-mono text-[11.5px] hover:underline"
                title="Copy session id"
              >
                {activeSessionId.slice(0, 18)}
              </button>
            </div>
            <div className="h-3 w-px bg-border" />
            {[
              ["Turns", String(totalTurns)],
              ["Tokens", totalTokens > 0 ? totalTokens.toLocaleString() : "—"],
              ["Latency", formatLatencyMs(lastLatencyMs)],
              ["Est. cost", formatCost(totalCost)],
            ].map(([label, value]) => (
              <div key={label} className="flex items-baseline gap-1.5">
                <span className="font-mono text-[9.5px] tracking-wide text-muted-foreground uppercase">{label}</span>
                <span className="font-mono text-[11.5px] tabular-nums">{value}</span>
              </div>
            ))}
            {onOpenSessionDetail && (
              <button
                type="button"
                onClick={() => onOpenSessionDetail(activeSessionId)}
                className="ml-auto text-[11.5px] text-primary hover:underline"
              >
                Logs &amp; traces →
              </button>
            )}
          </div>
        )}

        <div className="flex min-h-[360px] flex-1 flex-col gap-5 p-5">
          {!hasTranscript ? (
            <EmptyState agentName={agentName} onSeed={(text) => setPrompt(text)} />
          ) : (
            <>
              {historicalInvocations.map((inv) => (
                <div key={inv.invocation_id} className="flex flex-col gap-5">
                  {inv.prompt_text && (
                    <UserBubble text={inv.prompt_text} timestamp={inv.created_at ? formatTimestamp(inv.created_at, timezone) : undefined} currentUserId={activeSessionRecord?.user_id ?? undefined} />
                  )}
                  <div className="flex max-w-[760px] flex-col gap-2">
                    <AgentAttribution agentName={agentName} />
                    <div className="text-[13.5px] leading-[1.65] text-pretty">
                      {inv.status === "error" ? (
                        <span className="text-destructive">{inv.error_message ?? "This invocation failed."}</span>
                      ) : inv.response_text ? (
                        <MarkdownBlock text={inv.response_text} />
                      ) : (
                        <span className="italic text-muted-foreground">Not captured</span>
                      )}
                    </div>
                    <TurnFooter text={inv.response_text ?? undefined} />
                  </div>
                </div>
              ))}

              {hasLiveTurn && (
                <div className="flex flex-col gap-5">
                  {lastPrompt && <UserBubble text={lastPrompt} timestamp="just now" currentUserId={currentUserId} />}
                  <div className="flex max-w-[760px] flex-col gap-2">
                    <AgentAttribution agentName={agentName} modelLabel={currentModelName || undefined} />
                    <div className="text-[13.5px] leading-[1.65] text-pretty">
                      <LiveTurnBody agentId={agentId} segments={segments} isStreaming={isStreaming} />
                    </div>
                    {!isStreaming && sessionEnd && (
                      <TurnFooter text={streamedText} />
                    )}
                  </div>
                </div>
              )}
            </>
          )}

          {error && (
            <div className="rounded-md border border-destructive/30 bg-destructive/[0.06] p-3 text-sm text-destructive">
              <p>{error}</p>
              {rawError && rawError !== error && (
                <details className="mt-1 text-xs">
                  <summary className="cursor-pointer text-muted-foreground hover:text-foreground">Show details</summary>
                  <pre className="mt-1 whitespace-pre-wrap rounded bg-muted p-2 font-mono text-xs text-muted-foreground">{rawError}</pre>
                </details>
              )}
            </div>
          )}
        </div>

        {/* composer */}
        <div className="p-4 pt-0">
          <form onSubmit={handleSubmit}>
            <div className="flex flex-col rounded-xl border bg-card transition-shadow focus-within:shadow-[0_0_0_3px_var(--color-primary)]/[0.08] focus-within:ring-[3px] focus-within:ring-primary/[0.08]">
              <Textarea
                placeholder={hasTranscript ? "Ask a follow-up…" : "Enter your prompt…"}
                value={prompt}
                onChange={(e) => setPrompt(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault();
                    if (prompt.trim() && !isStreaming) handleSubmit(e);
                  }
                }}
                rows={2}
                className="resize-none rounded-b-none border-0 bg-transparent shadow-none focus-visible:ring-0"
              />
              <div className="flex items-center gap-2 rounded-b-xl border-t bg-muted px-2.5 py-2">
                <div className="relative flex items-center gap-2" ref={connectorsRef}>
                  {connectors.length > 0 && (
                    <button
                      type="button"
                      onClick={() => setShowConnectors((v) => !v)}
                      className="flex items-center gap-1.5 rounded-md border bg-card px-2 py-1 text-xs text-muted-foreground hover:text-foreground"
                      title="Connectors"
                    >
                      <Plug className="h-3 w-3" />
                      Connectors
                      {enabledConnectors.size > 0 && <span className="font-mono text-[10px] text-success">{enabledConnectors.size}</span>}
                    </button>
                  )}
                  {hasObo && !oboWarning && (
                    <span
                      className="flex items-center gap-1 rounded-md border border-primary/20 bg-primary/[0.06] px-1.5 py-1 text-[10px] text-primary"
                      title={`User identity will be delegated to: ${oboConnectorNames.join(", ")}`}
                    >
                      <UserCheck className="h-3 w-3" />
                      Identity delegated
                    </span>
                  )}
                  {oboWarning && (
                    <span className="flex items-center gap-1 rounded-md border border-warning/30 bg-warning-bg px-1.5 py-1 text-[10px] text-warning" title="OBO delegation requires a user token.">
                      <AlertTriangle className="h-3 w-3" />
                      Auth required
                    </span>
                  )}
                  {showConnectors && (() => {
                    const deployTimeConnectors = connectors.filter((c) => mcpNames.includes(c.name));
                    const invokeTimeConnectors = connectors.filter((c) => !mcpNames.includes(c.name));
                    return (
                      <div className="absolute bottom-9 left-0 z-50 w-72 rounded-lg border bg-card py-1 shadow-md">
                        {invokeTimeConnectors.length > 0 && (
                          <>
                            <div className="px-3 py-1.5 font-mono text-[10px] uppercase tracking-wide text-muted-foreground">Additional tools</div>
                            {invokeTimeConnectors.map((c) => {
                              const isEnabled = enabledConnectors.has(c.id);
                              const needsKey = c.auth_type === "api_key" && !c.has_user_api_key;
                              const isConnected = c.auth_type === "none" || (c.auth_type === "api_key" && c.has_user_api_key);
                              return (
                                <div key={c.id} className="flex items-center justify-between px-3 py-2 text-xs hover:bg-accent">
                                  <button type="button" onClick={() => toggleConnector(c)} className="flex min-w-0 flex-1 items-center gap-2">
                                    <span className="truncate" title={c.name}>{c.name}</span>
                                    {needsKey && <KeyRound className="h-3 w-3 shrink-0 text-warning" />}
                                  </button>
                                  <div className="flex shrink-0 items-center gap-1.5">
                                    {isConnected && c.auth_type !== "none" && (
                                      <button type="button" onClick={(e) => { e.stopPropagation(); void disconnectConnector(c); }} className="text-muted-foreground/50 hover:text-destructive">
                                        <Unplug className="h-3 w-3" />
                                      </button>
                                    )}
                                    <button type="button" onClick={() => toggleConnector(c)}>
                                      <div className={`relative h-4 w-7 rounded-full transition-colors ${isEnabled ? "bg-success" : "bg-muted-foreground/30"}`}>
                                        <div className={`absolute top-0.5 h-3 w-3 rounded-full bg-white shadow-sm transition-transform ${isEnabled ? "translate-x-3.5" : "translate-x-0.5"}`} />
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
                            <div className="mt-1 border-t px-3 py-1.5 pt-1.5 font-mono text-[10px] uppercase tracking-wide text-muted-foreground">Built-in tools</div>
                            {deployTimeConnectors.map((c) => (
                              <div key={c.id} className="flex items-center justify-between px-3 py-2 text-xs opacity-70">
                                <span className="truncate">{c.name}</span>
                                <div className="relative h-4 w-7 cursor-not-allowed rounded-full bg-success/60" title="Attached at deploy time">
                                  <div className="absolute top-0.5 h-3 w-3 translate-x-3.5 rounded-full bg-white shadow-sm" />
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
                      <div className="w-96 space-y-3 rounded-lg border bg-card p-4 shadow-lg">
                        <div className="text-sm font-medium">API key for {apiKeyDialog.serverName}</div>
                        <p className="text-xs text-muted-foreground">Enter your personal API key to connect to this MCP server.</p>
                        <input
                          type="password"
                          value={apiKeyInput}
                          onChange={(e) => setApiKeyInput(e.target.value)}
                          placeholder="Enter your API key"
                          onKeyDown={(e) => { if (e.key === "Enter") void handleSaveApiKey(); }}
                          className="h-9 w-full rounded-md border bg-input-bg px-3 text-sm"
                        />
                        <div className="flex justify-end gap-2">
                          <Button type="button" size="sm" variant="ghost" onClick={() => { setApiKeyDialog(null); setApiKeyInput(""); }}>Cancel</Button>
                          <Button type="button" size="sm" onClick={() => void handleSaveApiKey()} disabled={!apiKeyInput.trim() || savingApiKey}>
                            {savingApiKey ? "Saving..." : "Save"}
                          </Button>
                        </div>
                      </div>
                    </div>
                  )}
                </div>
                <div className="ml-auto flex items-center gap-2">
                  <span className="font-mono text-[10.5px] text-muted-foreground">⏎ to send</span>
                  {isStreaming ? (
                    <Button type="button" size="icon" variant="ghost" className="h-7 w-7" onClick={onCancel} title="Stop">
                      <Square className="h-3.5 w-3.5" />
                    </Button>
                  ) : (
                    <Button type="submit" size="icon" className="h-7 w-7" disabled={!prompt.trim()} title="Send">
                      <Send className="h-3.5 w-3.5" />
                    </Button>
                  )}
                </div>
              </div>
            </div>
          </form>
        </div>
      </Card>

      {/* rail */}
      <div className="flex flex-col gap-3.5">
        <Card className="gap-3.5 py-4">
          <CardContent className="flex flex-col gap-3.5">
            <div className="text-[13px] font-semibold">Run configuration</div>

            {qualifiers.length > 0 && (
              <div className="flex flex-col gap-1.5">
                <span className="font-mono text-[9.5px] tracking-wide text-muted-foreground uppercase">Endpoint</span>
                <Select value={qualifier} onValueChange={handleQualifierChange}>
                  <SelectTrigger size="sm" className="w-full font-mono text-xs">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {qualifiers.map((q) => <SelectItem key={q} value={q}>{q}</SelectItem>)}
                  </SelectContent>
                </Select>
              </div>
            )}

            {filteredModels.length > 0 && (
              <div className="flex flex-col gap-1.5">
                <span className="font-mono text-[9.5px] tracking-wide text-muted-foreground uppercase">Model</span>
                <Select value={selectedModel || modelId || ""} onValueChange={(v) => setSelectedModel(v === modelId ? (modelId ?? "") : v)}>
                  <SelectTrigger size="sm" className="w-full text-xs">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {groupedModels.map(([group, models]) => (
                      <SelectGroup key={group}>
                        <SelectLabel>{group}</SelectLabel>
                        {models.map((m) => (
                          <SelectItem key={m.model_id} value={m.model_id}>
                            {m.display_name}{m.model_id === modelId ? " (default)" : ""}
                          </SelectItem>
                        ))}
                      </SelectGroup>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            )}

            <div className="flex flex-col gap-1.5">
              <div className="flex items-center gap-1.5">
                <span className="font-mono text-[9.5px] tracking-wide text-muted-foreground uppercase">Credential</span>
                {(linkStatus === "linked" || linkStatus === "same-idp") && (
                  <>
                    <span className="inline-block h-1.5 w-1.5 rounded-full bg-success" title={linkStatus === "same-idp" ? "Same identity provider" : "Account linked"} />
                    {linkStatus === "linked" && (
                      <button type="button" onClick={() => void handleUnlinkAccount()} className="text-muted-foreground/50 hover:text-destructive" title="Unlink account">
                        <Unplug className="h-3 w-3" />
                      </button>
                    )}
                  </>
                )}
              </div>
              <Select value={selectedCredential} onValueChange={(v) => { setSelectedCredential(v); if (v !== MANUAL_TOKEN) setBearerToken(""); }}>
                <SelectTrigger size="sm" className="w-full text-xs">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {authorizerName ? (
                    <>
                      {linkStatus === "linked" && <SelectItem value={LINKED_TOKEN}>{authorizerName} / linked user token</SelectItem>}
                      {linkStatus === "same-idp" && <SelectItem value={USER_TOKEN}>{authorizerName} / current user&apos;s token</SelectItem>}
                      {!isExternalIdp && <SelectItem value={USER_TOKEN}>{authorizerName} / current user&apos;s token</SelectItem>}
                      {allCredentials.map((c) => (
                        <SelectItem key={c.id} value={String(c.id)}>{c.authorizer_name} / {c.label}</SelectItem>
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
                <Button type="button" size="sm" variant="outline" className="h-7 gap-1.5 text-xs" onClick={() => void handleLinkAccount()}>
                  <Link2 className="h-3 w-3" />Link account
                </Button>
              )}
              {resolvedAuthorizerId && linkStatus === "linking" && (
                <span className="text-xs text-muted-foreground">Linking...</span>
              )}
              {selectedCredential === MANUAL_TOKEN && (
                <input
                  type="password"
                  placeholder="Paste bearer token..."
                  value={bearerToken}
                  onChange={(e) => setBearerToken(e.target.value)}
                  className="h-8 w-full rounded-md border bg-input-bg px-2.5 text-xs"
                />
              )}
            </div>

            {(memoryNames.length > 0 || mcpNames.length > 0) && (
              <>
                <div className="h-px bg-border" />
                <div className="flex flex-col gap-2.5">
                  {memoryNames.length > 0 && (
                    <div className="flex items-center justify-between gap-2.5">
                      <span className="font-mono text-[9.5px] tracking-wide text-muted-foreground uppercase">Memory</span>
                      <span className="truncate font-mono text-[11.5px]">{memoryNames.join(", ")}</span>
                    </div>
                  )}
                  {mcpNames.length > 0 && (
                    <div className="flex items-center justify-between gap-2.5">
                      <span className="font-mono text-[9.5px] tracking-wide text-muted-foreground uppercase">MCP</span>
                      <span className="truncate font-mono text-[11.5px]">{mcpNames.join(", ")}</span>
                    </div>
                  )}
                </div>
              </>
            )}
          </CardContent>
        </Card>

        <Card className="gap-2.5 py-4">
          <CardContent className="flex flex-col gap-2.5">
            <div className="flex items-center gap-2">
              <span className="text-[13px] font-semibold">Sessions</span>
              <Badge variant="outline" className="text-[11px] px-1.5 py-0 font-mono">{sessions.length}</Badge>
              {sortedSessions.length > RAIL_SESSION_COUNT && (
                <button type="button" onClick={() => setShowAllSessions((v) => !v)} className="ml-auto text-[11.5px] text-primary hover:underline">
                  {showAllSessions ? "Show less" : "View all"}
                </button>
              )}
            </div>
            {sortedSessions.length === 0 ? (
              <p className="text-xs text-muted-foreground">No sessions yet.</p>
            ) : (
              railSessions.map((s) => {
                const variant = statusVariant(s.live_status === "active" ? "READY" : s.live_status === "error" ? "FAILED" : s.live_status === "expired" ? null : "CREATING");
                const isSelected = s.session_id === selectedSession;
                return (
                  <div
                    key={s.session_id}
                    role="button"
                    tabIndex={0}
                    onClick={() => { userPickedRef.current = true; setSelectedSession(s.session_id); setLastPrompt(null); }}
                    onKeyDown={(e) => { if (e.key === "Enter") { userPickedRef.current = true; setSelectedSession(s.session_id); setLastPrompt(null); } }}
                    className={`flex cursor-pointer flex-col gap-1 rounded-md border px-2.5 py-2 text-left transition-colors ${isSelected ? "border-primary/30 bg-primary/[0.05]" : "hover:bg-accent/50"}`}
                  >
                    <div className="flex items-center gap-1.5">
                      <span className={`h-1.5 w-1.5 shrink-0 rounded-full ${statusDotClass(variant)}`} />
                      <span className="truncate font-mono text-[11.5px]">{s.session_id.slice(0, 16)}</span>
                      <span className="shrink-0 font-mono text-[10px] tracking-wide uppercase text-muted-foreground">{s.live_status}</span>
                      {onOpenSessionDetail && (
                        <button
                          type="button"
                          onClick={(e) => { e.stopPropagation(); onOpenSessionDetail(s.session_id); }}
                          className="ml-auto shrink-0 text-[10.5px] text-primary hover:underline"
                        >
                          open
                        </button>
                      )}
                    </div>
                    <div className="flex items-center gap-1.5 font-mono text-[10.5px] text-muted-foreground">
                      <span>{s.invocations.length} turn{s.invocations.length === 1 ? "" : "s"}</span>
                      <span>·</span>
                      <span>{formatTimestamp(s.created_at, timezone)}</span>
                    </div>
                  </div>
                );
              })
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
