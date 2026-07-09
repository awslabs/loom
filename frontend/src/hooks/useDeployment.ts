import { useState, useEffect, useCallback } from "react";
import type {
  ConfigEntry,
  CredentialProvider,
  AgentIntegration,
} from "@/api/types";
import * as agentsApi from "@/api/agents";
import * as credentialsApi from "@/api/credentials";
import * as integrationsApi from "@/api/integrations";

export function useAgentConfig(agentId: number | null) {
  const [config, setConfig] = useState<ConfigEntry[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchConfig = useCallback(async () => {
    if (agentId === null) return;
    setLoading(true);
    setError(null);
    try {
      const data = await agentsApi.getAgentConfig(agentId);
      setConfig(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to fetch config");
    } finally {
      setLoading(false);
    }
  }, [agentId]);

  useEffect(() => {
    void fetchConfig();
  }, [fetchConfig]);

  const updateConfig = useCallback(
    async (config: Record<string, string>) => {
      if (agentId === null) return;
      const data = await agentsApi.updateAgentConfig(agentId, { config });
      setConfig(data);
      return data;
    },
    [agentId],
  );

  return { config, loading, error, fetchConfig, updateConfig };
}

export function useCredentialProviders(agentId: number | null) {
  const [providers, setProviders] = useState<CredentialProvider[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchProviders = useCallback(async () => {
    if (agentId === null) return;
    setLoading(true);
    setError(null);
    try {
      const data = await credentialsApi.listCredentialProviders(agentId);
      setProviders(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to fetch providers");
    } finally {
      setLoading(false);
    }
  }, [agentId]);

  useEffect(() => {
    void fetchProviders();
  }, [fetchProviders]);

  const createProvider = useCallback(
    async (request: Parameters<typeof credentialsApi.createCredentialProvider>[1]) => {
      if (agentId === null) return;
      const provider = await credentialsApi.createCredentialProvider(agentId, request);
      await fetchProviders();
      return provider;
    },
    [agentId, fetchProviders],
  );

  const deleteProvider = useCallback(
    async (providerId: number) => {
      if (agentId === null) return;
      await credentialsApi.deleteCredentialProvider(agentId, providerId);
      await fetchProviders();
    },
    [agentId, fetchProviders],
  );

  return { providers, loading, error, fetchProviders, createProvider, deleteProvider };
}

export function useIntegrations(agentId: number | null) {
  const [integrations, setIntegrations] = useState<AgentIntegration[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchIntegrations = useCallback(async () => {
    if (agentId === null) return;
    setLoading(true);
    setError(null);
    try {
      const data = await integrationsApi.listIntegrations(agentId);
      setIntegrations(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to fetch integrations");
    } finally {
      setLoading(false);
    }
  }, [agentId]);

  useEffect(() => {
    void fetchIntegrations();
  }, [fetchIntegrations]);

  const createIntegration = useCallback(
    async (request: Parameters<typeof integrationsApi.createIntegration>[1]) => {
      if (agentId === null) return;
      const integration = await integrationsApi.createIntegration(agentId, request);
      await fetchIntegrations();
      return integration;
    },
    [agentId, fetchIntegrations],
  );

  const updateIntegration = useCallback(
    async (
      integrationId: number,
      request: Parameters<typeof integrationsApi.updateIntegration>[2],
    ) => {
      if (agentId === null) return;
      const integration = await integrationsApi.updateIntegration(
        agentId,
        integrationId,
        request,
      );
      await fetchIntegrations();
      return integration;
    },
    [agentId, fetchIntegrations],
  );

  const deleteIntegration = useCallback(
    async (integrationId: number) => {
      if (agentId === null) return;
      await integrationsApi.deleteIntegration(agentId, integrationId);
      await fetchIntegrations();
    },
    [agentId, fetchIntegrations],
  );

  return {
    integrations,
    loading,
    error,
    fetchIntegrations,
    createIntegration,
    updateIntegration,
    deleteIntegration,
  };
}
