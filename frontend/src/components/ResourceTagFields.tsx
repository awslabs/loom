import { useState, useEffect } from "react";
import { Badge } from "@/components/ui/badge";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import * as settingsApi from "@/api/settings";
import type { TagPolicy, TagProfile } from "@/api/types";

const SESSION_KEY = "loom:selectedTagProfileId";

interface ResourceTagFieldsProps {
  onChange: (tags: Record<string, string>) => void;
  profileId?: string;
  /** When set, only profiles whose loom:group matches this value are shown,
   *  and the resolved loom:group tag is forced to this value. */
  groupRestriction?: string;
  /** When set, only the profile whose loom:owner matches this value is shown,
   *  it is auto-selected, and the dropdown is replaced with a read-only display. */
  ownerRestriction?: string;
}

export function ResourceTagFields({ onChange, profileId: controlledProfileId, groupRestriction, ownerRestriction }: ResourceTagFieldsProps) {
  const [tagPolicies, setTagPolicies] = useState<TagPolicy[]>([]);
  const [profiles, setProfiles] = useState<TagProfile[]>([]);
  const [selectedProfileId, setSelectedProfileId] = useState<string>(() => {
    return sessionStorage.getItem(SESSION_KEY) || "";
  });

  // Sync with controlled profileId from parent
  useEffect(() => {
    if (controlledProfileId !== undefined) {
      setSelectedProfileId(controlledProfileId);
      if (controlledProfileId) {
        sessionStorage.setItem(SESSION_KEY, controlledProfileId);
      } else {
        sessionStorage.removeItem(SESSION_KEY);
      }
    }
  }, [controlledProfileId]);

  useEffect(() => {
    void settingsApi.listTagPolicies().then(setTagPolicies).catch(() => {});
    void settingsApi.listTagProfiles().then(setProfiles).catch(() => {});
  }, []);

  // Filter profiles: first by group, then by owner if restricted
  const availableProfiles = profiles
    .filter((p) => !groupRestriction || p.tags["loom:group"] === groupRestriction)
    .filter((p) => !ownerRestriction || p.tags["loom:owner"] === ownerRestriction);

  // Auto-select the sole profile when owner is restricted
  useEffect(() => {
    if (ownerRestriction && availableProfiles.length === 1 && !selectedProfileId) {
      const id = availableProfiles[0]!.id.toString();
      setSelectedProfileId(id);
      sessionStorage.setItem(SESSION_KEY, id);
    }
  }, [ownerRestriction, availableProfiles, selectedProfileId]);

  // Resolve tags when profile or policies change
  useEffect(() => {
    const profile = availableProfiles.find((p) => p.id.toString() === selectedProfileId);
    const resolved: Record<string, string> = {};

    for (const tp of tagPolicies) {
      const profileVal = profile?.tags[tp.key];
      if (profileVal) {
        resolved[tp.key] = profileVal;
      } else if (tp.required && tp.default_value) {
        // Only fall back to default for required policies;
        // custom/optional tags should only appear when the profile explicitly sets them
        resolved[tp.key] = tp.default_value;
      }
    }

    // Force loom:group and loom:owner when restrictions are active
    if (groupRestriction) {
      resolved["loom:group"] = groupRestriction;
    }
    if (ownerRestriction) {
      resolved["loom:owner"] = ownerRestriction;
    }

    onChange(resolved);
  }, [selectedProfileId, availableProfiles, tagPolicies, groupRestriction]);

  const handleProfileChange = (value: string) => {
    setSelectedProfileId(value);
    if (value) {
      sessionStorage.setItem(SESSION_KEY, value);
    } else {
      sessionStorage.removeItem(SESSION_KEY);
    }
  };

  const requiredPolicies = tagPolicies.filter((tp) => tp.required);
  if (requiredPolicies.length === 0 && availableProfiles.length === 0) return null;

  const selectedProfile = availableProfiles.find((p) => p.id.toString() === selectedProfileId);

  return (
    <section className="space-y-3">
      <h4 className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
        Resource Tags
      </h4>
      <div className="flex items-end gap-3">
        <div className="w-1/3 min-w-0 space-y-1">
          <label className="text-xs text-muted-foreground">Tag Profile</label>
          {ownerRestriction && selectedProfile ? (
            <div className="flex h-9 items-center rounded-md border border-input bg-muted px-3 text-sm text-muted-foreground">
              {selectedProfile.name}
            </div>
          ) : (
            <Select value={selectedProfileId || ""} onValueChange={handleProfileChange}>
              <SelectTrigger className="w-full text-sm">
                <SelectValue placeholder="Select a tag profile..." />
              </SelectTrigger>
              <SelectContent>
                {availableProfiles.map((p) => (
                  <SelectItem key={p.id} value={p.id.toString()}>
                    {p.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          )}
        </div>
        {selectedProfile && tagPolicies.length > 0 && (
          <div className="flex flex-wrap gap-1.5 pb-1">
            {tagPolicies.map((tp) => {
              const val = selectedProfile.tags[tp.key];
              if (!val) return null;
              return (
                <Badge key={tp.key} variant="outline" className="text-[10px] px-1.5 py-0.5 font-normal">
                  {tp.key.replace(/^loom:/, "")}: {val}
                </Badge>
              );
            })}
          </div>
        )}
      </div>
      {!selectedProfileId && requiredPolicies.some((tp) => tp.required) && (
        <p className="text-[10px] text-amber-600 dark:text-amber-400">
          No tag profile selected. Required tags will use default values or &quot;missing&quot;.
        </p>
      )}
    </section>
  );
}
