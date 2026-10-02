import { useMemo, useState } from "react";
import { Check, Loader2, TriangleAlert } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { SkillDocument } from "@/components/SkillDocument";
import { buildSkillMd, parseSkillMd, suggestNextVersion } from "@/lib/skillMd";
import type { SkillFrontmatter } from "@/lib/skillMd";

const DESCRIPTION_MAX = 1024;

export interface SkillEditorValues {
  name: string;
  description: string;
  license: string;
  author: string;
  version: string;
  /** SKILL.md body — frontmatter is generated separately from the fields
   * above and is never part of this value, so the two can't disagree. */
  body: string;
}

interface SkillEditorProps {
  mode: "create" | "edit";
  initial: SkillEditorValues;
  /** Agents currently attached to this skill (edit mode only) — surfaced as
   * a "won't auto-update" check, since there's no version pinning in this
   * registry, every dependent picks up whatever's APPROVED on next redeploy. */
  dependentCount?: number;
  onSubmit: (values: SkillEditorValues) => Promise<void>;
  onCancel: () => void;
}

function CheckRow({ ok, label }: { ok: boolean; label: string }) {
  return (
    <div className="flex items-center gap-2 text-xs">
      {ok ? <Check className="h-3 w-3 text-success shrink-0" /> : <TriangleAlert className="h-3 w-3 text-warning shrink-0" />}
      <span className={ok ? "text-foreground" : "text-warning"}>{label}</span>
    </div>
  );
}

/** Create/edit surface for a skill: frontmatter fields (which generate the
 * YAML block — the user only ever edits the body), a live preview rendered
 * with the same component the detail page uses, and a short list of
 * pre-publish checks. Mirrors the Claude Design "Skills" editor mockup,
 * scoped to what a plain <textarea> + live preview can do — no code-editor
 * dependency (line numbers/diff-vs-published) was added for this. */
