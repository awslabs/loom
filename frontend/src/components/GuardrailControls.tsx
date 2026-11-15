// Shared Bedrock Guardrails controls (issue #17): the guardrail + version
// picker, a small segmented toggle, the alternates checklist, and the inline
// stream-event notice. Used by Settings, the agent wizard, the agent detail
// page, InvokePanel, and ChatPage.
import { ShieldAlert, ShieldCheck } from "lucide-react";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { SearchableSelect } from "@/components/ui/searchable-select";
import type { GuardrailConfig, GuardrailRef, GuardrailSummary, SSEGuardrail } from "@/api/types";
import {
  guardrailEventLabel,
  guardrailRefKey,
  guardrailRefLabel,
  pickDefaultVersion,
  policyLabel,
  sameGuardrailRef,
} from "@/lib/guardrails";

// ---- guardrail + version picker --------------------------------------------

interface GuardrailPickerProps {
  guardrails: GuardrailSummary[];
  value: Pick<GuardrailRef, "guardrail_id" | "guardrail_version">;
  /** Receives the picked guardrail's ARN too, so callers can store it. */
  onChange: (ref: GuardrailRef) => void;
  loading?: boolean;
  error?: string | null;
  disabled?: boolean;
}

export function GuardrailPicker({ guardrails, value, onChange, loading, error, disabled }: GuardrailPickerProps) {
  const selected = guardrails.find((g) => g.guardrail_id === value.guardrail_id);
  // Keep a value that isn't in the list (e.g. an env-provided default, or the
  // list failed to load) selectable instead of silently blanking it.
  const options = guardrails.map((g) => ({ value: g.guardrail_id, label: `${g.name} (${g.guardrail_id})`, group: g.status && g.status !== "READY" ? g.status : undefined }));
  if (value.guardrail_id && !selected) options.unshift({ value: value.guardrail_id, label: value.guardrail_id, group: undefined });
  const versions = selected?.versions ?? [];
  const versionOptions = value.guardrail_version && !versions.includes(value.guardrail_version)
    ? [value.guardrail_version, ...versions]
    : versions.length > 0 ? versions : ["DRAFT"];

  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex items-center gap-2">
        {disabled ? (
          <div className="flex h-8 min-w-0 flex-1 items-center truncate rounded-md border bg-muted px-2.5 text-xs text-muted-foreground">
            {selected ? `${selected.name} (${selected.guardrail_id})` : value.guardrail_id || "No guardrail selected"}
          </div>
        ) : (
          <SearchableSelect
            className="min-w-0 flex-1"
            options={options}
            value={value.guardrail_id}
            onValueChange={(id) => {
              const g = guardrails.find((x) => x.guardrail_id === id);
              onChange({
                guardrail_id: id,
                guardrail_arn: g?.guardrail_arn ?? "",
                guardrail_version: g ? pickDefaultVersion(g.versions) : value.guardrail_version || "DRAFT",
              });
            }}
            placeholder={loading ? "Loading guardrails…" : "Select guardrail…"}
          />
        )}
        <Select
          value={value.guardrail_version || undefined}
          disabled={disabled || !value.guardrail_id}
          onValueChange={(v) => onChange({ guardrail_id: value.guardrail_id, guardrail_arn: selected?.guardrail_arn ?? "", guardrail_version: v })}
        >
          <SelectTrigger size="sm" className="w-28 shrink-0 font-mono text-xs">
            <SelectValue placeholder="Version" />
          </SelectTrigger>
          <SelectContent>
            {versionOptions.map((v) => (
              <SelectItem key={v} value={v} className="font-mono text-xs">{v === "DRAFT" ? "DRAFT" : `v${v}`}</SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
      {error && <p className="text-[11px] text-destructive">Couldn&apos;t list guardrails: {error}</p>}
      {!error && !loading && guardrails.length === 0 && !disabled && (
        <p className="text-[11px] text-muted-foreground">No guardrails found in this region. Create one in the Amazon Bedrock console first.</p>
      )}
      {selected?.description && <p className="text-[11px] text-muted-foreground">{selected.description}</p>}
    </div>
  );
}

// ---- segmented toggle -------------------------------------------------------

export interface SegmentOption<T extends string> {
  value: T;
  label: string;
  disabled?: boolean;
  title?: string;
}

export function SegmentedToggle<T extends string>({ options, value, onChange, disabled }: { options: SegmentOption<T>[]; value: T; onChange: (v: T) => void; disabled?: boolean }) {
  return (
    <div className="inline-flex w-fit rounded-md border bg-accent/40 p-0.5">
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          disabled={disabled || o.disabled}
          title={o.title}
          onClick={() => onChange(o.value)}
          className={`rounded-[5px] px-3 py-1 text-xs font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-50 ${
            value === o.value ? "bg-background shadow-sm" : "text-muted-foreground"
          }`}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

// ---- alternates (runtime selection) ----------------------------------------

interface GuardrailAlternatesPickerProps {
  guardrails: GuardrailSummary[];
  primary: Pick<GuardrailRef, "guardrail_id" | "guardrail_version">;
  value: GuardrailRef[];
  onChange: (refs: GuardrailRef[]) => void;
}

/** Checklist of every (guardrail, version) pair other than the primary. */
export function GuardrailAlternatesPicker({ guardrails, primary, value, onChange }: GuardrailAlternatesPickerProps) {
  const isChecked = (ref: GuardrailRef) => value.some((v) => sameGuardrailRef(v, ref));
  const toggle = (ref: GuardrailRef) => {
    onChange(isChecked(ref) ? value.filter((v) => !sameGuardrailRef(v, ref)) : [...value, ref]);
  };
  // Alternates already saved but no longer listed (deleted version, list failed) stay visible so they can be removed.
  const listedKeys = new Set(guardrails.flatMap((g) => g.versions.map((v) => guardrailRefKey({ guardrail_id: g.guardrail_id, guardrail_version: v }))));
  const unlisted = value.filter((v) => !listedKeys.has(guardrailRefKey(v)));

  if (guardrails.length === 0 && unlisted.length === 0) {
    return <p className="text-[11px] text-muted-foreground">No other guardrails available.</p>;
  }
  return (
    <div className="max-h-48 overflow-y-auto rounded-md border">
      {guardrails.map((g) => (
        <div key={g.guardrail_id} className="grid grid-cols-[minmax(0,180px)_minmax(0,1fr)] items-center gap-2.5 border-b px-2.5 py-1.5 last:border-b-0">
          <span className="truncate text-xs font-medium" title={g.guardrail_id}>{g.name}</span>
          <div className="flex flex-wrap gap-1.5">
            {g.versions.map((v) => {
              const ref: GuardrailRef = { guardrail_id: g.guardrail_id, guardrail_arn: g.guardrail_arn, guardrail_version: v };
              const isPrimary = sameGuardrailRef(ref, primary);
              const checked = isPrimary || isChecked(ref);
              return (
                <button
                  key={v}
                  type="button"
                  disabled={isPrimary}
                  onClick={() => toggle(ref)}
                  title={isPrimary ? "Primary guardrail" : undefined}
                  className={`rounded-md px-2 py-0.5 font-mono text-[11px] transition-colors ${
                    checked ? "bg-primary text-primary-foreground" : "border text-foreground hover:bg-accent"
                  } ${isPrimary ? "cursor-default opacity-80" : ""}`}
                >
                  {v === "DRAFT" ? "DRAFT" : `v${v}`}
                  {isPrimary && <span className="ml-1 text-[9px]">primary</span>}
                </button>
              );
            })}
          </div>
        </div>
      ))}
      {unlisted.map((ref) => (
        <div key={guardrailRefKey(ref)} className="flex items-center gap-2.5 border-b px-2.5 py-1.5 last:border-b-0">
          <span className="truncate font-mono text-xs text-muted-foreground">{guardrailRefLabel(ref, guardrails)}</span>
          <button type="button" onClick={() => toggle(ref)} className="ml-auto text-[11px] text-primary hover:underline">remove</button>
        </div>
      ))}
    </div>
  );
}

// ---- read-only summary --------------------------------------------------------

/** Compact chips: name/id · version · mode · stream · redact. */
export function GuardrailConfigSummary({ config, guardrails }: { config: GuardrailConfig; guardrails: GuardrailSummary[] }) {
  const name = guardrails.find((g) => g.guardrail_id === config.guardrail_id)?.name;
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      <span className="text-[12.5px] font-medium">{name ?? config.guardrail_id}</span>
      {name && <span className="font-mono text-[11px] text-muted-foreground">{config.guardrail_id}</span>}
      <span className="rounded bg-accent px-1.5 py-0.5 font-mono text-[11px]">{config.guardrail_version === "DRAFT" ? "DRAFT" : `v${config.guardrail_version}`}</span>
      <span className="rounded bg-accent px-1.5 py-0.5 font-mono text-[11px]">{config.mode}</span>
      {config.mode === "enforce" && (
        <>
          <span className="rounded bg-accent px-1.5 py-0.5 font-mono text-[11px]">stream {config.stream_processing_mode}</span>
          <span className="rounded bg-accent px-1.5 py-0.5 font-mono text-[11px]">{config.redact_history ? "redact history" : "keep history"}</span>
        </>
      )}
      {config.allowed && config.allowed.length > 0 && (
        <span className="rounded border px-1.5 py-0.5 font-mono text-[11px] text-muted-foreground">+{config.allowed.length} alternate{config.allowed.length === 1 ? "" : "s"}</span>
      )}
    </div>
  );
}

// ---- stream notice -------------------------------------------------------------

/** Inline notice for an SSE `guardrail` event inside a response bubble. */
export function GuardrailNotice({ event }: { event: SSEGuardrail }) {
  const detected = event.action === "detected";
  const Icon = detected ? ShieldCheck : ShieldAlert;
  return (
    <div
      className={`my-1 flex flex-wrap items-center gap-1.5 rounded-md border px-2 py-1 text-[11.5px] ${
        detected ? "border-warning/40 bg-warning-bg text-warning" : "border-destructive/30 bg-destructive/[0.06] text-destructive"
      }`}
      title={`${event.guardrail_id} · ${event.guardrail_version}`}
    >
      <Icon className="h-3.5 w-3.5 shrink-0" />
      <span className="font-medium">{guardrailEventLabel({ ...event, policies: [] })}</span>
      {(event.policies ?? []).map((p, i) => (
        <span key={i} className="rounded border border-current/30 px-1.5 py-0 font-mono text-[10.5px]">
          {policyLabel(p)}{p.action ? ` · ${p.action.toLowerCase()}` : ""}
        </span>
      ))}
    </div>
  );
}

/** Policy chips for tables (interventions history). */
export function GuardrailPolicyChips({ event }: { event: Pick<SSEGuardrail, "policies"> }) {
  if (!event.policies || event.policies.length === 0) return <span className="text-muted-foreground">—</span>;
  return (
    <div className="flex flex-wrap gap-1">
      {event.policies.map((p, i) => (
        <span key={i} className="rounded border bg-muted px-1.5 py-0.5 font-mono text-[10.5px]" title={p.action}>
          {policyLabel(p)}{p.action ? ` · ${p.action.toLowerCase()}` : ""}
        </span>
      ))}
    </div>
  );
}
