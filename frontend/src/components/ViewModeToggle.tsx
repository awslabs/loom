import { LayoutGrid, TableIcon } from "lucide-react";

interface ViewModeToggleProps {
  viewMode: "cards" | "table";
  onViewModeChange: (mode: "cards" | "table") => void;
}

/** Segmented Cards/Table switch — neutral track, subtle-fill active segment (never a filled accent block). */
export function ViewModeToggle({ viewMode, onViewModeChange }: ViewModeToggleProps) {
  return (
    <div className="flex items-center gap-0.5 rounded-md border bg-input-bg p-[3px]" role="tablist">
      <button
        type="button"
        role="tab"
        aria-selected={viewMode === "cards"}
        className={`flex items-center rounded-[5px] px-2 py-1 transition-colors ${viewMode === "cards" ? "bg-accent text-foreground" : "text-muted-foreground hover:text-foreground"}`}
        onClick={() => onViewModeChange("cards")}
        title="Card view"
      >
        <LayoutGrid className="h-3.5 w-3.5" />
      </button>
      <button
        type="button"
        role="tab"
        aria-selected={viewMode === "table"}
        className={`flex items-center rounded-[5px] px-2 py-1 transition-colors ${viewMode === "table" ? "bg-accent text-foreground" : "text-muted-foreground hover:text-foreground"}`}
        onClick={() => onViewModeChange("table")}
        title="Table view"
      >
        <TableIcon className="h-3.5 w-3.5" />
      </button>
    </div>
  );
}
