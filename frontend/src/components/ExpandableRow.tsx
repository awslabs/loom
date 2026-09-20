import { ChevronDown, ChevronRight } from "lucide-react";
import { Card } from "@/components/ui/card";
import { StatusPill } from "@/components/StatusPill";
import type { BadgeVariant } from "@/lib/status";

interface ExpandableRowProps {
  expanded: boolean;
  onToggle: () => void;
  title: string;
  typeBadge?: string;
  statusLabel?: string;
  statusVariant?: BadgeVariant;
  subtitle?: string;
  meta?: React.ReactNode;
  actions?: React.ReactNode;
  children?: React.ReactNode;
  className?: string;
}

/**
 * Shared row for Security's five tabs: chevron + mono name + type pill + state pill +
 * secondary line, right-aligned meta/actions, and (when expanded) a body rendered inside
 * the SAME card — never a nested bordered box on a tinted fill.
 */
export function ExpandableRow({
  expanded,
  onToggle,
  title,
  typeBadge,
  statusLabel,
  statusVariant: variant,
  subtitle,
  meta,
  actions,
  children,
  className = "",
}: ExpandableRowProps) {
  return (
    <Card className={`gap-0 overflow-hidden py-0 ${className}`}>
      <div className={`flex items-center gap-3 px-[18px] py-3.5 ${expanded && children ? "border-b" : ""}`}>
        <button type="button" onClick={onToggle} className="shrink-0 text-muted-foreground hover:text-foreground">
          {expanded ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
        </button>
        <div className="flex min-w-0 flex-1 flex-col gap-0.5">
          <div className="flex items-center gap-2">
            <span className="truncate font-mono text-sm font-semibold">{title}</span>
            {typeBadge && (
              <span className="shrink-0 rounded-md border bg-muted px-1.5 py-0.5 font-mono text-[10px] tracking-wide text-muted-foreground">
                {typeBadge}
              </span>
            )}
            {statusLabel && <StatusPill label={statusLabel} variant={variant ?? "neutral"} />}
          </div>
          {subtitle && <span className="truncate font-mono text-[11.5px] text-muted-foreground">{subtitle}</span>}
        </div>
        <div className="ml-auto flex shrink-0 items-center gap-2.5">
          {meta}
          {actions}
        </div>
      </div>
      {expanded && children && <div className="px-[18px] py-4">{children}</div>}
    </Card>
  );
}
