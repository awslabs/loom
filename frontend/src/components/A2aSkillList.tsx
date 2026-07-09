import { useState, useEffect, useCallback } from "react";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { ChevronRight, ChevronDown } from "lucide-react";
import { toast } from "sonner";
import { getAgentSkills } from "@/api/a2a";
import type { A2aAgentSkill } from "@/api/types";

interface A2aSkillListProps {
  agentId: number;
}

function SkillRow({ skill }: { skill: A2aAgentSkill }) {
  const [expanded, setExpanded] = useState(false);

  return (
    <div className="rounded border bg-input-bg px-3 py-2">
      <button
        type="button"
        onClick={() => setExpanded(!expanded)}
        className="flex items-center gap-1.5 text-left w-full"
      >
        {expanded ? (
          <ChevronDown className="h-3 w-3 shrink-0 text-muted-foreground" />
        ) : (
          <ChevronRight className="h-3 w-3 shrink-0 text-muted-foreground" />
        )}
        <span className="text-sm font-medium">{skill.name}</span>
        {skill.description && (
          <span className="text-xs text-muted-foreground truncate"> — {skill.description}</span>
        )}
      </button>
      {expanded && (
        <div className="mt-2 pl-[22px] space-y-1.5 text-xs text-muted-foreground">
          <div className="text-[10px] text-muted-foreground/70">ID: {skill.skill_id}</div>
          {skill.tags.length > 0 && (
            <div className="flex flex-wrap gap-1">
              {skill.tags.map((tag) => (
                <Badge key={tag} variant="outline" className="text-[10px] px-1.5 py-0 font-normal">
                  {tag}
                </Badge>
              ))}
            </div>
          )}
          {skill.examples && skill.examples.length > 0 && (
            <div>
              <span className="text-[10px] font-medium text-muted-foreground/70">Examples:</span>
              <ul className="list-disc list-inside text-[11px] mt-0.5">
                {skill.examples.map((ex, i) => (
                  <li key={i}>{ex}</li>
                ))}
              </ul>
            </div>
          )}
          {skill.input_modes && skill.input_modes.length > 0 && (
            <div className="flex flex-wrap items-center gap-1">
              <span className="text-[10px] text-muted-foreground/70">Input:</span>
              {skill.input_modes.map((m) => (
                <Badge key={m} variant="outline" className="text-[10px] px-1 py-0 font-normal">
                  {m}
                </Badge>
              ))}
            </div>
          )}
          {skill.output_modes && skill.output_modes.length > 0 && (
            <div className="flex flex-wrap items-center gap-1">
              <span className="text-[10px] text-muted-foreground/70">Output:</span>
              {skill.output_modes.map((m) => (
                <Badge key={m} variant="outline" className="text-[10px] px-1 py-0 font-normal">
                  {m}
                </Badge>
              ))}
            </div>
          )}
        </div>
      )}
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
    <div className="space-y-2">
      <h4 className="text-xs font-medium text-muted-foreground">Skills ({skills.length})</h4>
      {skills.length === 0 ? (
        <p className="text-xs text-muted-foreground/50 py-2">No skills defined in the Agent Card.</p>
      ) : (
        <div className="grid gap-2 grid-cols-1">
          {skills.map((skill) => (
            <SkillRow key={skill.id} skill={skill} />
          ))}
        </div>
      )}
    </div>
  );
}
