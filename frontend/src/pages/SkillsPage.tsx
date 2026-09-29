import { useCallback, useEffect, useState } from "react";
import { ArrowLeft, ExternalLink, Loader2, Puzzle, RefreshCw } from "lucide-react";
import ReactMarkdown from "react-markdown";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { RegistryStatusBadge } from "@/components/RegistryStatusBadge";
import { useTimezone } from "@/contexts/TimezoneContext";
import { formatTimestamp } from "@/lib/format";
import { listRegistryRecords, getRegistryRecord } from "@/api/registry";
import { getRegistryConfig } from "@/api/settings";
import type { RegistryRecord, RegistryRecordDetail } from "@/api/types";

/** Agent Skills surface: the SKILL-typed records of the bound Agent Registry.
 *
 * Skills are the reuse unit of the registry — an agent is someone's
 * application, a skill is a capability another team can adopt. This page is a
 * read-only view served live from the bound AWS Agent Registry; record
 * lifecycle (submit, approve, reject) stays with the registry admin flows.
 */

interface SkillLinks {
  repositoryUrl?: string;
  websiteUrl?: string;
}

/** Pull the optional repository/website links out of the SKILL descriptor.
 * The `agentSkillsDefinition` descriptor carries a JSON `data` payload whose
 * schema belongs to the publisher, so parse defensively and surface only the
 * two well-known link fields. */
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

function SkillDetail({ recordId, onBack }: { recordId: string; onBack: () => void }) {
  const { timezone } = useTimezone();
  const [detail, setDetail] = useState<RegistryRecordDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getRegistryRecord(recordId)
      .then(setDetail)
      .catch((e) => setError(e instanceof Error ? e.message : "Failed to load skill detail"));
  }, [recordId]);

  const links = detail ? parseSkillLinks(detail) : {};

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

      {detail && (
        <>
          <div className="flex items-center gap-3 flex-wrap">
            <Puzzle className="h-6 w-6 text-muted-foreground" aria-hidden />
            <h1 className="text-2xl font-semibold">{detail.name}</h1>
            <RegistryStatusBadge status={detail.status} />
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
  const [registryEnabled, setRegistryEnabled] = useState<boolean | null>(null);
  const [skills, setSkills] = useState<RegistryRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(initialSelectedId ?? null);

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

  if (selectedId) {
    return <SkillDetail recordId={selectedId} onBack={() => setSelectedId(null)} />;
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
        <Button variant="outline" size="sm" onClick={() => void load()} className="gap-1.5">
          <RefreshCw className={`h-3 w-3 ${loading ? "animate-spin" : ""}`} /> Refresh
        </Button>
      </div>

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

      {!loading && !error && registryEnabled === true && skills.length === 0 && (
        <Card>
          <CardContent className="py-12">
            <div className="flex flex-col items-center gap-3 text-center">
              <Puzzle className="h-8 w-8 text-muted-foreground/40" aria-hidden />
              <div className="text-sm font-medium">No skills in the registry</div>
              <p className="max-w-md text-xs text-muted-foreground">
                SKILL records published to the bound Agent Registry will appear here.
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
