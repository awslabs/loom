import { useState, useEffect } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Key, Check, X, Shield } from "lucide-react";
import type { SSETokenInfo } from "@/api/types";
import { InvokePanel } from "@/components/InvokePanel";
import { LatencySummary } from "@/components/LatencySummary";
import { DeploymentPanel, ModelsCard } from "@/components/DeploymentPanel";
import { RegistryStatusBadge } from "@/components/RegistryStatusBadge";
import { RegistryActions } from "@/components/RegistryActions";
import { ExternalIntegrationSection } from "@/components/ExternalIntegrationSection";
import { AgentEvaluationsPanel } from "@/components/AgentEvaluationsPanel";
import { StatusPill } from "@/components/StatusPill";
import { statusVariant } from "@/lib/status";
import { useTimezone } from "@/contexts/TimezoneContext";
import { formatTimestamp, capitalize } from "@/lib/format";
import { useInvoke } from "@/hooks/useInvoke";
import { useAuth } from "@/contexts/AuthContext";
import { trackAction } from "@/api/audit";
import type { AgentResponse, SessionResponse } from "@/api/types";

interface AgentDetailPageProps {
  agent: AgentResponse;
  sessions: SessionResponse[];
  sessionsLoading: boolean;
  onSelectSession: (sessionId: string) => void;
  onSessionsRefresh: () => void;
  onRedeploy?: (id: number) => Promise<void>;
  onPatchAgent?: (id: number, updates: { description?: string | null; model_id?: string; allowed_model_ids?: string[] }) => Promise<AgentResponse>;
  onRefreshAgents?: () => void;
  canInvoke?: boolean;
  registryReadOnly?: boolean;
  registryEnabled?: boolean;
  userGroups?: string[];
  initialTab?: "details" | "invoke";
}

