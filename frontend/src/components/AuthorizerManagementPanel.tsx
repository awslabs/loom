import { useState, useEffect } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { SearchableSelect } from "@/components/ui/searchable-select";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { SortableCardGrid, SortButton, loadSortDirection, toggleSortDirection, saveSortDirection, type SortDirection } from "@/components/SortableCardGrid";
import { JsonConfigSection } from "@/components/JsonConfigSection";
import { useAuthorizerConfigs } from "@/hooks/useSecurity";
import { listCognitoPools, listAuthorizerCredentials, createAuthorizerCredential, deleteAuthorizerCredential } from "@/api/security";
import { Badge } from "@/components/ui/badge";
import { Pencil, Trash2, Plus, ChevronDown, ChevronRight, Key, Link2 } from "lucide-react";
import { toast } from "sonner";
import { useAuth } from "@/contexts/AuthContext";
import { trackAction } from "@/api/audit";
import type { CognitoPool, AuthorizerCredential } from "@/api/types";

function TagInput({
  values,
  onChange,
  placeholder,
}: {
  values: string[];
  onChange: (values: string[]) => void;
  placeholder?: string;
}) {
  const [input, setInput] = useState("");

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter") {
      e.preventDefault();
      const trimmed = input.trim();
      if (trimmed && !values.includes(trimmed)) {
        onChange([...values, trimmed]);
      }
      setInput("");
    }
  };

  const remove = (value: string) => {
    onChange(values.filter((v) => v !== value));
  };

  return (
    <div className="space-y-1.5">
      <Input
        placeholder={placeholder}
        value={input}
        onChange={(e) => setInput(e.target.value)}
        onKeyDown={handleKeyDown}
        className="text-sm"
      />
      {values.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {values.map((v) => (
            <Badge
              key={v}
              variant="outline"
              className="gap-1 px-2 py-0.5 text-xs font-normal bg-primary/10"
            >
              {v}
              <button
                type="button"
                onClick={() => remove(v)}
                className="text-muted-foreground hover:text-foreground ml-0.5"
              >
                &times;
              </button>
            </Badge>
          ))}
        </div>
      )}
    </div>
  );
}

