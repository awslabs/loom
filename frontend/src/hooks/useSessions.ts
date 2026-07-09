import { useState, useEffect, useCallback } from "react";
import type { SessionResponse } from "@/api/types";
import { listSessions } from "@/api/invocations";

export function useSessions(agentId: number | null) {
  const [sessions, setSessions] = useState<SessionResponse[]>([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (agentId === null) {
      setSessions([]);
      setLoading(false);
      return;
    }
    let cancelled = false;
    setSessions([]);
    setLoading(true);
    listSessions(agentId)
      .then((data) => { if (!cancelled) setSessions(data); })
      .catch(() => { if (!cancelled) setSessions([]); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [agentId]);

  const refetch = useCallback(async () => {
    if (agentId === null) return;
    setLoading(true);
    try {
      const data = await listSessions(agentId);
      setSessions(data);
    } catch {
      setSessions([]);
    } finally {
      setLoading(false);
    }
  }, [agentId]);

  return { sessions, loading, refetch };
}
