import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useTimezone } from "@/contexts/TimezoneContext";
import { formatUnixTime, formatMs } from "@/lib/format";
import type { SSESessionEnd } from "@/api/types";

interface LatencySummaryProps {
  sessionEnd: SSESessionEnd | null;
}

function MetricCell({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className="font-mono text-sm">{value}</div>
    </div>
  );
}

function formatTokens(count: number | null | undefined): string {
  if (count == null) return "—";
  if (count >= 1000) return `${(count / 1000).toFixed(1)}K`;
  return String(count);
}

function formatCost(cost: number | null | undefined): string {
  if (cost == null) return "—";
  if (cost < 0.01) return `~$${cost.toFixed(6)}`;
  return `~$${cost.toFixed(4)}`;
}

export function LatencySummary({ sessionEnd }: LatencySummaryProps) {
  const { timezone } = useTimezone();

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-sm font-medium">Invocation Metrics</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="grid grid-cols-3 md:grid-cols-7 gap-4">
          <MetricCell
            label="Client Invoke"
            value={formatUnixTime(sessionEnd?.client_invoke_time ?? null, timezone)}
          />
          <MetricCell
            label="Agent Start"
            value={formatUnixTime(sessionEnd?.agent_start_time ?? null, timezone)}
          />
          <MetricCell
            label="Cold Start"
            value={formatMs(sessionEnd?.cold_start_latency_ms ?? null)}
          />
          <MetricCell
            label="Duration"
            value={formatMs(sessionEnd?.client_duration_ms ?? null)}
          />
          <MetricCell
            label="Input Tokens"
            value={formatTokens(sessionEnd?.input_tokens)}
          />
          <MetricCell
            label="Output Tokens"
            value={formatTokens(sessionEnd?.output_tokens)}
          />
          <MetricCell
            label="Model Cost"
            value={formatCost(sessionEnd?.estimated_cost)}
          />
        </div>
      </CardContent>
    </Card>
  );
}
