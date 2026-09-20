import { toast } from "sonner";
import { Tooltip, TooltipTrigger, TooltipContent } from "@/components/ui/tooltip";

interface CopyFieldProps {
  label?: string;
  value: string;
  annotation?: React.ReactNode;
  mono?: boolean;
}

/** Single-line, truncated, copy-to-clipboard field. Never wraps — the full value is available via tooltip and copy. */
export function CopyField({ label, value, annotation, mono = true }: CopyFieldProps) {
  const handleCopy = () => {
    navigator.clipboard.writeText(value);
    toast.success("Copied to clipboard");
  };

  return (
    <div className="flex flex-col gap-1.5 min-w-0">
      {label && (
        <div className="flex items-center gap-2">
          <span className="font-mono text-[9.5px] tracking-wide text-muted-foreground uppercase">{label}</span>
          {annotation}
        </div>
      )}
      <div className="flex items-center overflow-hidden rounded-md border bg-input-bg">
        <Tooltip>
          <TooltipTrigger asChild>
            <div className={`min-w-0 flex-1 truncate px-2.5 py-1.5 text-xs ${mono ? "font-mono" : ""}`}>
              {value}
            </div>
          </TooltipTrigger>
          <TooltipContent className="max-w-md font-mono text-[11px] break-all">{value}</TooltipContent>
        </Tooltip>
        <button
          type="button"
          onClick={handleCopy}
          className="shrink-0 border-l bg-input-bg px-2.5 py-1.5 font-mono text-[10.5px] text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
        >
          copy
        </button>
      </div>
    </div>
  );
}
