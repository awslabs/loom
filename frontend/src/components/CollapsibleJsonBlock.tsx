import { useState } from "react";
import { Copy, Check } from "lucide-react";

export function CollapsibleJsonBlock({ children }: { children: React.ReactNode }) {
  const [copied, setCopied] = useState(false);

  const rawChildren = (children as { props?: { children?: unknown } } | null)?.props?.children;
  const text =
    typeof rawChildren === "string"
      ? rawChildren
      : Array.isArray(rawChildren)
        ? (rawChildren as unknown[]).join("")
        : String(rawChildren ?? "");

  const handleCopy = () => {
    void navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };

  return (
    <details className="mb-2 group">
      <summary className="cursor-pointer list-none flex items-center gap-1.5 rounded bg-black/10 dark:bg-white/10 px-3 py-1.5 text-xs font-mono text-muted-foreground hover:text-foreground select-none">
        <span className="inline-block transition-transform group-open:rotate-90">▶</span>
        JSON
      </summary>
      <div className="relative mt-1">
        <pre className="overflow-x-auto rounded bg-black/10 dark:bg-white/10 p-3 pr-8 text-xs font-mono">
          {children}
        </pre>
        <button
          onClick={handleCopy}
          className="absolute top-1.5 right-1.5 p-1 rounded hover:bg-black/10 dark:hover:bg-white/10 text-muted-foreground hover:text-foreground transition-colors"
          title="Copy JSON"
        >
          {copied ? <Check className="h-3 w-3" /> : <Copy className="h-3 w-3" />}
        </button>
      </div>
    </details>
  );
}
