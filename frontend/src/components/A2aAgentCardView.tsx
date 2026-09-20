import { Card, CardContent } from "@/components/ui/card";
import { CopyField } from "@/components/CopyField";
import { useTimezone } from "@/contexts/TimezoneContext";
import { formatTimestamp } from "@/lib/format";
import type { A2aAgent } from "@/api/types";

interface A2aAgentCardViewProps {
  agent: A2aAgent;
}

/** Right-rail summary of the fetched A2A Agent Card — facts only, no page-level chrome (name/description/refresh live in the detail header). */
export function A2aAgentCardView({ agent }: A2aAgentCardViewProps) {
  const { timezone } = useTimezone();
  const authLabel = agent.authentication_schemes.length > 0
    ? agent.authentication_schemes.join(", ")
    : agent.auth_type === "oauth2" ? "OAuth2" : "None";

  return (
    <Card className="gap-3.5 py-4">
      <CardContent className="flex flex-col gap-3.5">
        <span className="text-[13px] font-semibold">Agent card</span>
        <CopyField label="URL" value={agent.base_url} />
        <div className="flex items-center justify-between gap-2.5">
          <span className="font-mono text-[9.5px] tracking-wide text-muted-foreground uppercase">Protocol</span>
          <span className="font-mono text-xs">A2A v{agent.agent_version}</span>
        </div>
        <div className="flex items-center justify-between gap-2.5">
          <span className="font-mono text-[9.5px] tracking-wide text-muted-foreground uppercase">Auth</span>
          <span className="truncate font-mono text-xs">{authLabel}</span>
        </div>
        <div className="flex items-center justify-between gap-2.5">
          <span className="font-mono text-[9.5px] tracking-wide text-muted-foreground uppercase">Streaming</span>
          <span className="font-mono text-xs">{agent.capabilities.streaming ? "Supported" : "Not supported"}</span>
        </div>
        {agent.default_input_modes.length > 0 && (
          <div className="flex items-center justify-between gap-2.5">
            <span className="font-mono text-[9.5px] tracking-wide text-muted-foreground uppercase">Input modes</span>
            <span className="truncate font-mono text-xs">{agent.default_input_modes.join(", ")}</span>
          </div>
        )}
        {agent.default_output_modes.length > 0 && (
          <div className="flex items-center justify-between gap-2.5">
            <span className="font-mono text-[9.5px] tracking-wide text-muted-foreground uppercase">Output modes</span>
            <span className="truncate font-mono text-xs">{agent.default_output_modes.join(", ")}</span>
          </div>
        )}
        {agent.provider_organization && (
          <div className="flex items-center justify-between gap-2.5">
            <span className="font-mono text-[9.5px] tracking-wide text-muted-foreground uppercase">Provider</span>
            <span className="truncate font-mono text-xs">{agent.provider_organization}</span>
          </div>
        )}
        <div className="h-px bg-border" />
        <div className="flex items-center gap-1.5 font-mono text-[10.5px] text-muted-foreground">
          <span className={`h-1.5 w-1.5 shrink-0 rounded-full ${agent.last_fetched_at ? "bg-success" : "bg-status-neutral"}`} />
          {agent.last_fetched_at ? `card fetched ${formatTimestamp(agent.last_fetched_at, timezone)}` : "not fetched yet"}
        </div>
      </CardContent>
    </Card>
  );
}