export function AgentDetailPage({
  agent,
  sessions,
  onSelectSession,
  onSessionsRefresh,
  onRedeploy,
  onPatchAgent,
  onRefreshAgents,
  canInvoke = true,
  registryReadOnly,
  registryEnabled = false,
  userGroups = [],
  initialTab = "details",
}: AgentDetailPageProps) {
  const [editingDescription, setEditingDescription] = useState(false);
  const [descriptionDraft, setDescriptionDraft] = useState("");
  const [savingDescription, setSavingDescription] = useState(false);

  const handleEditDescription = () => {
    setDescriptionDraft(agent.description ?? "");
    setEditingDescription(true);
  };

  const handleSaveDescription = async () => {
    if (!onPatchAgent) return;
    setSavingDescription(true);
    try {
      await onPatchAgent(agent.id, { description: descriptionDraft.trim() || null });
      setEditingDescription(false);
    } finally {
      setSavingDescription(false);
    }
  };

  const handleCancelDescription = () => {
    setEditingDescription(false);
  };

  // Check if user can invoke this specific agent based on group tags
  const agentGroup = agent.tags?.["loom:group"] || "";
  const isSuperAdmin = userGroups.includes("g-admins-super");
  const isAdmin = userGroups.includes("t-admin");

  // Build allowed groups by stripping prefixes from group names
  let allowedGroups: string[] = [];
  if (isAdmin && !isSuperAdmin) {
    // Non-super admins: strip "g-admins-" prefix
    allowedGroups = userGroups
      .filter(g => g.startsWith("g-admins-"))
      .map(g => g.replace("g-admins-", ""));
  } else if (!isAdmin) {
    // Users: strip "g-users-" prefix
    allowedGroups = userGroups
      .filter(g => g.startsWith("g-users-"))
      .map(g => g.replace("g-users-", ""));
  }

  // Check if agent group matches any of the user's allowed groups
  const canInvokeThisAgent = isSuperAdmin || !agentGroup || allowedGroups.includes(agentGroup);
  const effectiveCanInvoke = canInvoke && canInvokeThisAgent;
  const { user, browserSessionId, authConfig } = useAuth();
  const { streamedText, segments, sessionStart, sessionEnd, isStreaming, error, rawError, tokenInfos, invoke, cancel } =
    useInvoke(agent.id, agent.authorizer_config?.name ?? undefined);

  // Resolve the backend-authoritative username for session ownership filtering
  const [backendUserId, setBackendUserId] = useState<string | null>(null);
  useEffect(() => {
    import("@/api/auth").then(({ fetchAuthMe }) => {
      fetchAuthMe().then((me) => setBackendUserId(me.username)).catch(() => {});
    });
  }, []);
  useEffect(() => {
    if (sessionStart?.user_id) setBackendUserId(sessionStart.user_id);
  }, [sessionStart]);
  const currentUserId = backendUserId ?? user?.username ?? user?.sub;

  const handleInvoke = async (prompt: string, qualifier: string, sessionId?: string, credentialId?: number, bearerToken?: string, modelId?: string, connectorIds?: number[], useLinkedToken?: boolean) => {
    if (user && browserSessionId) trackAction(user.username ?? user.sub, browserSessionId, 'agent', 'invoke', agent.name ?? agent.runtime_id ?? String(agent.id));
    await invoke(prompt, qualifier, sessionId, credentialId, bearerToken, modelId, connectorIds, useLinkedToken);
    onSessionsRefresh();
  };

  const isDeployed = agent.source === "deploy" || agent.source === "harness";
  const { timezone } = useTimezone();
  const typeLabel = agent.source === "harness" ? "MANAGED" : agent.source === "deploy" ? "CUSTOM" : null;
  const canManageRegistry = !registryReadOnly && registryEnabled;

  const approvalContext = (() => {
    switch (agent.registry_status) {
      case "DRAFT":
        return `Draft agents are invocable only by their owner. Submit for approval to expose ${agent.name ?? agent.runtime_id} to the ${agentGroup || "assigned"} group.`;
      case "PENDING_APPROVAL":
        return "Pending review by an administrator.";
      case "APPROVED":
        return `Approved — visible to the ${agentGroup || "assigned"} group.`;
      case "REJECTED":
        return "Rejected. Address the feedback and resubmit for approval.";
      case "DEPRECATED":
        return "Deprecated.";
      default:
        return "Not yet registered in the catalog registry.";
    }
  })();

  return (
    <Tabs key={initialTab} defaultValue={initialTab} className="gap-0">
      <div className="flex flex-col gap-4 rounded-t-xl border bg-card px-6 pt-5">
        <div className="flex items-start gap-4">
          <div className="flex min-w-0 flex-1 flex-col gap-2">
            <div className="flex flex-wrap items-center gap-2.5">
              <h1 className="truncate font-mono text-2xl font-semibold tracking-tight">
                {agent.name ?? agent.runtime_id}
              </h1>
              <StatusPill label={agent.status ?? "UNKNOWN"} variant={statusVariant(agent.status)} />
              {typeLabel && (
                <span className="rounded-md border bg-muted px-1.5 py-0.5 font-mono text-[10px] tracking-wide text-muted-foreground">
                  {typeLabel}
                </span>
              )}
              <RegistryStatusBadge status={agent.registry_status} showUnregistered={registryEnabled} registryEnabled={registryEnabled} />
            </div>
            {editingDescription ? (
              <div className="flex flex-col gap-2 max-w-xl">
                <Textarea
                  value={descriptionDraft}
                  onChange={(e) => setDescriptionDraft(e.target.value)}
                  placeholder="Describe what this agent does..."
                  className="text-xs resize-none"
                  rows={3}
                />
                <div className="flex gap-2">
                  <Button size="sm" className="h-6 text-xs" onClick={() => void handleSaveDescription()} disabled={savingDescription}>
                    <Check className="h-3 w-3 mr-1" />
                    Save
                  </Button>
                  <Button size="sm" variant="ghost" className="h-6 text-xs" onClick={handleCancelDescription} disabled={savingDescription}>
                    <X className="h-3 w-3 mr-1" />
                    Cancel
                  </Button>
                </div>
              </div>
            ) : (
              <div className="flex items-center gap-1.5 text-[13.5px] text-muted-foreground">
                <span className="max-w-xl truncate">{agent.description ?? <span className="italic">No description set.</span>}</span>
                {onPatchAgent && (
                  <button type="button" onClick={handleEditDescription} className="shrink-0 text-[11.5px] text-primary hover:underline">
                    Edit
                  </button>
                )}
              </div>
            )}
          </div>
        </div>
        <TabsList variant="line" className="h-auto justify-start gap-5 rounded-none bg-transparent p-0">
          <TabsTrigger value="details" className="rounded-none px-0.5 pb-2.5 text-[13.5px] font-medium data-[state=active]:shadow-none">Details</TabsTrigger>
          <TabsTrigger value="invoke" className="rounded-none px-0.5 pb-2.5 text-[13.5px] font-medium data-[state=active]:shadow-none">Invoke</TabsTrigger>
          <TabsTrigger value="evaluations" className="rounded-none px-0.5 pb-2.5 text-[13.5px] font-medium data-[state=active]:shadow-none">Evaluations</TabsTrigger>
        </TabsList>
      </div>

      {/* Details tab: two-column layout — main config cards + a facts/approval rail */}
      <TabsContent value="details" className="grid grid-cols-1 gap-4 pt-4 lg:grid-cols-[1fr_320px]">
        <div className="flex min-w-0 flex-col gap-4">
          {isDeployed && <DeploymentPanel agent={agent} onRedeploy={onRedeploy ?? (async () => {})} onPatchAgent={onPatchAgent} />}
          <ModelsCard agent={agent} onPatchAgent={onPatchAgent} />
          {agent.status === "READY" && (agent.deployment_status === "deployed" || isDeployed) && (
            <ExternalIntegrationSection agentId={agent.id} />
          )}
        </div>

        <div className="flex flex-col gap-3.5">
          <Card className="gap-3.5 py-4">
            <CardContent className="flex flex-col gap-3.5">
              <div className="flex flex-col gap-1">
                <span className="font-mono text-[9.5px] tracking-wide text-muted-foreground uppercase">Est. cost / run</span>
                <span className="font-mono text-[22px] font-semibold tracking-tight tabular-nums">
                  {agent.cost_summary && agent.cost_summary.total_cost > 0
                    ? (agent.cost_summary.total_cost < 0.01 ? `$${agent.cost_summary.total_cost.toFixed(6)}` : `$${agent.cost_summary.total_cost.toFixed(4)}`)
                    : "—"}
                </span>
              </div>
              <div className="h-px bg-border" />
              <div className="flex flex-col gap-2.5">
                <div className="flex items-center justify-between gap-2.5">
                  <span className="font-mono text-[9.5px] tracking-wide text-muted-foreground uppercase">Region</span>
                  <span className="font-mono text-xs">{agent.region}</span>
                </div>
                <div className="flex items-center justify-between gap-2.5">
                  <span className="font-mono text-[9.5px] tracking-wide text-muted-foreground uppercase">Account</span>
                  <span className="font-mono text-xs">{agent.account_id}</span>
                </div>
                {agent.memory_names && agent.memory_names.length > 0 && (
                  <div className="flex items-center justify-between gap-2.5">
                    <span className="font-mono text-[9.5px] tracking-wide text-muted-foreground uppercase">Memory</span>
                    <span className="truncate font-mono text-xs">{agent.memory_names.join(", ")}</span>
                  </div>
                )}
                {agent.mcp_names && agent.mcp_names.length > 0 && (
                  <div className="flex items-center justify-between gap-2.5">
                    <span className="font-mono text-[9.5px] tracking-wide text-muted-foreground uppercase">MCP</span>
                    <span className="truncate font-mono text-xs">{agent.mcp_names.join(", ")}</span>
                  </div>
                )}
                {agent.agent_framework && (
                  <div className="flex items-center justify-between gap-2.5">
                    <span className="font-mono text-[9.5px] tracking-wide text-muted-foreground uppercase">Framework</span>
                    <span className="font-mono text-xs">{capitalize(agent.agent_framework)}</span>
                  </div>
                )}
                {agent.registered_at && (
                  <div className="flex items-center justify-between gap-2.5">
                    <span className="font-mono text-[9.5px] tracking-wide text-muted-foreground uppercase">Registered</span>
                    <span className="font-mono text-xs">{formatTimestamp(agent.registered_at, timezone)}</span>
                  </div>
                )}
              </div>
            </CardContent>
          </Card>

          {agent.tags && Object.keys(agent.tags).length > 0 && (
            <Card className="gap-2.5 py-4">
              <CardHeader className="px-[18px]">
                <div className="flex items-center gap-2">
                  <CardTitle className="text-[13px] font-semibold">Labels</CardTitle>
                  <Badge variant="outline" className="text-[11px] px-1.5 py-0 font-mono">{Object.keys(agent.tags).length}</Badge>
                </div>
              </CardHeader>
              <CardContent className="flex flex-col gap-1.5 px-[18px]">
                {Object.entries(agent.tags).map(([key, value]) => (
                  <div key={key} className="flex items-center justify-between gap-2.5 font-mono text-[11.5px]">
                    <span className="text-muted-foreground">{key.replace(/^loom:/, "")}</span>
                    <span className="truncate">{value}</span>
                  </div>
                ))}
              </CardContent>
            </Card>
          )}

          {registryEnabled && (agent.registry_status || canManageRegistry) && (
            <Card className="gap-2.5 py-4">
              <CardHeader className="px-[18px]">
                <CardTitle className="text-[13px] font-semibold">Registry</CardTitle>
              </CardHeader>
              <CardContent className="flex flex-col gap-2.5 px-[18px]">
                <p className="text-[12.5px] leading-[1.55] text-muted-foreground">{approvalContext}</p>
                {canManageRegistry && (
                  <RegistryActions
                    resourceType="agent"
                    resourceId={agent.id}
                    registryRecordId={agent.registry_record_id}
                    registryStatus={agent.registry_status}
                    onAction={() => onRefreshAgents?.()}
                  />
                )}
              </CardContent>
            </Card>
          )}
        </div>
      </TabsContent>

      {/* Invoke tab: console + run-config/sessions rail */}
      <TabsContent value="invoke" className="space-y-4">
        {effectiveCanInvoke ? (
          <InvokePanel
            agentId={agent.id}
            agentName={agent.name ?? agent.runtime_id ?? String(agent.id)}
            qualifiers={agent.available_qualifiers}
            sessions={sessions.filter((s) => !s.user_id || s.user_id === currentUserId)}
            isStreaming={isStreaming}
            modelId={agent.model_id}
            allowedModelIds={agent.allowed_model_ids}
            memoryNames={agent.memory_names}
            mcpNames={agent.mcp_names}
            authorizerName={agent.authorizer_config?.name}
            authorizerPoolId={agent.authorizer_config?.pool_id}
            authorizerDiscoveryUrl={agent.authorizer_config?.discovery_url}
            isExternalIdp={Boolean(authConfig?.provider_type && authConfig.provider_type !== "cognito")}
            loginIssuerUrl={authConfig?.issuer_url}
            currentUserId={user?.username ?? user?.sub}
            streamedText={streamedText}
            segments={segments}
            sessionStart={sessionStart}
            sessionEnd={sessionEnd}
            error={error}
            rawError={rawError}
            onInvoke={handleInvoke}
            onCancel={cancel}
            onOpenSessionDetail={onSelectSession}
          />
        ) : (
          <Card className="border-muted-foreground/20">
            <CardContent className="pt-6 pb-6 text-center text-sm text-muted-foreground">
              <Key className="h-8 w-8 mx-auto mb-2 opacity-50" />
              {!canInvoke ? (
                <>
                  <p>You don't have permission to invoke agents.</p>
                  <p className="text-xs mt-1">Contact your administrator for the <code className="px-1 py-0.5 rounded bg-muted">invoke</code> scope.</p>
                </>
              ) : (
                <>
                  <p>This agent is in the <code className="px-1 py-0.5 rounded bg-muted">{agentGroup}</code> group.</p>
                  <p className="text-xs mt-1">You can only invoke agents in your assigned groups.</p>
                </>
              )}
            </CardContent>
          </Card>
        )}

        {sessionEnd && <LatencySummary sessionEnd={sessionEnd} />}

        {(sessionStart?.user_token || tokenInfos.length > 0) && (
          <TokenInfoCard userToken={sessionStart?.user_token} oboTokens={tokenInfos} groupMappings={authConfig?.group_mappings} authorizerName={agent.authorizer_config?.name} />
        )}
      </TabsContent>
      <TabsContent value="evaluations">
        <AgentEvaluationsPanel agentId={agent.id} />
      </TabsContent>
    </Tabs>
  );
}

