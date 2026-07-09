import { useState, useEffect, useCallback } from "react";
import type { McpServer, McpServerCreateRequest, McpServerUpdateRequest } from "@/api/types";
import * as mcpApi from "@/api/mcp";
import { toast } from "sonner";

export function useMcpServers() {
  const [servers, setServers] = useState<McpServer[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchServers = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await mcpApi.listMcpServers();
      setServers(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to fetch MCP servers");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void fetchServers();
  }, [fetchServers]);

  const createServer = useCallback(
    async (request: McpServerCreateRequest) => {
      const server = await mcpApi.createMcpServer(request);
      await fetchServers();
      toast.success("MCP server created");
      return server;
    },
    [fetchServers],
  );

  const updateServer = useCallback(
    async (id: number, request: McpServerUpdateRequest) => {
      const server = await mcpApi.updateMcpServer(id, request);
      await fetchServers();
      toast.success("MCP server updated");
      return server;
    },
    [fetchServers],
  );

  const deleteServer = useCallback(
    async (id: number) => {
      await mcpApi.deleteMcpServer(id);
      setServers((prev) => prev.filter((s) => s.id !== id));
      toast.success("MCP server deleted");
    },
    [],
  );

  return { servers, loading, error, fetchServers, createServer, updateServer, deleteServer };
}
