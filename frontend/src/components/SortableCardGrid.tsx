import { type ReactNode } from "react";
import { ArrowDownAZ, ArrowUpAZ } from "lucide-react";

export type SortDirection = "asc" | "desc";

/** Standalone sort toggle button — place wherever you want in the page layout. */
export function SortButton({
  direction,
  onClick,
}: {
  direction: SortDirection;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="flex items-center gap-1 px-2 py-1 rounded-md text-xs text-muted-foreground hover:text-foreground hover:bg-accent transition-colors"
      title={direction === "asc" ? "Sorted A-Z (click for Z-A)" : "Sorted Z-A (click for A-Z)"}
    >
      {direction === "asc" ? (
        <ArrowDownAZ className="h-3.5 w-3.5" />
      ) : (
        <ArrowUpAZ className="h-3.5 w-3.5" />
      )}
      {direction === "asc" ? "A-Z" : "Z-A"}
    </button>
  );
}

interface SortableCardGridProps<T> {
  items: T[];
  getId: (item: T) => string;
  getName: (item: T) => string;
  storageKey: string;
  sortDirection: SortDirection;
  onSortDirectionChange: (direction: SortDirection | null) => void;
  renderItem: (item: T) => ReactNode;
  prependItems?: ReactNode;
  className?: string;
}

function alphabeticalCompare(a: string, b: string, direction: SortDirection): number {
  const cmp = a.localeCompare(b, undefined, { sensitivity: "base" });
  return direction === "desc" ? -cmp : cmp;
}

export function SortableCardGrid<T>({
  items,
  getId,
  getName,
  sortDirection,
  renderItem,
  prependItems,
  className = "grid gap-4 md:grid-cols-2 lg:grid-cols-3",
}: SortableCardGridProps<T>) {
  const sortedItems = [...items].sort((a, b) =>
    alphabeticalCompare(getName(a), getName(b), sortDirection)
  );

  return (
    <div className={className}>
      {prependItems}
      {sortedItems.map((item) => (
        <div key={getId(item)}>
          {renderItem(item)}
        </div>
      ))}
    </div>
  );
}

/** Load persisted sort direction for a storage key, defaulting to "asc". */
export function loadSortDirection(key: string): SortDirection {
  try {
    const raw = localStorage.getItem(`loom-sort-${key}`);
    if (raw === "asc" || raw === "desc") return raw;
  } catch { /* ignore */ }
  return "asc";
}

/** Persist sort direction for a storage key. Pass null to clear. */
export function saveSortDirection(key: string, direction: SortDirection | null) {
  if (direction) {
    localStorage.setItem(`loom-sort-${key}`, direction);
  } else {
    localStorage.removeItem(`loom-sort-${key}`);
  }
}

/** Toggle sort direction and persist. Returns the new direction. */
export function toggleSortDirection(key: string, current: SortDirection): SortDirection {
  const next: SortDirection = current === "asc" ? "desc" : "asc";
  saveSortDirection(key, next);
  return next;
}
