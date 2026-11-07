// Settings > Models: the global default Bedrock guardrail (issue #17).
// GET/PUT /api/settings/guardrail-default; guardrail list from GET /api/settings/guardrails.
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import { StatusPill } from "@/components/StatusPill";
import { SettingsCard, SettingsRow } from "@/components/SettingsRow";
import { GuardrailPicker, SegmentedToggle } from "@/components/GuardrailControls";
import { useGuardrailCatalog } from "@/hooks/useGuardrails";
import { updateGuardrailDefault } from "@/api/settings";
import { emptyGuardrailConfig } from "@/lib/guardrails";
import type { GuardrailConfig, GuardrailDefault, GuardrailMode, GuardrailStreamProcessingMode } from "@/api/types";

interface Draft {
  enabled: boolean;
  locked: boolean;
  config: GuardrailConfig;
}

function toDraft(d: GuardrailDefault | null): Draft {
  return {
    enabled: d?.enabled ?? false,
    locked: d?.locked ?? false,
    config: d?.config ? { ...d.config, allowed: d.config.allowed ?? [] } : emptyGuardrailConfig(),
  };
}

function draftsEqual(a: Draft, b: Draft): boolean {
  return JSON.stringify(a) === JSON.stringify(b);
}

export function GuardrailDefaultSettings({ canEdit }: { canEdit: boolean }) {
  const { t } = useTranslation();
  const { guardrails, listError, listLoading, guardrailDefault, defaultLoading, setGuardrailDefault } = useGuardrailCatalog();
  const [draft, setDraft] = useState<Draft>(() => toDraft(null));
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [saveError, setSaveError] = useState("");

  useEffect(() => { setDraft(toDraft(guardrailDefault)); }, [guardrailDefault]);

  const baseline = toDraft(guardrailDefault);
  const isDirty = !draftsEqual(draft, baseline);
  const hasConfig = !!draft.config.guardrail_id && !!draft.config.guardrail_version;
  const configMissing = draft.enabled && !hasConfig;
  const readOnly = !canEdit;
  const isMonitor = draft.config.mode === "monitor";
  const setConfig = (patch: Partial<GuardrailConfig>) => setDraft((d) => ({ ...d, config: { ...d.config, ...patch } }));

  const save = async () => {
    setSaveError("");
    setSaving(true);
    try {
      const result = await updateGuardrailDefault({
        enabled: draft.enabled,
        locked: draft.locked,
        config: hasConfig ? draft.config : null,
      });
      setGuardrailDefault(result);
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    } catch (err: unknown) {
      setSaveError(err instanceof Error ? err.message : "Failed to save");
    } finally {
      setSaving(false);
    }
  };

  const source = guardrailDefault?.source ?? "none";
  const sourcePill = source === "environment"
    ? <StatusPill label={t("settings.guardrails.sourceEnvironment")} variant="info" />
    : source === "settings"
      ? <StatusPill label={t("settings.guardrails.sourceSettings")} variant={guardrailDefault?.enabled ? "success" : "neutral"} />
      : <StatusPill label={t("settings.guardrails.sourceNone")} variant="neutral" />;

  return (
    <>
      <SettingsCard title={t("settings.guardrails.title")} description={t("settings.guardrails.description")} action={defaultLoading ? undefined : sourcePill}>
        <div className="flex flex-col gap-1.5 border-b bg-muted px-[18px] py-2.5 text-[11.5px] leading-[1.5] text-muted-foreground">
          <span>{t("settings.guardrails.policiesNote")}</span>
          {source === "environment" && <span className="text-foreground">{t("settings.guardrails.environmentNote")}</span>}
          {readOnly && <span>{t("settings.guardrails.readOnlyNote")}</span>}
          {!defaultLoading && !guardrailDefault && <span className="text-destructive">{t("settings.guardrails.loadFailed")}</span>}
        </div>

        <SettingsRow label={t("settings.guardrails.enabled")} helper={t("settings.guardrails.enabledHelper")}>
          <label className="flex w-fit cursor-pointer items-center gap-2 text-xs">
            <input
              type="checkbox"
              className="h-3.5 w-3.5 accent-primary"
              checked={draft.enabled}
              disabled={readOnly}
              onChange={(e) => setDraft((d) => ({ ...d, enabled: e.target.checked }))}
            />
            {t("settings.guardrails.enabled")}
          </label>
        </SettingsRow>

        <SettingsRow label={t("settings.guardrails.guardrail")} helper={t("settings.guardrails.guardrailHelper")} align="start">
          <GuardrailPicker
            guardrails={guardrails}
            value={draft.config}
            loading={listLoading}
            error={listError}
            disabled={readOnly}
            onChange={(ref) => setConfig({ guardrail_id: ref.guardrail_id, guardrail_arn: ref.guardrail_arn ?? "", guardrail_version: ref.guardrail_version })}
          />
          {configMissing && <p className="text-[11px] text-destructive">{t("settings.guardrails.configRequired")}</p>}
        </SettingsRow>

        <SettingsRow label={t("settings.guardrails.mode")} align="start">
          <SegmentedToggle<GuardrailMode>
            options={[{ value: "enforce", label: "Enforce" }, { value: "monitor", label: "Monitor" }]}
            value={draft.config.mode}
            disabled={readOnly}
            onChange={(mode) => setConfig({ mode })}
          />
          <p className="text-[11px] leading-[1.5] text-muted-foreground">{t("settings.guardrails.modeHelper")}</p>
          <p className="text-[11px] leading-[1.5] text-muted-foreground">{t("settings.guardrails.modeManagedNote")}</p>
        </SettingsRow>

        <SettingsRow label={t("settings.guardrails.streamMode")} helper={t("settings.guardrails.streamModeHelper")} align="start">
          <SegmentedToggle<GuardrailStreamProcessingMode>
            options={[{ value: "sync", label: "Sync" }, { value: "async", label: "Async" }]}
            value={draft.config.stream_processing_mode}
            disabled={readOnly || isMonitor}
            onChange={(stream_processing_mode) => setConfig({ stream_processing_mode })}
          />
          {isMonitor ? (
            <p className="text-[11px] text-muted-foreground">{t("settings.guardrails.monitorOnlyField")}</p>
          ) : draft.config.stream_processing_mode === "async" ? (
            <p className="text-[11px] leading-[1.5] text-warning">{t("settings.guardrails.streamAsyncNote")}</p>
          ) : null}
        </SettingsRow>

        <SettingsRow label={t("settings.guardrails.redactHistory")} helper={t("settings.guardrails.redactHistoryHelper")} align="start">
          <label className="flex w-fit cursor-pointer items-center gap-2 text-xs">
            <input
              type="checkbox"
              className="h-3.5 w-3.5 accent-primary"
              checked={draft.config.redact_history}
              disabled={readOnly || isMonitor}
              onChange={(e) => setConfig({ redact_history: e.target.checked })}
            />
            {t("settings.guardrails.redactHistory")}
          </label>
          <p className="text-[11px] leading-[1.5] text-muted-foreground">
            {isMonitor ? t("settings.guardrails.monitorOnlyField") : t("settings.guardrails.redactHistoryNote")}
          </p>
        </SettingsRow>

        <SettingsRow label={t("settings.guardrails.locked")} helper={t("settings.guardrails.lockedHelper")} align="start">
          <label className="flex w-fit cursor-pointer items-center gap-2 text-xs">
            <input
              type="checkbox"
              className="h-3.5 w-3.5 accent-primary"
              checked={draft.locked}
              disabled={readOnly}
              onChange={(e) => setDraft((d) => ({ ...d, locked: e.target.checked }))}
            />
            {t("settings.guardrails.locked")}
          </label>
          <p className="text-[11px] leading-[1.5] text-muted-foreground">{t("settings.guardrails.lockedNote")}</p>
        </SettingsRow>
      </SettingsCard>

      {canEdit && (
        <div className="flex max-w-[980px] flex-wrap items-center gap-3 rounded-md border bg-muted px-3.5 py-2.5">
          <span className={`text-[12.5px] ${isDirty ? "" : "text-muted-foreground"}`}>
            {isDirty ? t("settings.guardrails.unsaved") : t("settings.guardrails.noChanges")}
          </span>
          {saveError && <span className="text-[12px] text-destructive">{saveError}</span>}
          <div className="ml-auto flex items-center gap-2">
            <Button size="sm" variant="outline" disabled={!isDirty || saving} onClick={() => { setDraft(baseline); setSaveError(""); }}>
              {t("settings.guardrails.discard")}
            </Button>
            <Button size="sm" disabled={!isDirty || saving || configMissing} onClick={() => void save()}>
              {saving ? t("settings.guardrails.saving") : t("settings.guardrails.save")}
            </Button>
            {saved && <span className="text-[11px] text-success">{t("settings.guardrails.saved")}</span>}
          </div>
        </div>
      )}
    </>
  );
}
