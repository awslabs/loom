import { useState, useEffect, useRef, useCallback, useMemo } from "react";
import { Send, Plus, Brain, LogOut, Bot, User, X, Loader2, Palette, RefreshCw, ChevronDown, Wrench, Plug, KeyRound, Unplug, Link2, UserCheck, AlertTriangle } from "lucide-react";
import { ApprovalRequestBubble } from "@/components/ApprovalDialog";
import { ElicitationRequestBubble } from "@/components/ElicitationDialog";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import ReactMarkdown from "react-markdown";
import { CollapsibleJsonBlock } from "@/components/CollapsibleJsonBlock";
import remarkGfm from "remark-gfm";
import { toast } from "sonner";
import { listAgents, fetchModels, fetchLitellmModels } from "@/api/agents";
import { listSessions, getSession, hideSession } from "@/api/invocations";
import { listMemories, getMemoryRecords } from "@/api/memories";
import { trackAction } from "@/api/audit";
import { useInvoke, clearInvokeState, sendElicitationResponse, type StreamSegment } from "@/hooks/useInvoke";
import { useAuth } from "@/contexts/AuthContext";
import { useTheme, isLightTheme, THEME_LABELS, type Theme } from "@/contexts/ThemeContext";
import { listConnectors, setUserApiKey, deleteUserApiKey } from "@/api/mcp";
import { listAuthorizerConfigs, checkAuthorizerLinkStatus, getAuthorizerLinkAuthorizeUrl, submitAuthorizerLinkCallback, deleteAuthorizerLink } from "@/api/security";
import { Input } from "@/components/ui/input";
import { groupModels } from "@/lib/models";
import type { AgentResponse, SessionResponse, MemoryResponse, MemoryRecordItem, ModelOption, ConnectorInfo } from "@/api/types";

interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  text: string;
  toolNames?: string[];
  hitlSegments?: StreamSegment[];
}

interface ChatPageProps {
  userGroups: string[];
  onLogout: () => void;
  viewAsUser?: string | null;
  onExitViewAs?: () => void;
}


