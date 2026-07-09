import { useState } from "react";
import { Textarea } from "@/components/ui/textarea";
import { Button } from "@/components/ui/button";
import { ChevronDown, ChevronRight } from "lucide-react";

interface JsonConfigSectionProps {
  /** Called when the user clicks Apply. Return an error string on failure, or null on success. */
  onApply: (json: string) => string | null | Promise<string | null>;
  /** Called when the user clicks Export. Return the JSON string to display. */
  onExport: () => string | Promise<string>;
  /** Optional label text (defaults to "Paste JSON"). */
  label?: string;
  /** Placeholder text for the textarea. */
  placeholder?: string;
  /** Hide the Apply button (e.g. in edit mode where only export is needed). */
  hideApply?: boolean;
}

export function JsonConfigSection({
  onApply,
  onExport,
  label = "Paste JSON",
  placeholder = '{"name": "...", "description": "..."}',
  hideApply = false,
}: JsonConfigSectionProps) {
  const [showSection, setShowSection] = useState(false);
  const [jsonInput, setJsonInput] = useState("");
  const [jsonError, setJsonError] = useState("");

  const handleApply = async () => {
    const error = await Promise.resolve(onApply(jsonInput));
    if (error) {
      setJsonError(error);
    } else {
      setJsonInput("");
      setJsonError("");
      setShowSection(false);
    }
  };

  const handleExport = async () => {
    try {
      const exported = await Promise.resolve(onExport());
      setJsonInput(exported);
      setJsonError("");
      if (!showSection) setShowSection(true);
    } catch (e) {
      setJsonError(e instanceof Error ? e.message : "Export failed");
      if (!showSection) setShowSection(true);
    }
  };

  const handleCancel = () => {
    setShowSection(false);
    setJsonInput("");
    setJsonError("");
  };

  return (
    <section className="space-y-2">
      <button
        type="button"
        onClick={() => { setShowSection(!showSection); setJsonError(""); }}
        className="flex items-center gap-1 text-xs font-medium text-muted-foreground uppercase tracking-wide hover:text-foreground"
      >
        {showSection ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}
        {label}
      </button>
      {showSection && (
        <div className="space-y-2">
          <Textarea
            placeholder={placeholder}
            value={jsonInput}
            onChange={(e) => { setJsonInput(e.target.value); setJsonError(""); }}
            rows={4}
            className="text-sm font-mono"
          />
          {jsonError && (
            <p className="text-xs text-red-500">{jsonError}</p>
          )}
          <div className="flex gap-2">
            {!hideApply && (
              <Button
                type="button"
                size="sm"
                variant="outline"
                onClick={() => void handleApply()}
                disabled={!jsonInput.trim()}
              >
                Apply
              </Button>
            )}
            <Button
              type="button"
              size="sm"
              variant="outline"
              onClick={() => void handleExport()}
            >
              Export
            </Button>
            <Button
              type="button"
              size="sm"
              variant="ghost"
              onClick={handleCancel}
            >
              Cancel
            </Button>
          </div>
        </div>
      )}
    </section>
  );
}
