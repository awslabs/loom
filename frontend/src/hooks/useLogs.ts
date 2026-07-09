import { useState, useCallback } from "react";
import type { LogEvent, LogStreamInfo, VendedLogSource } from "@/api/types";
import { getSessionLogs, listLogStreams, getAgentLogs, listVendedLogSources, getVendedLogs } from "@/api/logs";

export function useLogs() {
  const [logs, setLogs] = useState<LogEvent[]>([]);
  const [loading, setLoading] = useState(false);
  const [streams, setStreams] = useState<LogStreamInfo[]>([]);
  const [streamsLoading, setStreamsLoading] = useState(false);
  const [activeStream, setActiveStream] = useState<string>("");
  const [vendedSources, setVendedSources] = useState<VendedLogSource[]>([]);

  const fetchSessionLogs = useCallback(
    async (agentId: number, sessionId: string, qualifier = "DEFAULT", noCache = false) => {
      setLoading(true);
      try {
        const data = await getSessionLogs(agentId, sessionId, qualifier, undefined, noCache);
        setLogs(data.events);
        setActiveStream("");
      } catch {
        setLogs([]);
      } finally {
        setLoading(false);
      }
    },
    [],
  );

  const fetchLogStreams = useCallback(
    async (agentId: number, qualifier = "DEFAULT") => {
      setStreamsLoading(true);
      try {
        const [streamsData, vendedData] = await Promise.all([
          listLogStreams(agentId, qualifier),
          listVendedLogSources(agentId),
        ]);
        setStreams(streamsData.streams);
        setVendedSources(vendedData.sources);
      } catch {
        setStreams([]);
        setVendedSources([]);
      } finally {
        setStreamsLoading(false);
      }
    },
    [],
  );

  const fetchStreamLogs = useCallback(
    async (agentId: number, qualifier = "DEFAULT", streamName: string, noCache = false) => {
      setLoading(true);
      try {
        const data = await getAgentLogs(agentId, qualifier, { stream: streamName, noCache });
        setLogs(data.events);
        setActiveStream(streamName);
      } catch {
        setLogs([]);
      } finally {
        setLoading(false);
      }
    },
    [],
  );

  const fetchVendedLogs = useCallback(
    async (agentId: number, source: VendedLogSource, noCache = false) => {
      setLoading(true);
      try {
        const data = await getVendedLogs(agentId, source.log_group, source.stream, { noCache });
        setLogs(data.events);
        setActiveStream(source.key);
      } catch {
        setLogs([]);
      } finally {
        setLoading(false);
      }
    },
    [],
  );

  return {
    logs,
    loading,
    streams,
    streamsLoading,
    activeStream,
    vendedSources,
    fetchSessionLogs,
    fetchLogStreams,
    fetchStreamLogs,
    fetchVendedLogs,
  };
}
