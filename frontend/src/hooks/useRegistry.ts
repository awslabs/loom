import { useState, useEffect, useCallback, useRef } from "react";
import type { RegistryRecord } from "@/api/types";
import * as registryApi from "@/api/registry";

export function useRegistry() {
  const [records, setRecords] = useState<RegistryRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const enrichedIds = useRef(new Set<string>());

  const fetchRecords = useCallback(async (params?: { status?: string; descriptorType?: string }) => {
    setLoading(true);
    setError(null);
    try {
      const data = await registryApi.listRegistryRecords(params);
      setRecords(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to fetch registry records");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void fetchRecords();
  }, [fetchRecords]);

  // One-time: fetch details for records missing descriptions
  useEffect(() => {
    if (loading || records.length === 0) return;
    const missing = records.filter(
      (r) => !r.description && !enrichedIds.current.has(r.record_id),
    );
    if (missing.length === 0) return;

    for (const r of missing) {
      enrichedIds.current.add(r.record_id);
    }

    Promise.all(
      missing.map((r) =>
        registryApi.getRegistryRecord(r.record_id).catch(() => null),
      ),
    ).then((details) => {
      const descMap = new Map<string, string>();
      for (const d of details) {
        if (d?.description) descMap.set(d.record_id, d.description);
      }
      if (descMap.size > 0) {
        setRecords((prev) =>
          prev.map((r) =>
            descMap.has(r.record_id)
              ? { ...r, description: descMap.get(r.record_id)! }
              : r,
          ),
        );
      }
    });
  }, [loading, records]);

  return { records, loading, error, fetchRecords };
}