function TokenClaimsRow({ label, value, annotation, children }: { label: string; value?: unknown; annotation?: string; children?: React.ReactNode }) {
  if (value === undefined && !children) return null;
  if (value === null && !children) return null;
  return (
    <div className="flex items-baseline gap-2 py-0.5">
      <span className="text-xs text-muted-foreground w-12 shrink-0">{label}</span>
      {children ? (
        <div className="font-mono text-xs break-all">{children}</div>
      ) : (
        <span className="font-mono text-xs break-all">
          {Array.isArray(value) ? value.join(" ") : typeof value === "object" ? JSON.stringify(value) : String(value)}
          {annotation && <span className="text-muted-foreground ml-1 font-sans">({annotation})</span>}
        </span>
      )}
    </div>
  );
}

function resolveRoles(roles: string[] | undefined, groupMappings?: Record<string, string[]>): React.ReactNode | undefined {
  if (!roles || roles.length === 0) return undefined;
  if (!groupMappings || Object.keys(groupMappings).length === 0) {
    return roles.map((r, i) => (
      <div key={i} className="py-0.5">{r} <span className="text-muted-foreground">→ unmapped (configure IdP group mappings)</span></div>
    ));
  }
  return roles.map((r, i) => {
    const mapped = groupMappings[r];
    return (
      <div key={i} className="py-0.5">
        {r}
        {mapped
          ? <span className="text-green-600 dark:text-green-400 ml-1">→ {mapped.join(", ")}</span>
          : <span className="text-muted-foreground ml-1">→ unmapped (group or directory role)</span>}
      </div>
    );
  });
}

