import { useState, useEffect, useCallback } from "react";
import type { A2aAgent, A2aAgentCreateRequest, A2aAgentUpdateRequest } from "@/api/types";
import * as a2aApi from "@/api/a2a";
import { toast } from "sonner";

export function useA2aAgents() {
  const [agents, setAgents] = useState<A2aAgent[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchAgents = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await a2aApi.listA2aAgents();
      setAgents(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to fetch A2A agents");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void fetchAgents();
  }, [fetchAgents]);

  const createAgent = useCallback(
    async (request: A2aAgentCreateRequest) => {
      const agent = await a2aApi.createA2aAgent(request);
      await fetchAgents();
      toast.success("A2A agent registered");
      return agent;
    },
    [fetchAgents],
  );

  const updateAgent = useCallback(
    async (id: number, request: A2aAgentUpdateRequest) => {
      const agent = await a2aApi.updateA2aAgent(id, request);
      await fetchAgents();
      toast.success("A2A agent updated");
      return agent;
    },
    [fetchAgents],
  );

  const deleteAgent = useCallback(
    async (id: number) => {
      await a2aApi.deleteA2aAgent(id);
      setAgents((prev) => prev.filter((a) => a.id !== id));
      toast.success("A2A agent deleted");
    },
    [],
  );

  const refreshCard = useCallback(
    async (id: number) => {
      const agent = await a2aApi.refreshAgentCard(id);
      setAgents((prev) => prev.map((a) => (a.id === id ? agent : a)));
      toast.success("Agent Card refreshed");
      return agent;
    },
    [],
  );

  return { agents, loading, error, fetchAgents, createAgent, updateAgent, deleteAgent, refreshCard };
}
