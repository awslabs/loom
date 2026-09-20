import { statusDotClass, type BadgeVariant } from "@/lib/status";

interface StatusPillProps {
  label: string;
  variant: BadgeVariant;
  className?: string;
}

/** Dot + mono-caps label, same vocabulary as RegistryStatusBadge — for non-registry lifecycle states (deployment, runtime, code interpreter). */
export function StatusPill({ label, variant, className = "" }: StatusPillProps) {
  return (
    <span
      className={`inline-flex shrink-0 items-center gap-1 rounded-full border border-transparent px-1.5 py-0.5 text-[10px] font-medium tracking-wide ${
        variant === "success" ? "bg-success-bg text-success"
        : variant === "warning" ? "bg-warning-bg text-warning"
        : variant === "destructive" ? "bg-destructive/10 text-destructive"
        : "bg-status-neutral-bg text-status-neutral"
      } ${className}`}
    >
      <span className={`h-1.5 w-1.5 shrink-0 rounded-full ${statusDotClass(variant)}`} />
      {label}
    </span>
  );
}
