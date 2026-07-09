import { useState, useEffect } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Trash2, Plus, FlaskConical, ChevronDown, ChevronRight, Pencil, ArrowRightLeft } from "lucide-react";
import { JsonConfigSection } from "@/components/JsonConfigSection";
import { useAuth } from "@/contexts/AuthContext";
import {
  listIdentityProviders,
  createIdentityProvider,
  updateIdentityProvider,
  deleteIdentityProvider,
  testDiscovery,
  type IdentityProviderResponse,
  type CreateIdentityProviderRequest,
} from "@/api/identity_providers";

const PROVIDER_TYPES = [
  { value: "entra_id", label: "Microsoft Entra ID" },
  { value: "okta", label: "Okta" },
  { value: "auth0", label: "Auth0" },
  { value: "generic_oidc", label: "Generic OIDC" },
];

const PROVIDER_HINTS: Record<string, string> = {
  entra_id: "https://login.microsoftonline.com/{tenant-id}/v2.0",
  okta: "https://{your-domain}.okta.com",
  auth0: "https://{your-domain}.auth0.com/",
  generic_oidc: "https://your-issuer.example.com",
};

const GROUP_CLAIM_HINTS: Record<string, string> = {
  entra_id: "roles",
  okta: "groups",
  auth0: "https://your-namespace/roles",
  generic_oidc: "groups",
};

const LOOM_GROUPS = [
  "t-admin",
  "t-user",
  "g-admins-super",
  "g-admins-demo",
  "g-admins-security",
  "g-admins-memory",
  "g-admins-mcp",
  "g-admins-a2a",
  "g-admins-registry",
  "g-users-demo",
  "g-users-test",
  "g-users-strategics",
];

interface IdentityProviderPanelProps {
  readOnly?: boolean;
}

