import { useCallback, useEffect, useState } from "react";
import { ArrowLeft, ExternalLink, Loader2, Pencil, Plus, Puzzle, RefreshCw, Trash2 } from "lucide-react";
import ReactMarkdown from "react-markdown";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Skeleton } from "@/components/ui/skeleton";
import { toast } from "sonner";
import { RegistryStatusBadge } from "@/components/RegistryStatusBadge";
import { useTimezone } from "@/contexts/TimezoneContext";
import { useAuth } from "@/contexts/AuthContext";
import { formatTimestamp } from "@/lib/format";
import {
  listRegistryRecords,
  getRegistryRecord,
  createRegistryRecord,
  updateSkillRecord,
  deleteRegistryRecord,
} from "@/api/registry";
import { getRegistryConfig } from "@/api/settings";
import type { RegistryRecord, RegistryRecordDetail } from "@/api/types";

/** Agent Skills surface: the SKILL-typed records of the bound Agent Registry.
 *
 * Skills are the reuse unit of the registry — an agent is someone's
 * application, a skill is a capability another team can adopt. Browsing is
 * served live from the bound AWS Agent Registry; admins with registry:write
 * can also author/edit/delete SKILL records directly from this page (record
 * approval lifecycle — submit/approve/reject — still stays with the registry
 * admin flows elsewhere).
 */

interface SkillLinks {
  repositoryUrl?: string;
  websiteUrl?: string;
}

/** Pull the optional repository/website links out of the SKILL descriptor.
 * The `agentSkillsDefinition` descriptor carries a JSON `data` payload whose
 * schema belongs to the publisher, so parse defensively and surface only the
 * two well-known link fields. Note: AWS's server-side validation for this
 * descriptor only accepts data shaped exactly like {name, description,
 * license, metadata} (confirmed by direct trial — see issue #61), so a
 * repository/websiteUrl link can never actually appear on a record created
 * through this page's own form below; this remains solely for records
 * authored by other, non-Loom publishers that might use a different shape. */
function parseSkillLinks(detail: RegistryRecordDetail): SkillLinks {
  try {
    const def = detail.descriptors?.agentSkillsDefinition as { data?: string } | undefined;
    if (!def?.data) return {};
    const data = JSON.parse(def.data) as { repository?: { url?: string }; websiteUrl?: string };
    return { repositoryUrl: data.repository?.url, websiteUrl: data.websiteUrl };
  } catch {
    return {};
  }
}

interface SkillDefinition {
  name: string;
  description: string;
  license: string;
  author: string;
  version: string;
  skillMd: string;
}

/** Pull the structured fields + full SKILL.md body back out of a SKILL
 * record's descriptors, for pre-filling the edit form. */
function parseSkillDefinition(detail: RegistryRecordDetail): SkillDefinition {
  const def = detail.descriptors?.agentSkillsDefinition as
    | { data?: string; additionalData?: { skillMd?: { data?: string } } }
    | undefined;
  let name = detail.name;
  let description = detail.description ?? "";
  let license = "";
  let author = "";
  let version = "";
  try {
    if (def?.data) {
      const data = JSON.parse(def.data) as {
        name?: string;
        description?: string;
        license?: string;
        metadata?: { author?: string; version?: string };
      };
      name = data.name ?? name;
      description = data.description ?? description;
      license = data.license ?? "";
      author = data.metadata?.author ?? "";
      version = data.metadata?.version ?? "";
    }
  } catch {
    // fall through with whatever defaults were set above
  }
  return { name, description, license, author, version, skillMd: def?.additionalData?.skillMd?.data ?? "" };
}

function MetaRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex gap-3 text-xs py-1.5 border-b last:border-0">
      <span className="w-32 shrink-0 text-muted-foreground uppercase tracking-wide text-[10px] pt-0.5">{label}</span>
      <span className="min-w-0 break-all">{children}</span>
    </div>
  );
}

function ExternalLinkRow({ url }: { url: string }) {
  return (
    <a
      href={url}
      target="_blank"
      rel="noopener noreferrer"
      className="inline-flex items-center gap-1 text-primary hover:underline"
    >
      {url} <ExternalLink className="h-3 w-3 shrink-0" />
    </a>
  );
}

interface SkillFormValues {
  name: string;
  description: string;
  license: string;
  version: string;
  skillMd: string;
}

