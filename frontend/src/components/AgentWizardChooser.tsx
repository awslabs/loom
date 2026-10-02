import { useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { UploadCloud } from "lucide-react";

interface AgentWizardChooserProps {
  /** Start the 5-step guided wizard (R2). */
  onGuided: () => void;
  /** A manifest was chosen; hand its raw text up so it can be parsed and jump straight to review (R1/R6). */
  onImport: (json: string) => void;
  /** Optional escape hatch to the legacy "register an existing runtime by ARN" flow. */
  onRegisterArn?: () => void;
}

export function AgentWizardChooser({ onGuided, onImport, onRegisterArn }: AgentWizardChooserProps) {
  const [pasteOpen, setPasteOpen] = useState(false);
  const [pasteValue, setPasteValue] = useState("");
  const [pasteError, setPasteError] = useState("");
  const fileInputRef = useRef<HTMLInputElement>(null);

  const submitJson = (raw: string) => {
    const trimmed = raw.trim();
    if (!trimmed) {
      setPasteError("Paste a manifest first.");
      return;
    }
    try {
      JSON.parse(trimmed);
    } catch {
      setPasteError("Invalid JSON. Please check the format and try again.");
      return;
    }
    setPasteError("");
    onImport(trimmed);
  };

  const handleFile = (file: File) => {
    file.text().then((text) => {
      try {
        JSON.parse(text);
      } catch {
        setPasteError(`"${file.name}" is not valid JSON.`);
        setPasteOpen(true);
        return;
      }
      onImport(text);
    }).catch(() => {
      setPasteError(`Could not read "${file.name}".`);
      setPasteOpen(true);
    });
  };

  return (
    <div className="space-y-3">
      <div>
        <h3 className="text-sm font-medium">New agent — choose a path</h3>
        <p className="text-xs text-muted-foreground mt-1">
          Go through the guided setup, or import a manifest and go straight to review.
        </p>
      </div>

      <div className="grid gap-3 md:grid-cols-2">
        {/* Guided setup */}
        <div className="flex flex-col gap-3 rounded-lg border p-4">
          <div className="space-y-1">
            <div className="text-[10px] font-medium uppercase tracking-wide text-muted-foreground">Path 1</div>
            <div className="text-sm font-semibold">Guided setup</div>
            <p className="text-xs text-muted-foreground">
              Go through runtime, identity, models, access, and tools one step at a time, with validation at each step. Best for your first agent or a one-off.
            </p>
          </div>
          <div className="flex flex-col gap-0.5 rounded-md border overflow-hidden text-xs">
            {["Runtime", "Identity & models", "Access", "Tools & memory", "Lifecycle & tags"].map((s, i) => (
              <div key={s} className="flex items-center gap-2 px-3 py-1.5 bg-muted/40">
                <span className="font-mono text-[10px] text-muted-foreground">{i + 1}</span>
                <span>{s}</span>
              </div>
            ))}
            <div className="flex items-center gap-2 px-3 py-1.5 bg-primary/10 text-primary">
              <span className="font-mono text-[10px]">&rarr;</span>
              <span>Review &amp; deploy</span>
            </div>
          </div>
          <Button type="button" size="sm" className="mt-auto" onClick={onGuided}>
            Start guided setup
          </Button>
        </div>

        {/* Import manifest */}
        <div className="flex flex-col gap-3 rounded-lg border-2 border-primary/50 p-4 ring-2 ring-primary/10">
          <div className="space-y-1">
            <div className="text-[10px] font-medium uppercase tracking-wide text-primary">Path 2</div>
            <div className="text-sm font-semibold">Import manifest</div>
            <p className="text-xs text-muted-foreground">
              Load a JSON manifest for this agent and go straight to review before deploying.
            </p>
          </div>

          <button
            type="button"
            onClick={() => fileInputRef.current?.click()}
            onDragOver={(e) => e.preventDefault()}
            onDrop={(e) => {
              e.preventDefault();
              const file = e.dataTransfer.files?.[0];
              if (file) handleFile(file);
            }}
            className="flex min-h-[110px] flex-col items-center justify-center gap-1.5 rounded-md border-2 border-dashed border-primary/40 bg-primary/5 px-3 py-4 text-center hover:bg-primary/10"
          >
            <UploadCloud className="h-5 w-5 text-primary/70" />
            <div className="text-xs font-medium">Drop manifest here, or click to choose a file</div>
            <div className="text-[10px] font-mono text-muted-foreground">.json</div>
          </button>
          <input
            ref={fileInputRef}
            type="file"
            accept=".json,application/json"
            className="hidden"
            onChange={(e) => {
              const file = e.target.files?.[0];
              if (file) handleFile(file);
              e.target.value = "";
            }}
          />

          <div className="flex items-center gap-2 text-[10px] text-muted-foreground">
            <div className="h-px flex-1 bg-border" />
            or
            <div className="h-px flex-1 bg-border" />
          </div>

          {!pasteOpen ? (
            <Button type="button" size="sm" variant="outline" onClick={() => setPasteOpen(true)}>
              Paste JSON
            </Button>
          ) : (
            <div className="space-y-2">
              <Textarea
                autoFocus
                placeholder='{"deployment_type": "custom", "name": "...", "model": "...", "role": "..."}'
                value={pasteValue}
                onChange={(e) => { setPasteValue(e.target.value); setPasteError(""); }}
                rows={5}
                className="text-xs font-mono max-h-40 overflow-y-auto resize-none [field-sizing:fixed]"
              />
              {pasteError && <p className="text-xs text-red-500">{pasteError}</p>}
              <div className="flex gap-2">
                <Button type="button" size="sm" onClick={() => submitJson(pasteValue)} disabled={!pasteValue.trim()}>
                  Use this manifest
                </Button>
                <Button type="button" size="sm" variant="ghost" onClick={() => { setPasteOpen(false); setPasteValue(""); setPasteError(""); }}>
                  Cancel
                </Button>
              </div>
            </div>
          )}
          {pasteError && !pasteOpen && <p className="text-xs text-red-500">{pasteError}</p>}
        </div>
      </div>

      {onRegisterArn && (
        <button
          type="button"
          onClick={onRegisterArn}
          className="text-xs text-muted-foreground hover:text-foreground hover:underline"
        >
          Or register an existing AgentCore runtime by ARN instead &rarr;
        </button>
      )}
    </div>
  );
}