export function IdentityProviderPanel({ readOnly }: IdentityProviderPanelProps) {
  const { logout } = useAuth();
  const [providers, setProviders] = useState<IdentityProviderResponse[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [discoveryStatus, setDiscoveryStatus] = useState<string | null>(null);
  const [expandedId, setExpandedId] = useState<number | null>(null);
  const [confirmDeleteId, setConfirmDeleteId] = useState<number | null>(null);

  // Form state
  const [formName, setFormName] = useState("");
  const [formProviderType, setFormProviderType] = useState("entra_id");
  const [formIssuerUrl, setFormIssuerUrl] = useState("");
  const [formClientId, setFormClientId] = useState("");
  const [formClientSecret, setFormClientSecret] = useState("");
  const [formClientType, setFormClientType] = useState("public");
  const [formScopes, setFormScopes] = useState("");
  const [formAudience, setFormAudience] = useState("");
  const [formGroupClaimPath, setFormGroupClaimPath] = useState("");
  const [formStatus, setFormStatus] = useState("active");
  const [formMappings, setFormMappings] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);

  const fetchProviders = async () => {
    try {
      const data = await listIdentityProviders();
      setProviders(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load identity providers");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { void fetchProviders(); }, []);

  const resetForm = () => {
    setFormName("");
    setFormProviderType("entra_id");
    setFormIssuerUrl("");
    setFormClientId("");
    setFormClientSecret("");
    setFormClientType("public");
    setFormScopes("");
    setFormAudience("");
    setFormGroupClaimPath("");
    setFormStatus("active");
    setFormMappings({});
    setDiscoveryStatus(null);
  };

  const handleJsonApply = (json: string): string | null => {
    try {
      const obj = JSON.parse(json);
      if (obj.name) setFormName(obj.name);
      if (obj.provider_type) {
        setFormProviderType(obj.provider_type);
        setFormGroupClaimPath(obj.group_claim_path ?? GROUP_CLAIM_HINTS[obj.provider_type] ?? "groups");
      }
      if (obj.issuer_url) setFormIssuerUrl(obj.issuer_url);
      if (obj.client_id) setFormClientId(obj.client_id);
      if (obj.client_secret) setFormClientSecret(obj.client_secret);
      if (obj.client_type) setFormClientType(obj.client_type);
      if (obj.scopes) setFormScopes(obj.scopes);
      if (obj.audience) setFormAudience(obj.audience);
      if (obj.group_claim_path) setFormGroupClaimPath(obj.group_claim_path);
      if (obj.status) setFormStatus(obj.status);
      if (obj.group_mappings && typeof obj.group_mappings === "object") {
        const reversed: Record<string, string> = {};
        for (const [key, val] of Object.entries(obj.group_mappings)) {
          if (Array.isArray(val)) {
            for (const g of val as string[]) reversed[g] = key;
          } else if (typeof val === "string") {
            reversed[val] = key;
          }
        }
        setFormMappings(reversed);
      }
      setError(null);
      return null;
    } catch {
      return "Invalid JSON. Expected an identity provider configuration object.";
    }
  };

  const handleJsonExport = (): string => {
    const groupMappings: Record<string, string> = {};
    for (const [loomGroup, uuid] of Object.entries(formMappings)) {
      const trimmed = uuid.trim();
      if (!trimmed) continue;
      groupMappings[trimmed] = loomGroup;
    }
    return JSON.stringify({
      name: formName,
      provider_type: formProviderType,
      issuer_url: formIssuerUrl,
      client_id: formClientId,
      client_secret: formClientSecret || undefined,
      client_type: formClientType,
      scopes: formScopes || undefined,
      audience: formAudience || undefined,
      group_claim_path: formGroupClaimPath || undefined,
      group_mappings: Object.keys(groupMappings).length > 0 ? groupMappings : undefined,
      status: formStatus,
    }, null, 2);
  };

  const openEdit = (idp: IdentityProviderResponse) => {
    setEditingId(idp.id);
    setFormName(idp.name);
    setFormProviderType(idp.provider_type);
    setFormIssuerUrl(idp.issuer_url);
    setFormClientId(idp.client_id);
    setFormClientSecret("");
    setFormClientType(idp.client_type || "public");
    setFormScopes(idp.scopes || "");
    setFormAudience(idp.audience || "");
    setFormGroupClaimPath(idp.group_claim_path || "");
    setFormStatus(idp.status);
    const reversed: Record<string, string> = {};
    for (const [uuid, loomGroups] of Object.entries(idp.group_mappings)) {
      for (const g of loomGroups) {
        reversed[g] = uuid;
      }
    }
    setFormMappings(reversed);
    setShowForm(false);
    setDiscoveryStatus(null);
  };

  const handleTestDiscovery = async () => {
    if (!formIssuerUrl.trim()) return;
    setDiscoveryStatus("testing...");
    try {
      const result = await testDiscovery(formIssuerUrl.trim());
      if (result.status === "ok") {
        setDiscoveryStatus(`OK — JWKS: ${result.jwks_uri}`);
      } else {
        setDiscoveryStatus(`Error: ${result.detail}`);
      }
    } catch (e) {
      setDiscoveryStatus(`Error: ${e instanceof Error ? e.message : String(e)}`);
    }
  };

  const handleSave = async () => {
    setSaving(true);
    setError(null);

    // Determine upfront if this save will switch the active IdP.
    const savingAsActive = formStatus === "active";
    const currentActive = providers.find((p) => p.status === "active");
    const isIdPSwitch = savingAsActive && (!currentActive || currentActive.client_id !== formClientId);

    try {
      const groupMappings: Record<string, string[]> = {};
      for (const [loomGroup, uuid] of Object.entries(formMappings)) {
        const trimmed = uuid.trim();
        if (!trimmed) continue;
        if (!groupMappings[trimmed]) groupMappings[trimmed] = [];
        groupMappings[trimmed].push(loomGroup);
      }

      if (editingId) {
        await updateIdentityProvider(editingId, {
          name: formName,
          provider_type: formProviderType,
          issuer_url: formIssuerUrl,
          client_id: formClientId,
          client_secret: formClientSecret || undefined,
          client_type: formClientType,
          scopes: formScopes || undefined,
          audience: formAudience || undefined,
          group_claim_path: formGroupClaimPath || undefined,
          group_mappings: Object.keys(groupMappings).length > 0 ? groupMappings : undefined,
          status: formStatus,
        });
      } else {
        const data: CreateIdentityProviderRequest = {
          name: formName,
          provider_type: formProviderType,
          issuer_url: formIssuerUrl,
          client_id: formClientId,
          client_secret: formClientSecret || undefined,
          client_type: formClientType,
          scopes: formScopes || undefined,
          audience: formAudience || undefined,
          group_claim_path: formGroupClaimPath || undefined,
          group_mappings: Object.keys(groupMappings).length > 0 ? groupMappings : undefined,
          status: formStatus,
        };
        await createIdentityProvider(data);
      }

      if (isIdPSwitch) {
        logout();
        return;
      }

      resetForm();
      setShowForm(false);
      setEditingId(null);
      await fetchProviders();
    } catch (e) {
      // Any failure after saving an active IdP means the switch likely took effect
      if (isIdPSwitch || savingAsActive) {
        logout();
        return;
      }
      setError(e instanceof Error ? e.message : "Failed to save identity provider");
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (idp: IdentityProviderResponse) => {
    if (!confirm(`Delete identity provider "${idp.name}"?`)) return;
    try {
      await deleteIdentityProvider(idp.id);
      await fetchProviders();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to delete");
    }
  };

  const handleToggleStatus = async (idp: IdentityProviderResponse) => {
    try {
      const newStatus = idp.status === "active" ? "inactive" : "active";
      const currentActive = providers.find((p) => p.status === "active");
      const isSwitching = newStatus === "active" && currentActive && currentActive.id !== idp.id;

      await updateIdentityProvider(idp.id, { status: newStatus });

      if (isSwitching) {
        logout();
        return;
      }
      await fetchProviders();
    } catch (e) {
      // If activating a different IdP caused a 401, the switch took effect
      if (idp.status !== "active") {
        logout();
        return;
      }
      setError(e instanceof Error ? e.message : "Failed to update status");
    }
  };

  const editingProvider = editingId ? providers.find((p) => p.id === editingId) : null;

  const renderForm = (isEdit: boolean) => (
    <div className="space-y-4">
      <JsonConfigSection
        onApply={handleJsonApply}
        onExport={handleJsonExport}
        placeholder='{"name": "entra-id", "provider_type": "entra_id", "issuer_url": "...", ...}'
      />

      <div className="grid grid-cols-2 gap-4">
        <div className="space-y-1.5">
          <Label className="text-xs">Name</Label>
          <Input value={formName} onChange={(e) => setFormName(e.target.value)} placeholder="e.g. entra-id-prod" />
        </div>
        <div className="space-y-1.5">
          <Label className="text-xs">Provider Type</Label>
          <Select value={formProviderType} onValueChange={(v) => { setFormProviderType(v); setFormGroupClaimPath(GROUP_CLAIM_HINTS[v] ?? "groups"); }}>
            <SelectTrigger><SelectValue /></SelectTrigger>
            <SelectContent>
              {PROVIDER_TYPES.map((p) => (
                <SelectItem key={p.value} value={p.value}>{p.label}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </div>

      <div className="space-y-1.5">
        <Label className="text-xs">Issuer URL</Label>
        <div className="flex gap-2">
          <Input
            value={formIssuerUrl}
            onChange={(e) => setFormIssuerUrl(e.target.value)}
            placeholder={PROVIDER_HINTS[formProviderType] ?? ""}
            className="flex-1"
          />
          <Button type="button" size="sm" variant="outline" onClick={() => void handleTestDiscovery()}>
            <FlaskConical className="h-3.5 w-3.5 mr-1" />
            Test
          </Button>
        </div>
        {discoveryStatus && (
          <p className={`text-xs ${discoveryStatus.startsWith("OK") ? "text-green-600" : "text-destructive"}`}>
            {discoveryStatus}
          </p>
        )}
      </div>

      <div className="grid grid-cols-[auto_2fr_3fr] gap-4">
        <div className="space-y-1.5">
          <Label className="text-xs">Client Type</Label>
          <Select value={formClientType} onValueChange={setFormClientType}>
            <SelectTrigger className="w-[150px]"><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value="public">Public (PKCE)</SelectItem>
              <SelectItem value="confidential">Confidential</SelectItem>
            </SelectContent>
          </Select>
        </div>
        <div className="space-y-1.5">
          <Label className="text-xs">Client ID</Label>
          <Input value={formClientId} onChange={(e) => setFormClientId(e.target.value)} placeholder="App registration client ID" />
        </div>
        <div className="space-y-1.5">
          <Label className="text-xs">Client Secret</Label>
          <Input
            type="password"
            value={formClientSecret}
            onChange={(e) => setFormClientSecret(e.target.value)}
            placeholder={editingProvider?.has_client_secret ? "(stored — leave blank to keep)" : "Client secret value"}
          />
        </div>
      </div>
      <p className="text-[10px] text-muted-foreground -mt-2">Public: browser exchanges code directly via PKCE. Confidential: backend proxies code exchange with client secret.</p>

      <div className="grid grid-cols-2 gap-4">
        <div className="space-y-1.5">
          <Label className="text-xs">Scopes</Label>
          <Input value={formScopes} onChange={(e) => setFormScopes(e.target.value)} placeholder="openid profile email" />
        </div>
        <div className="space-y-1.5">
          <Label className="text-xs">Audience</Label>
          <Input value={formAudience} onChange={(e) => setFormAudience(e.target.value)} placeholder="api://client-id (optional, defaults to client_id)" />
        </div>
      </div>

      <div className="grid grid-cols-2 gap-4">
        <div className="space-y-1.5">
          <Label className="text-xs">Group Claim Path</Label>
          <Input value={formGroupClaimPath} onChange={(e) => setFormGroupClaimPath(e.target.value)} placeholder="groups" />
          <p className="text-[10px] text-muted-foreground">JWT claim containing group membership</p>
        </div>
        <div className="space-y-1.5">
          <Label className="text-xs">Status</Label>
          <Select value={formStatus} onValueChange={setFormStatus}>
            <SelectTrigger><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value="active">Active</SelectItem>
              <SelectItem value="inactive">Inactive</SelectItem>
            </SelectContent>
          </Select>
        </div>
      </div>

      {formProviderType === "entra_id" && (
      <div className="space-y-2">
        <Label className="text-xs">Group Mappings</Label>
        <p className="text-[10px] text-muted-foreground">Map each Loom group to its external IdP group identifier (e.g. Entra security group Object ID).</p>
        {LOOM_GROUPS.map((group) => (
          <div key={group} className="flex gap-2 items-center">
            <span className="text-xs font-mono w-40 shrink-0">{group}</span>
            <span className="text-xs text-muted-foreground shrink-0">&larr;</span>
            <Input
              value={formMappings[group] ?? ""}
              onChange={(e) => setFormMappings({ ...formMappings, [group]: e.target.value })}
              placeholder="External group ID (e.g. UUID)"
              className="flex-1 text-xs font-mono"
            />
          </div>
        ))}
      </div>
      )}

      <div className="flex gap-2">
        <Button size="sm" className="min-w-[120px]" onClick={() => void handleSave()} disabled={saving || !formName.trim() || !formIssuerUrl.trim() || !formClientId.trim()}>
          {saving ? "Saving..." : isEdit ? "Save" : "Create"}
        </Button>
        <Button size="sm" variant="ghost" onClick={() => { isEdit ? setEditingId(null) : setShowForm(false); resetForm(); }}>
          Cancel
        </Button>
      </div>
    </div>
  );

  if (loading) return <p className="text-sm text-muted-foreground">Loading identity providers...</p>;

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-sm font-medium">Identity Providers</h3>
          <p className="text-xs text-muted-foreground mt-1">
            Configure external identity providers for federated authentication.<br />
            Users can sign in via these providers instead of (or in addition to) Cognito.<br />
            Only one identity provider can be active at a time.
          </p>
        </div>
        <div className="shrink-0 ml-4">
          <Button size="sm" variant="outline" onClick={() => { resetForm(); setEditingId(null); setConfirmDeleteId(null); setShowForm(true); }} disabled={readOnly || showForm}>
            <Plus className="h-3.5 w-3.5 mr-1" />
            Add Identity Provider
          </Button>
        </div>
      </div>

      {error && <p className="text-sm text-destructive">{error}</p>}

      {showForm && (
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-sm font-medium">New Identity Provider</CardTitle>
          </CardHeader>
          <CardContent>
            {renderForm(false)}
          </CardContent>
        </Card>
      )}

      {providers.length === 0 && !showForm && (
        <p className="text-sm text-muted-foreground py-8">No identity providers configured. Loom uses Cognito for authentication.</p>
      )}

      {providers.map((idp) => (
        <Card key={idp.id} className="relative py-3 gap-1 transition-colors hover:bg-accent/50">
          <CardHeader className="gap-1 pb-2">
            <div className="flex items-center justify-between gap-2">
              <div className="flex items-center gap-2 min-w-0">
                <button
                  type="button"
                  onClick={() => setExpandedId(expandedId === idp.id ? null : idp.id)}
                  className="text-muted-foreground hover:text-foreground"
                >
                  {expandedId === idp.id ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
                </button>
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <span
                      className={`inline-block h-2 w-2 rounded-full shrink-0 ${idp.status === "active" ? "bg-green-500" : "bg-muted-foreground/30"}`}
                      title={idp.status === "active" ? "Active — login enabled" : "Inactive"}
                    />
                    <span className="text-sm font-medium">{idp.name}</span>
                    <Badge variant="outline" className="text-[10px]">
                      {PROVIDER_TYPES.find((p) => p.value === idp.provider_type)?.label ?? idp.provider_type}
                    </Badge>
                    {idp.status === "active" && (
                      <Badge variant="outline" className="text-[10px] border-green-500/50 text-green-600 dark:text-green-400">Active</Badge>
                    )}
                  </div>
                  <div className="text-xs text-muted-foreground">{idp.issuer_url}</div>
                </div>
              </div>
              {!readOnly && (
                <div className="flex items-center gap-2 shrink-0">
                  <Button
                    size="sm"
                    variant={idp.status === "active" ? "outline" : "default"}
                    className="h-6 text-xs"
                    onClick={() => void handleToggleStatus(idp)}
                  >
                    {idp.status === "active" ? "Deactivate" : "Activate"}
                  </Button>
                  <button
                    type="button"
                    onClick={() => openEdit(idp)}
                    className="text-muted-foreground/50 hover:text-foreground transition-colors"
                    title="Edit"
                  >
                    <Pencil className="h-3.5 w-3.5" />
                  </button>
                  <button
                    type="button"
                    onClick={() => setConfirmDeleteId(idp.id)}
                    className="text-muted-foreground/50 hover:text-destructive transition-colors"
                    title="Delete"
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                </div>
              )}
            </div>
          </CardHeader>
          <CardContent className="space-y-2">
            {confirmDeleteId === idp.id && (
              <div className="flex items-center justify-end gap-2 pt-1">
                <Button size="sm" variant="ghost" className="h-6 text-xs" onClick={() => setConfirmDeleteId(null)}>
                  Cancel
                </Button>
                <Button size="sm" variant="destructive" className="h-6 text-xs" onClick={() => void handleDelete(idp)}>
                  Confirm
                </Button>
              </div>
            )}

            {editingId === idp.id && (
              <div className="rounded border border-dashed p-3">
                {renderForm(true)}
              </div>
            )}

            {expandedId === idp.id && editingId !== idp.id && (
              <div className="pl-6 space-y-3">
                <div className="rounded border bg-input-bg p-3 space-y-1 text-xs">
                  <div><span className="text-muted-foreground">Client ID: </span><span className="font-mono">{idp.client_id}</span></div>
                  <div><span className="text-muted-foreground">Client Type: </span><span>{idp.client_type === "confidential" ? "Confidential" : "Public (PKCE)"}</span></div>
                  {idp.has_client_secret && <div><span className="text-muted-foreground">Client Secret: </span><span className="text-muted-foreground italic">(redacted)</span></div>}
                  {idp.scopes && <div><span className="text-muted-foreground">Scopes: </span><span className="break-all">{idp.scopes}</span></div>}
                  {idp.audience && <div><span className="text-muted-foreground">Audience: </span><span className="font-mono break-all">{idp.audience}</span></div>}
                  {idp.group_claim_path && <div><span className="text-muted-foreground">Group Claim Path: </span><span className="font-mono">{idp.group_claim_path}</span></div>}
                  {idp.jwks_uri && <div><span className="text-muted-foreground">JWKS URI: </span><span className="break-all">{idp.jwks_uri}</span></div>}
                  {idp.authorization_endpoint && <div><span className="text-muted-foreground">Authorization: </span><span className="break-all">{idp.authorization_endpoint}</span></div>}
                  {idp.token_endpoint && <div><span className="text-muted-foreground">Token: </span><span className="break-all">{idp.token_endpoint}</span></div>}
                </div>

                {idp.provider_type === "entra_id" && Object.keys(idp.group_mappings).length > 0 && (
                  <div>
                    <div className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground mb-2">
                      <ArrowRightLeft className="h-3.5 w-3.5" />
                      Mappings
                    </div>
                    <table className="text-xs w-full border-collapse border border-border rounded">
                      <thead>
                        <tr className="text-muted-foreground bg-accent">
                          <th className="text-left font-medium px-2 py-1 border border-border">Loom Group</th>
                          <th className="text-left font-medium px-2 py-1 border border-border">External ID</th>
                        </tr>
                      </thead>
                      <tbody>
                        {Object.entries(idp.group_mappings).flatMap(([ext, loom]) =>
                          loom.map((g) => (
                            <tr key={`${ext}-${g}`} className="bg-background">
                              <td className="px-2 py-0.5 font-mono border border-border">{g}</td>
                              <td className="px-2 py-0.5 font-mono text-muted-foreground border border-border">{ext}</td>
                            </tr>
                          ))
                        )}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>
            )}
          </CardContent>
        </Card>
      ))}
    </div>
  );
}