const DEFAULT_SKILL_VERSION = "1.0.0";
const EMPTY_SKILL_FORM: SkillFormValues = { name: "", description: "", license: "MIT", version: DEFAULT_SKILL_VERSION, skillMd: "" };

/** Create/edit form for a SKILL record. Author is never an input here — it's
 * always the current Loom user on create, and preserved from the existing
 * record on edit (both enforced server-side, not just in this form). */
function SkillForm({
  initial,
  submitLabel,
  onSubmit,
  onCancel,
}: {
  initial: SkillFormValues;
  submitLabel: string;
  onSubmit: (values: SkillFormValues) => Promise<void>;
  onCancel: () => void;
}) {
  const [values, setValues] = useState<SkillFormValues>(initial);
  const [submitting, setSubmitting] = useState(false);

  const set = <K extends keyof SkillFormValues>(key: K, value: SkillFormValues[K]) =>
    setValues((v) => ({ ...v, [key]: value }));

  const canSubmit = values.name.trim() && values.description.trim() && values.license.trim() && values.version.trim() && values.skillMd.trim();

  const handleSubmit = async () => {
    setSubmitting(true);
    try {
      await onSubmit(values);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Card>
      <CardContent className="p-4 space-y-3">
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          <div className="space-y-1.5">
            <Label htmlFor="skill-name" className="text-xs">Name</Label>
            <Input id="skill-name" value={values.name} onChange={(e) => set("name", e.target.value)} placeholder="e.g. security-scan" />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="skill-license" className="text-xs">License</Label>
            <Input id="skill-license" value={values.license} onChange={(e) => set("license", e.target.value)} placeholder="e.g. MIT" />
          </div>
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="skill-description" className="text-xs">Description</Label>
          <Textarea
            id="skill-description"
            value={values.description}
            onChange={(e) => set("description", e.target.value)}
            rows={2}
            placeholder="What this skill does and when an agent should use it"
          />
        </div>
        <div className="space-y-1.5 max-w-[200px]">
          <Label htmlFor="skill-version" className="text-xs">Version</Label>
          <Input id="skill-version" value={values.version} onChange={(e) => set("version", e.target.value)} placeholder={DEFAULT_SKILL_VERSION} />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="skill-md" className="text-xs">SKILL.md body</Label>
          <Textarea
            id="skill-md"
            value={values.skillMd}
            onChange={(e) => set("skillMd", e.target.value)}
            rows={12}
            className="font-mono text-xs"
            placeholder={"---\nname: security-scan\ndescription: ...\n---\n\n# Security Scan\n\n..."}
          />
        </div>
        <div className="flex items-center gap-2 pt-1">
          <Button size="sm" disabled={!canSubmit || submitting} onClick={() => void handleSubmit()} className="gap-1.5">
            {submitting && <Loader2 className="h-3 w-3 animate-spin" />}
            {submitLabel}
          </Button>
          <Button size="sm" variant="outline" disabled={submitting} onClick={onCancel}>Cancel</Button>
        </div>
      </CardContent>
    </Card>
  );
}

function SkillDetail({
  recordId,
  canWrite,
  onBack,
  onDeleted,
}: {
  recordId: string;
  canWrite: boolean;
  onBack: () => void;
  onDeleted: () => void;
}) {
  const { timezone } = useTimezone();
  const [detail, setDetail] = useState<RegistryRecordDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);
  const [deleting, setDeleting] = useState(false);

  const load = useCallback(() => {
    getRegistryRecord(recordId)
      .then(setDetail)
      .catch((e) => setError(e instanceof Error ? e.message : "Failed to load skill detail"));
  }, [recordId]);

  useEffect(() => { load(); }, [load]);

  const links = detail ? parseSkillLinks(detail) : {};

  const handleUpdate = async (values: SkillFormValues) => {
    try {
      await updateSkillRecord(recordId, {
        skill_name: values.name,
        skill_description: values.description,
        skill_license: values.license,
        skill_version: values.version,
        skill_md: values.skillMd,
      });
      toast.success("Skill updated");
      setEditing(false);
      load();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Failed to update skill");
    }
  };

  const handleDelete = async () => {
    if (!window.confirm(`Delete skill "${detail?.name ?? recordId}"? This cannot be undone.`)) return;
    setDeleting(true);
    try {
      await deleteRegistryRecord(recordId);
      toast.success("Skill deleted");
      onDeleted();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Failed to delete skill");
      setDeleting(false);
    }
  };

  return (
    <div className="space-y-4">
      <Button variant="outline" size="sm" onClick={onBack} className="gap-1.5">
        <ArrowLeft className="h-3 w-3" /> Back to Skills
      </Button>

      {error && <div className="text-sm text-destructive">{error}</div>}
      {!detail && !error && (
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" /> Loading skill…
        </div>
      )}

      {detail && editing && (
        <SkillForm
          initial={{ ...parseSkillDefinition(detail), name: parseSkillDefinition(detail).name }}
          submitLabel="Save Changes"
          onSubmit={handleUpdate}
          onCancel={() => setEditing(false)}
        />
      )}

      {detail && !editing && (
        <>
          <div className="flex items-center gap-3 flex-wrap">
            <Puzzle className="h-6 w-6 text-muted-foreground" aria-hidden />
            <h1 className="text-2xl font-semibold">{detail.name}</h1>
            <RegistryStatusBadge status={detail.status} />
            {canWrite && (
              <div className="ml-auto flex items-center gap-2">
                <Button size="sm" variant="outline" onClick={() => setEditing(true)} className="gap-1.5">
                  <Pencil className="h-3 w-3" /> Edit
                </Button>
                <Button size="sm" variant="outline" disabled={deleting} onClick={() => void handleDelete()} className="gap-1.5 text-destructive hover:text-destructive">
                  {deleting ? <Loader2 className="h-3 w-3 animate-spin" /> : <Trash2 className="h-3 w-3" />} Delete
                </Button>
              </div>
            )}
          </div>

          <Card>
            <CardContent className="p-4">
              <div className="text-xs font-semibold uppercase tracking-wide text-muted-foreground mb-2">Description</div>
              <div className="prose prose-sm dark:prose-invert max-w-none text-sm">
                <ReactMarkdown>{detail.description ?? "No description."}</ReactMarkdown>
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardContent className="p-4">
              <div className="text-xs font-semibold uppercase tracking-wide text-muted-foreground mb-1">Record metadata</div>
              <MetaRow label="Record ID"><code className="text-[10px]">{detail.record_id}</code></MetaRow>
              {detail.record_version && <MetaRow label="Record version">{detail.record_version}</MetaRow>}
              {detail.status_reason && <MetaRow label="Status reason">{detail.status_reason}</MetaRow>}
              {links.repositoryUrl && <MetaRow label="Repository"><ExternalLinkRow url={links.repositoryUrl} /></MetaRow>}
              {links.websiteUrl && <MetaRow label="Website"><ExternalLinkRow url={links.websiteUrl} /></MetaRow>}
              {detail.created_at && <MetaRow label="Created">{formatTimestamp(detail.created_at, timezone)}</MetaRow>}
              {detail.updated_at && <MetaRow label="Updated">{formatTimestamp(detail.updated_at, timezone)}</MetaRow>}
            </CardContent>
          </Card>
        </>
      )}
    </div>
  );
}