export function AuthorizerManagementPanel({ readOnly }: { readOnly?: boolean }) {
  const { user, browserSessionId } = useAuth();
  const { configs, loading, error, createConfig, updateConfig, deleteConfig } = useAuthorizerConfigs();
  const [showAddForm, setShowAddForm] = useState(false);
  const [expandedId, setExpandedId] = useState<number | null>(null);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [confirmDeleteId, setConfirmDeleteId] = useState<number | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [sortDir, setSortDir] = useState<SortDirection>(() => loadSortDirection("security-authorizers"));

  // Cognito pools from AWS
  const [cognitoPools, setCognitoPools] = useState<CognitoPool[]>([]);
  const [poolsLoading, setPoolsLoading] = useState(false);

  // Credentials per authorizer
  const [credentials, setCredentials] = useState<Record<number, AuthorizerCredential[]>>({});
  const [showAddCred, setShowAddCred] = useState<number | null>(null);
  const [credLabel, setCredLabel] = useState("");
  const [credClientId, setCredClientId] = useState("");
  const [credClientSecret, setCredClientSecret] = useState("");
  const [credSubmitting, setCredSubmitting] = useState(false);
  const [confirmDeleteCredId, setConfirmDeleteCredId] = useState<{ authId: number; credId: number } | null>(null);

  const fetchCredentials = async (authId: number) => {
    try {
      const creds = await listAuthorizerCredentials(authId);
      setCredentials((prev) => ({ ...prev, [authId]: creds }));
    } catch {
      toast.error("Failed to load credentials");
    }
  };

  const handleCreateCredential = async (authId: number) => {
    if (!credLabel.trim() || !credClientId.trim()) return;
    setCredSubmitting(true);
    try {
      if (user && browserSessionId) trackAction(user.username ?? user.sub, browserSessionId, 'security', 'add_credential', credLabel.trim());
      await createAuthorizerCredential(authId, {
        label: credLabel.trim(),
        client_id: credClientId.trim(),
        client_secret: credClientSecret.trim() || undefined,
      });
      setShowAddCred(null);
      setCredLabel("");
      setCredClientId("");
      setCredClientSecret("");
      toast.success("Credential added");
      fetchCredentials(authId);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Failed to add credential");
    } finally {
      setCredSubmitting(false);
    }
  };

  const handleDeleteCredential = async (authId: number, credId: number) => {
    setCredSubmitting(true);
    try {
      await deleteAuthorizerCredential(authId, credId);
      setConfirmDeleteCredId(null);
      toast.success("Credential deleted");
      fetchCredentials(authId);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Failed to delete credential");
    } finally {
      setCredSubmitting(false);
    }
  };

  // Form state
  const [formType, setFormType] = useState("cognito");
  const [formName, setFormName] = useState("");
  const [formPoolId, setFormPoolId] = useState("");
  const [formDiscoveryUrl, setFormDiscoveryUrl] = useState("");
  const [formAllowedAudience, setFormAllowedAudience] = useState<string[]>([]);
  const [formAllowedClients, setFormAllowedClients] = useState<string[]>([]);
  const [formAllowedScopes, setFormAllowedScopes] = useState<string[]>([]);
  const [formUserClientId, setFormUserClientId] = useState("");
  const [formUserClientSecret, setFormUserClientSecret] = useState("");
  const [formUserRedirectUri, setFormUserRedirectUri] = useState("");

  const fetchPools = () => {
    setPoolsLoading(true);
    listCognitoPools()
      .then(setCognitoPools)
      .catch(() => toast.error("Failed to load Cognito pools"))
      .finally(() => setPoolsLoading(false));
  };

  // Fetch pools when the add form opens with Cognito type, or when editing a Cognito config
  useEffect(() => {
    if ((showAddForm || editingId !== null) && formType === "cognito" && cognitoPools.length === 0) {
      fetchPools();
    }
  }, [showAddForm, editingId, formType]);

  // Auto-populate discovery URL when a Cognito pool is selected
  useEffect(() => {
    if (formType === "cognito" && formPoolId) {
      const pool = cognitoPools.find((p) => p.pool_id === formPoolId);
      if (pool) {
        setFormDiscoveryUrl(pool.discovery_url);
      }
    }
  }, [formPoolId, formType, cognitoPools]);

  const resetForm = () => {
    setFormType("cognito");
    setFormName("");
    setFormPoolId("");
    setFormDiscoveryUrl("");
    setFormAllowedClients([]);
    setFormAllowedScopes([]);
    setFormUserClientId("");
    setFormUserClientSecret("");
    setFormUserRedirectUri("");
  };

  const handleCreate = async () => {
    if (!formName.trim()) return;
    setSubmitting(true);
    try {
      if (user && browserSessionId) trackAction(user.username ?? user.sub, browserSessionId, 'security', 'add_authorizer', formName.trim());
      await createConfig({
        name: formName.trim(),
        authorizer_type: formType,
        pool_id: formPoolId || undefined,
        discovery_url: formDiscoveryUrl || undefined,
        allowed_audience: formAllowedAudience,
        allowed_clients: formAllowedClients,
        allowed_scopes: formAllowedScopes,
        user_client_id: formUserClientId || undefined,
        user_client_secret: formUserClientSecret || undefined,
        user_redirect_uri: formUserRedirectUri || undefined,
      });
      resetForm();
      setShowAddForm(false);
      toast.success("Authorizer config created");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Failed to create config");
    } finally {
      setSubmitting(false);
    }
  };

  const startEdit = (id: number) => {
    const config = configs.find((c) => c.id === id);
    if (!config) return;
    setEditingId(id);
    setFormType(config.authorizer_type);
    setFormName(config.name);
    setFormPoolId(config.pool_id ?? "");
    setFormDiscoveryUrl(config.discovery_url ?? "");
    setFormAllowedAudience(config.allowed_audience);
    setFormAllowedClients(config.allowed_clients);
    setFormAllowedScopes(config.allowed_scopes);
    setFormUserClientId(config.user_client_id ?? "");
    setFormUserClientSecret("");
    setFormUserRedirectUri(config.user_redirect_uri ?? "");
  };

  const handleUpdate = async (id: number) => {
    setSubmitting(true);
    try {
      await updateConfig(id, {
        name: formName.trim() || undefined,
        authorizer_type: formType,
        pool_id: formPoolId || undefined,
        discovery_url: formDiscoveryUrl || undefined,
        allowed_audience: formAllowedAudience,
        allowed_clients: formAllowedClients,
        allowed_scopes: formAllowedScopes,
        user_client_id: formUserClientId || undefined,
        user_client_secret: formUserClientSecret || undefined,
        user_redirect_uri: formUserRedirectUri || undefined,
      });
      setEditingId(null);
      resetForm();
      toast.success("Authorizer config updated");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Failed to update config");
    } finally {
      setSubmitting(false);
    }
  };

  const handleDelete = async (id: number) => {
    setSubmitting(true);
    try {
      const authName = configs.find(c => c.id === id)?.name ?? String(id);
      if (user && browserSessionId) trackAction(user.username ?? user.sub, browserSessionId, 'security', 'delete_authorizer', authName);
      await deleteConfig(id);
      setConfirmDeleteId(null);
      setCredentials((prev) => {
        const next = { ...prev };
        delete next[id];
        return next;
      });
      toast.success("Authorizer config deleted");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Failed to delete config");
    } finally {
      setSubmitting(false);
    }
  };

  const poolOptions = cognitoPools.map((p) => ({
    value: p.pool_id,
    label: `${p.pool_name} (${p.pool_id})`,
  }));

  const handleJsonApply = (json: string): string | null => {
    try {
      const obj = JSON.parse(json);
      if (obj.name) setFormName(obj.name);
      if (obj.authorizer_type) setFormType(obj.authorizer_type);
      if (obj.pool_id) setFormPoolId(obj.pool_id);
      if (obj.discovery_url) setFormDiscoveryUrl(obj.discovery_url);
      if (Array.isArray(obj.allowed_audience)) setFormAllowedAudience(obj.allowed_audience);
      if (Array.isArray(obj.allowed_clients)) setFormAllowedClients(obj.allowed_clients);
      if (Array.isArray(obj.allowed_scopes)) setFormAllowedScopes(obj.allowed_scopes);
      if (obj.user_client_id) setFormUserClientId(obj.user_client_id);
      if (obj.user_client_secret) setFormUserClientSecret(obj.user_client_secret);
      if (obj.user_redirect_uri) setFormUserRedirectUri(obj.user_redirect_uri);
      return null;
    } catch {
      return "Invalid JSON. Expected an authorizer configuration object.";
    }
  };

  const handleJsonExport = (): string => {
    return JSON.stringify({
      name: formName || undefined,
      authorizer_type: formType,
      pool_id: formPoolId || undefined,
      discovery_url: formDiscoveryUrl || undefined,
      allowed_audience: formAllowedAudience.length > 0 ? formAllowedAudience : undefined,
      allowed_clients: formAllowedClients.length > 0 ? formAllowedClients : undefined,
      allowed_scopes: formAllowedScopes.length > 0 ? formAllowedScopes : undefined,
      user_client_id: formUserClientId || undefined,
      user_redirect_uri: formUserRedirectUri || undefined,
    }, null, 2);
  };

  const renderForm = (isEdit: boolean, id?: number) => (
    <div className="space-y-3">
      <JsonConfigSection
        onApply={handleJsonApply}
        onExport={handleJsonExport}
        placeholder='{"name": "my-cognito", "authorizer_type": "cognito", "pool_id": "us-east-1_xxx", ...}'
      />
      <div className="flex gap-3">
        <div className="w-[30%] min-w-0">
          <label className="text-xs text-muted-foreground">Config Name</label>
          <Input value={formName} onChange={(e) => setFormName(e.target.value)} placeholder="Authorizer name that builders select" />
        </div>
        <div className="w-[15%] min-w-0">
          <label className="text-xs text-muted-foreground">Type</label>
          <Select value={formType} onValueChange={(v) => { setFormType(v); setFormPoolId(""); setFormDiscoveryUrl(""); }}>
            <SelectTrigger className="w-full text-sm"><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value="cognito">Amazon Cognito</SelectItem>
              <SelectItem value="entra_id">Microsoft Entra ID</SelectItem>
              <SelectItem value="okta">Okta</SelectItem>
              <SelectItem value="other">Other</SelectItem>
            </SelectContent>
          </Select>
        </div>
        {formType === "cognito" && (
          <div className="flex-1 min-w-0">
            <label className="text-xs text-muted-foreground">Cognito User Pool</label>
            {poolsLoading ? (
              <Skeleton className="h-9" />
            ) : (
              <SearchableSelect
                options={poolOptions}
                value={formPoolId}
                onValueChange={setFormPoolId}
                placeholder="Search for a pool..."
              />
            )}
          </div>
        )}
      </div>
      <div>
        <label className="text-xs text-muted-foreground">Discovery URL</label>
        <Input
          value={formDiscoveryUrl}
          onChange={(e) => setFormDiscoveryUrl(e.target.value)}
          placeholder="https://..."
          readOnly={formType === "cognito"}
          className={formType === "cognito" ? "bg-muted/50" : ""}
        />
      </div>
      <div className="space-y-3">
        <div className="min-h-[5.5rem]">
          <label className="text-xs text-muted-foreground">Allowed Audience (press Enter to add)</label>
          <TagInput values={formAllowedAudience} onChange={setFormAllowedAudience} placeholder="Audience URI" />
        </div>
      </div>
      <div className="grid grid-cols-2 gap-3">
        <div className="min-h-[5.5rem]">
          <label className="text-xs text-muted-foreground">Allowed Clients (press Enter to add)</label>
          <TagInput values={formAllowedClients} onChange={setFormAllowedClients} placeholder="Client ID" />
        </div>
        <div className="min-h-[5.5rem]">
          <label className="text-xs text-muted-foreground">Allowed Scopes (press Enter to add)</label>
          <TagInput values={formAllowedScopes} onChange={setFormAllowedScopes} placeholder="Scope" />
        </div>
      </div>
      <div className="border-t pt-3 mt-3">
        <label className="text-xs font-medium text-muted-foreground">User Authentication (for cross-IdP linking)</label>
        <div className="grid grid-cols-3 gap-3 mt-2">
          <div>
            <label className="text-xs text-muted-foreground">User Client ID</label>
            <Input value={formUserClientId} onChange={(e) => setFormUserClientId(e.target.value)} placeholder="OAuth client ID for user auth" className="text-sm" />
          </div>
          <div>
            <label className="text-xs text-muted-foreground">User Client Secret</label>
            <Input type="password" value={formUserClientSecret} onChange={(e) => setFormUserClientSecret(e.target.value)} placeholder="(optional)" className="text-sm" />
          </div>
          <div>
            <label className="text-xs text-muted-foreground">User Redirect URI</label>
            <Input value={formUserRedirectUri} onChange={(e) => setFormUserRedirectUri(e.target.value)} placeholder="https://your-app/oauth/link-callback" className="text-sm" />
          </div>
        </div>
      </div>
      <div className="flex gap-2">
        <Button size="sm" className="min-w-[120px]" onClick={() => isEdit && id ? handleUpdate(id) : handleCreate()} disabled={submitting || !formName.trim()}>
          {submitting ? "Saving..." : isEdit ? "Save" : "Create"}
        </Button>
        <Button size="sm" variant="ghost" onClick={() => { isEdit ? setEditingId(null) : setShowAddForm(false); resetForm(); }}>
          Cancel
        </Button>
      </div>
    </div>
  );

  if (loading) {
    return <div className="space-y-3">{Array.from({ length: 3 }).map((_, i) => <Skeleton key={i} className="h-12" />)}</div>;
  }

  if (error) {
    return <p className="text-sm text-destructive">{error}</p>;
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-sm font-medium">Authorizer Configurations</h3>
          <p className="text-xs text-muted-foreground mt-1">
            These are the authorizers approved for use in Loom.<br />
            Builders can only select from these authorizers when deploying agents.<br />
            Authorizer management is the responsibility of the security team.
          </p>
        </div>
        <div className="flex items-center gap-2 shrink-0 ml-4">
          <SortButton direction={sortDir} onClick={() => setSortDir(toggleSortDirection("security-authorizers", sortDir))} />
          <Button size="sm" variant="outline" onClick={() => { setShowAddForm(!showAddForm); resetForm(); }} disabled={readOnly}>
            <Plus className="h-3.5 w-3.5 mr-1" />
            Add Authorizer
          </Button>
        </div>
      </div>

      {showAddForm && (
        <Card>
          <CardContent className="pt-4">
            {renderForm(false)}
          </CardContent>
        </Card>
      )}

      {configs.length === 0 ? (
        <p className="text-sm text-muted-foreground py-8">No authorizer configs yet. Add one above.</p>
      ) : (
        <SortableCardGrid
          items={configs}
          getId={(c) => c.id.toString()}
          getName={(c) => c.name}
          storageKey="security-authorizers"
          sortDirection={sortDir}
          onSortDirectionChange={(d) => { if (d) { setSortDir(d); saveSortDirection("security-authorizers", d); } }}
          className="grid gap-2"
          renderItem={(config) => (
            <Card className="relative py-3 gap-1 transition-colors hover:bg-accent/50">
              <CardHeader className="gap-1 pb-2">
                <div className="flex items-center justify-between gap-2">
                  <div className="flex items-center gap-2 min-w-0">
                    <button
                      type="button"
                      onClick={() => {
                        const next = expandedId === config.id ? null : config.id;
                        setExpandedId(next);
                        if (next !== null && !credentials[config.id]) {
                          fetchCredentials(config.id);
                        }
                      }}
                      className="text-muted-foreground hover:text-foreground"
                    >
                      {expandedId === config.id ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
                    </button>
                    <div className="min-w-0">
                      <div className="flex items-center gap-2">
                        <span className="text-sm font-medium">{config.name}</span>
                        <Badge variant="outline" className="text-[10px]">
                          {config.authorizer_type === "cognito" ? "Amazon Cognito" : config.authorizer_type === "entra_id" ? "Microsoft Entra ID" : config.authorizer_type === "okta" ? "Okta" : config.authorizer_type}
                        </Badge>
                        {config.user_client_id && (
                          <Badge variant="outline" className="text-[10px] border-green-500/50 text-green-600 dark:text-green-400">Linkable</Badge>
                        )}
                      </div>
                      {config.discovery_url && <div className="text-xs text-muted-foreground">{config.discovery_url}</div>}
                    </div>
                  </div>
                  {!readOnly && (
                    <div className="flex items-center gap-1 shrink-0">
                      <button
                        type="button"
                        onClick={() => startEdit(config.id)}
                        className="text-muted-foreground/50 hover:text-foreground transition-colors"
                        title="Edit"
                      >
                        <Pencil className="h-3.5 w-3.5" />
                      </button>
                      <button
                        type="button"
                        onClick={() => setConfirmDeleteId(config.id)}
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
                {config.tags && Object.keys(config.tags).length > 0 && (
                  <div className="flex flex-wrap gap-1 ml-6">
                    {Object.entries(config.tags).map(([key, value]) => (
                      <Badge key={key} variant="outline" className="text-[10px] px-1.5 py-0 font-normal">
                        {key.replace(/^loom:/, "")}: {value}
                      </Badge>
                    ))}
                  </div>
                )}

                {confirmDeleteId === config.id && (
                  <div className="flex items-center justify-end gap-2 pt-1">
                    <Button size="sm" variant="ghost" className="h-6 text-xs" onClick={() => setConfirmDeleteId(null)}>
                      Cancel
                    </Button>
                    <Button size="sm" variant="destructive" className="h-6 text-xs" onClick={() => handleDelete(config.id)} disabled={submitting}>
                      Confirm
                    </Button>
                  </div>
                )}

                {editingId === config.id && (
                  <div className="rounded border border-dashed p-3">
                    {renderForm(true, config.id)}
                  </div>
                )}

                {expandedId === config.id && editingId !== config.id && (
                  <div className="pl-6 space-y-3">
                    <div className="rounded border bg-input-bg p-3 space-y-1 text-xs">
                      {config.pool_id && <div><span className="text-muted-foreground">Pool: </span>{config.pool_id}</div>}
                      {config.discovery_url && <div><span className="text-muted-foreground">Discovery URL: </span><span className="break-all">{config.discovery_url}</span></div>}
                      {config.allowed_audience.length > 0 && <div><span className="text-muted-foreground">Allowed Audience: </span>{config.allowed_audience.join(", ")}</div>}
                      {config.allowed_clients.length > 0 && <div><span className="text-muted-foreground">Allowed Clients: </span>{config.allowed_clients.join(", ")}</div>}
                      {config.allowed_scopes.length > 0 && <div><span className="text-muted-foreground">Allowed Scopes: </span>{config.allowed_scopes.join(", ")}</div>}
                    </div>

                    {(config.user_client_id || config.has_user_client_secret || config.user_redirect_uri) && (
                      <div>
                        <div className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground mb-2">
                          <Link2 className="h-3.5 w-3.5" />
                          User Linking
                        </div>
                        <div className="rounded border bg-input-bg p-3 space-y-1 text-xs">
                          {config.user_client_id && <div><span className="text-muted-foreground">Client ID: </span>{config.user_client_id}</div>}
                          {config.has_user_client_secret && <div><span className="text-muted-foreground">Client Secret: </span>(stored in Secrets Manager)</div>}
                          {config.user_redirect_uri && <div><span className="text-muted-foreground">Redirect URI: </span>{config.user_redirect_uri}</div>}
                        </div>
                      </div>
                    )}

                    {/* Credentials section */}
                    <div>
                      <div className="flex items-center justify-between mb-2">
                        <div className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
                          <Key className="h-3.5 w-3.5" />
                          Credentials
                        </div>
                        {!readOnly && (
                          <Button
                            size="sm"
                            variant="ghost"
                            className="h-6 text-xs"
                            onClick={() => {
                              setShowAddCred(showAddCred === config.id ? null : config.id);
                              setCredLabel("");
                              setCredClientId("");
                              setCredClientSecret("");
                            }}
                          >
                            <Plus className="h-3 w-3 mr-1" />
                            Add
                          </Button>
                        )}
                      </div>

                      {showAddCred === config.id && (
                        <div className="rounded border border-dashed p-3 mb-2 space-y-2">
                          <div className="flex gap-2">
                            <div className="w-1/4 min-w-0">
                              <label className="text-xs text-muted-foreground">Label</label>
                              <Input
                                value={credLabel}
                                onChange={(e) => setCredLabel(e.target.value)}
                                placeholder="e.g. Production M2M"
                                className="text-sm h-8"
                              />
                            </div>
                            <div className="w-1/4 min-w-0">
                              <label className="text-xs text-muted-foreground">Client ID</label>
                              <Input
                                value={credClientId}
                                onChange={(e) => setCredClientId(e.target.value)}
                                placeholder="Client ID"
                                className="text-sm h-8"
                              />
                            </div>
                            <div className="w-1/2 min-w-0">
                              <label className="text-xs text-muted-foreground">Client Secret</label>
                              <Input
                                type="password"
                                value={credClientSecret}
                                onChange={(e) => setCredClientSecret(e.target.value)}
                                placeholder="Client Secret (optional)"
                                className="text-sm h-8"
                              />
                            </div>
                          </div>
                          <div className="flex gap-2">
                            <Button
                              size="sm"
                              className="h-7 text-xs"
                              onClick={() => handleCreateCredential(config.id)}
                              disabled={credSubmitting || !credLabel.trim() || !credClientId.trim()}
                            >
                              {credSubmitting ? "Saving..." : "Save"}
                            </Button>
                            <Button
                              size="sm"
                              variant="ghost"
                              className="h-7 text-xs"
                              onClick={() => setShowAddCred(null)}
                            >
                              Cancel
                            </Button>
                          </div>
                        </div>
                      )}

                      {credentials[config.id]?.length ? (
                        <div className="space-y-1">
                          {credentials[config.id]!.map((cred) => (
                            <div
                              key={cred.id}
                              className="flex items-center justify-between rounded border bg-input-bg px-3 py-1.5 text-xs"
                            >
                              <div className="flex items-center gap-3">
                                <span className="font-medium">{cred.label}</span>
                                <span className="text-muted-foreground font-mono">{cred.client_id}</span>
                                {cred.has_secret && (
                                  <span className="rounded-full border border-border bg-accent px-1.5 py-0.5 text-[10px] text-muted-foreground">
                                    secret stored
                                  </span>
                                )}
                              </div>
                              {!readOnly && (
                                <div>
                                  {confirmDeleteCredId?.authId === config.id && confirmDeleteCredId?.credId === cred.id ? (
                                    <div className="flex items-center gap-1">
                                      <Button
                                        size="sm"
                                        variant="destructive"
                                        className="h-6 text-xs"
                                        onClick={() => handleDeleteCredential(config.id, cred.id)}
                                        disabled={credSubmitting}
                                      >
                                        Confirm
                                      </Button>
                                      <Button
                                        size="sm"
                                        variant="ghost"
                                        className="h-6 text-xs"
                                        onClick={() => setConfirmDeleteCredId(null)}
                                      >
                                        Cancel
                                      </Button>
                                    </div>
                                  ) : (
                                    <Button
                                      size="sm"
                                      variant="ghost"
                                      className="h-6 w-6 p-0"
                                      onClick={() => setConfirmDeleteCredId({ authId: config.id, credId: cred.id })}
                                    >
                                      <Trash2 className="h-3 w-3" />
                                    </Button>
                                  )}
                                </div>
                              )}
                            </div>
                          ))}
                        </div>
                      ) : credentials[config.id] ? (
                        <p className="text-xs text-muted-foreground">No credentials configured.</p>
                      ) : null}
                    </div>
                  </div>
                )}
              </CardContent>
            </Card>
          )}
        />
      )}
    </div>
  );
}
