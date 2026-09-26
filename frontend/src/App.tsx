import { useState, useEffect, useCallback, useRef, Children } from "react";
import { useTranslation } from "react-i18next";
import { Toaster } from "@/components/ui/sonner";
import { toast } from "sonner";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Tooltip, TooltipTrigger, TooltipContent, TooltipProvider } from "@/components/ui/tooltip";
import {
  TimezoneProvider,
  useTimezone,
} from "@/contexts/TimezoneContext";
import { ThemeProvider, useTheme, isLightTheme } from "@/contexts/ThemeContext";
import { useAgents } from "@/hooks/useAgents";
import { useSessions } from "@/hooks/useSessions";
import { clearInvokeState } from "@/hooks/useInvoke";
import { getSession, getInvocation } from "@/api/invocations";
import { CatalogPage } from "@/pages/CatalogPage";
import { AgentListPage } from "@/pages/AgentListPage";
import { AgentDetailPage } from "@/pages/AgentDetailPage";
import { SessionDetailPage } from "@/pages/SessionDetailPage";
import { InvocationDetailPage } from "@/pages/InvocationDetailPage";
import { SecurityAdminPage } from "@/pages/SecurityAdminPage";
import { MemoryManagementPage } from "@/pages/MemoryManagementPage";
import { SettingsPage } from "@/pages/SettingsPage";
import { IntegrationsPage } from "@/pages/IntegrationsPage";
import { SkillsPage } from "@/pages/SkillsPage";
import type { SessionResponse, InvocationResponse } from "@/api/types";
import { getRegistryConfig } from "@/api/settings";
import { listRegistryRecords } from "@/api/registry";
import { listMemories } from "@/api/memories";
import { listMcpServers } from "@/api/mcp";
import { listA2aAgents } from "@/api/a2a";
import { AuthProvider, useAuth, GROUP_SCOPES, type Scope } from "@/contexts/AuthContext";
import { LoginPage } from "@/pages/LoginPage";
import { BookOpen, Shield, Bot, Brain, Network, LogOut, User, Settings, Eye, BarChart3, Sun, Moon, Puzzle } from "lucide-react";
import { AdminDashboardPage } from "./pages/AdminDashboardPage";
import { ChatPage } from "./pages/ChatPage";
import { OAuthLinkCallbackPage } from "./pages/OAuthLinkCallbackPage";
import { recordPageView, sendBeaconPageView, trackAction } from "./api/audit";

// Consolidated navigation (issue #20): MCP Servers and A2A Agents merged into
// one "Integrations" persona with a tab per resource type; Tagging moved
// under Settings as a tab; Costs moved under Admin as a tab; Registry folded
// into Catalog as a collapsible section. `mcp`/`a2a`/`tagging`/`costs`/
// `registry` are no longer top-level personas — they are internal
// tab/section-selection state within `integrations`/`settings`/`admin`/
// `catalog` respectively.
//
// Scope-gate reference (which scope governs sidebar/tab visibility vs. the
// readOnly/edit-ability prop passed to each page):
//   - Integrations sidebar item: mcp:read || a2a:read (either tab visible)
//     - MCP tab: visible iff mcp:read; editable iff mcp:write
//     - A2A tab: visible iff a2a:read; editable iff a2a:write
//   - Settings > Tagging tab: visible iff tagging:read; editable iff tagging:write
//     (previously gated by agent:write||security:write||memory:write, which
//     had nothing to do with tag management — every existing group already
//     carries tagging:read/write alongside those scopes, so this is a no-op
//     for current groups and a correctness fix for future ones)
//   - Admin > Costs tab: visible iff costs:read; editable iff costs:write
//     (previously gated by catalog:read, which is unrelated to cost data;
//     g-admins-super and g-admins-demo already have costs:read/write, so
//     this is also a no-op for current groups)
//   - Catalog > Registry section: visible iff registry:read; editable iff
//     registry:write (unchanged from the standalone Registry page's gate)
type Persona = "catalog" | "security" | "builder" | "memory" | "integrations" | "skills" | "settings" | "admin";

