import { useState, useEffect } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { toast } from "sonner";
import type { ConfigEntry } from "@/api/types";

const MASKED = "********";

interface EditableEntry {
  key: string;
  value: string;
  is_secret: boolean;
  isNew?: boolean;
  modified?: boolean;
}

interface ConfigurationEditorProps {
  config: ConfigEntry[];
  loading: boolean;
  onSave: (config: Record<string, string>) => Promise<unknown>;
}

export function ConfigurationEditor({ config, loading, onSave }: ConfigurationEditorProps) {
  const [entries, setEntries] = useState<EditableEntry[]>([]);
  const [saving, setSaving] = useState(false);
  const [dirty, setDirty] = useState(false);

  useEffect(() => {
    setEntries(
      config.map((c) => ({
        key: c.key,
        value: c.is_secret ? MASKED : c.value,
        is_secret: c.is_secret,
        modified: false,
      })),
    );
    setDirty(false);
  }, [config]);

  const addEntry = () => {
    setEntries([...entries, { key: "", value: "", is_secret: false, isNew: true, modified: true }]);
    setDirty(true);
  };

  const updateEntry = (index: number, field: keyof EditableEntry, val: string | boolean) => {
    setEntries((prev) =>
      prev.map((entry, i) => (i === index ? { ...entry, [field]: val, modified: true } : entry)),
    );
    setDirty(true);
  };

  const removeEntry = (index: number) => {
    setEntries(entries.filter((_, i) => i !== index));
    setDirty(true);
  };

  const handleSave = async () => {
    setSaving(true);
    try {
      const toSave: Record<string, string> = {};
      for (const e of entries) {
        if (!e.key.trim()) continue;
        // Skip unchanged masked secret entries
        if (e.is_secret && !e.modified && e.value === MASKED) continue;
        toSave[e.key.trim()] = e.value;
      }
      await onSave(toSave);
      setDirty(false);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Failed to save configuration");
    } finally {
      setSaving(false);
    }
  };

  return (
    <Card>
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <CardTitle className="text-sm font-medium">Configuration</CardTitle>
          <div className="flex gap-2">
            <Button size="sm" variant="outline" onClick={addEntry}>
              + Add Entry
            </Button>
            <Button
              size="sm"
              onClick={handleSave}
              disabled={saving || !dirty || loading}
            >
              {saving ? "Saving..." : "Save Configuration"}
            </Button>
          </div>
        </div>
      </CardHeader>
      <CardContent>
        {entries.length === 0 ? (
          <div className="text-sm text-muted-foreground text-center py-4">
            No configuration entries. Click &quot;Add Entry&quot; to add one.
          </div>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-[200px]">Key</TableHead>
                <TableHead>Value</TableHead>
                <TableHead className="w-[80px] text-center">Secret</TableHead>
                <TableHead className="w-[60px]" />
              </TableRow>
            </TableHeader>
            <TableBody>
              {entries.map((entry, i) => (
                <TableRow key={i}>
                  <TableCell>
                    <Input
                      value={entry.key}
                      onChange={(e) => updateEntry(i, "key", e.target.value)}
                      placeholder="KEY_NAME"
                      className="h-8 text-xs font-mono"
                    />
                  </TableCell>
                  <TableCell>
                    <Input
                      type={entry.is_secret && !entry.isNew ? "password" : "text"}
                      value={entry.value}
                      onChange={(e) => updateEntry(i, "value", e.target.value)}
                      placeholder={entry.is_secret && !entry.isNew ? MASKED : "value"}
                      className="h-8 text-xs font-mono"
                    />
                  </TableCell>
                  <TableCell className="text-center">
                    <input
                      type="checkbox"
                      checked={entry.is_secret}
                      onChange={(e) => updateEntry(i, "is_secret", e.target.checked)}
                      className="h-4 w-4"
                    />
                  </TableCell>
                  <TableCell>
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={() => removeEntry(i)}
                      className="h-8 w-8 p-0"
                    >
                      &times;
                    </Button>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </CardContent>
    </Card>
  );
}
