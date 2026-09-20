import { MemoryManagementPanel } from "../components/MemoryManagementPanel";
import { ViewModeToggle } from "@/components/ViewModeToggle";

interface MemoryManagementPageProps {
  viewMode: "cards" | "table";
  onViewModeChange: (mode: "cards" | "table") => void;
  readOnly?: boolean;
  groupRestriction?: string;
  ownerRestriction?: string;
  userGroups?: string[];
}

export function MemoryManagementPage({ viewMode, onViewModeChange, readOnly, groupRestriction, ownerRestriction, userGroups = [] }: MemoryManagementPageProps) {

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between">
        <div>
          <h2 className="text-lg font-semibold">Memory Administration</h2>
          <p className="text-sm text-muted-foreground">Create new AgentCore Memory resources with configurable strategies or import existing ones.</p>
        </div>
        <ViewModeToggle viewMode={viewMode} onViewModeChange={onViewModeChange} />
      </div>
      <MemoryManagementPanel viewMode={viewMode} readOnly={readOnly} groupRestriction={groupRestriction} ownerRestriction={ownerRestriction} userGroups={userGroups} />
    </div>
  );
}
