import { ArrowUp, ArrowDown } from "lucide-react";
import { TableHead } from "@/components/ui/table";
import type { SortDirection } from "@/components/SortableCardGrid";

interface SortableTableHeadProps {
  column: string;
  activeColumn: string | null;
  direction: SortDirection;
  onSort: (column: string) => void;
  className?: string;
  children: React.ReactNode;
}

export function SortableTableHead({
  column,
  activeColumn,
  direction,
  onSort,
  className,
  children,
}: SortableTableHeadProps) {
  const isActive = activeColumn === column;
  return (
    <TableHead
      className={`${className ?? ""} cursor-pointer select-none hover:text-foreground transition-colors`}
      onClick={() => onSort(column)}
    >
      <span className="inline-flex items-center gap-1">
        {children}
        {isActive && (
          direction === "asc"
            ? <ArrowUp className="h-3 w-3" />
            : <ArrowDown className="h-3 w-3" />
        )}
      </span>
    </TableHead>
  );
}

/** Generic sort helper for table rows. */
export function sortRows<T>(
  rows: T[],
  column: string | null,
  direction: SortDirection,
  getters: Record<string, (item: T) => string | number>,
): T[] {
  if (!column || !getters[column]) return rows;
  const getter = getters[column];
  return [...rows].sort((a, b) => {
    const va = getter(a);
    const vb = getter(b);
    let cmp: number;
    if (typeof va === "number" && typeof vb === "number") {
      cmp = va - vb;
    } else {
      cmp = String(va).localeCompare(String(vb), undefined, { sensitivity: "base" });
    }
    return direction === "desc" ? -cmp : cmp;
  });
}
