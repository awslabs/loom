import { useState, useEffect, useCallback } from "react";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { toast } from "sonner";
import { getAgentSkills } from "@/api/a2a";
import type { A2aAgentSkill } from "@/api/types";

interface A2aSkillListProps {
  agentId: number;
}

function SkillRow({ skill }: { skill: A2aAgentSkill }) {
  const [expanded, setExpanded] = useState(false);
  const hasExtra = skill.tags.length > 0 || (skill.examples?.length ?? 0) > 0 || (skill.input_modes?.length ?? 0) > 0 || (skill.output_modes?.length ?? 0) > 0;

  return (
    <div className="grid grid-cols-[190px_minmax(0,1fr)] gap-4 border-b px-4 py-3 last:border-b-0" style={{ alignItems: "baseline" }}>
      <button
        type="button"
        onClick={() => hasExtra && setExpanded((v) => !v)}
        className={`flex flex-wrap items-center gap-1.5 text-left font-mono text-[12.5px] font-semibold ${hasExtra ? "cursor-pointer hover:text-primary" : "cursor-default"}`}
      >
        <span>{skill.name}</span>
        {skill.tags.slice(0, 1).map((tag) => (
          <span key={tag} className="rounded border bg-muted px-1 py-px font-mono text-[9px] uppercase tracking-wide text-muted-foreground">
            {tag}
          </span>
        ))}
      </button>
      <div className="flex flex-col gap-2 text-[13px] leading-[1.55] text-muted-foreground">
        <span>{skill.description || "—"}</span>
        {expanded && (
          <div className="flex flex-col gap-1.5 text-[11px]">
            <span className="text-muted-foreground/70">ID: {skill.skill_id}</span>
            {skill.tags.length > 1 && (
              <div className="flex flex-wrap items-center gap-1">
                {skill.tags.map((tag) => (
                  <span key={tag} className="rounded border bg-muted px-1.5 py-0.5 font-mono text-[9.5px] uppercase tracking-wide text-muted-foreground">
                    {tag}
                  </span>
                ))}
              </div>
            )}
            {skill.examples && skill.examples.length > 0 && (
              <div>
                <span className="text-muted-foreground/70">Examples:</span>
                <ul className="list-disc list-inside mt-0.5">
                  {skill.examples.map((ex, i) => (
                    <li key={i}>{ex}</li>
                  ))}
                </ul>
              </div>
            )}
            {skill.input_modes && skill.input_modes.length > 0 && (
              <div className="flex flex-wrap items-center gap-1">
                <span className="text-muted-foreground/70">Input:</span>
                <span className="font-mono">{skill.input_modes.join(", ")}</span>
              </div>
            )}
            {skill.output_modes && skill.output_modes.length > 0 && (
              <div className="flex flex-wrap items-center gap-1">
                <span className="text-muted-foreground/70">Output:</span>
                <span className="font-mono">{skill.output_modes.join(", ")}</span>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

export function A2aSkillList({ agentId }: A2aSkillListProps) {
  const [skills, setSkills] = useState<A2aAgentSkill[]>([]);
  const [loading, setLoading] = useState(true);

  const fetchSkills = useCallback(async () => {
    try {
      const data = await getAgentSkills(agentId);
      setSkills(data);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Failed to fetch skills");
    } finally {
      setLoading(false);
    }
  }, [agentId]);

  useEffect(() => {
    void fetchSkills();
  }, [fetchSkills]);

  if (loading) {
    return (
      <div className="space-y-2">
        {Array.from({ length: 2 }).map((_, i) => (
          <Skeleton key={i} className="h-10" />
        ))}
      </div>
    );
  }

  return (
    <Card className="gap-0 py-0">
      <div className="flex items-center gap-2.5 border-b px-[18px] py-3.5">
        <span className="text-[13.5px] font-semibold">Skills</span>
        <span className="rounded-md border bg-muted px-1.5 py-0.5 font-mono text-[10px] text-muted-foreground">{skills.length}</span>
      </div>
      {skills.length === 0 ? (
        <div className="px-[18px] py-6 text-sm text-muted-foreground">No skills defined in the Agent Card.</div>
      ) : (
        <div className="flex flex-col">
          {skills.map((skill) => (
            <SkillRow key={skill.id} skill={skill} />
          ))}
        </div>
      )}
    </Card>
  );
}
