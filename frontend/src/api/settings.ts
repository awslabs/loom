import { apiFetch } from "./client";
import type { TagPolicy, TagPolicyCreateRequest, TagPolicyUpdateRequest, TagProfile, TagProfileCreateRequest, VpcConfig, VpcConfigCreateRequest, VpcConfigDetail } from "./types";

// Site Settings API
export interface SiteSetting {
  id: number | null;
  key: string;
  value: string;
  updated_at: string | null;
}

export function listSiteSettings(): Promise<SiteSetting[]> {
  return apiFetch<SiteSetting[]>("/api/settings/site");
}

export function updateSiteSetting(key: string, value: string): Promise<SiteSetting> {
  return apiFetch<SiteSetting>(`/api/settings/site/${key}`, {
    method: "PUT",
    body: JSON.stringify({ key, value }),
  });
}

export function listTagPolicies(): Promise<TagPolicy[]> {
  return apiFetch<TagPolicy[]>("/api/settings/tags");
}

export function createTagPolicy(request: TagPolicyCreateRequest): Promise<TagPolicy> {
  return apiFetch<TagPolicy>("/api/settings/tags", {
    method: "POST",
    body: JSON.stringify(request),
  });
}

export function updateTagPolicy(id: number, request: TagPolicyUpdateRequest): Promise<TagPolicy> {
  return apiFetch<TagPolicy>(`/api/settings/tags/${id}`, {
    method: "PUT",
    body: JSON.stringify(request),
  });
}

export function deleteTagPolicy(id: number): Promise<void> {
  return apiFetch<void>(`/api/settings/tags/${id}`, {
    method: "DELETE",
  });
}

// Tag Profile API
export function listTagProfiles(): Promise<TagProfile[]> {
  return apiFetch<TagProfile[]>("/api/settings/tag-profiles");
}

export function createTagProfile(request: TagProfileCreateRequest): Promise<TagProfile> {
  return apiFetch<TagProfile>("/api/settings/tag-profiles", {
    method: "POST",
    body: JSON.stringify(request),
  });
}

export function updateTagProfile(id: number, request: TagProfileCreateRequest): Promise<TagProfile> {
  return apiFetch<TagProfile>(`/api/settings/tag-profiles/${id}`, {
    method: "PUT",
    body: JSON.stringify(request),
  });
}

export function deleteTagProfile(id: number): Promise<void> {
  return apiFetch<void>(`/api/settings/tag-profiles/${id}`, {
    method: "DELETE",
  });
}

// Registry Configuration API
export interface RegistryConfig {
  registry_arn: string;
  registry_id: string;
  enabled: boolean;
}

export function getRegistryConfig(): Promise<RegistryConfig> {
  return apiFetch<RegistryConfig>("/api/settings/registry");
}

export function updateRegistryConfig(registry_arn: string): Promise<RegistryConfig> {
  return apiFetch<RegistryConfig>("/api/settings/registry", {
    method: "PUT",
    body: JSON.stringify({ registry_arn }),
  });
}

// Enabled Models API
export interface EnabledModelsConfig {
  model_ids: string[];
  all_models: { model_id: string; display_name: string; group?: string }[];
}

export function getEnabledModels(): Promise<EnabledModelsConfig> {
  return apiFetch<EnabledModelsConfig>("/api/settings/models");
}

export function updateEnabledModels(model_ids: string[]): Promise<EnabledModelsConfig> {
  return apiFetch<EnabledModelsConfig>("/api/settings/models", {
    method: "PUT",
    body: JSON.stringify({ model_ids }),
  });
}

export function refreshLitellmModels(): Promise<EnabledModelsConfig> {
  return apiFetch<EnabledModelsConfig>("/api/settings/litellm-proxy/refresh", {
    method: "POST",
  });
}

// LiteLLM Proxy Configuration API
export interface LitellmProxyConfig {
  enabled: boolean;
  base_url: string;
  discovery_base_url: string;
  has_master_key: boolean;
}

export function getLitellmProxyConfig(): Promise<LitellmProxyConfig> {
  return apiFetch<LitellmProxyConfig>("/api/settings/litellm-proxy");
}

export function updateLitellmProxyConfig(
  enabled: boolean,
  base_url: string,
  discovery_base_url: string,
  master_key?: string,
): Promise<LitellmProxyConfig> {
  return apiFetch<LitellmProxyConfig>("/api/settings/litellm-proxy", {
    method: "PUT",
    body: JSON.stringify({
      enabled,
      base_url,
      discovery_base_url,
      ...(master_key ? { master_key } : {}),
    }),
  });
}

// VPC Configuration API
export function listVpcConfigs(): Promise<VpcConfig[]> {
  return apiFetch<VpcConfig[]>("/api/settings/vpc-configs");
}

export function createVpcConfig(request: VpcConfigCreateRequest): Promise<VpcConfig> {
  return apiFetch<VpcConfig>("/api/settings/vpc-configs", {
    method: "POST",
    body: JSON.stringify(request),
  });
}

export function updateVpcConfig(id: number, request: VpcConfigCreateRequest): Promise<VpcConfig> {
  return apiFetch<VpcConfig>(`/api/settings/vpc-configs/${id}`, {
    method: "PUT",
    body: JSON.stringify(request),
  });
}

export function deleteVpcConfig(id: number): Promise<void> {
  return apiFetch<void>(`/api/settings/vpc-configs/${id}`, {
    method: "DELETE",
  });
}

export function getVpcConfigDetail(id: number): Promise<VpcConfigDetail> {
  return apiFetch<VpcConfigDetail>(`/api/settings/vpc-configs/${id}/detail`);
}
