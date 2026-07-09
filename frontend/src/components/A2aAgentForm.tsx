import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Badge } from "@/components/ui/badge";
import { Loader2 } from "lucide-react";
import { testA2aConnection, testA2aConnectionPreCreate, exportA2aAgent } from "@/api/a2a";
import { JsonConfigSection } from "./JsonConfigSection";
import { useAuth } from "@/contexts/AuthContext";
import type { A2aAgentCreateRequest, TestConnectionResult } from "@/api/types";

interface A2aAgentFormProps {
  onSubmit: (data: A2aAgentCreateRequest) => Promise<void>;
  onCancel: () => void;
  initialData?: Partial<A2aAgentCreateRequest> & { id?: number };
}

export function A2aAgentForm({ onSubmit, onCancel, initialData }: A2aAgentFormProps) {
  const { hasScope } = useAuth();
  const [name, setName] = useState(initialData?.name ?? "");
  const [baseUrl, setBaseUrl] = useState(initialData?.base_url ?? "");
  const [authType, setAuthType] = useState<"none" | "oauth2">(initialData?.auth_type ?? "none");
  const [wellKnownUrl, setWellKnownUrl] = useState(initialData?.oauth2_well_known_url ?? "");
  const [clientId, setClientId] = useState(initialData?.oauth2_client_id ?? "");
  const [clientSecret, setClientSecret] = useState("");
  const [scopes, setScopes] = useState(initialData?.oauth2_scopes ?? "");
  const [delegationMode, setDelegationMode] = useState<"m2m" | "obo">(initialData?.delegation_mode ?? "m2m");
  const [submitting, setSubmitting] = useState(false);
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<TestConnectionResult | null>(null);

  const handleSubmit = async () => {
    if (!baseUrl.trim()) return;
    setSubmitting(true);
    try {
      const request: A2aAgentCreateRequest = {
        base_url: baseUrl.trim(),
        auth_type: authType,
      };
      if (name.trim()) request.name = name.trim();
      if (authType === "oauth2") {
        if (wellKnownUrl.trim()) request.oauth2_well_known_url = wellKnownUrl.trim();
        if (clientId.trim()) request.oauth2_client_id = clientId.trim();
        if (clientSecret) request.oauth2_client_secret = clientSecret;
        if (scopes.trim()) request.oauth2_scopes = scopes.trim();
        request.delegation_mode = delegationMode;
      }
      await onSubmit(request);
    } finally {
      setSubmitting(false);
    }
  };

  const handleTest = async () => {
    if (!baseUrl.trim()) return;
    setTesting(true);
    setTestResult(null);
    try {
      let result: TestConnectionResult;
      if (initialData?.id) {
        result = await testA2aConnection(initialData.id);
      } else {
        const config: Parameters<typeof testA2aConnectionPreCreate>[0] = {
          base_url: baseUrl.trim(),
          auth_type: authType,
        };
        if (authType === "oauth2") {
          if (wellKnownUrl.trim()) config.oauth2_well_known_url = wellKnownUrl.trim();
          if (clientId.trim()) config.oauth2_client_id = clientId.trim();
          if (clientSecret) config.oauth2_client_secret = clientSecret;
          if (scopes.trim()) config.oauth2_scopes = scopes.trim();
        }
        result = await testA2aConnectionPreCreate(config);
      }
      setTestResult(result);
    } catch (e) {
      setTestResult({ success: false, message: e instanceof Error ? e.message : "Test failed" });
    } finally {
      setTesting(false);
    }
  };

  return (
    <div className="space-y-3">
      <JsonConfigSection
        onApply={(json) => {
          try {
            const parsed = JSON.parse(json);
            if (parsed.name !== undefined) setName(parsed.name);
            if (parsed.base_url) setBaseUrl(parsed.base_url);
            if (parsed.auth_type && ["none", "oauth2"].includes(parsed.auth_type)) {
              setAuthType(parsed.auth_type);
            }
            if (parsed.oauth2_well_known_url !== undefined) setWellKnownUrl(parsed.oauth2_well_known_url);
            if (parsed.oauth2_client_id !== undefined) setClientId(parsed.oauth2_client_id);
            if (parsed.oauth2_client_secret !== undefined) setClientSecret(parsed.oauth2_client_secret);
            if (parsed.oauth2_scopes !== undefined) setScopes(parsed.oauth2_scopes);
            if (parsed.delegation_mode === "m2m" || parsed.delegation_mode === "obo") setDelegationMode(parsed.delegation_mode);
            return null;
          } catch {
            return "Invalid JSON. Please check the format and try again.";
          }
        }}
        onExport={async () => {
          if (initialData?.id && hasScope("admin:write")) {
            const data = await exportA2aAgent(initialData.id);
            return JSON.stringify(data, null, 2);
          }
          const result: Record<string, unknown> = {};
          if (name) result.name = name;
          if (baseUrl) result.base_url = baseUrl;
          result.auth_type = authType;
          if (authType === "oauth2") {
            if (wellKnownUrl) result.oauth2_well_known_url = wellKnownUrl;
            if (clientId) result.oauth2_client_id = clientId;
            result.oauth2_client_secret = "(redacted)";
            if (scopes) result.oauth2_scopes = scopes;
            result.delegation_mode = delegationMode;
          }
          return JSON.stringify(result, null, 2);
        }}
        placeholder={'{"name": "...", "base_url": "https://...", "auth_type": "oauth2", "oauth2_well_known_url": "https://...", "oauth2_client_id": "...", "oauth2_client_secret": "...", "oauth2_scopes": "..."}'}
      />

      <div className="flex gap-3">
        <div className="w-[22%] min-w-0">
          <label className="text-xs text-muted-foreground">Name</label>
          <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="Display name (optional)" />
        </div>
        <div className="flex-1 min-w-0">
          <label className="text-xs text-muted-foreground">Base URL *</label>
          <Input
            value={baseUrl}
            onChange={(e) => setBaseUrl(e.target.value)}
            placeholder="https://recipe-agent.example.com"
          />
          <p className="text-[10px] text-muted-foreground mt-0.5">
            The Agent Card will be fetched from &lt;base_url&gt;/.well-known/agent.json
          </p>
        </div>
      </div>

      <div className="space-y-2">
        <label className="text-xs text-muted-foreground font-medium">Authentication</label>
        <div className="flex items-center gap-4">
          <label className="flex items-center gap-1.5 text-sm cursor-pointer">
            <input
              type="radio"
              checked={authType === "none"}
              onChange={() => setAuthType("none")}
              className="h-3.5 w-3.5"
            />
            None
          </label>
          <label className="flex items-center gap-1.5 text-sm cursor-pointer">
            <input
              type="radio"
              checked={authType === "oauth2"}
              onChange={() => setAuthType("oauth2")}
              className="h-3.5 w-3.5"
            />
            OAuth2
          </label>
        </div>

        {authType === "oauth2" && (
          <div className="space-y-2 pl-2 border-l-2 border-border ml-1">
            <div>
              <label className="text-xs text-muted-foreground">Well-Known URL</label>
              <Input
                value={wellKnownUrl}
                onChange={(e) => setWellKnownUrl(e.target.value)}
                placeholder="https://auth.example.com/.well-known/openid-configuration"
              />
            </div>
            <div className="flex gap-3">
              <div className="w-[25%] min-w-0">
                <label className="text-xs text-muted-foreground">Client ID</label>
                <Input value={clientId} onChange={(e) => setClientId(e.target.value)} placeholder="Client ID" />
              </div>
              <div className="w-[40%] min-w-0">
                <label className="text-xs text-muted-foreground">Client Secret</label>
                <Input
                  type="password"
                  value={clientSecret}
                  onChange={(e) => setClientSecret(e.target.value)}
                  placeholder={initialData?.id ? "(unchanged)" : "Client secret"}
                />
              </div>
              <div className="flex-1 min-w-0">
                <label className="text-xs text-muted-foreground">Scopes</label>
                <Input value={scopes} onChange={(e) => setScopes(e.target.value)} placeholder="openid profile (space-separated)" />
              </div>
            </div>
            <div className="w-[280px]">
              <label className="text-xs text-muted-foreground">Delegation Mode</label>
              <Select value={delegationMode} onValueChange={(v) => setDelegationMode(v as "m2m" | "obo")}>
                <SelectTrigger className="w-full text-sm">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="m2m">M2M (shared agent identity)</SelectItem>
                  <SelectItem value="obo">On-Behalf-Of (user identity)</SelectItem>
                </SelectContent>
              </Select>
              <p className="text-[10px] text-muted-foreground mt-0.5 whitespace-nowrap">
                OBO uses RFC 8693 token exchange to delegate the invoking user&apos;s identity downstream.
              </p>
            </div>
          </div>
        )}
      </div>

      <div className="flex items-center gap-2">
        <Button size="sm" variant="outline" onClick={handleTest} disabled={testing || !baseUrl.trim()}>
          {testing ? (
            <>
              <Loader2 className="h-3.5 w-3.5 mr-1 animate-spin" />
              Testing...
            </>
          ) : (
            "Test Connection"
          )}
        </Button>
        {testResult && (
          <Badge variant={testResult.success ? "default" : "destructive"} className="text-xs">
            {testResult.message}
          </Badge>
        )}
      </div>

      <div className="flex items-center gap-2 pt-2">
        <Button size="sm" className="min-w-[120px]" onClick={handleSubmit} disabled={submitting || !baseUrl.trim()}>
          {submitting ? (initialData?.id ? "Updating..." : "Registering...") : (initialData?.id ? "Update" : "Register")}
        </Button>
        <Button size="sm" variant="ghost" onClick={onCancel}>
          Cancel
        </Button>
      </div>
    </div>
  );
}