interface SkillsPageProps {
  initialSelectedId?: string | null;
}

export function SkillsPage({ initialSelectedId }: SkillsPageProps) {
  const { timezone } = useTimezone();
  const { user, hasScope } = useAuth();
  const canWrite = hasScope("registry:write");
  const [registryEnabled, setRegistryEnabled] = useState<boolean | null>(null);
  const [skills, setSkills] = useState<RegistryRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(initialSelectedId ?? null);
  const [creating, setCreating] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const config = await getRegistryConfig();
      setRegistryEnabled(config.enabled);
      if (!config.enabled) {
        setSkills([]);
        return;
      }
      const records = await listRegistryRecords({ descriptorType: "SKILL" });
      setSkills([...records].sort((a, b) => a.name.localeCompare(b.name)));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load skills from the registry");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  const handleCreate = async (values: SkillFormValues) => {
    try {
      await createRegistryRecord({
        resource_type: "skill",
        skill_name: values.name,
        skill_description: values.description,
        skill_license: values.license,
        skill_version: values.version,
        skill_md: values.skillMd,
      });
      toast.success("Skill created");
      setCreating(false);
      void load();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Failed to create skill");
    }
  };

  if (selectedId) {
    return (
      <SkillDetail
        recordId={selectedId}
        canWrite={canWrite}
        onBack={() => setSelectedId(null)}
        onDeleted={() => { setSelectedId(null); void load(); }}
      />
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex items-start justify-between">
        <div>
          <h2 className="text-2xl font-semibold">Skills</h2>
          <p className="text-sm text-muted-foreground">
            Reusable agent capabilities published to the Agent Registry.
          </p>
        </div>
        <div className="flex items-center gap-2">
          {canWrite && registryEnabled && !creating && (
            <Button size="sm" onClick={() => setCreating(true)} className="gap-1.5">
              <Plus className="h-3 w-3" /> New Skill
            </Button>
          )}
          <Button variant="outline" size="sm" onClick={() => void load()} className="gap-1.5">
            <RefreshCw className={`h-3 w-3 ${loading ? "animate-spin" : ""}`} /> Refresh
          </Button>
        </div>
      </div>

      {creating && (
        <SkillForm
          initial={{ ...EMPTY_SKILL_FORM }}
          submitLabel="Create Skill"
          onSubmit={handleCreate}
          onCancel={() => setCreating(false)}
        />
      )}

      {user && creating && (
        <p className="text-[11px] text-muted-foreground">
          Authored as <code>{user.username}</code>.
        </p>
      )}

      {loading && (
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
          {Array.from({ length: 3 }).map((_, i) => (
            <Skeleton key={i} className="h-32" />
          ))}
        </div>
      )}
      {error && <div className="text-sm text-destructive">{error}</div>}

      {!loading && !error && registryEnabled === false && (
        <Card>
          <CardContent className="py-12">
            <div className="flex flex-col items-center gap-3 text-center">
              <Puzzle className="h-8 w-8 text-muted-foreground/40" aria-hidden />
              <div className="text-sm font-medium">Agent Registry not configured</div>
              <p className="max-w-md text-xs text-muted-foreground">
                Skills are served from the AWS Agent Registry. Configure a registry ARN in
                Settings to browse the skills published to it.
              </p>
            </div>
          </CardContent>
        </Card>
      )}

      {!loading && !error && registryEnabled === true && skills.length === 0 && !creating && (
        <Card>
          <CardContent className="py-12">
            <div className="flex flex-col items-center gap-3 text-center">
              <Puzzle className="h-8 w-8 text-muted-foreground/40" aria-hidden />
              <div className="text-sm font-medium">No skills in the registry</div>
              <p className="max-w-md text-xs text-muted-foreground">
                {canWrite
                  ? "Create one above, or SKILL records published elsewhere will appear here."
                  : "SKILL records published to the bound Agent Registry will appear here."}
              </p>
            </div>
          </CardContent>
        </Card>
      )}

      {!loading && !error && skills.length > 0 && (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
          {skills.map((s) => (
            <Card
              key={s.record_id}
              role="button"
              tabIndex={0}
              aria-label={`Open skill ${s.name}`}
              onClick={() => setSelectedId(s.record_id)}
              onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); setSelectedId(s.record_id); } }}
              className="cursor-pointer transition-colors hover:bg-accent/50 focus-visible:ring-2 focus-visible:ring-primary outline-none"
            >
              <CardContent className="p-4 space-y-2">
                <div className="flex items-center justify-between gap-2">
                  <div className="flex items-center gap-2 min-w-0">
                    <Puzzle className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden />
                    <span className="text-sm font-semibold truncate">{s.name}</span>
                  </div>
                  <RegistryStatusBadge status={s.status} />
                </div>
                {s.updated_at && (
                  <span className="text-[10px] text-muted-foreground">
                    updated {formatTimestamp(s.updated_at, timezone)}
                  </span>
                )}
                <p className="text-xs text-muted-foreground line-clamp-4">
                  {s.description ?? "No description."}
                </p>
              </CardContent>
            </Card>
          ))}
        </div>
      )}

      {!loading && skills.length > 0 && (
        <p className="text-[11px] text-muted-foreground">
          Served live from the bound Agent Registry ({skills.length} SKILL record{skills.length === 1 ? "" : "s"}).
        </p>
      )}
    </div>
  );
}