const USER_GROUPS: Record<string, string[]> = {
  "admin": ["t-admin", "g-admins-super"],
  "demo-admin": ["t-admin", "g-admins-demo"],
  "security-admin": ["t-admin", "g-admins-security"],
  "memory-admin": ["t-admin", "g-admins-memory"],
  "mcp-admin": ["t-admin", "g-admins-mcp"],
  "a2a-admin": ["t-admin", "g-admins-a2a"],
  "registry-admin": ["t-admin", "g-admins-registry"],
  "demo-user-1": ["t-user", "g-users-demo"],
  "demo-user-2": ["t-user", "g-users-demo"],
  "demo-user-3": ["t-user", "g-users-demo"],
  "demo-user-4": ["t-user", "g-users-demo"],
  "demo-user-5": ["t-user", "g-users-demo"],
  "demo-user-6": ["t-user", "g-users-demo"],
  "demo-user-7": ["t-user", "g-users-demo"],
  "demo-user-8": ["t-user", "g-users-demo"],
  "demo-user-9": ["t-user", "g-users-demo"],
  "test-user": ["t-user", "g-users-test"],
};

const VIEW_AS_USERS = Object.keys(USER_GROUPS);

function SidebarClock() {
  const { timezone } = useTimezone();

  const formatTime = () => {
    const now = new Date();
    const opts: Intl.DateTimeFormatOptions = {
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
      hour12: true,
      timeZone: timezone === "UTC" ? "UTC" : undefined,
    };
    return now.toLocaleTimeString(undefined, opts);
  };

  const [time, setTime] = useState(formatTime);

  useEffect(() => {
    const id = setInterval(() => setTime(formatTime()), 1000);
    return () => clearInterval(id);
  });

  return (
    <span className="text-[10px] text-muted-foreground tabular-nums">{time}</span>
  );
}

