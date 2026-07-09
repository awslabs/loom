import { useState, useCallback } from "react";
import { toast } from "sonner";
import type { TraceSummary, TraceDetailResponse } from "@/api/types";
import { getSessionTraces, getTraceDetail } from "@/api/traces";

export function useTraces() {
  const [traces, setTraces] = useState<TraceSummary[]>([]);
  const [tracesLoading, setTracesLoading] = useState(false);
  const [selectedTrace, setSelectedTrace] = useState<TraceDetailResponse | null>(null);
  const [traceDetailLoading, setTraceDetailLoading] = useState(false);

  const fetchSessionTraces = useCallback(
    async (agentId: number, sessionId: string) => {
      setTracesLoading(true);
      try {
        const data = await getSessionTraces(agentId, sessionId);
        setTraces(data.traces);
      } catch {
        setTraces([]);
      } finally {
        setTracesLoading(false);
      }
    },
    [],
  );

  const fetchTraceDetail = useCallback(
    async (agentId: number, traceId: string) => {
      setTraceDetailLoading(true);
      try {
        const data = await getTraceDetail(agentId, traceId);
        setSelectedTrace(data);
      } catch (e) {
        const msg = e instanceof Error ? e.message : "Failed to load trace detail";
        toast.error(msg);
        setSelectedTrace(null);
      } finally {
        setTraceDetailLoading(false);
      }
    },
    [],
  );

  return {
    traces,
    tracesLoading,
    selectedTrace,
    traceDetailLoading,
    fetchSessionTraces,
    fetchTraceDetail,
    setSelectedTrace,
  };
}