export function ChatPage({ userGroups, onLogout, viewAsUser, onExitViewAs }: ChatPageProps) {
  const { user, browserSessionId, authConfig: loginAuthConfig } = useAuth();
  const { theme, setTheme } = useTheme();

  const userGroupNames = userGroups
    .filter((g) => g.startsWith("g-users-"))
    .map((g) => g.replace("g-users-", ""));

  const currentUserIdLocal = user?.username ?? user?.sub;
  // Backend-authoritative user_id: set from session_start to ensure consistency
  const [backendUserId, setBackendUserId] = useState<string | null>(null);
  const currentUserId = backendUserId ?? currentUserIdLocal;

  // Agent state
  const [agents, setAgents] = useState<AgentResponse[]>([]);
  const [agentsLoading, setAgentsLoading] = useState(true);
  const [selectedAgentId, setSelectedAgentId] = useState<number | null>(null);

  // Agent list search/sort
  const [agentSearch, setAgentSearch] = useState("");
  const [agentSort, setAgentSort] = useState<"asc" | "desc">("asc");
  const [showThemePicker, setShowThemePicker] = useState(false);
  const themePickerRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!showThemePicker) return;
    function handleClickOutside(e: MouseEvent) {
      if (themePickerRef.current && !themePickerRef.current.contains(e.target as Node)) {
        setShowThemePicker(false);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, [showThemePicker]);

  // Session state
  const [sessions, setSessions] = useState<SessionResponse[]>([]);
  const [currentSessionId, setCurrentSessionId] = useState<string | null>(null);
  const [sessionToHide, setSessionToHide] = useState<string | null>(null);
  const [hidingSession, setHidingSession] = useState(false);

  // Chat state
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [pendingPrompt, setPendingPrompt] = useState<string | null>(null);
  const [queuedPrompt, setQueuedPrompt] = useState<string | null>(null);
  const [input, setInput] = useState("");
  // Persist HITL segments per invocation ID so they survive re-fetches
  const hitlSegmentsMap = useRef<Map<string, StreamSegment[]>>(new Map());

  // Memory panel state
  const [showMemory, setShowMemory] = useState(false);
  const [memories, setMemories] = useState<MemoryResponse[]>([]);
  const [memoryRecords, setMemoryRecords] = useState<MemoryRecordItem[]>([]);
  const [memoryRecordsLoading, setMemoryRecordsLoading] = useState(false);
  const [memoryRecordsError, setMemoryRecordsError] = useState<string | null>(null);
  const [memoryRefreshCounter, setMemoryRefreshCounter] = useState(0);

  // Model selection state
  const [allModels, setAllModels] = useState<ModelOption[]>([]);
  const [selectedModelId, setSelectedModelId] = useState<string | null>(null);
  const [showModelPicker, setShowModelPicker] = useState(false);
  const modelPickerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    // /api/agents/models is Bedrock-only (see backend's TestModelsEndpointsSplit) —
    // LiteLLM's catalog is a separate on-demand endpoint. Merge both so agents whose
    // allowed_model_ids reference LiteLLM models still resolve to entries here;
    // otherwise the runtime model-switch picker has nothing to match against and
    // silently renders as if the agent only has one allowed model.
    Promise.all([
      fetchModels().catch(() => []),
      fetchLitellmModels().catch(() => []),
    ]).then(([bedrockModels, litellmModels]) => {
      setAllModels([...bedrockModels, ...litellmModels]);
    });
  }, []);

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

  // Authorizer linking state
  const [resolvedAuthorizerId, setResolvedAuthorizerId] = useState<number | null>(null);
  const [linkStatus, setLinkStatus] = useState<"unknown" | "linked" | "unlinked" | "linking" | "not-configured" | "same-idp">("unknown");

  // Resolve authorizer ID when selected agent changes
  useEffect(() => {
    if (!selectedAgentId) { setResolvedAuthorizerId(null); setLinkStatus("unknown"); return; }
    const agent = agents.find((a) => a.id === selectedAgentId);
    const authConfig = agent?.authorizer_config;
    if (!authConfig?.type) { setResolvedAuthorizerId(null); setLinkStatus("not-configured"); return; }

    // Same-IdP detection: login issuer matches agent's authorizer discovery URL
    // Only applies when user logged in via Cognito directly (not external IdP),
    // since an Entra user's token is NOT valid for a Cognito authorizer.
    const isExternalLogin = loginAuthConfig?.provider_type && loginAuthConfig.provider_type !== "cognito";
    if (!isExternalLogin && loginAuthConfig?.user_pool_id && authConfig.pool_id &&
        loginAuthConfig.user_pool_id === authConfig.pool_id) {
      setLinkStatus("same-idp");
      setResolvedAuthorizerId(null);
      return;
    }
    if (isExternalLogin && authConfig.discovery_url && loginAuthConfig?.issuer_url) {
      const entraPattern = /login\.microsoftonline\.com\/([^/]+)/i;
      const issuerMatch = entraPattern.exec(loginAuthConfig.issuer_url);
      const discoveryMatch = entraPattern.exec(authConfig.discovery_url);
      let sameIdp = false;
      if (issuerMatch && discoveryMatch) {
        sameIdp = issuerMatch[1]!.toLowerCase() === discoveryMatch[1]!.toLowerCase();
      } else {
        const base = authConfig.discovery_url.replace(/\/?\.well-known\/openid-configuration\/?$/, "").replace(/\/+$/, "");
        sameIdp = base.toLowerCase() === loginAuthConfig.issuer_url.replace(/\/+$/, "").toLowerCase();
      }
      if (sameIdp) {
        setLinkStatus("same-idp");
        setResolvedAuthorizerId(null);
        return;
      }
    }

    listAuthorizerConfigs()
      .then((configs) => {
        const match = configs.find((c) =>
          (authConfig.name && c.name === authConfig.name) ||
          (authConfig.pool_id && c.pool_id === authConfig.pool_id) ||
          (authConfig.discovery_url && c.discovery_url === authConfig.discovery_url)
        );
        if (match) setResolvedAuthorizerId(match.id);
        else setResolvedAuthorizerId(null);
      })
      .catch(() => setResolvedAuthorizerId(null));
  }, [selectedAgentId, agents, loginAuthConfig]);

  // Check link status when authorizer is resolved
  useEffect(() => {
    if (!resolvedAuthorizerId) return;
    if (linkStatus === "same-idp") return;
    checkAuthorizerLinkStatus(resolvedAuthorizerId)
      .then((r) => {
        if (r.linkable === false) setLinkStatus("not-configured");
        else setLinkStatus(r.linked ? "linked" : "unlinked");
      })
      .catch(() => setLinkStatus("unknown"));
  }, [resolvedAuthorizerId]);

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
      if (selectedAgentId != null) sessionStorage.setItem("loom_link_agent_id", String(selectedAgentId));
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
    } catch {
      // Unlink failed silently
    }
  };

  // Connectors state (scoped per agent)
  const connectorStorageKey = selectedAgentId != null ? `loom:enabledConnectors:${selectedAgentId}:${currentUserId ?? "anonymous"}` : null;
  const [connectors, setConnectors] = useState<ConnectorInfo[]>([]);
  const [enabledConnectors, setEnabledConnectors] = useState<Set<number>>(new Set());
  const [showConnectors, setShowConnectors] = useState(false);
  const [apiKeyDialog, setApiKeyDialog] = useState<{ serverId: number; serverName: string } | null>(null);
  const [apiKeyInput, setApiKeyInput] = useState("");
  const [savingApiKey, setSavingApiKey] = useState(false);
  const connectorsRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!connectorStorageKey) { setEnabledConnectors(new Set()); return; }
    const stored = localStorage.getItem(connectorStorageKey);
    if (stored) {
      try {
        setEnabledConnectors(new Set(JSON.parse(stored) as number[]));
      } catch { setEnabledConnectors(new Set()); }
    } else {
      setEnabledConnectors(new Set());
    }
  }, [connectorStorageKey, agents, selectedAgentId, connectors]);

  const toggleConnector = (c: ConnectorInfo) => {
    const isEnabled = enabledConnectors.has(c.id);
    if (isEnabled) {
      setEnabledConnectors((prev) => {
        const next = new Set(prev);
        next.delete(c.id);
        if (connectorStorageKey) localStorage.setItem(connectorStorageKey, JSON.stringify([...next]));
        return next;
      });
    } else if (c.auth_type === "api_key" && !c.has_user_api_key) {
      setApiKeyDialog({ serverId: c.id, serverName: c.name });
      setShowConnectors(false);
    } else {
      setEnabledConnectors((prev) => {
        const next = new Set(prev);
        next.add(c.id);
        if (connectorStorageKey) localStorage.setItem(connectorStorageKey, JSON.stringify([...next]));
        return next;
      });
    }
  };

  useEffect(() => {
    listConnectors().then(setConnectors).catch(() => {});
  }, []);

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
        if (connectorStorageKey) localStorage.setItem(connectorStorageKey, JSON.stringify([...next]));
        return next;
      });
      setApiKeyDialog(null);
      setApiKeyInput("");
      toast.success("API key saved");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Failed to save API key");
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
        if (connectorStorageKey) localStorage.setItem(connectorStorageKey, JSON.stringify([...next]));
        return next;
      });
      toast.success(`Disconnected from ${c.name}`);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Failed to disconnect");
    }
  };

  const messagesEndRef = useRef<HTMLDivElement>(null);

  // Per-agent chat state preservation (enables background streaming)
  const savedAgentState = useRef<
    Map<number, { messages: ChatMessage[]; pendingPrompt: string | null; currentSessionId: string | null }>
  >(new Map());

  const { streamedText, segments, sessionStart, sessionEnd, isStreaming, toolNames, error, invoke, cancel } = useInvoke(
    selectedAgentId ?? 0,
  );

  // Load and filter agents by group
  useEffect(() => {
    setAgentsLoading(true);
    listAgents()
      .then((all) => {
        const accessible = all.filter((a) => {
          if (a.deployment_status === "removing") return false;
          const group = (a.tags["loom:group"] as string | undefined) ?? "";
          return !group || userGroupNames.includes(group);
        });
        setAgents(accessible);
        const savedAgentId = sessionStorage.getItem("loom_link_agent_id");
        if (savedAgentId) {
          sessionStorage.removeItem("loom_link_agent_id");
          const id = Number(savedAgentId);
          if (accessible.some((a) => a.id === id)) {
            setSelectedAgentId(id);
            return;
          }
        }
        if (accessible.length === 1) {
          const first = accessible[0];
          if (first) setSelectedAgentId(first.id);
        }
      })
      .catch(() => {})
      .finally(() => setAgentsLoading(false));
  }, []);

  // Load sessions for selected agent (server-side user scoping)
  useEffect(() => {
    if (selectedAgentId === null) {
      setSessions([]);
      return;
    }
    if (isStreaming) return;
    listSessions(selectedAgentId, currentUserId ?? undefined)
      .then((data) => {
        setSessions(data);
      })
      .catch(() => {});
  }, [selectedAgentId, currentUserId, isStreaming]);

  // Load memories for selected agent
  useEffect(() => {
    if (!selectedAgentId) {
      setMemories([]);
      return;
    }
    const agent = agents.find((a) => a.id === selectedAgentId);
    if (!agent || agent.memory_names.length === 0) {
      setMemories([]);
      return;
    }
    listMemories()
      .then((all) => {
        setMemories(all.filter((m) => agent.memory_names.includes(m.name)));
      })
      .catch(() => {});
  }, [selectedAgentId, agents]);

  // Load memory records when panel is opened (scoped to current user via JWT)
  useEffect(() => {
    if (!showMemory || memories.length === 0) {
      if (!showMemory) {
        setMemoryRecords([]);
        setMemoryRecordsError(null);
      }
      return;
    }
    setMemoryRecordsLoading(true);
    setMemoryRecordsError(null);
    const firstMemory = memories[0];
    if (!firstMemory) {
      setMemoryRecordsLoading(false);
      return;
    }
    getMemoryRecords(firstMemory.id)
      .then((res) => {
        setMemoryRecords(res.records);
        setMemoryRecordsError(null);
      })
      .catch((err) => {
        const errorMsg = err instanceof Error ? err.message : "Failed to load memories";
        setMemoryRecordsError(errorMsg);
        setMemoryRecords([]);
        toast.error("Failed to load memories", {
          description: "Check that the memory resource is active and try again.",
        });
      })
      .finally(() => setMemoryRecordsLoading(false));
  }, [showMemory, memories, memoryRefreshCounter]);

  const filteredAgents = useMemo(() => {
    let result = agents;
    if (agentSearch.trim()) {
      const q = agentSearch.toLowerCase();
      result = result.filter(
        (a) =>
          (a.name ?? a.runtime_id).toLowerCase().includes(q) ||
          (a.description ?? "").toLowerCase().includes(q),
      );
    }
    result = [...result].sort((a, b) => {
      const cmp = (a.name ?? a.runtime_id).localeCompare(b.name ?? b.runtime_id);
      return agentSort === "desc" ? -cmp : cmp;
    });
    return result;
  }, [agents, agentSearch, agentSort]);

  const selectedAgent = agents.find((a) => a.id === selectedAgentId);

  const availableModels = useMemo(() => {
    if (!selectedAgent) return [];
    // The catalog (allModels) is filtered by the admin's global enabled-models
    // allowlist (Settings -> Models), which is independent of — and may be
    // narrower than — this agent's own allowed_model_ids. The invoke endpoint
    // only ever validates against the agent's allowed_model_ids, so synthesize
    // an entry for any allowed id the catalog is missing rather than silently
    // hiding an otherwise-invocable model from the picker.
    const withFallback = (ids: string[]) =>
      ids.map((id) => allModels.find((m) => m.model_id === id) ?? { model_id: id, display_name: id });
    const allowed = selectedAgent.allowed_model_ids;
    if (allowed.length > 0) return withFallback(allowed);
    if (selectedAgent.model_id) return withFallback([selectedAgent.model_id]);
    return [];
  }, [selectedAgent, allModels]);

  useEffect(() => {
    setSelectedModelId(null);
  }, [selectedAgentId]);

  // When a session starts, immediately refresh the sessions list so the tab appears in the sidebar
  const lastSessionStartRef = useRef<typeof sessionStart>(null);
  useEffect(() => {
    if (sessionStart && sessionStart !== lastSessionStartRef.current && selectedAgentId !== null) {
      lastSessionStartRef.current = sessionStart;
      setCurrentSessionId(sessionStart.session_id);
      // Use the backend's authoritative user_id for future session queries
      if (sessionStart.user_id && sessionStart.user_id !== backendUserId) {
        setBackendUserId(sessionStart.user_id);
      }
      listSessions(selectedAgentId, sessionStart.user_id ?? currentUserId ?? undefined)
        .then((data) => {
          setSessions(data);
        })
        .catch(() => {});
    }
  }, [sessionStart, selectedAgentId, currentUserId, backendUserId]);

  // When invocation completes, load the authoritative session from the backend
  // and use it to populate the chat history. setPendingPrompt(null) is deferred
  // until AFTER setMessages so the streaming bubble stays visible while the
  // fetch is in progress — eliminating the flash-of-empty-content.
  const lastSessionEndRef = useRef<typeof sessionEnd>(null);
  const pendingPromptRef = useRef<string | null>(null);
  pendingPromptRef.current = pendingPrompt;
  const toolNamesRef = useRef<string[]>([]);
  toolNamesRef.current = toolNames;
  const segmentsRef = useRef<StreamSegment[]>([]);
  segmentsRef.current = segments;
  const streamedTextRef = useRef<string>("");
  streamedTextRef.current = streamedText;

  useEffect(() => {
    if (sessionEnd && sessionEnd !== lastSessionEndRef.current && pendingPromptRef.current) {
      lastSessionEndRef.current = sessionEnd;
      setCurrentSessionId(sessionEnd.session_id);

      if (selectedAgentId !== null) {
        const sessionId = sessionEnd.session_id;
        // Load authoritative messages from the backend, then clear pendingPrompt.
        // Keeping pendingPrompt set until setMessages runs prevents the streaming
        // bubble from disappearing before the persisted messages are ready.
        //
        // Capture the current pendingPrompt so we only clear it if it hasn't been
        // replaced by a new invocation (e.g. auto-sent queued prompt) by the time
        // the async fetch completes.
        const capturedPending = pendingPromptRef.current;
        const capturedToolNames = toolNamesRef.current.length > 0 ? [...toolNamesRef.current] : undefined;
        const capturedHitlSegments = segmentsRef.current.filter(
          s => s.type === "tool_use" || s.type === "approval_request" || s.type === "approval_resolved" || s.type === "elicitation_request"
        );
        getSession(selectedAgentId, sessionId)
          .then((session) => {
            const msgs: ChatMessage[] = [];
            const lastInv = session.invocations[session.invocations.length - 1];
            // Store HITL segments for this invocation
            if (lastInv && capturedHitlSegments.length > 0) {
              hitlSegmentsMap.current.set(lastInv.invocation_id, capturedHitlSegments);
            }
            for (const inv of session.invocations) {
              if (inv.prompt_text)
                msgs.push({ id: `user-${inv.invocation_id}`, role: "user", text: inv.prompt_text });
              if (inv.response_text)
                msgs.push({
                  id: `assistant-${inv.invocation_id}`,
                  role: "assistant",
                  text: inv.response_text,
                  hitlSegments: hitlSegmentsMap.current.get(inv.invocation_id),
                });
            }
            // Attach tool names to the last assistant message
            if (capturedToolNames) {
              for (let i = msgs.length - 1; i >= 0; i--) {
                if (msgs[i]!.role === "assistant") { msgs[i]!.toolNames = capturedToolNames; break; }
              }
            }
            setMessages(msgs);
            // Only clear pendingPrompt if it still matches the prompt from this
            // completed stream. If auto-send replaced it with a queued prompt,
            // the ref will have changed and we must not clear it.
            if (pendingPromptRef.current === capturedPending) {
              setPendingPrompt(null);
            }
          })
          .catch(() => {
            if (pendingPromptRef.current === capturedPending) {
              setPendingPrompt(null);
            }
          });

        listSessions(selectedAgentId, currentUserId ?? undefined)
          .then((data) => {
            setSessions(data);
          })
          .catch(() => {});
      } else {
        setPendingPrompt(null);
      }
    }
  }, [sessionEnd, selectedAgentId, currentUserId]);

  // Clear pending prompt on error
  useEffect(() => {
    if (error && pendingPrompt && !isStreaming) {
      setPendingPrompt(null);
    }
  }, [error, pendingPrompt, isStreaming]);

  // Auto-send queued prompt when streaming completes without error
  useEffect(() => {
    if (!isStreaming && queuedPrompt && !error) {
      const prompt = queuedPrompt;
      setQueuedPrompt(null);
      setPendingPrompt(prompt);
      const agentName = agents.find((a) => a.id === selectedAgentId)?.name ?? String(selectedAgentId ?? 0);
      if (user && browserSessionId) trackAction(user.username ?? user.sub, browserSessionId, "agent", "invoke", agentName);
      const agent = agents.find((a) => a.id === selectedAgentId);
      const rtModel = selectedModelId && agent && selectedModelId !== agent.model_id ? selectedModelId : undefined;
      const deployNames = agent?.mcp_names ?? [];
      const invokeOnlyIds = Array.from(enabledConnectors).filter((id) => {
        const c = connectors.find((cn) => cn.id === id);
        return c && !deployNames.includes(c.name);
      });
      const activeConnectorIds = invokeOnlyIds.length > 0 ? invokeOnlyIds : undefined;
      invoke(prompt, "DEFAULT", currentSessionId ?? undefined, undefined, undefined, rtModel, activeConnectorIds, linkStatus === "linked" ? true : undefined);
    }
  }, [isStreaming, queuedPrompt, error, selectedModelId, selectedAgentId, agents, enabledConnectors, connectors, linkStatus]);

  // Scroll to bottom on new messages or streaming updates
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, streamedText, isStreaming, queuedPrompt]);

  const handleSend = useCallback(async () => {
    if (!input.trim() || selectedAgentId === null) return;
    const prompt = input.trim();
    if (isStreaming) {
      // Enqueue — last-write-wins
      setQueuedPrompt(prompt);
      setInput("");
      return;
    }
    setInput("");
    setPendingPrompt(prompt);
    const agentName = agents.find((a) => a.id === selectedAgentId)?.name ?? String(selectedAgentId);
    if (user && browserSessionId) trackAction(user.username ?? user.sub, browserSessionId, "agent", "invoke", agentName);
    const runtimeModelId = selectedModelId && selectedAgent && selectedModelId !== selectedAgent.model_id ? selectedModelId : undefined;
    const deployNames = selectedAgent?.mcp_names ?? [];
    const invokeOnlyIds = Array.from(enabledConnectors).filter((id) => {
      const c = connectors.find((cn) => cn.id === id);
      return c && !deployNames.includes(c.name);
    });
    const activeConnectorIds = invokeOnlyIds.length > 0 ? invokeOnlyIds : undefined;
    await invoke(prompt, "DEFAULT", currentSessionId ?? undefined, undefined, undefined, runtimeModelId, activeConnectorIds, linkStatus === "linked" ? true : undefined);
  }, [input, isStreaming, selectedAgentId, currentSessionId, invoke, agents, user, browserSessionId, selectedModelId, selectedAgent, enabledConnectors, connectors, linkStatus]);

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      void handleSend();
    }
  };

  const handleConfirmHideSession = useCallback(async () => {
    if (!sessionToHide || selectedAgentId === null) return;
    setHidingSession(true);
    try {
      await hideSession(selectedAgentId, sessionToHide);
      const agentName = agents.find((a) => a.id === selectedAgentId)?.name ?? String(selectedAgentId);
      if (user && browserSessionId) trackAction(user.username ?? user.sub, browserSessionId, "agent", "remove_conversation", agentName);
      setSessions((prev) => prev.filter((s) => s.session_id !== sessionToHide));
      // If the hidden session was active, reset to blank chat
      if (currentSessionId === sessionToHide) {
        setMessages([]);
        setCurrentSessionId(null);
        setPendingPrompt(null);
      }
      setSessionToHide(null);
    } finally {
      setHidingSession(false);
    }
  }, [sessionToHide, selectedAgentId, currentSessionId, agents, user, browserSessionId]);

  const handleNewConversation = useCallback(() => {
    setMessages([]);
    setCurrentSessionId(null);
    setPendingPrompt(null);
    setQueuedPrompt(null);
    lastSessionEndRef.current = null;
    lastSessionStartRef.current = null;
    if (selectedAgentId !== null) {
      clearInvokeState(selectedAgentId);
      const agentName = agents.find((a) => a.id === selectedAgentId)?.name ?? String(selectedAgentId);
      if (user && browserSessionId) trackAction(user.username ?? user.sub, browserSessionId, "agent", "new_conversation", agentName);
    }
  }, [selectedAgentId, agents, user, browserSessionId]);

  const handleSelectAgent = useCallback(
    (id: number) => {
      if (id === selectedAgentId) return;
      const agentName = agents.find((a) => a.id === id)?.name ?? String(id);
      if (user && browserSessionId) trackAction(user.username ?? user.sub, browserSessionId, "navigation", "agent_detail", agentName);
      // Save current agent state without cancelling the in-flight stream
      if (selectedAgentId !== null) {
        savedAgentState.current.set(selectedAgentId, {
          messages,
          pendingPrompt,
          currentSessionId,
        });
      }
      // Restore saved state for the target agent (or blank slate)
      const saved = savedAgentState.current.get(id);
      setMessages(saved?.messages ?? []);
      setPendingPrompt(saved?.pendingPrompt ?? null);
      setQueuedPrompt(null);
      setCurrentSessionId(saved?.currentSessionId ?? null);
      // Reset so the sessionEnd effect re-fires for the restored agent
      lastSessionEndRef.current = null;
      setSelectedAgentId(id);
    },
    [selectedAgentId, messages, pendingPrompt, currentSessionId, agents, user, browserSessionId],
  );

  const handleSelectSession = useCallback(
    async (sessionId: string) => {
      if (selectedAgentId === null) return;
      if (user && browserSessionId) trackAction(user.username ?? user.sub, browserSessionId, "navigation", "session_detail", sessionId);
      try {
        const session = await getSession(selectedAgentId, sessionId);
        const msgs: ChatMessage[] = [];
        for (const inv of session.invocations) {
          if (inv.prompt_text) {
            msgs.push({ id: `user-${inv.invocation_id}`, role: "user", text: inv.prompt_text });
          }
          if (inv.response_text) {
            msgs.push({
              id: `assistant-${inv.invocation_id}`,
              role: "assistant",
              text: inv.response_text,
              hitlSegments: hitlSegmentsMap.current.get(inv.invocation_id),
            });
          }
        }
        setMessages(msgs);
        setCurrentSessionId(sessionId);
        setPendingPrompt(null);
      } catch {
        // silently fail
      }
    },
    [selectedAgentId, user, browserSessionId],
  );

  // Only show streaming indicators for the session that is actively streaming.
  // When a user views a different session while a new one is streaming in the
  // background, the thinking/response bubbles must not appear in that other session.
  const isCurrentlyStreaming =
    isStreaming && (!sessionStart || sessionStart.session_id === currentSessionId);

  const hasMemory = selectedAgent && selectedAgent.memory_names.length > 0;

  // OBO delegation detection: any MCP connector tied to this agent uses OBO mode
  const agentMcpNames = selectedAgent?.mcp_names ?? [];
  const oboConnectorNames = connectors
    .filter((c) => c.delegation_mode === "obo" && agentMcpNames.includes(c.name))
    .map((c) => c.name);
  const hasObo = oboConnectorNames.length > 0;
  const userTokenAvailable = linkStatus === "linked" || linkStatus === "same-idp";
  const oboWarning = hasObo && !userTokenAvailable;

  return (
    <div className="h-screen bg-background flex flex-col overflow-hidden">
      {/* View-as banner for admins previewing the end-user experience */}
      {viewAsUser && onExitViewAs && (
        <div className="shrink-0 bg-primary/10 border-b border-primary/20 px-4 py-1.5 flex items-center justify-between text-xs text-primary">
          <span>
            Previewing end-user experience as <strong>{viewAsUser}</strong>
          </span>
          <button onClick={onExitViewAs} className="hover:underline font-medium">
            Exit preview
          </button>
        </div>
      )}

      <div className="flex-1 flex overflow-hidden">
        {/* Sidebar */}
        <aside className="w-64 border-r bg-card flex flex-col shrink-0 h-full overflow-hidden">
          {/* Logo */}
          <div className="p-4 border-b shrink-0">
            <img
              src={
                isLightTheme(theme)
                  ? "/assets/loom_light_alt.png"
                  : "/assets/loom_dark_alt.png"
              }
              alt="Loom"
              className="h-15"
            />
          </div>

          {/* Agent display (single agent) */}
          {agents.length === 1 && selectedAgent && (
            <div className="p-3 border-b shrink-0">
              <p className="text-xs font-medium text-muted-foreground mb-1.5">Agent</p>
              <div className="px-3 py-2 rounded bg-primary text-primary-foreground text-sm">
                <span className="truncate block">{selectedAgent.name ?? selectedAgent.runtime_id}</span>
              </div>
            </div>
          )}

          {/* Agent picker (shown when multiple agents available) */}
          {agents.length > 1 && (
            <div className="p-3 border-b shrink-0">
              <div className="flex items-center justify-between mb-1.5">
                <p className="text-xs font-medium text-muted-foreground">Agent</p>
                <div className="flex gap-1">
                  {(["asc", "desc"] as const).map((opt) => (
                    <button
                      key={opt}
                      onClick={() => setAgentSort(opt)}
                      className={`text-xs px-1.5 py-0.5 rounded transition-colors ${
                        agentSort === opt
                          ? "bg-primary/20 text-primary"
                          : "text-muted-foreground hover:bg-accent"
                      }`}
                      title={opt === "asc" ? "Sort A–Z" : "Sort Z–A"}
                    >
                      {opt === "asc" ? "A–Z" : "Z–A"}
                    </button>
                  ))}
                </div>
              </div>
              <input
                type="text"
                placeholder="Search agents…"
                value={agentSearch}
                onChange={(e) => setAgentSearch(e.target.value)}
                className="w-full text-xs rounded border bg-background px-2 py-1 mb-2 outline-none focus:ring-1 ring-ring placeholder:text-muted-foreground/50"
              />
              <div className="space-y-1">
                {filteredAgents.length === 0 ? (
                  <p className="text-xs text-muted-foreground px-1">No agents match</p>
                ) : (
                  filteredAgents.map((a) => (
                    <button
                      key={a.id}
                      onClick={() => handleSelectAgent(a.id)}
                      className={`w-full text-left px-3 py-2 rounded text-sm transition-colors ${
                        selectedAgentId === a.id
                          ? "bg-primary text-primary-foreground"
                          : "text-muted-foreground hover:bg-accent hover:text-accent-foreground"
                      }`}
                    >
                      <span className="truncate block">{a.name ?? a.runtime_id}</span>
                    </button>
                  ))
                )}
              </div>
            </div>
          )}

          {/* New conversation button */}
          <div className="p-3 border-b shrink-0">
            <Button
              variant="outline"
              size="sm"
              className="w-full gap-2"
              onClick={handleNewConversation}
              disabled={selectedAgentId === null}
            >
              <Plus className="h-3.5 w-3.5" />
              New Conversation
            </Button>
          </div>

          {/* Conversation history */}
          <div className="flex-1 overflow-y-auto p-2">
            <p className="px-2 py-1 text-xs font-medium text-muted-foreground">Conversations</p>

            {/* Inline hide confirmation */}
            {sessionToHide && (
              <div className="mx-1 mb-2 rounded border border-destructive/40 bg-destructive/5 p-3 text-xs space-y-2">
                <p className="font-medium text-foreground">Remove this conversation?</p>
                <p className="text-muted-foreground">This removes it from your view only. The underlying data, logs, and any memories the agent formed remain on the backend.</p>
                <div className="flex gap-2 pt-1">
                  <Button size="sm" variant="destructive" className="h-6 text-xs px-2" onClick={() => void handleConfirmHideSession()} disabled={hidingSession}>
                    {hidingSession ? "Removing…" : "Remove"}
                  </Button>
                  <Button size="sm" variant="ghost" className="h-6 text-xs px-2" onClick={() => setSessionToHide(null)} disabled={hidingSession}>
                    Cancel
                  </Button>
                </div>
              </div>
            )}

            {sessions.length === 0 ? (
              <p className="px-2 py-1 text-xs text-muted-foreground">No conversations yet</p>
            ) : (
              sessions.map((session) => {
                const isActive = currentSessionId === session.session_id;
                const isCurrentlyStreamingSession = isStreaming && isActive;
                const isOwned = !!session.user_id && session.user_id === currentUserId;
                return (
                  <div
                    key={session.session_id}
                    className={`group relative flex items-stretch rounded text-xs transition-colors ${
                      isActive
                        ? "bg-primary text-primary-foreground"
                        : "text-muted-foreground hover:bg-accent hover:text-accent-foreground"
                    }`}
                  >
                    <button
                      onClick={() => void handleSelectSession(session.session_id)}
                      className="flex-1 text-left px-3 py-2 min-w-0"
                    >
                      <div className="font-medium truncate">
                        {session.created_at
                          ? new Date(session.created_at).toLocaleString(undefined, {
                              month: "short",
                              day: "numeric",
                              hour: "2-digit",
                              minute: "2-digit",
                            })
                          : session.session_id.slice(0, 12) + "..."}
                      </div>
                      <div className={isActive ? "opacity-75" : "text-muted-foreground"}>
                        {session.invocations.length}{" "}
                        {session.invocations.length === 1 ? "exchange" : "exchanges"}
                      </div>
                    </button>
                    {!isCurrentlyStreamingSession && isOwned && (
                      <button
                        onClick={(e) => { e.stopPropagation(); setSessionToHide(session.session_id); }}
                        className={`opacity-0 group-hover:opacity-100 transition-opacity shrink-0 px-1.5 flex items-center ${
                          isActive ? "text-primary-foreground/70 hover:text-primary-foreground" : "text-muted-foreground hover:text-foreground"
                        }`}
                        title="Remove from history"
                      >
                        <X className="h-3 w-3" />
                      </button>
                    )}
                  </div>
                );
              })
            )}
          </div>

          {/* Memory button */}
          {hasMemory && (
            <div className="p-3 shrink-0">
              <Button
                variant="outline"
                size="sm"
                className="w-full gap-2"
                onClick={() => setShowMemory((v) => !v)}
              >
                <Brain className="h-3.5 w-3.5" />
                My Memory
              </Button>
            </div>
          )}

          {/* User info + theme + logout */}
          <div className="p-3 border-t shrink-0">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2 min-w-0">
                <User className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                <span className="text-xs text-muted-foreground truncate">
                  {user?.username ?? "User"}
                </span>
              </div>
              <div className="flex items-center gap-1">
                <div className="relative" ref={themePickerRef}>
                  <button
                    onClick={() => setShowThemePicker((v) => !v)}
                    className="text-muted-foreground hover:text-foreground transition-colors"
                    title="Change theme"
                  >
                    <Palette className="h-3.5 w-3.5" />
                  </button>
                  {showThemePicker && (
                    <div className="absolute bottom-6 right-0 z-50 w-44 rounded border bg-white shadow-md py-1">
                      <div className="px-3 py-1 text-[10px] font-semibold text-gray-400 uppercase tracking-wide">Light</div>
                      {(Object.entries(THEME_LABELS) as [Theme, string][])
                        .filter(([k]) => isLightTheme(k as Theme))
                        .map(([k, v]) => (
                          <button
                            key={k}
                            onClick={() => {
                              setTheme(k);
                              setShowThemePicker(false);
                            }}
                            className={`w-full text-left px-3 py-1.5 text-xs transition-colors hover:bg-gray-100 text-gray-700 ${
                              theme === k ? "font-bold" : ""
                            }`}
                          >
                            {v}
                          </button>
                        ))}
                      <div className="px-3 py-1 mt-1 text-[10px] font-semibold text-gray-400 uppercase tracking-wide border-t border-gray-100">Dark</div>
                      {(Object.entries(THEME_LABELS) as [Theme, string][])
                        .filter(([k]) => !isLightTheme(k as Theme))
                        .map(([k, v]) => (
                          <button
                            key={k}
                            onClick={() => {
                              setTheme(k);
                              setShowThemePicker(false);
                            }}
                            className={`w-full text-left px-3 py-1.5 text-xs transition-colors hover:bg-gray-100 text-gray-700 ${
                              theme === k ? "font-bold" : ""
                            }`}
                          >
                            {v}
                          </button>
                        ))}
                    </div>
                  )}
                </div>
                <button
                  onClick={onLogout}
                  className="text-muted-foreground hover:text-foreground transition-colors"
                  title="Sign out"
                >
                  <LogOut className="h-3.5 w-3.5" />
                </button>
              </div>
            </div>
          </div>
        </aside>

        {/* Main chat area */}
        <div className="flex-1 flex flex-col overflow-hidden">
          {agentsLoading ? (
            <div className="flex-1 flex items-center justify-center">
              <p className="text-muted-foreground text-sm">Loading...</p>
            </div>
          ) : agents.length === 0 ? (
            <div className="flex-1 flex items-center justify-center">
              <div className="text-center">
                <Bot className="h-12 w-12 mx-auto mb-3 text-muted-foreground opacity-40" />
                <p className="text-muted-foreground">No agents available for your account.</p>
                <p className="text-xs text-muted-foreground mt-1">
                  Contact your administrator for access.
                </p>
              </div>
            </div>
          ) : selectedAgentId === null ? (
            <div className="flex-1 flex items-center justify-center">
              <div className="text-center">
                <Bot className="h-12 w-12 mx-auto mb-3 text-muted-foreground opacity-40" />
                <p className="text-muted-foreground">Select an agent to start chatting</p>
              </div>
            </div>
          ) : (
            <>
              {/* Chat header */}
              <div className="border-b px-6 py-3 flex items-center gap-3 shrink-0">
                <Bot className="h-5 w-5 text-muted-foreground shrink-0 self-start mt-0.5" />
                <div>
                  <div className="font-medium">
                    {selectedAgent?.name ?? selectedAgent?.runtime_id ?? "Agent"}
                  </div>
                  {selectedAgent?.description && (
                    <div className="text-xs text-muted-foreground">
                      {selectedAgent.description}
                    </div>
                  )}
                </div>
              </div>

              {/* Messages */}
              <div className="flex-1 overflow-y-auto relative">
                {messages.length === 0 && !isCurrentlyStreaming && !pendingPrompt ? (
                  <div className="absolute inset-0 flex items-center justify-center">
                    <div className="text-center text-muted-foreground">
                      <p className="text-sm">
                        Start a conversation with{" "}
                        {selectedAgent?.name ?? "the agent"}
                      </p>
                      <p className="text-xs mt-1">Type a message below to begin</p>
                    </div>
                  </div>
                ) : (
                  <div className="max-w-3xl mx-auto px-6 py-6 space-y-4">
                    {messages.map((msg) => (
                      <MessageBubble key={msg.id} role={msg.role} text={msg.text} toolNames={msg.toolNames} hitlSegments={msg.hitlSegments} />
                    ))}

                    {/* In-flight user message */}
                    {pendingPrompt && (
                      <MessageBubble role="user" text={pendingPrompt} />
                    )}

                    {/* Thinking indicator — shown while waiting for first segment */}
                    {isCurrentlyStreaming && segments.length === 0 && <ThinkingBubble />}

                    {/* Streaming bubble — renders segments inline (text + tool calls) */}
                    {((isCurrentlyStreaming && segments.length > 0) ||
                      (!isCurrentlyStreaming && pendingPrompt !== null && (!!streamedText || segments.length > 0))) && (
                      <StreamingBubble
                        segments={segments}
                        isStreaming={isCurrentlyStreaming}
                        onElicitationRespond={
                          selectedAgentId != null
                            ? (id, action, content) => {
                                // Annotate the segment with the user's response for persistence
                                const seg = segments.find(
                                  (s) => s.type === "elicitation_request" && s.data.elicitation_id === id
                                );
                                if (seg && seg.type === "elicitation_request") {
                                  if (action === "decline") {
                                    seg.resolvedSummary = "Declined";
                                  } else if (content) {
                                    // Match display format: yes/no choices show as "Yes"/"No"
                                    const keys = Object.keys(content);
                                    if (keys.length === 1 && keys[0] === "response") {
                                      seg.resolvedSummary = content.response === "yes" ? "Yes" : "No";
                                    } else if (keys.length === 1 && keys[0] === "approved") {
                                      seg.resolvedSummary = content.approved ? "Yes" : "No";
                                    } else {
                                      seg.resolvedSummary = Object.entries(content).map(([k, v]) => `${k}: ${v}`).join(", ");
                                    }
                                  } else {
                                    seg.resolvedSummary = "Approved";
                                  }
                                }
                                sendElicitationResponse(selectedAgentId, id, action, content);
                              }
                            : undefined
                        }
                      />
                    )}

                    {/* Error display */}
                    {error && !isStreaming && (
                      <div className="flex justify-start">
                        <div className="max-w-[70%] rounded-2xl px-4 py-3 bg-destructive/10 text-destructive text-sm">
                          {error}
                        </div>
                      </div>
                    )}

                    {/* Queued message bubble */}
                    {queuedPrompt && (
                      <div className="flex justify-end">
                        <div className="relative max-w-[70%] rounded-2xl px-4 py-3 bg-primary/50 text-primary-foreground text-sm">
                          <ReactMarkdown remarkPlugins={[remarkGfm]} components={{
                            p: ({ children }) => <p className="mb-2 last:mb-0">{children}</p>,
                            ul: ({ children }) => <ul className="list-disc pl-4 mb-2 space-y-0.5">{children}</ul>,
                            ol: ({ children }) => <ol className="list-decimal pl-4 mb-2 space-y-0.5">{children}</ol>,
                            li: ({ children }) => <li className="leading-snug">{children}</li>,
                            code: ({ className, children }) => className?.startsWith("language-") ? <code className={className}>{children}</code> : <code className="rounded bg-black/10 dark:bg-white/10 px-1 py-0.5 text-xs font-mono">{children}</code>,
                            pre: ({ children }) => <pre className="mb-2 overflow-x-auto rounded bg-black/10 dark:bg-white/10 p-3 text-xs font-mono">{children}</pre>,
                            strong: ({ children }) => <strong className="font-semibold">{children}</strong>,
                            a: ({ href, children }) => <a href={href} className="underline underline-offset-2 hover:opacity-80" target="_blank" rel="noopener noreferrer">{children}</a>,
                          }}>{queuedPrompt}</ReactMarkdown>
                          <button
                            onClick={() => setQueuedPrompt(null)}
                            className="absolute -top-2 -right-2 h-5 w-5 rounded-full bg-destructive text-destructive-foreground flex items-center justify-center hover:bg-destructive/80"
                            title="Cancel queued message"
                          >
                            <X className="h-3 w-3" />
                          </button>
                        </div>
                      </div>
                    )}

                    <div ref={messagesEndRef} />
                  </div>
                )}
              </div>

              {/* Auth linking banner */}
              {resolvedAuthorizerId && linkStatus === "unlinked" && selectedAgent && (
                <div className="px-4 pt-2 shrink-0">
                  <div className="max-w-3xl mx-auto flex items-center gap-3 rounded-lg border border-amber-200 dark:border-amber-800 bg-amber-50 dark:bg-amber-950/30 px-4 py-2.5">
                    <Link2 className="h-4 w-4 text-amber-600 dark:text-amber-400 shrink-0" />
                    <div className="flex-1 min-w-0">
                      <p className="text-xs text-amber-800 dark:text-amber-300">
                        <span className="font-medium">{selectedAgent.name}</span> requires authentication via <span className="font-medium">{selectedAgent.authorizer_config?.name ?? "an external provider"}</span>.
                      </p>
                      <p className="text-xs text-amber-800 dark:text-amber-300">
                        Link your account to use this agent.
                      </p>
                    </div>
                    <Button
                      size="sm"
                      variant="outline"
                      className="shrink-0 h-7 text-xs border-amber-300 dark:border-amber-700 hover:bg-amber-100 dark:hover:bg-amber-900/50"
                      onClick={() => void handleLinkAccount()}
                    >
                      <Link2 className="h-3 w-3 mr-1" />
                      Link Account
                    </Button>
                  </div>
                </div>
              )}

              {/* Input area */}
              <div className="px-4 pt-2 pb-4 shrink-0">
                <div className="max-w-3xl mx-auto rounded-xl border bg-background shadow-sm">
                  <Textarea
                    placeholder="Message..."
                    value={input}
                    onChange={(e) => setInput(e.target.value)}
                    onKeyDown={handleKeyDown}
                    rows={1}
                    className="resize-none border-0 shadow-none focus-visible:ring-0 rounded-none rounded-t-xl"
                  />
                  <div className="flex items-center justify-between px-3 py-2 bg-background rounded-b-xl">
                    <div className="relative" ref={connectorsRef}>
                      {connectors.length > 0 && (
                        <button
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
                      {showConnectors && (() => {
                        const agentMcpNames = agents.find((a) => a.id === selectedAgentId)?.mcp_names ?? [];
                        const deployTimeConnectors = connectors.filter((c) => agentMcpNames.includes(c.name));
                        const invokeTimeConnectors = connectors.filter((c) => !agentMcpNames.includes(c.name));
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
                                          onClick={(e) => { e.stopPropagation(); void disconnectConnector(c); }}
                                          className="text-muted-foreground/50 hover:text-destructive transition-colors"
                                          title={`Disconnect ${c.name}`}
                                        >
                                          <Unplug className="h-3 w-3" />
                                        </button>
                                      )}
                                      <button onClick={() => toggleConnector(c)}>
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
                                size="sm"
                                variant="ghost"
                                onClick={() => { setApiKeyDialog(null); setApiKeyInput(""); }}
                              >
                                Cancel
                              </Button>
                              <Button
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
                    <div className="flex items-center gap-2">
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
                          title="OBO delegation requires authentication — link your account to use this agent."
                        >
                          <AlertTriangle className="h-3 w-3" />
                          OBO requires authentication
                        </span>
                      )}
                      {resolvedAuthorizerId && linkStatus === "linked" && (
                        <div className="flex items-center gap-1.5">
                          <span className="inline-block h-1.5 w-1.5 rounded-full bg-green-500" title="Account linked" />
                          <span className="text-[10px] text-muted-foreground">Linked</span>
                          <button
                            onClick={() => void handleUnlinkAccount()}
                            className="text-muted-foreground/50 hover:text-destructive transition-colors"
                            title="Unlink account"
                          >
                            <Unplug className="h-3 w-3" />
                          </button>
                        </div>
                      )}
                      {resolvedAuthorizerId && linkStatus === "unlinked" && (
                        <button
                          onClick={() => void handleLinkAccount()}
                          className="flex items-center gap-1 text-xs text-muted-foreground rounded-md border px-2 py-1 hover:text-foreground hover:border-foreground/30 cursor-pointer"
                          title="Link your account to this agent's authorizer"
                        >
                          <Link2 className="h-3 w-3" />
                          <span>Link Account</span>
                        </button>
                      )}
                      {resolvedAuthorizerId && linkStatus === "linking" && (
                        <span className="text-[10px] text-muted-foreground">Linking...</span>
                      )}
                      {availableModels.length > 0 && (
                        <div className="relative" ref={modelPickerRef}>
                          <button
                            onClick={() => { if (availableModels.length > 1) setShowModelPicker((v) => !v); }}
                            className={`flex items-center gap-1 text-xs text-muted-foreground rounded-md border px-2 py-1 ${
                              availableModels.length > 1 ? "hover:text-foreground hover:border-foreground/30 cursor-pointer" : "cursor-default"
                            }`}
                          >
                            <span>
                              {selectedModelId
                                ? (availableModels.find((m) => m.model_id === selectedModelId)?.display_name ?? selectedModelId)
                                : (availableModels.find((m) => m.model_id === selectedAgent?.model_id)?.display_name ?? selectedAgent?.model_id ?? "Model")}
                            </span>
                            {availableModels.length > 1 && <ChevronDown className="h-3 w-3" />}
                          </button>
                          {showModelPicker && (
                            <div className="absolute bottom-7 right-0 z-50 w-56 rounded-lg border bg-background shadow-md py-1 max-h-64 overflow-y-auto">
                              {groupModels(availableModels).map(([group, models]) => (
                                <div key={group}>
                                  <div className="px-3 py-1 text-[10px] font-medium text-muted-foreground uppercase tracking-wider">
                                    {group}
                                  </div>
                                  {models.map((m) => {
                                    const isDefault = m.model_id === selectedAgent?.model_id;
                                    const isSelected = selectedModelId ? m.model_id === selectedModelId : isDefault;
                                    return (
                                      <button
                                        key={m.model_id}
                                        onClick={() => {
                                          setSelectedModelId(isDefault ? null : m.model_id);
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
                        size="icon"
                        variant="ghost"
                        className="h-7 w-7"
                        onClick={() => void handleSend()}
                        disabled={!input.trim()}
                        title={isStreaming ? "Enqueue message" : "Send"}
                      >
                        <Send className="h-4 w-4" />
                      </Button>
                      {isStreaming && (
                        <Button variant="ghost" size="icon" className="h-7 w-7" onClick={cancel} title="Cancel stream">
                          <X className="h-4 w-4" />
                        </Button>
                      )}
                    </div>
                  </div>
                </div>
                <p className="text-center text-xs text-muted-foreground mt-2 max-w-3xl mx-auto">
                  Be mindful of personal information you enter into conversations.
                </p>
              </div>
            </>
          )}
        </div>

        {/* Memory panel (right side drawer) */}
        {showMemory && (
          <MemoryPanel
            memories={memories}
            sessions={sessions}
            currentSessionId={currentSessionId}
            records={memoryRecords}
            recordsLoading={memoryRecordsLoading}
            recordsError={memoryRecordsError}
            onRefresh={() => setMemoryRefreshCounter((c) => c + 1)}
            onClose={() => setShowMemory(false)}
          />
        )}
      </div>
    </div>
  );
}

function ThinkingBubble() {
  const [dots, setDots] = useState(".");

  useEffect(() => {
    const id = setInterval(() => {
      setDots((prev) => (prev.length >= 3 ? "." : prev + "."));
    }, 400);
    return () => clearInterval(id);
  }, []);

  return (
    <div className="flex justify-start">
      <div className="bg-muted rounded-2xl px-4 py-3 flex items-center gap-2 text-sm text-muted-foreground">
        <Loader2 className="h-3.5 w-3.5 animate-spin shrink-0" />
        <span>
          thinking
          <span className="inline-block w-5 text-left">{dots}</span>
        </span>
      </div>
    </div>
  );
}

function formatToolName(raw: string): string {
  const parts = raw.split("___");
  return parts.length > 1 ? parts.slice(1).join(" / ") : raw;
}

function ChatElapsedTimer({ since }: { since: number }) {
  const [elapsed, setElapsed] = useState(0);
  useEffect(() => {
    setElapsed(Math.floor((Date.now() - since) / 1000));
    const id = setInterval(() => setElapsed(Math.floor((Date.now() - since) / 1000)), 1000);
    return () => clearInterval(id);
  }, [since]);
  return <span className="tabular-nums">({elapsed}s)</span>;
}

function ChatToolUseBlock({ tools, isActive }: { tools: { name: string; index: number; total: number; timestamp: number }[]; isActive: boolean }) {
  const tool = tools[0]!;
  return (
    <div className="py-1 my-0.5 text-xs text-muted-foreground border-l-2 border-muted-foreground/30 pl-2">
      <div className="flex items-center gap-1.5">
        <Wrench className="h-3 w-3 shrink-0" />
        <span className="font-medium text-foreground/70">{formatToolName(tool.name)}</span>
        <span className="text-muted-foreground/60">({tool.index}/{tool.total})</span>
        {isActive && (
          <>
            <ChatElapsedTimer since={tool.timestamp} />
            <span className="flex gap-0.5 ml-0.5">
              <span className="h-1 w-1 rounded-full bg-muted-foreground/50 animate-bounce [animation-delay:0ms]" />
              <span className="h-1 w-1 rounded-full bg-muted-foreground/50 animate-bounce [animation-delay:150ms]" />
              <span className="h-1 w-1 rounded-full bg-muted-foreground/50 animate-bounce [animation-delay:300ms]" />
            </span>
          </>
        )}
      </div>
    </div>
  );
}

function StreamingBubble({
  segments,
  isStreaming,
  onElicitationRespond,
}: {
  segments: StreamSegment[];
  isStreaming: boolean;
  onElicitationRespond?: (id: string, action: "accept" | "decline", content?: Record<string, unknown>) => void;
}) {
  return (
    <div className="flex justify-start">
      <div className="max-w-[84%] rounded-2xl px-4 py-3 text-sm break-words bg-muted">
        {(() => {
          const blocks: React.ReactNode[] = [];
          segments.forEach((seg, i) => {
            if (seg.type === "tool_use") {
              const active = isStreaming && i === segments.length - 1;
              blocks.push(
                <ChatToolUseBlock key={`tools-${i}`} tools={[{ name: seg.name, index: seg.index, total: seg.total, timestamp: seg.timestamp }]} isActive={active} />
              );
            } else if (seg.type === "approval_request") {
              blocks.push(<ApprovalRequestBubble key={`approval-${i}`} data={seg.data} />);
            } else if (seg.type === "approval_resolved") {
              // Skip render — approval status is already shown inline in the ApprovalRequestBubble
            } else if (seg.type === "elicitation_request") {
              blocks.push(<ElicitationRequestBubble key={`elicit-${i}`} data={seg.data} onRespond={onElicitationRespond} />);
            } else {
              blocks.push(
                <ReactMarkdown
                  key={i}
                  remarkPlugins={[remarkGfm]}
                  components={{
                    p: ({ children }) => <p className="mb-2 last:mb-0">{children}</p>,
                    h1: ({ children }) => <h1 className="text-base font-bold mb-2 mt-3 first:mt-0">{children}</h1>,
                    h2: ({ children }) => <h2 className="text-sm font-bold mb-2 mt-3 first:mt-0">{children}</h2>,
                    h3: ({ children }) => <h3 className="text-sm font-semibold mb-1 mt-2 first:mt-0">{children}</h3>,
                    ul: ({ children }) => <ul className="list-disc pl-4 mb-2 space-y-0.5">{children}</ul>,
                    ol: ({ children }) => <ol className="list-decimal pl-4 mb-2 space-y-0.5">{children}</ol>,
                    li: ({ children }) => <li className="leading-snug">{children}</li>,
                    pre: ({ children }) => {
                      const codeClass = (children as { props?: { className?: string } } | null)?.props?.className ?? "";
                      if (codeClass.includes("language-json")) {
                        return <CollapsibleJsonBlock>{children}</CollapsibleJsonBlock>;
                      }
                      return <pre className="mb-2 overflow-x-auto rounded bg-black/10 dark:bg-white/10 p-3 text-xs font-mono">{children}</pre>;
                    },
                    code: ({ className, children }) =>
                      className?.startsWith("language-") ? (
                        <code className={className}>{children}</code>
                      ) : (
                        <code className="rounded bg-black/10 dark:bg-white/10 px-1 py-0.5 text-xs font-mono">{children}</code>
                      ),
                    blockquote: ({ children }) => (
                      <blockquote className="border-l-2 border-muted-foreground/30 pl-3 italic text-muted-foreground mb-2">{children}</blockquote>
                    ),
                    table: ({ children }) => (
                      <div className="overflow-x-auto mb-2"><table className="border-collapse text-xs w-full">{children}</table></div>
                    ),
                    thead: ({ children }) => <thead>{children}</thead>,
                    tbody: ({ children }) => <tbody>{children}</tbody>,
                    tr: ({ children }) => <tr>{children}</tr>,
                    th: ({ children }) => <th className="border border-border px-2 py-1 text-left font-semibold bg-muted/50">{children}</th>,
                    td: ({ children }) => <td className="border border-border px-2 py-1">{children}</td>,
                    strong: ({ children }) => <strong className="font-semibold">{children}</strong>,
                    a: ({ href, children }) => (
                      <a href={href} className="underline underline-offset-2 hover:opacity-80" target="_blank" rel="noopener noreferrer">{children}</a>
                    ),
                  }}
                >
                  {seg.content}
                </ReactMarkdown>,
              );
            }
          });
          return blocks;
        })()}
        {isStreaming && (
          <span className="inline-block w-1.5 h-4 bg-current animate-pulse ml-0.5 align-text-bottom opacity-70" />
        )}
      </div>
    </div>
  );
}

function MessageBubble({
  role,
  text,
  isStreaming,
  toolNames,
  hitlSegments,
}: {
  role: "user" | "assistant";
  text: string;
  isStreaming?: boolean;
  toolNames?: string[];
  hitlSegments?: StreamSegment[];
}) {
  const isUser = role === "user";
  return (
    <div className={`flex ${isUser ? "justify-end" : "justify-start"}`}>
      <div
        className={`${isUser ? "max-w-[70%]" : "max-w-[84%]"} rounded-2xl px-4 py-3 text-sm break-words ${
          isUser ? "bg-primary text-primary-foreground" : "bg-muted"
        }`}
      >
          {hitlSegments && hitlSegments.length > 0 ? (
            <div className="mb-2 space-y-1">
              {hitlSegments.map((seg, i) => {
                if (seg.type === "tool_use") return (
                  <div key={`h-tool-${i}`} className="py-1 text-xs text-muted-foreground border-l-2 border-muted-foreground/30 pl-2">
                    <div className="flex items-center gap-1.5">
                      <Wrench className="h-3 w-3 shrink-0" />
                      <span className="font-medium text-foreground/70">{formatToolName(seg.name)}</span>
                      <span className="text-muted-foreground/60">({seg.index}/{seg.total})</span>
                    </div>
                  </div>
                );
                if (seg.type === "approval_request") return <ApprovalRequestBubble key={`h-approval-${i}`} data={seg.data} resolved />;
                if (seg.type === "elicitation_request") return <ElicitationRequestBubble key={`h-elicit-${i}`} data={seg.data} resolved resolvedSummary={seg.resolvedSummary} />;
                return null;
              })}
            </div>
          ) : toolNames && toolNames.length > 0 ? (
            <div className="py-1 mb-2 text-xs text-muted-foreground border-l-2 border-muted-foreground/30 pl-2 space-y-0.5">
              <div className="flex items-center gap-1.5">
                <Wrench className="h-3 w-3 shrink-0" />
                <span>Tool calls ({toolNames.length}/{toolNames.length}):</span>
              </div>
              {toolNames.map((name, i) => (
                <div key={i} className="pl-[18px] font-medium text-foreground/70">{formatToolName(name)}</div>
              ))}
            </div>
          ) : null}
          <ReactMarkdown
            remarkPlugins={[remarkGfm]}
            components={{
              p: ({ children }) => <p className="mb-2 last:mb-0">{children}</p>,
              h1: ({ children }) => (
                <h1 className="text-base font-bold mb-2 mt-3 first:mt-0">{children}</h1>
              ),
              h2: ({ children }) => (
                <h2 className="text-sm font-bold mb-2 mt-3 first:mt-0">{children}</h2>
              ),
              h3: ({ children }) => (
                <h3 className="text-sm font-semibold mb-1 mt-2 first:mt-0">{children}</h3>
              ),
              ul: ({ children }) => (
                <ul className="list-disc pl-4 mb-2 space-y-0.5">{children}</ul>
              ),
              ol: ({ children }) => (
                <ol className="list-decimal pl-4 mb-2 space-y-0.5">{children}</ol>
              ),
              li: ({ children }) => <li className="leading-snug">{children}</li>,
              pre: ({ children }) => {
                const codeClass = (children as { props?: { className?: string } } | null)?.props?.className ?? '';
                if (codeClass.includes('language-json')) {
                  return <CollapsibleJsonBlock>{children}</CollapsibleJsonBlock>;
                }
                return (
                  <pre className="mb-2 overflow-x-auto rounded bg-black/10 dark:bg-white/10 p-3 text-xs font-mono">{children}</pre>
                );
              },
              code: ({ className, children }) =>
                className?.startsWith("language-") ? (
                  <code className={className}>{children}</code>
                ) : (
                  <code className="rounded bg-black/10 dark:bg-white/10 px-1 py-0.5 text-xs font-mono">
                    {children}
                  </code>
                ),
              blockquote: ({ children }) => (
                <blockquote className="border-l-2 border-muted-foreground/30 pl-3 italic text-muted-foreground mb-2">
                  {children}
                </blockquote>
              ),
              table: ({ children }) => (
                <div className="overflow-x-auto mb-2">
                  <table className="border-collapse text-xs w-full">{children}</table>
                </div>
              ),
              thead: ({ children }) => <thead>{children}</thead>,
              tbody: ({ children }) => <tbody>{children}</tbody>,
              tr: ({ children }) => <tr>{children}</tr>,
              th: ({ children }) => (
                <th className="border border-border px-2 py-1 text-left font-semibold bg-muted/50">
                  {children}
                </th>
              ),
              td: ({ children }) => (
                <td className="border border-border px-2 py-1">{children}</td>
              ),
              strong: ({ children }) => (
                <strong className="font-semibold">{children}</strong>
              ),
              a: ({ href, children }) => (
                <a
                  href={href}
                  className="underline underline-offset-2 hover:opacity-80"
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  {children}
                </a>
              ),
            }}
          >
            {text}
          </ReactMarkdown>
          {isStreaming && (
            <span className="inline-block w-1.5 h-4 bg-current animate-pulse ml-0.5 align-text-bottom opacity-70" />
          )}
      </div>
    </div>
  );
}

// Map a memoryStrategyId prefix to a human-readable group label
function strategyLabel(strategyId: string): string {
  if (strategyId.includes("userPreference") || strategyId.includes("user_preference")) return "Preferences";
  if (strategyId.includes("summary") || strategyId.includes("Summary")) return "Summaries";
  if (strategyId.includes("semantic") || strategyId.includes("Semantic")) return "Facts & Context";
  if (strategyId.includes("episodic") || strategyId.includes("Episodic")) return "Episodes";
  return "Memory";
}

function formatRelativeDate(iso: string): string {
  try {
    const d = new Date(iso);
    const now = Date.now();
    const diffMs = now - d.getTime();
    const diffDays = Math.floor(diffMs / 86400000);
    if (diffDays === 0) return "today";
    if (diffDays === 1) return "yesterday";
    if (diffDays < 7) return `${diffDays}d ago`;
    if (diffDays < 30) return `${Math.floor(diffDays / 7)}w ago`;
    return `${Math.floor(diffDays / 30)}mo ago`;
  } catch {
    return "";
  }
}

function MemoryPanel({
  memories,
  sessions,
  currentSessionId,
  records,
  recordsLoading,
  recordsError,
  onRefresh,
  onClose,
}: {
  memories: MemoryResponse[];
  sessions: SessionResponse[];
  currentSessionId: string | null;
  records: MemoryRecordItem[];
  recordsLoading: boolean;
  recordsError: string | null;
  onRefresh: () => void;
  onClose: () => void;
}) {
  // Group records by strategy type label
  const grouped = new Map<string, MemoryRecordItem[]>();
  for (const rec of records) {
    const label = strategyLabel(rec.memoryStrategyId);
    if (!grouped.has(label)) grouped.set(label, []);
    grouped.get(label)!.push(rec);
  }

  // Current session's invocation count
  const currentSession = sessions.find((s) => s.session_id === currentSessionId);
  const sessionMessageCount = currentSession?.invocations.length ?? 0;

  const noMemoryConfigured = memories.length === 0;

  return (
    <div className="w-80 border-l bg-card flex flex-col h-full shrink-0">
      <div className="p-4 border-b flex items-center justify-between shrink-0">
        <div className="flex items-center gap-2">
          <Brain className="h-4 w-4" />
          <span className="font-medium text-sm">My Memory</span>
        </div>
        <div className="flex items-center gap-1">
          <button
            onClick={onRefresh}
            disabled={recordsLoading}
            className="text-muted-foreground hover:text-foreground transition-colors disabled:opacity-50"
            title="Refresh memories"
          >
            <RefreshCw className={`h-3.5 w-3.5 ${recordsLoading ? "animate-spin" : ""}`} />
          </button>
          <button
            onClick={onClose}
            className="text-muted-foreground hover:text-foreground transition-colors"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto p-4 space-y-5">
        {noMemoryConfigured ? (
          <p className="text-sm text-muted-foreground text-center py-8">
            No memory configured for this agent.
          </p>
        ) : recordsLoading ? (
          <div className="flex items-center justify-center py-8 gap-2 text-muted-foreground text-sm">
            <Loader2 className="h-4 w-4 animate-spin" />
            Loading memories…
          </div>
        ) : recordsError ? (
          <div className="text-center py-8 space-y-2">
            <p className="text-sm text-destructive font-medium">
              Failed to load memories.
            </p>
            <p className="text-xs text-muted-foreground">
              Check that the memory resource is active and try again.
            </p>
          </div>
        ) : records.length === 0 ? (
          <div className="space-y-3">
            {currentSessionId && (
              <div className="rounded border p-3 text-xs text-muted-foreground">
                Current conversation:{" "}
                <span className="font-medium text-foreground">
                  {sessionMessageCount} {sessionMessageCount === 1 ? "exchange" : "exchanges"}
                </span>
              </div>
            )}
            <p className="text-sm text-muted-foreground text-center py-4">
              No memories stored yet. Keep chatting — the agent will remember things as you go.
            </p>
          </div>
        ) : (
          <>
            {currentSessionId && (
              <div className="rounded border p-3 text-xs text-muted-foreground">
                Current conversation:{" "}
                <span className="font-medium text-foreground">
                  {sessionMessageCount} {sessionMessageCount === 1 ? "exchange" : "exchanges"}
                </span>
              </div>
            )}

            {Array.from(grouped.entries()).map(([label, items]) => (
              <div key={label}>
                <h3 className="text-xs font-medium text-muted-foreground mb-2 uppercase tracking-wide">
                  {label}
                </h3>
                <div className="space-y-2">
                  {items.map((rec) => (
                    <div key={rec.memoryRecordId} className="rounded border p-3 text-sm">
                      <p className="leading-snug">{rec.text}</p>
                      <div className="text-xs text-muted-foreground mt-1.5 space-y-0.5">
                        <p>Created {formatRelativeDate(rec.createdAt)}</p>
                        <p>Updated {formatRelativeDate(rec.updatedAt)}</p>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </>
        )}

        <p className="text-xs text-muted-foreground pt-4 border-t">
          Memory is managed automatically by the agent during your conversations. You can only see your own memories.
        </p>
      </div>
    </div>
  );
}
