import { useState } from "react";
import { RoleManagementPanel } from "@/components/RoleManagementPanel";
import { AuthorizerManagementPanel } from "@/components/AuthorizerManagementPanel";
import { PermissionRequestsPanel } from "@/components/PermissionRequestsPanel";
import { IdentityProviderPanel } from "@/components/IdentityProviderPanel";
import { ApprovalPolicyPanel } from "@/components/ApprovalPolicyPanel";

type SecurityTab = "identity" | "roles" | "authorizers" | "permissions" | "approvals";

export function SecurityAdminPage({ readOnly }: { readOnly?: boolean }) {
  const [activeTab, setActiveTab] = useState<SecurityTab>("identity");

  const tabs: { key: SecurityTab; label: string }[] = [
    { key: "identity", label: "Identity Providers" },
    { key: "roles", label: "IAM Roles" },
    { key: "authorizers", label: "Authorizers" },
    { key: "approvals", label: "Approval Policies" },
    { key: "permissions", label: "Permission Requests" },
  ];

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-lg font-semibold">Security Administration</h2>
        <p className="text-sm text-muted-foreground">Manage identity providers, IAM roles, authorizer configurations, and permission requests.</p>
      </div>

      <div className="flex rounded-md border text-sm w-fit" role="tablist">
        {tabs.map((tab, i) => (
          <button
            key={tab.key}
            type="button"
            role="tab"
            aria-selected={activeTab === tab.key}
            className={`px-4 py-1.5 transition-colors ${
              i === 0 ? "rounded-l-md" : ""
            } ${
              i === tabs.length - 1 ? "rounded-r-md" : ""
            } ${
              activeTab === tab.key
                ? "bg-primary text-primary-foreground"
                : "hover:bg-accent"
            }`}
            onClick={() => setActiveTab(tab.key)}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {activeTab === "identity" && <IdentityProviderPanel readOnly={readOnly} />}
      {activeTab === "roles" && <RoleManagementPanel readOnly={readOnly} />}
      {activeTab === "authorizers" && <AuthorizerManagementPanel readOnly={readOnly} />}
      {activeTab === "permissions" && <PermissionRequestsPanel readOnly={readOnly} />}
      {activeTab === "approvals" && <ApprovalPolicyPanel readOnly={readOnly} />}
    </div>
  );
}
