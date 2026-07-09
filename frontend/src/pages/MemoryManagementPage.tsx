import { LayoutGrid, TableIcon } from "lucide-react";
import { MemoryManagementPanel } from "../components/MemoryManagementPanel";

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
        <div className="flex rounded-md border text-sm shrink-0" role="tablist">
          <button
            type="button"
            role="tab"
            aria-selected={viewMode === "cards"}
            className={`px-2 py-1 rounded-l-md transition-colors ${viewMode === "cards" ? "bg-primary text-primary-foreground" : "hover:bg-accent"}`}
            onClick={() => onViewModeChange("cards")}
            title="Card view"
          >
            <LayoutGrid className="h-3.5 w-3.5" />
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={viewMode === "table"}
            className={`px-2 py-1 rounded-r-md transition-colors ${viewMode === "table" ? "bg-primary text-primary-foreground" : "hover:bg-accent"}`}
            onClick={() => onViewModeChange("table")}
            title="Table view"
          >
            <TableIcon className="h-3.5 w-3.5" />
          </button>
        </div>
      </div>
      <MemoryManagementPanel viewMode={viewMode} readOnly={readOnly} groupRestriction={groupRestriction} ownerRestriction={ownerRestriction} userGroups={userGroups} />
    </div>
  );
}
