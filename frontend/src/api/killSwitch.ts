import { apiFetch } from "./client";
import type { KillSwitchActionResponse, KillSwitchStatus } from "./types";

/** The agent's kill-switch state: Loom's record, the role's live state, the audit trail. */
export function getKillSwitchStatus(agentId: number): Promise<KillSwitchStatus> {
  return apiFetch<KillSwitchStatus>(`/api/agents/${agentId}/kill-switch`);
}

/** Stop the agent: deny its execution role everything but telemetry and stop its sessions. */
export function stopAgent(
  agentId: number,
  reason: string,
  acknowledgeSharedRole = false,
): Promise<KillSwitchActionResponse> {
  return apiFetch<KillSwitchActionResponse>(`/api/agents/${agentId}/stop`, {
    method: "POST",
    body: JSON.stringify({ reason, acknowledge_shared_role: acknowledgeSharedRole }),
  });
}

/** Resume the agent: detach the deny policy. Nothing is redeployed. */
export function resumeAgent(
  agentId: number,
  reason: string,
  acknowledgeSharedRole = false,
): Promise<KillSwitchActionResponse> {
  return apiFetch<KillSwitchActionResponse>(`/api/agents/${agentId}/resume`, {
    method: "POST",
    body: JSON.stringify({ reason, acknowledge_shared_role: acknowledgeSharedRole }),
  });
}
