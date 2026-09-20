import { useState } from "react";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { RoleManagementPanel } from "@/components/RoleManagementPanel";
import { AuthorizerManagementPanel } from "@/components/AuthorizerManagementPanel";
import { PermissionRequestsPanel } from "@/components/PermissionRequestsPanel";
import { IdentityProviderPanel } from "@/components/IdentityProviderPanel";
import { ApprovalPolicyPanel } from "@/components/ApprovalPolicyPanel";
import type { AgentResponse } from "@/api/types";

type SecurityTab = "identity" | "roles" | "authorizers" | "permissions" | "approvals";

export function SecurityAdminPage({ readOnly, agents = [] }: { readOnly?: boolean; agents?: AgentResponse[] }) {
  const [activeTab, setActiveTab] = useState<SecurityTab>("identity");
  const [counts, setCounts] = useState<Partial<Record<SecurityTab, number>>>({});

  const setCount = (tab: SecurityTab) => (n: number) => setCounts((prev) => (prev[tab] === n ? prev : { ...prev, [tab]: n }));

  const tabs: { key: SecurityTab; label: string }[] = [
    { key: "identity", label: "Identity providers" },
    { key: "roles", label: "IAM roles" },
    { key: "authorizers", label: "Authorizers" },
    { key: "approvals", label: "Approval policies" },
    { key: "permissions", label: "Permission requests" },
  ];

  return (
    <div className="space-y-4">
      <div>
        <h2 className="text-lg font-semibold">Security</h2>
        <p className="text-sm text-muted-foreground">Identity, roles, and authorization for the platform.</p>
      </div>

      <Tabs value={activeTab} onValueChange={(v) => setActiveTab(v as SecurityTab)}>
        <TabsList variant="line" className="h-auto justify-start gap-5 rounded-none border-b bg-transparent p-0">
          {tabs.map((tab) => (
            <TabsTrigger key={tab.key} value={tab.key} className="gap-1.5 rounded-none px-0.5 pb-2.5 text-[13px] font-medium data-[state=active]:shadow-none">
              {tab.label}
              {counts[tab.key] !== undefined && (
                <span className="rounded-md bg-muted px-1.5 py-0 font-mono text-[10px] text-muted-foreground">{counts[tab.key]}</span>
              )}
            </TabsTrigger>
          ))}
        </TabsList>

        <TabsContent value="identity" className="pt-4"><IdentityProviderPanel readOnly={readOnly} onCountChange={setCount("identity")} /></TabsContent>
        <TabsContent value="roles" className="pt-4"><RoleManagementPanel readOnly={readOnly} agents={agents} onCountChange={setCount("roles")} /></TabsContent>
        <TabsContent value="authorizers" className="pt-4"><AuthorizerManagementPanel readOnly={readOnly} onCountChange={setCount("authorizers")} /></TabsContent>
        <TabsContent value="permissions" className="pt-4"><PermissionRequestsPanel readOnly={readOnly} onCountChange={setCount("permissions")} /></TabsContent>
        <TabsContent value="approvals" className="pt-4"><ApprovalPolicyPanel readOnly={readOnly} onCountChange={setCount("approvals")} /></TabsContent>
      </Tabs>
    </div>
  );
}
