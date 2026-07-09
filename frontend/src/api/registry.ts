import { apiFetch } from "./client";
import type { RegistryRecord, RegistryRecordDetail, RegistryRecordCreateRequest, RegistrySearchResult } from "./types";

export function listRegistryRecords(params?: { status?: string; descriptorType?: string }): Promise<RegistryRecord[]> {
  const searchParams = new URLSearchParams();
  if (params?.status) searchParams.set("status", params.status);
  if (params?.descriptorType) searchParams.set("descriptor_type", params.descriptorType);
  const qs = searchParams.toString();
  return apiFetch<RegistryRecord[]>(`/api/registry/records${qs ? `?${qs}` : ""}`);
}

export function getRegistryRecord(recordId: string): Promise<RegistryRecordDetail> {
  return apiFetch<RegistryRecordDetail>(`/api/registry/records/${encodeURIComponent(recordId)}`);
}

export function createRegistryRecord(request: RegistryRecordCreateRequest): Promise<RegistryRecordDetail> {
  return apiFetch<RegistryRecordDetail>("/api/registry/records", {
    method: "POST",
    body: JSON.stringify(request),
  });
}

export function submitForApproval(recordId: string): Promise<void> {
  return apiFetch<void>(`/api/registry/records/${encodeURIComponent(recordId)}/submit`, { method: "POST" });
}

export function approveRecord(recordId: string, reason: string): Promise<void> {
  return apiFetch<void>(`/api/registry/records/${encodeURIComponent(recordId)}/approve`, {
    method: "POST",
    body: JSON.stringify({ reason }),
  });
}

export function rejectRecord(recordId: string, reason: string): Promise<void> {
  return apiFetch<void>(`/api/registry/records/${encodeURIComponent(recordId)}/reject`, {
    method: "POST",
    body: JSON.stringify({ reason }),
  });
}

export function deleteRegistryRecord(recordId: string): Promise<void> {
  return apiFetch<void>(`/api/registry/records/${encodeURIComponent(recordId)}`, { method: "DELETE" });
}

export function searchRegistry(query: string): Promise<RegistrySearchResult> {
  return apiFetch<RegistrySearchResult>(`/api/registry/search?q=${encodeURIComponent(query)}`);
}
