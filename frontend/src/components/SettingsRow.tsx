import { Card } from "@/components/ui/card";

interface SettingsCardProps {
  title: string;
  description?: string;
  action?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
}

/** Titled card shell shared by every Settings tab — max-width 980px, hairline rows inside. */
export function SettingsCard({ title, description, action, children, className = "" }: SettingsCardProps) {
  return (
    <Card className={`max-w-[980px] gap-0 overflow-hidden py-0 ${className}`}>
      <div className="flex flex-wrap items-center gap-2.5 border-b px-[18px] py-3.5">
        <span className="text-[13.5px] font-semibold">{title}</span>
        {description && <span className="text-[12.5px] text-muted-foreground">{description}</span>}
        {action && <div className="ml-auto shrink-0">{action}</div>}
      </div>
      <div className="flex flex-col">{children}</div>
    </Card>
  );
}

interface SettingsRowProps {
  label: string;
  helper?: string;
  align?: "center" | "start";
  children: React.ReactNode;
}

/** grid-cols-[200px_minmax(0,1fr)] settings row: label + helper left, control right, capped at 420px. */
export function SettingsRow({ label, helper, align = "center", children }: SettingsRowProps) {
  return (
    <div className={`grid grid-cols-[200px_minmax(0,1fr)] gap-4 border-b px-[18px] py-3.5 last:border-b-0 ${align === "start" ? "items-start" : "items-center"}`}>
      <div className="flex flex-col gap-0.5">
        <span className="text-[12.5px] font-medium">{label}</span>
        {helper && <span className="text-[11.5px] text-muted-foreground">{helper}</span>}
      </div>
      <div className="flex max-w-[420px] flex-col gap-1.5">{children}</div>
    </div>
  );
}
