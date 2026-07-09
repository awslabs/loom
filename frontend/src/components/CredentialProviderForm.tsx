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
import type { CredentialProvider, CredentialProviderCreateRequest } from "@/api/types";

interface CredentialProviderFormProps {
  providers: CredentialProvider[];
  loading: boolean;
  onCreate: (request: CredentialProviderCreateRequest) => Promise<unknown>;
  onDelete: (id: number) => Promise<void>;
}

const VENDORS = ["google", "microsoft", "github", "slack", "salesforce", "custom"];
const PROVIDER_TYPES = ["mcp_server", "a2a", "api_target"];

export function CredentialProviderForm({
  providers,
  loading,
  onCreate,
  onDelete,
}: CredentialProviderFormProps) {
  const [showForm, setShowForm] = useState(false);
  const [name, setName] = useState("");
  const [vendor, setVendor] = useState("google");
  const [clientId, setClientId] = useState("");
  const [clientSecret, setClientSecret] = useState("");
  const [authServerUrl, setAuthServerUrl] = useState("");
  const [scopesInput, setScopesInput] = useState("");
  const [providerType, setProviderType] = useState("mcp_server");
  const [creating, setCreating] = useState(false);

  const resetForm = () => {
    setName("");
    setVendor("google");
    setClientId("");
    setClientSecret("");
    setAuthServerUrl("");
    setScopesInput("");
    setProviderType("mcp_server");
  };

  const handleCreate = async () => {
    if (!name.trim() || !clientId.trim() || !clientSecret.trim() || !authServerUrl.trim()) return;
    setCreating(true);
    try {
      const scopes = scopesInput
        .split(",")
        .map((s) => s.trim())
        .filter(Boolean);
      await onCreate({
        name: name.trim(),
        vendor,
        client_id: clientId.trim(),
        client_secret: clientSecret.trim(),
        auth_server_url: authServerUrl.trim(),
        scopes,
        provider_type: providerType,
      });
      resetForm();
      setShowForm(false);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Failed to create credential provider");
    } finally {
      setCreating(false);
    }
  };

  return (
    <Card>
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <CardTitle className="text-sm font-medium">Credential Providers</CardTitle>
          <Button
            size="sm"
            variant="outline"
            onClick={() => setShowForm(!showForm)}
          >
            {showForm ? "Cancel" : "+ Add Provider"}
          </Button>
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        {showForm && (
          <div className="rounded border p-3 space-y-3">
            <div className="grid grid-cols-2 gap-2">
              <Input
                placeholder="Provider name"
                value={name}
                onChange={(e) => setName(e.target.value)}
                className="h-8 text-xs"
              />
              <Select value={vendor} onValueChange={setVendor}>
                <SelectTrigger className="h-8 text-xs">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {VENDORS.map((v) => (
                    <SelectItem key={v} value={v}>
                      {v}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="grid grid-cols-2 gap-2">
              <Input
                placeholder="Client ID"
                value={clientId}
                onChange={(e) => setClientId(e.target.value)}
                className="h-8 text-xs"
              />
              <Input
                type="password"
                placeholder="Client Secret"
                value={clientSecret}
                onChange={(e) => setClientSecret(e.target.value)}
                className="h-8 text-xs"
              />
            </div>
            <Input
              placeholder="Auth Server URL"
              value={authServerUrl}
              onChange={(e) => setAuthServerUrl(e.target.value)}
              className="h-8 text-xs"
            />
            <div className="grid grid-cols-2 gap-2">
              <Input
                placeholder="Scopes (comma-separated)"
                value={scopesInput}
                onChange={(e) => setScopesInput(e.target.value)}
                className="h-8 text-xs"
              />
              <Select value={providerType} onValueChange={setProviderType}>
                <SelectTrigger className="h-8 text-xs">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {PROVIDER_TYPES.map((t) => (
                    <SelectItem key={t} value={t}>
                      {t}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <Button
              size="sm"
              onClick={handleCreate}
              disabled={creating || !name.trim() || !clientId.trim() || !clientSecret.trim() || !authServerUrl.trim()}
            >
              {creating ? "Creating..." : "Create Provider"}
            </Button>
          </div>
        )}

        {loading ? (
          <div className="text-sm text-muted-foreground text-center py-4">Loading...</div>
        ) : providers.length === 0 ? (
          <div className="text-sm text-muted-foreground text-center py-4">
            No credential providers configured.
          </div>
        ) : (
          <div className="space-y-2">
            {providers.map((provider) => (
              <div
                key={provider.id}
                className="flex items-center justify-between rounded border p-3 text-xs"
              >
                <div className="space-y-1">
                  <div className="flex items-center gap-2">
                    <span className="font-medium">{provider.name}</span>
                    <Badge variant="outline">{provider.vendor}</Badge>
                    <Badge variant="secondary">{provider.provider_type}</Badge>
                  </div>
                  {provider.scopes.length > 0 && (
                    <div className="text-muted-foreground">
                      Scopes: {provider.scopes.join(", ")}
                    </div>
                  )}
                  {provider.callback_url && (
                    <div className="text-muted-foreground font-mono truncate max-w-md">
                      Callback: {provider.callback_url}
                    </div>
                  )}
                </div>
                <Button
                  size="sm"
                  variant="destructive"
                  onClick={() => onDelete(provider.id)}
                >
                  Delete
                </Button>
              </div>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