function subAnnotation(sub?: string, aud?: string | string[], iss?: string): string | undefined {
  if (!sub) return undefined;
  if (iss?.includes("okta.com") || iss?.includes("cognito-idp")) {
    return "user identifier";
  }
  const clientId = Array.isArray(aud) ? aud[0] : aud;
  const cleanClientId = clientId?.replace("api://", "") ?? "unknown";
  return `per-user id for client_id: ${cleanClientId}`;
}

function TokenInfoCard({ userToken, oboTokens, groupMappings, authorizerName }: { userToken?: SSETokenInfo; oboTokens: SSETokenInfo[]; groupMappings?: Record<string, string[]>; authorizerName?: string }) {
  return (
    <Card>
      <CardHeader className="pb-2">
        <div className="flex items-center gap-2">
          <Shield className="h-4 w-4 text-muted-foreground" />
          <CardTitle className="text-sm font-medium">Token Info</CardTitle>
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        {userToken && (
          <details open>
            <summary className="cursor-pointer text-xs font-medium flex items-center gap-1.5">
              <Badge variant="outline" className="text-[10px] px-1.5 py-0">user</Badge>
              <span className="text-muted-foreground">{userToken.source ?? "login"}{authorizerName ? ` (${authorizerName})` : ""}</span>
            </summary>
            <div className="mt-1.5 pl-2 border-l-2 border-muted-foreground/20">
              <TokenClaimsRow label="iss" value={userToken.claims.iss} annotation={userToken.claims.iss ? "issuer" : undefined} />
              <TokenClaimsRow label="sub" value={userToken.claims.sub} annotation={subAnnotation(userToken.claims.sub, userToken.claims.aud, userToken.claims.iss)} />
              <TokenClaimsRow label="aud" value={userToken.claims.aud} annotation={userToken.claims.aud ? "audience" : undefined} />
              <TokenClaimsRow label="cid" value={userToken.claims.cid} annotation={userToken.claims.cid ? "client application" : undefined} />
              <TokenClaimsRow label="scp" value={userToken.claims.scp} annotation={userToken.claims.scp ? "scopes" : undefined} />
              {userToken.claims.roles && userToken.claims.roles.length > 0 && (
                <TokenClaimsRow label="roles">{resolveRoles(userToken.claims.roles, groupMappings)}</TokenClaimsRow>
              )}
              <TokenClaimsRow label="act" value={userToken.claims.act} />
              <TokenClaimsRow label="exp" value={userToken.claims.exp ? new Date(userToken.claims.exp * 1000).toISOString() : undefined} annotation={userToken.claims.exp ? "token expiry" : undefined} />
            </div>
          </details>
        )}
        {oboTokens.map((t, i) => (
          <details key={i} open>
            <summary className="cursor-pointer text-xs font-medium flex items-center gap-1.5">
              <Badge variant="outline" className="text-[10px] px-1.5 py-0 border-amber-500/50 text-amber-700 dark:text-amber-400">obo</Badge>
              <span className="text-muted-foreground">{t.credential_provider ?? t.flow ?? "exchange"}</span>
            </summary>
            <div className="mt-1.5 pl-2 border-l-2 border-amber-500/30">
              <TokenClaimsRow label="iss" value={t.claims.iss} annotation={t.claims.iss ? "issuer" : undefined} />
              <TokenClaimsRow label="sub" value={t.claims.sub} annotation={subAnnotation(t.claims.sub, t.claims.aud, t.claims.iss)} />
              <TokenClaimsRow label="aud" value={t.claims.aud} annotation={t.claims.aud ? "audience" : undefined} />
              <TokenClaimsRow label="azp" value={t.claims.azp ?? t.claims.appid} annotation={t.claims.azp || t.claims.appid ? "authorized party: actor that performed the OBO exchange" : undefined} />
              <TokenClaimsRow label="cid" value={t.claims.cid} annotation={t.claims.cid ? "client that performed the token exchange" : undefined} />
              <TokenClaimsRow label="scp" value={t.claims.scp} annotation={t.claims.scp ? "scopes" : undefined} />
              <TokenClaimsRow label="roles" value={t.claims.roles} />
              <TokenClaimsRow label="act" value={t.claims.act} />
              <TokenClaimsRow label="exp" value={t.claims.exp ? new Date(t.claims.exp * 1000).toISOString() : undefined} annotation={t.claims.exp ? "token expiry" : undefined} />
            </div>
          </details>
        ))}
      </CardContent>
    </Card>
  );
}
