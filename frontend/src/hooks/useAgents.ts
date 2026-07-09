import { useState, useEffect, useCallback, useRef } from "react";
import type { AgentResponse, AgentDeployRequest, AgentHarnessDeployRequest } from "@/api/types";
import * as agentsApi from "@/api/agents";
import { ApiError } from "@/api/client";
import { toast } from "sonner";

const POLL_INTERVAL_MS = 2000;

const DEPLOY_IN_PROGRESS = new Set([
  "initializing",
  "creating_credentials",
  "creating_role",
  "building_artifact",
  "deploying",
  "updating",
  "ENDPOINT_CREATING",
]);

function needsPolling(agent: AgentResponse): boolean {
  return (
    agent.status === "DELETING" ||
    (agent.source === "deploy" &&
      (agent.status === "CREATING" || agent.status === "UPDATING" ||
        DEPLOY_IN_PROGRESS.has(agent.deployment_status ?? "") ||
        agent.endpoint_status === "CREATING")) ||
    (agent.source === "harness" &&
      (agent.status === "CREATING" || agent.status === "UPDATING" ||
        DEPLOY_IN_PROGRESS.has(agent.deployment_status ?? "")))
  );
}

export function useAgents() {
  const [agents, setAgents] = useState<AgentResponse[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [deleteStartTimes, setDeleteStartTimes] = useState<Record<number, number>>({});
  const [updateStartTimes, setUpdateStartTimes] = useState<Record<number, number>>({});
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const initialLoadDone = useRef(false);

  const fetchAgents = useCallback(async () => {
    if (!initialLoadDone.current) {
      setLoading(true);
    }
    setError(null);
    try {
      const data = await agentsApi.listAgents();
      setAgents(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to fetch agents");
    } finally {
      setLoading(false);
      initialLoadDone.current = true;
    }
  }, []);

  // Status polling for agents that are creating or deleting
  const agentsRef = useRef(agents);
  agentsRef.current = agents;

  const watchIds = agents
    .filter(needsPolling)
    .map((a) => a.id)
    .sort()
    .join(",");

  useEffect(() => {
    if (!watchIds) {
      if (pollRef.current) {
        clearInterval(pollRef.current);
        pollRef.current = null;
      }
      return;
    }

    if (pollRef.current) {
      clearInterval(pollRef.current);
    }

    pollRef.current = setInterval(async () => {
      const toWatch = agentsRef.current.filter(needsPolling);
      if (toWatch.length === 0) {
        if (pollRef.current) {
          clearInterval(pollRef.current);
          pollRef.current = null;
        }
        return;
      }

      for (const agent of toWatch) {
        try {
          const updated = await agentsApi.fetchAgentStatus(agent.id);
          setAgents((prev) =>
            prev.map((a) => (a.id === updated.id ? updated : a)),
          );
          // Clear update start time once the agent leaves UPDATING
          if (agent.status === "UPDATING" && updated.status !== "UPDATING") {
            setUpdateStartTimes((prev) => {
              const next = { ...prev };
              delete next[agent.id];
              return next;
            });
          }
        } catch (e) {
          // If a DELETING agent returns 404, it's gone from AWS — purge locally
          if (agent.status === "DELETING" && e instanceof ApiError && e.status === 404) {
            try {
              await agentsApi.purgeAgent(agent.id);
            } catch {
              // ignore cleanup errors
            }
            setAgents((prev) => prev.filter((a) => a.id !== agent.id));
            setDeleteStartTimes((prev) => {
              const next = { ...prev };
              delete next[agent.id];
              return next;
            });
            toast.success("Agent deleted");
          }
        }
      }
    }, POLL_INTERVAL_MS);

    return () => {
      if (pollRef.current) {
        clearInterval(pollRef.current);
        pollRef.current = null;
      }
    };
  }, [watchIds]);

  const registerAgent = useCallback(
    async (arn: string, modelId?: string) => {
      const agent = await agentsApi.registerAgent({ source: "register", arn, model_id: modelId });
      await fetchAgents();
      return agent;
    },
    [fetchAgents],
  );

  const deployAgent = useCallback(
    async (request: AgentDeployRequest, existingAgentId?: number) => {
      const agent = existingAgentId
        ? await agentsApi.updateDeployAgent(existingAgentId, request)
        : await agentsApi.deployAgent(request);
      if (existingAgentId) {
        setUpdateStartTimes((prev) => ({ ...prev, [existingAgentId]: Date.now() }));
      }
      await fetchAgents();
      return agent;
    },
    [fetchAgents],
  );

  const deployHarnessAgent = useCallback(
    async (request: AgentHarnessDeployRequest, existingAgentId?: number) => {
      const agent = existingAgentId
        ? await agentsApi.updateHarnessAgent(existingAgentId, request)
        : await agentsApi.deployHarnessAgent(request);
      if (existingAgentId) {
        setUpdateStartTimes((prev) => ({ ...prev, [existingAgentId]: Date.now() }));
      }
      await fetchAgents();
      return agent;
    },
    [fetchAgents],
  );

  const redeployAgent = useCallback(
    async (id: number) => {
      const agent = await agentsApi.redeployAgent(id);
      await fetchAgents();
      return agent;
    },
    [fetchAgents],
  );

  const refreshAgent = useCallback(
    async (id: number) => {
      const agent = await agentsApi.refreshAgent(id);
      await fetchAgents();
      return agent;
    },
    [fetchAgents],
  );

  const patchAgent = useCallback(
    async (id: number, updates: { description?: string | null }) => {
      const agent = await agentsApi.patchAgent(id, updates);
      setAgents((prev) => prev.map((a) => (a.id === id ? agent : a)));
      return agent;
    },
    [],
  );

  const deleteAgent = useCallback(
    async (id: number, cleanupAws: boolean = false) => {
      const updated = await agentsApi.deleteAgent(id, cleanupAws);
      if (updated.status === "DELETING") {
        // Async deletion — update local state so polling picks it up
        setDeleteStartTimes((prev) => ({ ...prev, [id]: Date.now() }));
        setAgents((prev) => prev.map((a) => (a.id === id ? updated : a)));
        toast.success("Agent deletion initiated");
      } else {
        // Immediately removed (local-only or no runtime)
        setAgents((prev) => prev.filter((a) => a.id !== id));
        toast.success(cleanupAws ? "Agent deleted" : "Agent removed from Loom");
      }
    },
    [],
  );

  return { agents, loading, error, deleteStartTimes, updateStartTimes, fetchAgents, registerAgent, deployAgent, deployHarnessAgent, redeployAgent, refreshAgent, patchAgent, deleteAgent };
}