function SidebarSection({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  const items = Children.toArray(children).filter(Boolean);
  if (items.length === 0) return null;
  return (
    <div className="space-y-1">
      <div className="px-3 pt-1 text-[10px] font-semibold text-muted-foreground/70 uppercase tracking-wide">
        {label}
      </div>
      {items}
    </div>
  );
}

function SidebarItem({
  icon: Icon,
  label,
  active,
  onClick,
  disabled,
  badge,
  count,
}: {
  icon: React.ComponentType<{ className?: string }>;
  label: string;
  active: boolean;
  onClick: () => void;
  disabled?: boolean;
  badge?: string;
  count?: number;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className={`relative flex w-full items-center gap-3 rounded-md px-3 py-2 text-sm whitespace-nowrap transition-colors ${
        disabled
          ? "text-muted-foreground/50 cursor-not-allowed"
          : active
            ? "bg-accent text-foreground"
            : "text-muted-foreground hover:bg-accent/50 hover:text-accent-foreground"
      }`}
    >
      {active && <span className="absolute left-0 top-1.5 bottom-1.5 w-0.5 rounded-full bg-primary" />}
      <Icon className="h-4 w-4 shrink-0" />
      <span className="truncate">{label}</span>
      {badge && <span className="text-[10px] italic shrink-0">{badge}</span>}
      {typeof count === "number" && (
        <span className="ml-auto shrink-0 font-mono text-[10px] tabular-nums text-muted-foreground">{count}</span>
      )}
    </button>
  );
}

function AppContent() {
  const { t } = useTranslation();
  const { isAuthenticated, isLoading, user, logout, hasScope, browserSessionId } = useAuth();
  const { theme, toggleTheme } = useTheme();

  // Determine default persona based on user's scopes
  const getDefaultPersona = useCallback((): Persona => {
    if (hasScope("catalog:read")) return "catalog";
    if (hasScope("security:read") || hasScope("security:write")) return "security";
    if (hasScope("memory:read") || hasScope("memory:write")) return "memory";
    if (hasScope("agent:read") || hasScope("agent:write")) return "builder";
    if (hasScope("admin:read") || hasScope("costs:read")) return "admin";
    if (hasScope("tagging:read") || hasScope("settings:read")) return "settings";
    if (hasScope("mcp:read") || hasScope("mcp:write") || hasScope("a2a:read") || hasScope("a2a:write")) return "integrations";
    return "catalog"; // fallback
  }, [hasScope]);

  const [activePersona, setActivePersona] = useState<Persona>(getDefaultPersona());
  const [agentInitialTab, setAgentInitialTab] = useState<"details" | "invoke">("details");
  const [viewAsUser, setViewAsUser] = useState<string | null>(null);
  const [pendingMcpId, setPendingMcpId] = useState<number | null>(null);
  const [pendingA2aId, setPendingA2aId] = useState<number | null>(null);
  const [pendingSkillId, setPendingSkillId] = useState<string | null>(null);
  const [integrationsTab, setIntegrationsTab] = useState<"mcp" | "a2a">("mcp");

  // Reset all navigation state when user logs in (skip if returning from link callback)
  const hasResetForSession = useRef(false);
  useEffect(() => {
    if (isAuthenticated) {
      if (hasResetForSession.current) return;
      hasResetForSession.current = true;
      const linkReturnId = localStorage.getItem("loom_link_return_agent_id");
      if (linkReturnId && window.location.pathname !== "/oauth/link-callback") {
        localStorage.removeItem("loom_link_return_agent_id");
        const agentId = parseInt(linkReturnId, 10) || null;
        if (agentId) {
          setSelectedAgentId(agentId);
          setActivePersona("builder");
          setAgentInitialTab("invoke");
        }
        return;
      }
      setActivePersona(getDefaultPersona());
      setSelectedAgentId(null);
      setSelectedSessionId(null);
      setSessionDetail(null);
      setSelectedInvocationId(null);
      setInvocationDetail(null);
      setViewAsUser(null);
    } else {
      hasResetForSession.current = false;
    }
  }, [isAuthenticated, getDefaultPersona]);

  // Page view tracking
  const pageEntryRef = useRef<{ persona: string; enteredAt: string } | null>(null);
  useEffect(() => {
    const userId = user?.username || user?.sub;
    if (pageEntryRef.current && userId && browserSessionId) {
      const prev = pageEntryRef.current;
      const duration = Math.round((Date.now() - new Date(prev.enteredAt).getTime()) / 1000);
      recordPageView(userId, browserSessionId, prev.persona, prev.enteredAt, duration).catch(() => {});
    }
    pageEntryRef.current = { persona: activePersona, enteredAt: new Date().toISOString() };
  }, [activePersona, user, browserSessionId]);

  useEffect(() => {
    const handleBeforeUnload = () => {
      const userId = user?.username || user?.sub;
      if (pageEntryRef.current && userId && browserSessionId) {
        const prev = pageEntryRef.current;
        const duration = Math.round((Date.now() - new Date(prev.enteredAt).getTime()) / 1000);
        sendBeaconPageView(userId, browserSessionId, prev.persona, prev.enteredAt, duration);
      }
    };
    window.addEventListener("beforeunload", handleBeforeUnload);
    return () => window.removeEventListener("beforeunload", handleBeforeUnload);
  }, [user, browserSessionId]);

  const isAdmin = user?.groups?.includes("t-admin") ?? false;

  // Determine if the effective user (real or view-as) is an end-user (t-user, not t-admin)
  const effectiveUserGroups = viewAsUser
    ? (USER_GROUPS[viewAsUser] ?? [])
    : (user?.groups ?? []);
  const isEndUser =
    effectiveUserGroups.includes("t-user") && !effectiveUserGroups.includes("t-admin");

  const effectiveHasScope = useCallback(
    (scope: Scope) => {
      if (!viewAsUser) return hasScope(scope);
      const groups = USER_GROUPS[viewAsUser] ?? [];
      return groups.some((g) => (GROUP_SCOPES[g] ?? []).includes(scope));
    },
    [viewAsUser, hasScope],
  );

  // Compute group restriction for resource filtering.
  // Admins (t-admin): no restriction (see all resources including untagged)
  // Users (t-user): extract group tag from first g-users-* group
  const effectiveGroups = viewAsUser
    ? (USER_GROUPS[viewAsUser] ?? [])
    : (user?.groups ?? []);
  const groupRestriction = effectiveGroups.includes("t-admin")
    ? undefined
    : effectiveGroups.find((g) => g.startsWith("g-users-"))?.replace("g-users-", "");

  // For non-admin users, restrict tag profile selection to their own profile.
  // For demo-admin-N users, map to the corresponding demo-user-N profile.
  const _username = user?.username ?? user?.sub ?? "";
  const _demoAdminMatch = _username.match(/^demo-admin-(\d+)$/);
  const ownerRestriction = !isAdmin
    ? _username
    : _demoAdminMatch
      ? `demo-user-${_demoAdminMatch[1]}`
      : undefined;

  const { agents, loading, deleteStartTimes, updateStartTimes, fetchAgents, registerAgent, deployAgent, deployHarnessAgent, redeployAgent, refreshAgent, patchAgent, deleteAgent } = useAgents();

  // Re-fetch agents after authentication completes and when navigating to agent tabs
  useEffect(() => {
    if (isAuthenticated) void fetchAgents();
  }, [isAuthenticated, fetchAgents]);

  useEffect(() => {
    if (isAuthenticated && (activePersona === "catalog" || activePersona === "builder")) {
      void fetchAgents();
    }
    if (activePersona !== "integrations") {
      setPendingMcpId(null);
      setPendingA2aId(null);
    }
    if (activePersona !== "skills") {
      setPendingSkillId(null);
    }
  }, [activePersona, isAuthenticated, fetchAgents]);

  const [registryEnabled, setRegistryEnabled] = useState(false);
  useEffect(() => {
    if (isAuthenticated) void getRegistryConfig().then((c) => setRegistryEnabled(c.enabled)).catch(() => {});
  }, [isAuthenticated]);

  // Sidebar counts for Memory and Integrations (Agents already gets its count from `agents`).
  const [memoryCount, setMemoryCount] = useState(0);
  const [mcpCount, setMcpCount] = useState(0);
  const [a2aCount, setA2aCount] = useState(0);
  const [skillsCount, setSkillsCount] = useState(0);
  useEffect(() => {
    if (isAuthenticated && effectiveHasScope("memory:read")) {
      void listMemories().then((data) => setMemoryCount(data.length)).catch(() => {});
    }
  }, [isAuthenticated, effectiveHasScope]);
  useEffect(() => {
    if (isAuthenticated && effectiveHasScope("mcp:read")) {
      void listMcpServers().then((data) => setMcpCount(data.length)).catch(() => {});
    }
  }, [isAuthenticated, effectiveHasScope]);
  useEffect(() => {
    if (isAuthenticated && effectiveHasScope("a2a:read")) {
      void listA2aAgents().then((data) => setA2aCount(data.length)).catch(() => {});
    }
  }, [isAuthenticated, effectiveHasScope]);
  useEffect(() => {
    if (isAuthenticated && effectiveHasScope("registry:read")) {
      void getRegistryConfig()
        .then((c) => (c.enabled ? listRegistryRecords({ descriptorType: "SKILL" }) : []))
        .then((data) => setSkillsCount(data.length))
        .catch(() => {});
    }
  }, [isAuthenticated, effectiveHasScope]);

  type ViewMode = "cards" | "table";
  const [catalogViewMode, setCatalogViewMode] = useState<ViewMode>("cards");
  const [agentsViewMode, setAgentsViewMode] = useState<ViewMode>("cards");
  const [memoryViewMode, setMemoryViewMode] = useState<ViewMode>("cards");
  const [mcpViewMode, setMcpViewMode] = useState<ViewMode>("cards");
  const [a2aViewMode, setA2aViewMode] = useState<ViewMode>("cards");
  const [selectedAgentId, setSelectedAgentId] = useState<number | null>(null);
  const [selectedSessionId, setSelectedSessionId] = useState<string | null>(null);
  const [sessionDetail, setSessionDetail] = useState<SessionResponse | null>(null);
  const [selectedInvocationId, setSelectedInvocationId] = useState<string | null>(null);
  const [invocationDetail, setInvocationDetail] = useState<InvocationResponse | null>(null);
  const [pendingScopedInvocationId, setPendingScopedInvocationId] = useState<string | null>(null);

  const selectedAgent = agents.find((a) => a.id === selectedAgentId) ?? null;
  const { sessions, loading: sessionsLoading, refetch: refetchSessions } =
    useSessions(selectedAgentId);

  // Fetch session detail when selected
  useEffect(() => {
    if (selectedAgentId === null || selectedSessionId === null) {
      setSessionDetail(null);
      return;
    }
    void getSession(selectedAgentId, selectedSessionId).then(setSessionDetail);
  }, [selectedAgentId, selectedSessionId]);

  // Fetch invocation detail when selected
  useEffect(() => {
    if (selectedAgentId === null || selectedSessionId === null || selectedInvocationId === null) {
      setInvocationDetail(null);
      return;
    }
    void getInvocation(selectedAgentId, selectedSessionId, selectedInvocationId).then(setInvocationDetail);
  }, [selectedAgentId, selectedSessionId, selectedInvocationId]);

  if (isLoading) {
    return (
      <div className="min-h-screen bg-background flex items-center justify-center">
        <p className="text-muted-foreground">{t("common.loading")}</p>
      </div>
    );
  }

  if (window.location.pathname === "/oauth/link-callback") {
    return <OAuthLinkCallbackPage />;
  }

  if (window.location.pathname === "/oauth/callback" && isAuthenticated) {
    const returnPath = sessionStorage.getItem("loom_link_return_url") || "/";
    window.location.replace(returnPath);
    return null;
  }

  if (!isAuthenticated) {
    return <LoginPage />;
  }



  const handleSelectAgent = (id: number) => {
    const agentName = agents.find((a) => a.id === id)?.name ?? String(id);
    if (user && browserSessionId) trackAction(user.username ?? user.sub, browserSessionId, "navigation", "agent_detail", agentName);
    setSelectedAgentId(id);
    setAgentInitialTab("details");
    setSelectedSessionId(null);
    setSessionDetail(null);
    setSelectedInvocationId(null);
    setInvocationDetail(null);
  };

  const handleSelectSession = (sessionId: string) => {
    if (user && browserSessionId) trackAction(user.username ?? user.sub, browserSessionId, "navigation", "session_detail", sessionId);
    setSelectedSessionId(sessionId);
  };

  const handleSelectInvocation = (invocationId: string) => {
    if (user && browserSessionId) trackAction(user.username ?? user.sub, browserSessionId, "navigation", "invocation_detail", invocationId);
    setSelectedInvocationId(invocationId);
  };

  const handleDelete = async (id: number, cleanupAws: boolean) => {
    try {
      const agentName = agents.find(a => a.id === id)?.name ?? String(id);
      if (user && browserSessionId) trackAction(user.username ?? user.sub, browserSessionId, 'agent', 'delete', agentName);
      await deleteAgent(id, cleanupAws);
      // Clear cached invoke state and prompt for this agent so they don't
      // bleed into a new agent that might reuse the same DB id.
      clearInvokeState(id);
      sessionStorage.removeItem(`loom:invokePrompt:${id}`);
      // Remove persisted connector preferences for this agent
      Object.keys(localStorage)
        .filter((k) => k.startsWith(`loom:enabledConnectors:${id}:`))
        .forEach((k) => localStorage.removeItem(k));
      // If the deleted agent was selected, clear all drill-down state
      if (selectedAgentId === id) {
        setSelectedAgentId(null);
        setSelectedSessionId(null);
        setSessionDetail(null);
        setSelectedInvocationId(null);
        setInvocationDetail(null);
      }
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Delete failed");
    }
  };

  // Breadcrumb (for builder/agents persona drill-down)
  const breadcrumb: { label: string; onClick?: () => void }[] = [
    {
      label: "Agents",
      onClick: selectedAgentId
        ? () => {
            setSelectedAgentId(null);
            setSelectedSessionId(null);
            setSessionDetail(null);
            setSelectedInvocationId(null);
            setInvocationDetail(null);
            void fetchAgents();
          }
        : undefined,
    },
  ];

  if (selectedAgent) {
    breadcrumb.push({
      label: selectedAgent.name ?? selectedAgent.runtime_id,
      onClick: selectedSessionId
        ? () => {
            setSelectedSessionId(null);
            setSessionDetail(null);
            setSelectedInvocationId(null);
            setInvocationDetail(null);
          }
        : undefined,
    });
  }

  if (selectedSessionId) {
    breadcrumb.push({
      label: selectedSessionId,
      onClick: selectedInvocationId
        ? () => {
            setSelectedInvocationId(null);
            setInvocationDetail(null);
          }
        : undefined,
    });
  }

  if (selectedInvocationId) {
    breadcrumb.push({ label: selectedInvocationId });
  }

  // End-user chat layout — rendered when user (or admin in view-as mode) is a t-user
  if (isEndUser) {
    return (
      <ChatPage
        userGroups={effectiveUserGroups}
        onLogout={() => {
          if (viewAsUser) {
            setViewAsUser(null);
          } else {
            if (user && browserSessionId)
              trackAction(user.username ?? user.sub, browserSessionId, "auth", "logout");
            logout();
          }
        }}
        viewAsUser={viewAsUser ?? null}
        onExitViewAs={viewAsUser ? () => setViewAsUser(null) : undefined}
      />
    );
  }

  return (
    <div className="h-screen bg-background flex overflow-hidden">
      {/* Sidebar */}
      <aside className="w-56 border-r bg-card flex flex-col shrink-0 h-screen overflow-y-auto">
        <div className="p-4 border-b">
          <img
            src={isLightTheme(theme) ? "/assets/loom_light_alt.png" : "/assets/loom_dark_alt.png"}
            alt="Loom"
            className="h-15"
          />
        </div>
        <nav className="flex-1 p-2 space-y-3">
          <SidebarSection label={t("nav.sections.home")}>
            {effectiveHasScope("catalog:read") && (
              <SidebarItem
                icon={BookOpen}
                label={t("nav.catalog")}
                active={activePersona === "catalog"}
                onClick={() => setActivePersona("catalog")}
              />
            )}
          </SidebarSection>
          <SidebarSection label={t("nav.sections.build")}>
            {(effectiveHasScope("agent:read") || effectiveHasScope("agent:write")) && (
              <SidebarItem
                icon={Bot}
                label={t("nav.agents")}
                active={activePersona === "builder"}
                onClick={() => setActivePersona("builder")}
                count={agents.length}
              />
            )}
            {(effectiveHasScope("memory:read") || effectiveHasScope("memory:write")) && (
              <SidebarItem
                icon={Brain}
                label={t("nav.memory")}
                active={activePersona === "memory"}
                onClick={() => setActivePersona("memory")}
                count={memoryCount}
              />
            )}
            {(effectiveHasScope("mcp:read") || effectiveHasScope("mcp:write") || effectiveHasScope("a2a:read") || effectiveHasScope("a2a:write")) && (
              <SidebarItem
                icon={Network}
                label={t("nav.integrations")}
                active={activePersona === "integrations"}
                onClick={() => setActivePersona("integrations")}
                count={mcpCount + a2aCount}
              />
            )}
            {effectiveHasScope("registry:read") && (
              <SidebarItem
                icon={Puzzle}
                label={t("nav.skills")}
                active={activePersona === "skills"}
                onClick={() => setActivePersona("skills")}
                count={skillsCount}
              />
            )}
          </SidebarSection>
          <SidebarSection label={t("nav.sections.operate")}>
            {(effectiveHasScope("security:read") || effectiveHasScope("security:write")) && (
              <SidebarItem
                icon={Shield}
                label={t("nav.security")}
                active={activePersona === "security"}
                onClick={() => setActivePersona("security")}
              />
            )}
            {(effectiveHasScope("admin:read") || effectiveHasScope("costs:read") || effectiveHasScope("costs:write")) && (
              <SidebarItem
                icon={BarChart3}
                label={t("nav.analytics")}
                active={activePersona === "admin"}
                onClick={() => setActivePersona("admin")}
              />
            )}
          </SidebarSection>
          <SidebarSection label={t("nav.sections.system")}>
            {(effectiveHasScope("settings:read") || effectiveHasScope("tagging:read") || effectiveHasScope("tagging:write")) && (
              <SidebarItem
                icon={Settings}
                label={t("nav.settings")}
                active={activePersona === "settings"}
                onClick={() => setActivePersona("settings")}
              />
            )}
          </SidebarSection>
        </nav>
        <div className="p-2 border-t space-y-1">
          {user && (
            <TooltipProvider>
              <Tooltip>
                <TooltipTrigger asChild>
                  <div className="px-3 py-1 flex items-center gap-2 min-w-0">
                    <User className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                    <span className="text-xs text-muted-foreground truncate">
                      {user.username || "User"}
                    </span>
                  </div>
                </TooltipTrigger>
                <TooltipContent side="top" sideOffset={4}>
                  {user.username || "User"}
                </TooltipContent>
              </Tooltip>
            </TooltipProvider>
          )}
          {isAdmin && (
            <div className="px-3 py-1">
              <Select value={viewAsUser ?? "admin"} onValueChange={(v) => setViewAsUser(v === "admin" ? null : v)}>
                <SelectTrigger className="h-7 w-full gap-1 text-xs text-muted-foreground">
                  <Eye className="h-3 w-3 shrink-0" />
                  <SelectValue />
                </SelectTrigger>
                <SelectContent className="max-h-[80vh]">
                  {VIEW_AS_USERS.map((u) => (
                    <SelectItem key={u} value={u}>{u}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          )}
          <div className="px-3 py-1 flex items-center justify-end gap-2">
            <span className="inline-flex items-center rounded-full border border-border bg-input-bg px-2 py-0.5">
              <SidebarClock />
            </span>
            <span className="inline-flex items-center rounded-full border border-border bg-input-bg px-2 py-0.5 text-[10px] text-muted-foreground">
              v{__APP_VERSION__}
            </span>
            <button
              type="button"
              onClick={toggleTheme}
              className="text-muted-foreground hover:text-foreground transition-colors"
              title={t("common.changeTheme")}
            >
              {theme === "light" ? <Moon className="h-3.5 w-3.5" /> : <Sun className="h-3.5 w-3.5" />}
            </button>
            <button
              type="button"
              onClick={() => {
                if (user && browserSessionId) trackAction(user.username ?? user.sub, browserSessionId, "auth", "logout");
                logout();
              }}
              className="text-muted-foreground hover:text-foreground transition-colors"
              title={t("common.signOut")}
            >
              <LogOut className="h-3.5 w-3.5" />
            </button>
          </div>
        </div>
      </aside>

      {/* Main content */}
      <div className="flex-1 flex flex-col overflow-y-auto">
        {activePersona === "builder" && selectedAgentId !== null && (
          <header className="border-b">
            <div className="max-w-7xl px-8 py-3 flex items-center justify-between gap-4">
              <nav className="flex items-center gap-1 text-sm text-muted-foreground min-w-0">
                {breadcrumb.map((item, i) => (
                  <span key={i} className="flex items-center gap-1 min-w-0">
                    {i > 0 && <span className="shrink-0">/</span>}
                    {item.onClick ? (
                      <button
                        onClick={item.onClick}
                        className="hover:text-foreground transition-colors truncate"
                      >
                        {item.label}
                      </button>
                    ) : (
                      <span className="text-foreground truncate">{item.label}</span>
                    )}
                  </span>
                ))}
              </nav>
            </div>
          </header>
        )}

        <main className="max-w-7xl px-8 py-6 flex-1 w-full">
          {activePersona === "catalog" && (
            <CatalogPage
              agents={agents}
              loading={loading}
              viewMode={catalogViewMode}
              onViewModeChange={setCatalogViewMode}
              onSelectAgent={(id) => { handleSelectAgent(id); setActivePersona("builder"); }}
              onRefreshAgent={refreshAgent}
              onDelete={handleDelete}
              readOnly={!effectiveHasScope("agent:write")}
              agentDeleteStartTimes={deleteStartTimes}
              canViewAgents={effectiveHasScope("agent:read")}
              canViewMemories={effectiveHasScope("memory:read")}
              canViewMcp={effectiveHasScope("mcp:read")}
              canViewA2a={effectiveHasScope("a2a:read")}
              canViewSkills={effectiveHasScope("registry:read")}
              groupRestriction={groupRestriction}
              userGroups={viewAsUser ? (USER_GROUPS[viewAsUser] ?? []) : (user?.groups ?? [])}
              onNavigateToMcp={(serverId) => { setPendingMcpId(serverId); setIntegrationsTab("mcp"); setActivePersona("integrations"); }}
              onNavigateToA2a={(agentId) => { setPendingA2aId(agentId); setIntegrationsTab("a2a"); setActivePersona("integrations"); }}
              onNavigateToSkill={(recordId) => { setPendingSkillId(recordId); setActivePersona("skills"); }}
            />
          )}

          {activePersona === "builder" && (
            <>
              {selectedAgentId === null && (
                <AgentListPage
                  agents={agents}
                  loading={loading}
                  viewMode={agentsViewMode}
                  onViewModeChange={setAgentsViewMode}
                  onRegister={registerAgent}
                  onDeploy={deployAgent}
                  onDeployHarness={deployHarnessAgent}
                  onSelectAgent={handleSelectAgent}
                  onRefreshAgent={refreshAgent}
                  onDelete={handleDelete}
                  readOnly={!effectiveHasScope("agent:write")}
                  groupRestriction={groupRestriction}
                  ownerRestriction={ownerRestriction}
                  deleteStartTimes={deleteStartTimes}
                  updateStartTimes={updateStartTimes}
                  userGroups={viewAsUser ? (USER_GROUPS[viewAsUser] ?? []) : (user?.groups ?? [])}
                />
              )}

              {selectedAgent && !selectedSessionId && (
                <AgentDetailPage
                  agent={selectedAgent}
                  sessions={sessions}
                  sessionsLoading={sessionsLoading}
                  onSelectSession={handleSelectSession}
                  onSessionsRefresh={() => void refetchSessions()}
                  onRedeploy={async (id) => {
                    const agentName = agents.find(a => a.id === id)?.name ?? String(id);
                    if (user && browserSessionId) trackAction(user.username ?? user.sub, browserSessionId, 'agent', 'redeploy', agentName);
                    await redeployAgent(id);
                  }}
                  onPatchAgent={patchAgent}
                  onRefreshAgents={() => void fetchAgents()}
                  canInvoke={effectiveHasScope("invoke")}
                  registryReadOnly={!effectiveHasScope("registry:write")}
                  registryEnabled={registryEnabled}
                  userGroups={viewAsUser ? (USER_GROUPS[viewAsUser] ?? []) : (user?.groups ?? [])}
                  initialTab={agentInitialTab}
                />
              )}

              {selectedAgent && sessionDetail && !selectedInvocationId && (
                <SessionDetailPage
                  agent={selectedAgent}
                  session={sessionDetail}
                  onSelectInvocation={handleSelectInvocation}
                  onRerunInInvoke={() => {
                    setSelectedSessionId(null);
                    setSessionDetail(null);
                    setAgentInitialTab("invoke");
                  }}
                  initialScopedInvocationId={pendingScopedInvocationId}
                />
              )}

              {selectedAgent && sessionDetail && invocationDetail && (
                <InvocationDetailPage
                  agent={selectedAgent}
                  session={sessionDetail}
                  invocation={invocationDetail}
                  onOpenLogs={() => {
                    setPendingScopedInvocationId(invocationDetail.invocation_id);
                    setSelectedInvocationId(null);
                    setInvocationDetail(null);
                  }}
                  onRerunPrompt={() => {
                    if (invocationDetail.prompt_text) {
                      sessionStorage.setItem(`loom:invokePrompt:${selectedAgent.id}`, invocationDetail.prompt_text);
                    }
                    setSelectedSessionId(null);
                    setSessionDetail(null);
                    setSelectedInvocationId(null);
                    setInvocationDetail(null);
                    setAgentInitialTab("invoke");
                  }}
                />
              )}
            </>
          )}

          {activePersona === "security" && <SecurityAdminPage readOnly={!effectiveHasScope("security:write")} agents={agents} />}
          {activePersona === "memory" && <MemoryManagementPage viewMode={memoryViewMode} onViewModeChange={setMemoryViewMode} readOnly={!effectiveHasScope("memory:write")} groupRestriction={groupRestriction} ownerRestriction={ownerRestriction} userGroups={viewAsUser ? (USER_GROUPS[viewAsUser] ?? []) : (user?.groups ?? [])} />}
          {activePersona === "integrations" && (
            <IntegrationsPage
              canViewMcp={effectiveHasScope("mcp:read")}
              canViewA2a={effectiveHasScope("a2a:read")}
              canEditMcp={effectiveHasScope("mcp:write")}
              canEditA2a={effectiveHasScope("a2a:write")}
              activeTab={integrationsTab}
              onActiveTabChange={setIntegrationsTab}
              mcpViewMode={mcpViewMode}
              onMcpViewModeChange={setMcpViewMode}
              a2aViewMode={a2aViewMode}
              onA2aViewModeChange={setA2aViewMode}
              pendingMcpId={pendingMcpId}
              pendingA2aId={pendingA2aId}
              agents={agents}
            />
          )}
          {activePersona === "skills" && (
            <SkillsPage key={`skill-${pendingSkillId ?? "none"}`} initialSelectedId={pendingSkillId} />
          )}
          {activePersona === "settings" && (
            <SettingsPage
              canViewTagging={effectiveHasScope("tagging:read")}
              canEditTagging={effectiveHasScope("tagging:write")}
              userGroups={user?.groups || []}
              agents={agents}
            />
          )}
          {activePersona === "admin" && (
            <AdminDashboardPage
              canViewSessions={effectiveHasScope("admin:read")}
              canViewCosts={effectiveHasScope("costs:read")}
              canEditCosts={effectiveHasScope("costs:write")}
              costsGroupRestriction={groupRestriction}
            />
          )}
        </main>
      </div>

      <Toaster />
    </div>
  );
}

export default function App() {
  return (
    <AuthProvider>
      <ThemeProvider>
        <TimezoneProvider>
          <TooltipProvider>
            <AppContent />
          </TooltipProvider>
        </TimezoneProvider>
      </ThemeProvider>
    </AuthProvider>
  );
}
