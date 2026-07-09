import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Badge } from "@/components/ui/badge";
import { Loader2 } from "lucide-react";
import { testConnectionPreCreate, exportMcpServer } from "@/api/mcp";
import { JsonConfigSection } from "./JsonConfigSection";
import { useAuth } from "@/contexts/AuthContext";
import type { McpServerCreateRequest, TestConnectionResult } from "@/api/types";

interface McpServerFormProps {
  onSubmit: (data: McpServerCreateRequest) => Promise<void>;
  onCancel: () => void;
  initialData?: Partial<McpServerCreateRequest> & { id?: number };
}

export function McpServerForm({ onSubmit, onCancel, initialData }: McpServerFormProps) {
  const { hasScope } = useAuth();
  const [name, setName] = useState(initialData?.name ?? "");
  const [description, setDescription] = useState(initialData?.description ?? "");
  const [endpointUrl, setEndpointUrl] = useState(initialData?.endpoint_url ?? "");
  const [transportType, setTransportType] = useState<"sse" | "streamable_http">(
    initialData?.transport_type ?? "sse",
  );
  const [authType, setAuthType] = useState<"none" | "oauth2" | "api_key">(initialData?.auth_type ?? "none");
  const [wellKnownUrl, setWellKnownUrl] = useState(initialData?.oauth2_well_known_url ?? "");
  const [clientId, setClientId] = useState(initialData?.oauth2_client_id ?? "");
  const [clientSecret, setClientSecret] = useState("");
  const [scopes, setScopes] = useState(initialData?.oauth2_scopes ?? "");
  const [delegationMode, setDelegationMode] = useState<"m2m" | "obo">(initialData?.delegation_mode ?? "m2m");
  const [oboGrantType, setOboGrantType] = useState<"JWT_AUTHORIZATION_GRANT" | "TOKEN_EXCHANGE">(initialData?.obo_grant_type ?? "TOKEN_EXCHANGE");
  const [audience, setAudience] = useState(initialData?.oauth2_audience ?? "");
  const [apiKeyHeaderName, setApiKeyHeaderName] = useState(initialData?.api_key_header_name ?? "x-api-key");
  const [apiKey, setApiKey] = useState("");
  const [supportsElicitation, setSupportsElicitation] = useState(initialData?.supports_elicitation ?? false);
  const [submitting, setSubmitting] = useState(false);
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<TestConnectionResult | null>(null);

  const handleSubmit = async () => {
    if (!name.trim() || !endpointUrl.trim()) return;
    setSubmitting(true);
    try {
      const request: McpServerCreateRequest = {
        name: name.trim(),
        description: description.trim() || undefined,
        endpoint_url: endpointUrl.trim(),
        transport_type: transportType,
        auth_type: authType,
      };
      if (authType === "oauth2") {
        if (wellKnownUrl.trim()) request.oauth2_well_known_url = wellKnownUrl.trim();
        if (clientId.trim()) request.oauth2_client_id = clientId.trim();
        if (clientSecret) request.oauth2_client_secret = clientSecret;
        if (scopes.trim()) request.oauth2_scopes = scopes.trim();
        request.delegation_mode = delegationMode;
        if (delegationMode === "obo") {
          request.obo_grant_type = oboGrantType;
          if (audience.trim()) request.oauth2_audience = audience.trim();
        }
      }
      if (authType === "api_key") {
        request.api_key_header_name = apiKeyHeaderName;
        if (apiKey) request.api_key = apiKey;
      }
      request.supports_elicitation = supportsElicitation;
      await onSubmit(request);
    } finally {
      setSubmitting(false);
    }
  };

  const handleTest = async () => {
    if (!endpointUrl.trim()) return;
    setTesting(true);
    setTestResult(null);
    try {
      const config: Parameters<typeof testConnectionPreCreate>[0] = {
        endpoint_url: endpointUrl.trim(),
        transport_type: transportType,
        auth_type: authType,
      };
      if (authType === "oauth2") {
        if (wellKnownUrl.trim()) config.oauth2_well_known_url = wellKnownUrl.trim();
        if (clientId.trim()) config.oauth2_client_id = clientId.trim();
        if (clientSecret) config.oauth2_client_secret = clientSecret;
        if (scopes.trim()) config.oauth2_scopes = scopes.trim();
        config.delegation_mode = delegationMode;
        if (delegationMode === "obo" && audience.trim()) config.oauth2_audience = audience.trim();
      }
      if (authType === "api_key") {
        (config as Record<string, string>).api_key_header_name = apiKeyHeaderName;
        if (apiKey) (config as Record<string, string>).api_key = apiKey;
      }
      const result = await testConnectionPreCreate(config);
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
            if (parsed.name) setName(parsed.name);
            if (parsed.description !== undefined) setDescription(parsed.description);
            if (parsed.endpoint_url) setEndpointUrl(parsed.endpoint_url);
            if (parsed.transport_type && ["sse", "streamable_http"].includes(parsed.transport_type)) {
              setTransportType(parsed.transport_type);
            }
            if (parsed.auth_type && ["none", "oauth2", "api_key"].includes(parsed.auth_type)) {
              setAuthType(parsed.auth_type);
            }
            if (parsed.oauth2_well_known_url !== undefined) setWellKnownUrl(parsed.oauth2_well_known_url);
            if (parsed.oauth2_client_id !== undefined) setClientId(parsed.oauth2_client_id);
            if (parsed.oauth2_client_secret !== undefined) setClientSecret(parsed.oauth2_client_secret);
            if (parsed.oauth2_scopes !== undefined) setScopes(parsed.oauth2_scopes);
            if (parsed.delegation_mode === "m2m" || parsed.delegation_mode === "obo") setDelegationMode(parsed.delegation_mode);
            if (parsed.obo_grant_type === "JWT_AUTHORIZATION_GRANT" || parsed.obo_grant_type === "TOKEN_EXCHANGE") setOboGrantType(parsed.obo_grant_type);
            if (parsed.oauth2_audience !== undefined) setAudience(parsed.oauth2_audience);
            if (parsed.api_key_header_name !== undefined) setApiKeyHeaderName(parsed.api_key_header_name);
            if (parsed.api_key !== undefined) setApiKey(parsed.api_key);
            if (parsed.supports_elicitation !== undefined) setSupportsElicitation(!!parsed.supports_elicitation);
            return null;
          } catch {
            return "Invalid JSON. Please check the format and try again.";
          }
        }}
        onExport={async () => {
          if (initialData?.id && hasScope("admin:write")) {
            const data = await exportMcpServer(initialData.id);
            return JSON.stringify(data, null, 2);
          }
          const result: Record<string, unknown> = {};
          if (name) result.name = name;
          if (endpointUrl) result.endpoint_url = endpointUrl;
          result.transport_type = transportType;
          if (description) result.description = description;
          result.auth_type = authType;
          if (authType === "oauth2") {
            if (wellKnownUrl) result.oauth2_well_known_url = wellKnownUrl;
            if (clientId) result.oauth2_client_id = clientId;
            result.oauth2_client_secret = "(redacted)";
            if (scopes) result.oauth2_scopes = scopes;
            result.delegation_mode = delegationMode;
            if (delegationMode === "obo") result.obo_grant_type = oboGrantType;
            if (delegationMode === "obo" && audience) result.oauth2_audience = audience;
          }
          if (authType === "api_key") {
            result.api_key_header_name = apiKeyHeaderName;
            result.api_key = "(redacted)";
          }
          if (supportsElicitation) result.supports_elicitation = true;
          return JSON.stringify(result, null, 2);
        }}
        placeholder={'{"name": "...", "endpoint_url": "https://...", "transport_type": "sse", "auth_type": "oauth2|api_key", "oauth2_well_known_url": "https://...", "oauth2_client_id": "...", "oauth2_client_secret": "...", "oauth2_scopes": "...", "api_key_header_name": "x-api-key", "api_key": "..."}'}
      />

      <div className="flex gap-3">
        <div className="w-1/3 min-w-0">
          <label className="text-xs text-muted-foreground">Name *</label>
          <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="Server name" />
        </div>
        <div className="flex-1 min-w-0">
          <label className="text-xs text-muted-foreground">Endpoint URL *</label>
          <Input
            value={endpointUrl}
            onChange={(e) => setEndpointUrl(e.target.value)}
            placeholder="https://example.com/mcp"
          />
        </div>
        <div className="w-[180px]">
          <label className="text-xs text-muted-foreground">Transport</label>
          <Select value={transportType} onValueChange={(v) => setTransportType(v as "sse" | "streamable_http")}>
            <SelectTrigger className="w-full text-sm">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="sse">SSE</SelectItem>
              <SelectItem value="streamable_http">Streamable HTTP</SelectItem>
            </SelectContent>
          </Select>
        </div>
      </div>

      <div>
        <label className="text-xs text-muted-foreground">Description</label>
        <Textarea
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          placeholder="Optional description"
          rows={2}
        />
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
          <label className="flex items-center gap-1.5 text-sm cursor-pointer">
            <input
              type="radio"
              checked={authType === "api_key"}
              onChange={() => setAuthType("api_key")}
              className="h-3.5 w-3.5"
            />
            API Key
          </label>
        </div>

        {authType === "oauth2" && (
          <div className="space-y-2 pl-2 border-l-2 border-border ml-1">
            <div className="flex gap-3">
              <div className="flex-1 min-w-0">
                <label className="text-xs text-muted-foreground">Well-Known URL</label>
                <Input
                  value={wellKnownUrl}
                  onChange={(e) => setWellKnownUrl(e.target.value)}
                  placeholder="https://auth.example.com/.well-known/openid-configuration"
                />
              </div>
            </div>
            <div className="flex gap-3">
              <div className="flex-1 min-w-0">
                <label className="text-xs text-muted-foreground">Client ID</label>
                <Input value={clientId} onChange={(e) => setClientId(e.target.value)} placeholder="Client ID" />
              </div>
              <div className="flex-1 min-w-0">
                <label className="text-xs text-muted-foreground">Client Secret</label>
                <Input
                  type="password"
                  value={clientSecret}
                  onChange={(e) => setClientSecret(e.target.value)}
                  placeholder={initialData?.id ? "(unchanged)" : "Client secret"}
                />
              </div>
            </div>
            <div>
              <label className="text-xs text-muted-foreground">Scopes</label>
              <Input value={scopes} onChange={(e) => setScopes(e.target.value)} placeholder="openid profile (space-separated)" />
            </div>
            <div className="flex gap-3">
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
              </div>
              {delegationMode === "obo" && (
                <div className="w-[280px]">
                  <label className="text-xs text-muted-foreground">OBO Grant Type</label>
                  <Select value={oboGrantType} onValueChange={(v) => setOboGrantType(v as "JWT_AUTHORIZATION_GRANT" | "TOKEN_EXCHANGE")}>
                    <SelectTrigger className="w-full text-sm">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="JWT_AUTHORIZATION_GRANT">JWT Authorization Grant (Entra ID)</SelectItem>
                      <SelectItem value="TOKEN_EXCHANGE">Token Exchange (Okta)</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
              )}
              {delegationMode === "obo" && oboGrantType === "TOKEN_EXCHANGE" && (
                <div className="w-[280px]">
                  <label className="text-xs text-muted-foreground">Audience</label>
                  <Input
                    value={audience}
                    onChange={(e) => setAudience(e.target.value)}
                    placeholder="e.g. loom"
                    className="text-sm"
                  />
                </div>
              )}
            </div>
          </div>
        )}

        {authType === "api_key" && (
          <div className="space-y-2 pl-2 border-l-2 border-border ml-1">
            <div className="flex gap-3">
              <div className="w-[200px]">
                <label className="text-xs text-muted-foreground">Header Name</label>
                <Select value={apiKeyHeaderName} onValueChange={setApiKeyHeaderName}>
                  <SelectTrigger className="w-full text-sm">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="x-api-key">x-api-key</SelectItem>
                    <SelectItem value="Authorization">Authorization</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div className="flex-1 min-w-0">
                <label className="text-xs text-muted-foreground">API Key</label>
                <Input
                  type="password"
                  value={apiKey}
                  onChange={(e) => setApiKey(e.target.value)}
                  placeholder={initialData?.id ? "(unchanged)" : "API key"}
                />
              </div>
            </div>
          </div>
        )}
      </div>

      <div className="space-y-2">
        <label className="flex items-center gap-2 text-sm cursor-pointer">
          <input
            type="checkbox"
            checked={supportsElicitation}
            onChange={(e) => setSupportsElicitation(e.target.checked)}
            className="h-3.5 w-3.5"
          />
          Supports MCP elicitation (requires WebSocket invocation)
        </label>
      </div>

      <div className="flex items-center gap-2">
        <Button size="sm" variant="outline" onClick={handleTest} disabled={testing || !endpointUrl.trim()}>
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
        <Button size="sm" className="min-w-[120px]" onClick={handleSubmit} disabled={submitting || !name.trim() || !endpointUrl.trim()}>
          {submitting ? (initialData?.id ? "Updating..." : "Creating...") : (initialData?.id ? "Update" : "Create")}
        </Button>
        <Button size="sm" variant="ghost" onClick={onCancel}>
          Cancel
        </Button>
      </div>
    </div>
  );
}
