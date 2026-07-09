import { useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { toast } from "sonner";
import type {
  AgentIntegration,
  IntegrationCreateRequest,
  CredentialProvider,
} from "@/api/types";

interface IntegrationManagerProps {
  integrations: AgentIntegration[];
  credentialProviders: CredentialProvider[];
  loading: boolean;
  onCreate: (request: IntegrationCreateRequest) => Promise<unknown>;
  onUpdate: (
    id: number,
    request: { enabled?: boolean },
  ) => Promise<unknown>;
  onDelete: (id: number) => Promise<void>;
}

const INTEGRATION_TYPES = ["mcp_server", "a2a", "api_target", "custom"];

export function IntegrationManager({
  integrations,
  credentialProviders,
  loading,
  onCreate,
  onUpdate,
  onDelete,
}: IntegrationManagerProps) {
  const [showForm, setShowForm] = useState(false);
  const [formType, setFormType] = useState("mcp_server");
  const [configKey, setConfigKey] = useState("");
  const [configValue, setConfigValue] = useState("");
  const [configPairs, setConfigPairs] = useState<Record<string, string>>({});
  const [selectedProvider, setSelectedProvider] = useState<string>("");
  const [creating, setCreating] = useState(false);

  const addConfigPair = () => {
    if (!configKey.trim()) return;
    setConfigPairs({ ...configPairs, [configKey.trim()]: configValue });
    setConfigKey("");
    setConfigValue("");
  };

  const removeConfigPair = (key: string) => {
    const updated = { ...configPairs };
    delete updated[key];
    setConfigPairs(updated);
  };

  const handleCreate = async () => {
    setCreating(true);
    try {
      const request: IntegrationCreateRequest = {
        integration_type: formType,
        integration_config: configPairs,
      };
      if (selectedProvider) {
        request.credential_provider_id = Number(selectedProvider);
      }
      await onCreate(request);
      setShowForm(false);
      setConfigPairs({});
      setSelectedProvider("");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Failed to create integration");
    } finally {
      setCreating(false);
    }
  };

  const handleToggle = async (integration: AgentIntegration) => {
    await onUpdate(integration.id, { enabled: !integration.enabled });
  };

  return (
    <Card>
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <CardTitle className="text-sm font-medium">Integrations</CardTitle>
          <Button
            size="sm"
            variant="outline"
            onClick={() => setShowForm(!showForm)}
          >
            {showForm ? "Cancel" : "+ Add Integration"}
          </Button>
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        {showForm && (
          <div className="rounded border p-3 space-y-3">
            <div className="flex gap-2">
              <Select value={formType} onValueChange={setFormType}>
                <SelectTrigger className="w-[180px] h-8 text-xs">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {INTEGRATION_TYPES.map((t) => (
                    <SelectItem key={t} value={t}>
                      {t}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              {credentialProviders.length > 0 && (
                <Select value={selectedProvider} onValueChange={setSelectedProvider}>
                  <SelectTrigger className="w-[200px] h-8 text-xs">
                    <SelectValue placeholder="Credential provider (optional)" />
                  </SelectTrigger>
                  <SelectContent>
                    {credentialProviders.map((p) => (
                      <SelectItem key={p.id} value={String(p.id)}>
                        {p.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              )}
            </div>
            <div className="text-xs text-muted-foreground">Configuration</div>
            <div className="flex gap-2">
              <Input
                placeholder="Key"
                value={configKey}
                onChange={(e) => setConfigKey(e.target.value)}
                className="flex-1 h-8 text-xs"
              />
              <Input
                placeholder="Value"
                value={configValue}
                onChange={(e) => setConfigValue(e.target.value)}
                className="flex-1 h-8 text-xs"
              />
              <Button size="sm" variant="outline" onClick={addConfigPair}>
                Add
              </Button>
            </div>
            {Object.keys(configPairs).length > 0 && (
              <div className="flex flex-wrap gap-1">
                {Object.entries(configPairs).map(([k, v]) => (
                  <Badge key={k} variant="secondary" className="text-xs gap-1">
                    {k}={v}
                    <button onClick={() => removeConfigPair(k)}>&times;</button>
                  </Badge>
                ))}
              </div>
            )}
            <Button size="sm" onClick={handleCreate} disabled={creating}>
              {creating ? "Creating..." : "Create Integration"}
            </Button>
          </div>
        )}

        {loading ? (
          <div className="text-sm text-muted-foreground text-center py-4">Loading...</div>
        ) : integrations.length === 0 ? (
          <div className="text-sm text-muted-foreground text-center py-4">
            No integrations configured.
          </div>
        ) : (
          <div className="space-y-2">
            {integrations.map((integration) => (
              <div
                key={integration.id}
                className="flex items-center justify-between rounded border p-3 text-xs"
              >
                <div className="space-y-1">
                  <div className="flex items-center gap-2">
                    <span className="font-medium">{integration.integration_type}</span>
                    <Badge variant={integration.enabled ? "default" : "outline"}>
                      {integration.enabled ? "enabled" : "disabled"}
                    </Badge>
                  </div>
                  {Object.keys(integration.integration_config).length > 0 && (
                    <div className="flex flex-wrap gap-1">
                      {Object.entries(integration.integration_config).map(([k, v]) => (
                        <span key={k} className="text-muted-foreground">
                          {k}={v}
                        </span>
                      ))}
                    </div>
                  )}
                </div>
                <div className="flex gap-2">
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() => handleToggle(integration)}
                  >
                    {integration.enabled ? "Disable" : "Enable"}
                  </Button>
                  <Button
                    size="sm"
                    variant="destructive"
                    onClick={() => onDelete(integration.id)}
                  >
                    Delete
                  </Button>
                </div>
              </div>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
