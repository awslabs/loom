import { apiFetch } from "./client";
import type { KillSwitchActionResponse, KillSwitchStatus } from "./types";

/** The agent's kill-switch state: Loom's record, the runtime policy's live state, the audit trail. */
export function getKillSwitchStatus(agentId: number): Promise<KillSwitchStatus> {
  return apiFetch<KillSwitchStatus>(`/api/agents/${agentId}/kill-switch`);
}

/** Stop the agent: deny every invocation in its runtime's resource policy and end its sessions. */
export function stopAgent(agentId: number, reason: string): Promise<KillSwitchActionResponse> {
  return apiFetch<KillSwitchActionResponse>(`/api/agents/${agentId}/stop`, {
    method: "POST",
    body: JSON.stringify({ reason }),
  });
}

/** Resume the agent: remove Loom's deny statement. Nothing is redeployed. */
export function resumeAgent(agentId: number, reason: string): Promise<KillSwitchActionResponse> {
  return apiFetch<KillSwitchActionResponse>(`/api/agents/${agentId}/resume`, {
    method: "POST",
    body: JSON.stringify({ reason }),
  });
}