export function SkillEditor({ mode, initial, dependentCount = 0, onSubmit, onCancel }: SkillEditorProps) {
  const [name, setName] = useState(initial.name);
  const [description, setDescription] = useState(initial.description);
  const [license, setLicense] = useState(initial.license);
  const [version, setVersion] = useState(mode === "edit" ? suggestNextVersion(initial.version) : initial.version);
  const [body, setBody] = useState(() => parseSkillMd(initial.body).body || initial.body);
  const [submitting, setSubmitting] = useState(false);

  const hasWhenToApply = /##\s+when to apply/i.test(body);
  const checks = [
    { ok: true, label: "Frontmatter parses (generated from the fields, always valid)" },
    { ok: description.trim().length > 0, label: "Description present" },
    { ok: hasWhenToApply, label: 'Has a "When to Apply" section' },
    ...(mode === "edit" && dependentCount > 0
      ? [{ ok: false, label: `${dependentCount} agent${dependentCount === 1 ? "" : "s"} will pick this up on next redeploy` }]
      : []),
  ];

  const canSubmit = name.trim() && description.trim() && license.trim() && version.trim() && body.trim() && !submitting;

  const previewFrontmatter: SkillFrontmatter = { name, description, license, author: initial.author, version };
  const previewMd = useMemo(() => buildSkillMd(previewFrontmatter, body), [previewFrontmatter, body]);

  const handleSubmit = async () => {
    setSubmitting(true);
    try {
      await onSubmit({ name, description, license, author: initial.author, version, body: previewMd });
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center justify-end gap-2">
        <Button size="sm" variant="outline" disabled={submitting} onClick={onCancel}>Cancel</Button>
        <Button size="sm" disabled={!canSubmit} onClick={() => void handleSubmit()} className="gap-1.5">
          {submitting && <Loader2 className="h-3 w-3 animate-spin" />}
          {mode === "create" ? "Create Skill" : `Publish v${version}`}
        </Button>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-[280px_minmax(0,1fr)_minmax(0,1fr)] gap-0 border rounded-lg overflow-hidden">
        {/* frontmatter fields */}
        <div className="flex flex-col gap-4 p-4 bg-muted/30 border-b lg:border-b-0 lg:border-r">
          <div className="text-[10px] font-mono uppercase tracking-wide text-muted-foreground">Frontmatter</div>

          <div className="space-y-1.5">
            <Label htmlFor="skill-editor-name" className="text-xs">Name</Label>
            <Input
              id="skill-editor-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              disabled={mode === "edit"}
              placeholder="e.g. security-scan"
              className="font-mono text-xs"
            />
            <div className="text-[11px] text-muted-foreground">
              {mode === "edit" ? "Immutable after creation." : "Lowercase, hyphens."}
            </div>
          </div>

          <div className="space-y-1.5">
            <div className="flex items-center gap-2">
              <Label htmlFor="skill-editor-description" className="text-xs">Description</Label>
              <span className="ml-auto text-[10px] font-mono text-muted-foreground tabular-nums">{description.length} / {DESCRIPTION_MAX}</span>
            </div>
            <Textarea
              id="skill-editor-description"
              value={description}
              onChange={(e) => setDescription(e.target.value.slice(0, DESCRIPTION_MAX))}
              rows={3}
              placeholder="What this skill does and when an agent should use it"
            />
            <div className="text-[11px] leading-snug text-muted-foreground">Agents read this to decide when to apply the skill.</div>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1.5">
              <Label htmlFor="skill-editor-version" className="text-xs">Version</Label>
              <Input id="skill-editor-version" value={version} onChange={(e) => setVersion(e.target.value)} className="font-mono text-xs" placeholder="1.0.0" />
              {mode === "edit" && initial.version && <div className="text-[10.5px] font-mono text-muted-foreground">was {initial.version}</div>}
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="skill-editor-license" className="text-xs">License</Label>
              <Input id="skill-editor-license" value={license} onChange={(e) => setLicense(e.target.value)} className="font-mono text-xs" placeholder="MIT" />
            </div>
          </div>

          <div className="space-y-1.5">
            <Label className="text-xs">Author</Label>
            <div className="flex items-center h-8 px-2.5 rounded-md border bg-muted font-mono text-xs text-muted-foreground">{initial.author}</div>
          </div>

          <div className="h-px bg-border" />

          <div className="flex flex-col gap-2">
            <div className="text-[10px] font-mono uppercase tracking-wide text-muted-foreground">Checks</div>
            {checks.map((c) => <CheckRow key={c.label} ok={c.ok} label={c.label} />)}
          </div>
        </div>

        {/* body source */}
        <div className="flex flex-col min-w-0 border-b lg:border-b-0 lg:border-r">
          <div className="flex items-center gap-2 px-3 py-2 border-b bg-muted/30 text-[10px] font-mono uppercase tracking-wide text-muted-foreground">
            SKILL.md body
            <span className="ml-auto font-sans text-muted-foreground/70 normal-case">{body.split("\n").length} lines</span>
          </div>
          <Textarea
            value={body}
            onChange={(e) => setBody(e.target.value)}
            rows={22}
            className="flex-1 rounded-none border-0 resize-none font-mono text-xs leading-relaxed focus-visible:ring-0"
            placeholder={"# Skill Title\n\nWhat this skill does.\n\n## When to Apply\n\n- ...\n\n## How It Works\n\n1. ...\n\n## Prerequisites\n\n- ..."}
          />
        </div>

        {/* preview */}
        <div className="flex flex-col min-w-0 bg-muted/10">
          <div className="flex items-center gap-2 px-3 py-2 border-b bg-muted/30 text-[10px] font-mono uppercase tracking-wide text-muted-foreground">
            Preview — as agents see it
          </div>
          <div className="flex-1 overflow-y-auto p-4">
            <div className="text-lg font-semibold mb-1">{name || "untitled-skill"}</div>
            <SkillDocument body={parseSkillMd(previewMd).body} />
          </div>
        </div>
      </div>
    </div>
  );
}
