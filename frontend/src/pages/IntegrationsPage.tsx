import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { McpServersPage } from "@/pages/McpServersPage";
import { A2aAgentsPage } from "@/pages/A2aAgentsPage";
import type { AgentResponse } from "@/api/types";

export type IntegrationsTab = "mcp" | "a2a";

interface IntegrationsPageProps {
  canViewMcp: boolean;
  canViewA2a: boolean;
  canEditMcp: boolean;
  canEditA2a: boolean;
  activeTab: IntegrationsTab;
  onActiveTabChange: (tab: IntegrationsTab) => void;
  mcpViewMode: "cards" | "table";
  onMcpViewModeChange: (mode: "cards" | "table") => void;
  a2aViewMode: "cards" | "table";
  onA2aViewModeChange: (mode: "cards" | "table") => void;
  pendingMcpId?: number | null;
  pendingA2aId?: number | null;
  agents?: AgentResponse[];
}

/**
 * Merges the former standalone MCP Servers and A2A Agents pages into one
 * "Integrations" page with a tab per resource type. Each tab is gated
 * independently: a tab renders only if the caller has the corresponding
 * read scope (mcp:read / a2a:read) — not merely hidden content within an
 * always-visible tab.
 */
export function IntegrationsPage({
  canViewMcp,
  canViewA2a,
  canEditMcp,
  canEditA2a,
  activeTab,
  onActiveTabChange,
  mcpViewMode,
  onMcpViewModeChange,
  a2aViewMode,
  onA2aViewModeChange,
  pendingMcpId,
  pendingA2aId,
  agents = [],
}: IntegrationsPageProps) {
  const { t } = useTranslation();
  const [mcpCount, setMcpCount] = useState(0);
  const [a2aCount, setA2aCount] = useState(0);

  // If the caller only has access to one of the two tabs, render it directly
  // without the Tabs shell so a single-scope user isn't shown an empty tab list.
  if (canViewMcp && !canViewA2a) {
    return (
      <McpServersPage
        viewMode={mcpViewMode}
        onViewModeChange={onMcpViewModeChange}
        readOnly={!canEditMcp}
        initialSelectedId={pendingMcpId}
        agents={agents}
        key={`mcp-${pendingMcpId}`}
      />
    );
  }
  if (canViewA2a && !canViewMcp) {
    return (
      <A2aAgentsPage
        viewMode={a2aViewMode}
        onViewModeChange={onA2aViewModeChange}
        readOnly={!canEditA2a}
        initialSelectedId={pendingA2aId}
        agents={agents}
        key={`a2a-${pendingA2aId}`}
      />
    );
  }
  if (!canViewMcp && !canViewA2a) {
    return null;
  }

  return (
    <div className="flex flex-col gap-4">
      <div>
        <h2 className="text-lg font-semibold">Integrations</h2>
        <p className="text-sm text-muted-foreground">Tool servers and peer agents available to this platform.</p>
      </div>
      <Tabs value={activeTab} onValueChange={(v) => onActiveTabChange(v as IntegrationsTab)}>
        <TabsList>
          <TabsTrigger value="mcp" className="gap-1.5">
            {t("nav.mcpServers")}
            <span className="rounded-md bg-muted px-1.5 py-0 font-mono text-[10px] text-muted-foreground">{mcpCount}</span>
          </TabsTrigger>
          <TabsTrigger value="a2a" className="gap-1.5">
            {t("nav.a2aAgents")}
            <span className="rounded-md bg-muted px-1.5 py-0 font-mono text-[10px] text-muted-foreground">{a2aCount}</span>
          </TabsTrigger>
        </TabsList>
        <TabsContent value="mcp">
          <McpServersPage
            viewMode={mcpViewMode}
            onViewModeChange={onMcpViewModeChange}
            readOnly={!canEditMcp}
            initialSelectedId={pendingMcpId}
            agents={agents}
            onCountChange={setMcpCount}
            key={`mcp-${pendingMcpId}`}
          />
        </TabsContent>
        <TabsContent value="a2a">
          <A2aAgentsPage
            viewMode={a2aViewMode}
            onViewModeChange={onA2aViewModeChange}
            readOnly={!canEditA2a}
            initialSelectedId={pendingA2aId}
            agents={agents}
            onCountChange={setA2aCount}
            key={`a2a-${pendingA2aId}`}
          />
        </TabsContent>
      </Tabs>
    </div>
  );
}
