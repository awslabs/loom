import { useState, useEffect, useCallback } from "react";
import type {
  ManagedRole,
  ManagedRoleCreateRequest,
  ManagedRoleUpdateRequest,
  AuthorizerConfigResponse,
  AuthorizerConfigCreateRequest,
  AuthorizerConfigUpdateRequest,
  PermissionRequestResponse,
  PermissionRequestCreateRequest,
  PermissionRequestReviewRequest,
} from "@/api/types";
import * as securityApi from "@/api/security";

export function useManagedRoles() {
  const [roles, setRoles] = useState<ManagedRole[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchRoles = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await securityApi.listManagedRoles();
      setRoles(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to fetch managed roles");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void fetchRoles();
  }, [fetchRoles]);

  const createRole = useCallback(
    async (request: ManagedRoleCreateRequest) => {
      const role = await securityApi.createManagedRole(request);
      await fetchRoles();
      return role;
    },
    [fetchRoles],
  );

  const updateRole = useCallback(
    async (id: number, request: ManagedRoleUpdateRequest) => {
      const role = await securityApi.updateManagedRole(id, request);
      await fetchRoles();
      return role;
    },
    [fetchRoles],
  );

  const deleteRole = useCallback(
    async (id: number) => {
      await securityApi.deleteManagedRole(id);
      await fetchRoles();
    },
    [fetchRoles],
  );

  return { roles, loading, error, fetchRoles, createRole, updateRole, deleteRole };
}

export function useAuthorizerConfigs() {
  const [configs, setConfigs] = useState<AuthorizerConfigResponse[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchConfigs = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await securityApi.listAuthorizerConfigs();
      setConfigs(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to fetch authorizer configs");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void fetchConfigs();
  }, [fetchConfigs]);

  const createConfig = useCallback(
    async (request: AuthorizerConfigCreateRequest) => {
      const config = await securityApi.createAuthorizerConfig(request);
      await fetchConfigs();
      return config;
    },
    [fetchConfigs],
  );

  const updateConfig = useCallback(
    async (id: number, request: AuthorizerConfigUpdateRequest) => {
      const config = await securityApi.updateAuthorizerConfig(id, request);
      await fetchConfigs();
      return config;
    },
    [fetchConfigs],
  );

  const deleteConfig = useCallback(
    async (id: number) => {
      await securityApi.deleteAuthorizerConfig(id);
      await fetchConfigs();
    },
    [fetchConfigs],
  );

  return { configs, loading, error, fetchConfigs, createConfig, updateConfig, deleteConfig };
}

export function usePermissionRequests(statusFilter?: string) {
  const [requests, setRequests] = useState<PermissionRequestResponse[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchRequests = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await securityApi.listPermissionRequests(statusFilter);
      setRequests(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to fetch permission requests");
    } finally {
      setLoading(false);
    }
  }, [statusFilter]);

  useEffect(() => {
    void fetchRequests();
  }, [fetchRequests]);

  const createRequest = useCallback(
    async (request: PermissionRequestCreateRequest) => {
      const result = await securityApi.createPermissionRequest(request);
      await fetchRequests();
      return result;
    },
    [fetchRequests],
  );

  const reviewRequest = useCallback(
    async (id: number, request: PermissionRequestReviewRequest) => {
      const result = await securityApi.reviewPermissionRequest(id, request);
      await fetchRequests();
      return result;
    },
    [fetchRequests],
  );

  return { requests, loading, error, fetchRequests, createRequest, reviewRequest };
}
