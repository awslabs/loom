import { useState, useEffect, useCallback } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { Plus, Pencil, Trash2, Lock, ChevronDown, ChevronRight } from "lucide-react";
import { toast } from "sonner";
import { useAuth } from "@/contexts/AuthContext";
import { trackAction } from "@/api/audit";
import { JsonConfigSection } from "@/components/JsonConfigSection";
import { SortableCardGrid, SortButton, loadSortDirection, toggleSortDirection, saveSortDirection, type SortDirection } from "@/components/SortableCardGrid";
import {
  listTagPolicies,
  listTagProfiles,
  createTagPolicy,
  updateTagPolicy,
  deleteTagPolicy,
  createTagProfile,
  updateTagProfile,
  deleteTagProfile,
} from "@/api/settings";
import type { TagPolicy, TagProfile } from "@/api/types";

interface TaggingPageProps {
  readOnly?: boolean;
  userGroups?: string[];
}

export function TaggingPage({ readOnly, userGroups = [] }: TaggingPageProps) {
  const { user, browserSessionId } = useAuth();
  const isSuperAdmin = userGroups.includes("g-admins-super");
  const isAdminUser = userGroups.includes("t-admin");
  const userGroup = userGroups.find((g) => g.startsWith("g-users-"))?.replace("g-users-", "");
  const [tagPolicies, setTagPolicies] = useState<TagPolicy[]>([]);
  const [profiles, setProfiles] = useState<TagProfile[]>([]);
  const [loading, setLoading] = useState(true);
  const [policySortDir, setPolicySortDir] = useState<SortDirection>(() => loadSortDirection("tag-policies"));
  const [profileSortDir, setProfileSortDir] = useState<SortDirection>(() => loadSortDirection("tag-profiles"));

  // Policy form state
  const [showPolicyForm, setShowPolicyForm] = useState(false);
  const [editingPolicyId, setEditingPolicyId] = useState<number | null>(null);
  const [policyFormKey, setPolicyFormKey] = useState("");
  const [policyFormDefault, setPolicyFormDefault] = useState("");
  const [policyFormShowOnCard, setPolicyFormShowOnCard] = useState(true);
  const [confirmDeletePolicyId, setConfirmDeletePolicyId] = useState<number | null>(null);

  // Profile form state
  const [showProfileForm, setShowProfileForm] = useState(false);
  const [editingProfileId, setEditingProfileId] = useState<number | null>(null);
  const [profileFormName, setProfileFormName] = useState("");
  const [profileFormTags, setProfileFormTags] = useState<Record<string, string>>({});
  const [profileEnabledCustomKeys, setProfileEnabledCustomKeys] = useState<Set<string>>(new Set());
  const [submitting, setSubmitting] = useState(false);
  const [confirmDeleteProfileId, setConfirmDeleteProfileId] = useState<number | null>(null);
  const [collapsedGroups, setCollapsedGroups] = useState<Set<string>>(new Set());

  const fetchData = useCallback(async () => {
    try {
      const [policies, profs] = await Promise.all([listTagPolicies(), listTagProfiles()]);
      setTagPolicies(policies);
      setProfiles(profs);
    } catch {
      toast.error("Failed to load tagging data");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void fetchData();
  }, [fetchData]);

  const platformPolicies = tagPolicies.filter((tp) => tp.designation === "platform:required");
  const customPolicies = tagPolicies.filter((tp) => tp.designation === "custom:optional");

  // --- Policy CRUD ---
  const resetPolicyForm = () => {
    setPolicyFormKey("");
    setPolicyFormDefault("");
    setPolicyFormShowOnCard(true);
    setEditingPolicyId(null);
    setShowPolicyForm(false);
  };

  const startEditPolicy = (policy: TagPolicy) => {
    setEditingPolicyId(policy.id);
    setPolicyFormKey(policy.key);
    setPolicyFormDefault(policy.default_value || "");
    setPolicyFormShowOnCard(policy.show_on_card);
    setShowPolicyForm(true);
  };

  const handlePolicySubmit = async () => {
    if (!editingPolicyId && !policyFormKey.trim()) return;
    setSubmitting(true);
    try {
      if (editingPolicyId) {
        if (user && browserSessionId) trackAction(user.username ?? user.sub, browserSessionId, 'tagging', 'edit_tag', policyFormKey);
        const existing = tagPolicies.find((tp) => tp.id === editingPolicyId);
        await updateTagPolicy(editingPolicyId, {
          key: policyFormKey,
          default_value: policyFormDefault || undefined,
          required: existing?.required ?? false,
          show_on_card: policyFormShowOnCard,
        });
        toast.success("Tag policy updated");
      } else {
        if (user && browserSessionId) trackAction(user.username ?? user.sub, browserSessionId, 'tagging', 'add_tag', policyFormKey.trim());
        await createTagPolicy({
          key: policyFormKey.trim(),
          default_value: policyFormDefault || undefined,
          required: false,
          show_on_card: policyFormShowOnCard,
        });
        toast.success("Tag policy created");
      }
      resetPolicyForm();
      void fetchData();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Failed to save tag policy");
    } finally {
      setSubmitting(false);
    }
  };

  const handlePolicyDelete = async (id: number) => {
    const policy = tagPolicies.find((tp) => tp.id === id);
    if (policy && user && browserSessionId) trackAction(user.username ?? user.sub, browserSessionId, 'tagging', 'delete_tag', policy.key);
    if (policy) {
      const usingProfiles = profiles.filter((p) => p.tags[policy.key]);
      if (usingProfiles.length > 0) {
        const names = usingProfiles.map((p) => p.name).join(", ");
        toast.error(`Cannot delete: tag is used by profile(s): ${names}. Remove the tag from those profiles first.`);
        setConfirmDeletePolicyId(null);
        return;
      }
    }
    setSubmitting(true);
    try {
      await deleteTagPolicy(id);
      setConfirmDeletePolicyId(null);
      toast.success("Tag policy deleted");
      void fetchData();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Failed to delete tag policy");
    } finally {
      setSubmitting(false);
    }
  };

  // --- Profile CRUD ---
  const resetProfileForm = () => {
    setProfileFormName("");
    setProfileFormTags({});
    setProfileEnabledCustomKeys(new Set());
    setEditingProfileId(null);
    setShowProfileForm(false);
  };

  const startEditProfile = (profile: TagProfile) => {
    setEditingProfileId(profile.id);
    setProfileFormName(profile.name);
    setProfileFormTags({ ...profile.tags });
    const enabledKeys = new Set<string>();
    for (const cp of customPolicies) {
      if (profile.tags[cp.key]) enabledKeys.add(cp.key);
    }
    setProfileEnabledCustomKeys(enabledKeys);
    setShowProfileForm(true);
  };

  const startCreateProfile = () => {
    resetProfileForm();
    const initial: Record<string, string> = {};
    for (const tp of platformPolicies) {
      initial[tp.key] = tp.default_value || "";
    }
    setProfileFormTags(initial);
    setShowProfileForm(true);
  };

  const handleProfileSubmit = async () => {
    if (!profileFormName.trim()) return;
    const finalTags: Record<string, string> = {};
    for (const tp of platformPolicies) {
      const val = profileFormTags[tp.key];
      if (val) finalTags[tp.key] = val;
    }
    for (const key of profileEnabledCustomKeys) {
      const val = profileFormTags[key];
      if (val) finalTags[key] = val;
    }
    setSubmitting(true);
    try {
      if (editingProfileId) {
        if (user && browserSessionId) trackAction(user.username ?? user.sub, browserSessionId, 'tagging', 'edit_profile', profileFormName.trim());
        await updateTagProfile(editingProfileId, { name: profileFormName.trim(), tags: finalTags });
        toast.success("Tag profile updated");
      } else {
        if (user && browserSessionId) trackAction(user.username ?? user.sub, browserSessionId, 'tagging', 'add_profile', profileFormName.trim());
        await createTagProfile({ name: profileFormName.trim(), tags: finalTags });
        toast.success("Tag profile created");
      }
      resetProfileForm();
      void fetchData();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Failed to save tag profile");
    } finally {
      setSubmitting(false);
    }
  };

  const handleProfileDelete = async (id: number) => {
    setSubmitting(true);
    try {
      const profileName = profiles.find(p => p.id === id)?.name ?? String(id);
      if (user && browserSessionId) trackAction(user.username ?? user.sub, browserSessionId, 'tagging', 'delete_profile', profileName);
      await deleteTagProfile(id);
      setConfirmDeleteProfileId(null);
      toast.success("Tag profile deleted");
      void fetchData();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Failed to delete tag profile");
    } finally {
      setSubmitting(false);
    }
  };

  const toggleCustomKey = (key: string) => {
    setProfileEnabledCustomKeys((prev) => {
      const next = new Set(prev);
      if (next.has(key)) {
        next.delete(key);
        setProfileFormTags((tags) => {
          const updated = { ...tags };
          delete updated[key];
          return updated;
        });
      } else {
        next.add(key);
        const policy = customPolicies.find((p) => p.key === key);
        if (policy?.default_value) {
          setProfileFormTags((tags) => ({ ...tags, [key]: policy.default_value! }));
        }
      }
      return next;
    });
  };

  if (loading) {
    return (
      <div className="space-y-6">
        <div>
          <h2 className="text-lg font-semibold">Tagging</h2>
          <p className="text-sm text-muted-foreground">Manage tag policies and tag profiles.</p>
        </div>
        <div className="space-y-3">
          {Array.from({ length: 3 }).map((_, i) => (
            <Skeleton key={i} className="h-16" />
          ))}
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-lg font-semibold">Tagging</h2>
        <p className="text-sm text-muted-foreground">Manage tag policies and tag profiles.</p>
      </div>

      {/* Tags Section */}
      <div className="space-y-4">
        <div className="flex items-center justify-between">
          <div>
            <h3 className="text-sm font-medium">Tags</h3>
            <p className="text-xs text-muted-foreground mt-1">
              Platform tags are required for all resources. Custom tags are optional and can be included in profiles.
            </p>
          </div>
          <div className="flex items-center gap-2 shrink-0 ml-4">
            <SortButton direction={policySortDir} onClick={() => setPolicySortDir(toggleSortDirection("tag-policies", policySortDir))} />
            {!readOnly && (
              <Button
                size="sm"
                variant="outline"
                onClick={() => { resetPolicyForm(); setShowPolicyForm(true); }}
              >
                <Plus className="h-3.5 w-3.5 mr-1" />
                Add Custom Tag
              </Button>
            )}
          </div>
        </div>

        {showPolicyForm && (
          <Card>
            <CardContent className="pt-4 space-y-3">
              <JsonConfigSection
                  hideApply={!!editingPolicyId}
                  placeholder='{ "key": "cost-center", "default_value": "engineering", "show_on_card": true }'
                  onApply={(json) => {
                    let parsed: unknown;
                    try { parsed = JSON.parse(json); } catch { return "Invalid JSON"; }
                    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) return "Expected a JSON object";
                    const row = parsed as Record<string, unknown>;
                    if (typeof row.key !== "string" || !row.key.trim()) return "Missing required field: key";
                    setPolicyFormKey(row.key.trim());
                    setPolicyFormDefault(typeof row.default_value === "string" ? row.default_value : "");
                    setPolicyFormShowOnCard(typeof row.show_on_card === "boolean" ? row.show_on_card : true);
                    return null;
                  }}
                  onExport={() => {
                    if (editingPolicyId) {
                      const p = tagPolicies.find((tp) => tp.id === editingPolicyId);
                      if (!p) return "{}";
                      return JSON.stringify({ key: p.key, ...(p.default_value ? { default_value: p.default_value } : {}), show_on_card: p.show_on_card }, null, 2);
                    }
                    return JSON.stringify(
                      customPolicies.map((p) => ({
                        key: p.key,
                        ...(p.default_value ? { default_value: p.default_value } : {}),
                        show_on_card: p.show_on_card,
                      })),
                      null, 2
                    );
                  }}
                />
              <div className="flex gap-3">
                {editingPolicyId ? (
                  <div className="w-1/3 min-w-0 space-y-1">
                    <label className="text-xs text-muted-foreground">Key</label>
                    <Input value={policyFormKey} disabled className="text-sm" />
                  </div>
                ) : (
                  <div className="w-1/3 min-w-0 space-y-1">
                    <label className="text-xs text-muted-foreground">Key *</label>
                    <Input
                      value={policyFormKey}
                      onChange={(e) => setPolicyFormKey(e.target.value)}
                      placeholder="e.g. cost-center"
                      maxLength={128}
                      className="text-sm"
                    />
                  </div>
                )}
                <div className="w-1/3 min-w-0 space-y-1">
                  <label className="text-xs text-muted-foreground">Default Value</label>
                  <Input
                    value={policyFormDefault}
                    onChange={(e) => setPolicyFormDefault(e.target.value)}
                    placeholder="Optional default"
                    maxLength={128}
                    className="text-sm"
                  />
                </div>
                <div className="flex items-end pb-1">
                  <label className="flex items-center gap-2 cursor-pointer select-none text-xs text-muted-foreground">
                    <input
                      type="checkbox"
                      checked={policyFormShowOnCard}
                      onChange={(e) => setPolicyFormShowOnCard(e.target.checked)}
                      className="h-3.5 w-3.5"
                    />
                    Show on card
                  </label>
                </div>
              </div>
              <div className="flex items-center gap-2 pt-1">
                <Button
                  size="sm"
                  className="min-w-[100px]"
                  onClick={handlePolicySubmit}
                  disabled={submitting || (!editingPolicyId && !policyFormKey.trim())}
                >
                  {submitting ? "Saving..." : editingPolicyId ? "Update" : "Create"}
                </Button>
                <Button size="sm" variant="ghost" onClick={resetPolicyForm}>
                  Cancel
                </Button>
                <Badge variant="outline" className="text-[10px] px-1.5 py-0 font-normal ml-2">
                  custom:optional
                </Badge>
              </div>
            </CardContent>
          </Card>
        )}

        {tagPolicies.length === 0 && !showPolicyForm ? (
          <p className="text-sm text-muted-foreground py-4">No tag policies defined.</p>
        ) : (
          <SortableCardGrid
            items={tagPolicies}
            getId={(p) => p.id.toString()}
            getName={(p) => `${p.designation === "platform:required" ? "0" : "1"}:${p.key}`}
            storageKey="tag-policies"
            sortDirection={policySortDir}
            onSortDirectionChange={(d) => { if (d) { setPolicySortDir(d); saveSortDirection("tag-policies", d); } }}
            className="grid gap-2 md:grid-cols-2 lg:grid-cols-3"
            renderItem={(policy) =>
              policy.designation === "platform:required" ? (
                <Card className="relative py-3 gap-1 transition-colors hover:bg-accent/50">
                  <CardHeader className="gap-1 pb-2">
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-sm font-medium truncate min-w-0">{policy.key}</span>
                      <div className="flex items-center gap-1 shrink-0">
                        <Lock className="h-3.5 w-3.5 text-muted-foreground/50" />
                      </div>
                    </div>
                  </CardHeader>
                  <CardContent className="flex flex-wrap gap-1">
                    <Badge variant="outline" className="text-[10px] px-1.5 py-0 font-normal">
                      platform:required
                    </Badge>
                    <Badge variant="outline" className="text-[10px] px-1.5 py-0 font-normal">
                      {policy.show_on_card ? "displayed on cards" : "not displayed on cards"}
                    </Badge>
                  </CardContent>
                </Card>
              ) : (
                <Card className="relative py-3 gap-1 transition-colors hover:bg-accent/50">
                  <CardHeader className="gap-1 pb-2">
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-sm font-medium truncate min-w-0">{policy.key}</span>
                      {!readOnly && isSuperAdmin && (
                        <div className="flex items-center gap-1 shrink-0">
                          <button
                            type="button"
                            onClick={() => startEditPolicy(policy)}
                            className="text-muted-foreground/50 hover:text-foreground transition-colors"
                            title="Edit"
                          >
                            <Pencil className="h-3.5 w-3.5" />
                          </button>
                          <button
                            type="button"
                            onClick={() => setConfirmDeletePolicyId(policy.id)}
                            className="text-muted-foreground/50 hover:text-destructive transition-colors"
                            title="Delete"
                          >
                            <Trash2 className="h-3.5 w-3.5" />
                          </button>
                        </div>
                      )}
                    </div>
                  </CardHeader>
                  <CardContent className="space-y-1.5">
                    {policy.default_value && (
                      <div className="text-[10px] text-muted-foreground truncate">default: {policy.default_value}</div>
                    )}
                    <div className="flex flex-wrap gap-1">
                      <Badge variant="outline" className="text-[10px] px-1.5 py-0 font-normal">
                        custom:optional
                      </Badge>
                      <Badge variant="outline" className="text-[10px] px-1.5 py-0 font-normal">
                        {policy.show_on_card ? "displayed on cards" : "not displayed on cards"}
                      </Badge>
                    </div>
                    {confirmDeletePolicyId === policy.id && (
                      <div className="flex items-center justify-end gap-2 pt-1">
                        <Button
                          size="sm"
                          variant="ghost"
                          className="h-6 text-xs"
                          onClick={() => setConfirmDeletePolicyId(null)}
                        >
                          Cancel
                        </Button>
                        <Button
                          size="sm"
                          variant="destructive"
                          className="h-6 text-xs"
                          onClick={() => handlePolicyDelete(policy.id)}
                          disabled={submitting}
                        >
                          Confirm
                        </Button>
                      </div>
                    )}
                  </CardContent>
                </Card>
              )
            }
          />
        )}
      </div>

      {/* Tag Profiles Section */}
      <div className="space-y-4">
        <div className="flex items-center justify-between">
          <div>
            <h3 className="text-sm font-medium">Tag Profiles</h3>
            <p className="text-xs text-muted-foreground mt-1">
              Tag profiles are named sets of tag values applied to resources deployed by Loom.
            </p>
          </div>
          <div className="flex items-center gap-2 shrink-0 ml-4">
            <SortButton direction={profileSortDir} onClick={() => setProfileSortDir(toggleSortDirection("tag-profiles", profileSortDir))} />
            {!readOnly && (
              <Button
                size="sm"
                variant="outline"
                onClick={startCreateProfile}
              >
                <Plus className="h-3.5 w-3.5 mr-1" />
                Add Profile
              </Button>
            )}
          </div>
        </div>

        {showProfileForm && (
          <Card>
            <CardContent className="pt-4 space-y-4">
              <JsonConfigSection
                  hideApply={!!editingProfileId}
                  placeholder='{ "name": "team-alpha", "tags": { "loom:application": "app", "loom:group": "alpha", "loom:owner": "user1" } }'
                  onApply={(json) => {
                    let parsed: unknown;
                    try { parsed = JSON.parse(json); } catch { return "Invalid JSON"; }
                    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) return "Expected a JSON object";
                    const row = parsed as Record<string, unknown>;
                    if (typeof row.name !== "string" || !row.name.trim()) return "Missing required field: name";
                    if (!row.tags || typeof row.tags !== "object" || Array.isArray(row.tags)) return "Missing required field: tags";
                    setProfileFormName(row.name.trim());
                    const tags = row.tags as Record<string, string>;
                    setProfileFormTags(tags);
                    const enabledKeys = new Set<string>();
                    for (const cp of customPolicies) {
                      if (tags[cp.key]) enabledKeys.add(cp.key);
                    }
                    setProfileEnabledCustomKeys(enabledKeys);
                    return null;
                  }}
                  onExport={() => {
                    if (editingProfileId) {
                      const p = profiles.find((pr) => pr.id === editingProfileId);
                      if (!p) return "{}";
                      return JSON.stringify({ name: p.name, tags: p.tags }, null, 2);
                    }
                    const visibleProfiles = !isAdminUser && userGroup
                      ? profiles.filter((p) => p.tags?.["loom:group"] === userGroup)
                      : profiles;
                    return JSON.stringify(visibleProfiles.map((p) => ({ name: p.name, tags: p.tags })), null, 2);
                  }}
                />

              <div className="space-y-1">
                <label className="text-xs text-muted-foreground">Profile Name *</label>
                <Input
                  value={profileFormName}
                  onChange={(e) => setProfileFormName(e.target.value)}
                  placeholder="e.g. Team Alpha - Production"
                  maxLength={128}
                  className="w-1/3"
                />
              </div>

              {platformPolicies.length > 0 && (
                <div className="space-y-2">
                  <div className="flex items-center gap-2">
                    <label className="text-xs font-medium text-muted-foreground">Platform (Required)</label>
                    <Badge variant="outline" className="text-[10px] px-1.5 py-0 font-normal">platform:required</Badge>
                  </div>
                  <div className="flex gap-3">
                    {platformPolicies.map((tp) => (
                      <div key={tp.key} className="flex-1 min-w-0 space-y-1">
                        <label className="text-xs text-muted-foreground">
                          {tp.key}
                          <span className="text-destructive"> *</span>
                        </label>
                        <Input
                          placeholder={
                            tp.key === "loom:application"
                              ? "Identifier for the application"
                              : tp.key === "loom:group"
                                ? "Identifier for the group or team"
                                : tp.key === "loom:owner"
                                  ? "Identifier or email alias for the owner"
                                  : tp.default_value || `Enter ${tp.key}`
                          }
                          value={profileFormTags[tp.key] || ""}
                          onChange={(e) =>
                            setProfileFormTags((prev) => ({ ...prev, [tp.key]: e.target.value }))
                          }
                          maxLength={128}
                          className="text-sm"
                        />
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {customPolicies.length > 0 && (
                <div className="space-y-2">
                  <div className="flex items-center gap-2">
                    <label className="text-xs font-medium text-muted-foreground">Custom (Optional)</label>
                    <Badge variant="outline" className="text-[10px] px-1.5 py-0 font-normal">custom:optional</Badge>
                  </div>
                  <div className="space-y-2">
                    {customPolicies.map((tp) => {
                      const enabled = profileEnabledCustomKeys.has(tp.key);
                      return (
                        <div key={tp.key} className="flex items-center gap-3">
                          <label className="flex items-center gap-2 cursor-pointer select-none min-w-[160px]">
                            <input
                              type="checkbox"
                              checked={enabled}
                              onChange={() => toggleCustomKey(tp.key)}
                              className="h-3.5 w-3.5"
                            />
                            <span className="text-xs text-muted-foreground">{tp.key}</span>
                          </label>
                          {enabled && (
                            <Input
                              placeholder={tp.default_value || `Enter ${tp.key}`}
                              value={profileFormTags[tp.key] || ""}
                              onChange={(e) =>
                                setProfileFormTags((prev) => ({ ...prev, [tp.key]: e.target.value }))
                              }
                              maxLength={128}
                              className="text-sm flex-1"
                            />
                          )}
                        </div>
                      );
                    })}
                  </div>
                </div>
              )}

              <div className="flex items-center gap-2 pt-1">
                <Button
                  size="sm"
                  className="min-w-[100px]"
                  onClick={handleProfileSubmit}
                  disabled={submitting || !profileFormName.trim()}
                >
                  {submitting ? "Saving..." : editingProfileId ? "Update" : "Create"}
                </Button>
                <Button size="sm" variant="ghost" onClick={resetProfileForm}>
                  Cancel
                </Button>
              </div>
            </CardContent>
          </Card>
        )}

        {(() => {
          const visibleProfiles = !isAdminUser && userGroup
            ? profiles.filter((p) => p.tags?.["loom:group"] === userGroup)
            : profiles;
          if (visibleProfiles.length === 0 && !showProfileForm) {
            return (
              <p className="text-sm text-muted-foreground py-8">
                No tag profiles yet. Create one to apply consistent tags across agents and memory resources.
              </p>
            );
          }
          const grouped = new Map<string, TagProfile[]>();
          for (const p of visibleProfiles) {
            const group = p.tags?.["loom:group"] || "ungrouped";
            const list = grouped.get(group);
            if (list) list.push(p);
            else grouped.set(group, [p]);
          }
          const sortedGroups = [...grouped.entries()].sort((a, b) =>
            a[0] === "ungrouped" ? 1 : b[0] === "ungrouped" ? -1 : a[0].localeCompare(b[0])
          );
          const toggleGroup = (group: string) => {
            setCollapsedGroups((prev) => {
              const next = new Set(prev);
              if (next.has(group)) next.delete(group);
              else next.add(group);
              return next;
            });
          };
          return sortedGroups.map(([group, groupProfiles]) => (
            <div key={group} className="space-y-2">
              <button
                type="button"
                onClick={() => toggleGroup(group)}
                className="flex items-center gap-1 text-xs font-medium text-muted-foreground uppercase tracking-wide hover:text-foreground"
              >
                {collapsedGroups.has(group) ? <ChevronRight className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
                {group} ({groupProfiles.length})
              </button>
              {collapsedGroups.has(group) ? null : <SortableCardGrid
                items={groupProfiles}
                getId={(p) => p.id.toString()}
                getName={(p) => p.name}
                storageKey={`tag-profiles-${group}`}
                sortDirection={profileSortDir}
                onSortDirectionChange={(d) => { if (d) { setProfileSortDir(d); saveSortDirection("tag-profiles", d); } }}
                className="grid gap-2 md:grid-cols-2 lg:grid-cols-3"
                renderItem={(profile) => {
                  const profileGroup = profile.tags?.["loom:group"] || "";
                  const isDemoAdmin = userGroups.includes("g-admins-demo") && !isSuperAdmin;
                  const canEditProfile = !readOnly && (isSuperAdmin || (isDemoAdmin && profileGroup === "demo"));

                  return (
                    <Card className="relative py-3 gap-1 transition-colors hover:bg-accent/50">
                      <CardHeader className="gap-1 pb-2">
                        <div className="flex items-center justify-between gap-2">
                          <span className="text-sm font-medium truncate min-w-0">{profile.name}</span>
                          {canEditProfile && (
                            <div className="flex items-center gap-1 shrink-0">
                              <button
                                type="button"
                                onClick={() => startEditProfile(profile)}
                                className="text-muted-foreground/50 hover:text-foreground transition-colors"
                                title="Edit"
                              >
                                <Pencil className="h-3.5 w-3.5" />
                              </button>
                              <button
                                type="button"
                                onClick={() => setConfirmDeleteProfileId(profile.id)}
                                className="text-muted-foreground/50 hover:text-destructive transition-colors"
                                title="Delete"
                              >
                                <Trash2 className="h-3.5 w-3.5" />
                              </button>
                            </div>
                          )}
                        </div>
                      </CardHeader>
                      <CardContent className="space-y-1.5">
                        <div className="flex flex-wrap gap-1">
                          {Object.entries(profile.tags).map(([key, value]) => (
                            <Badge
                              key={key}
                              variant="outline"
                              className="text-[10px] px-1.5 py-0 font-normal"
                            >
                              {key.replace(/^loom:/, "")}: {value}
                            </Badge>
                          ))}
                        </div>
                        {confirmDeleteProfileId === profile.id && (
                          <div className="flex items-center justify-end gap-2 pt-1">
                            <Button
                              size="sm"
                              variant="ghost"
                              className="h-6 text-xs"
                              onClick={() => setConfirmDeleteProfileId(null)}
                            >
                              Cancel
                            </Button>
                            <Button
                              size="sm"
                              variant="destructive"
                              className="h-6 text-xs"
                              onClick={() => handleProfileDelete(profile.id)}
                              disabled={submitting}
                            >
                              Confirm
                            </Button>
                          </div>
                        )}
                      </CardContent>
                    </Card>
                  );
                }}
              />}
            </div>
          ));
        })()}
      </div>
    </div>
  );
}
