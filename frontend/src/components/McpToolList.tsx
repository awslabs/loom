import { useState, useEffect, useCallback } from "react";
import { Button } from "@/components/ui/button";


import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import { Loader2, RefreshCw, ChevronRight, ChevronDown, Play, ArrowLeft } from "lucide-react";
import { toast } from "sonner";
import { useAuth } from "@/contexts/AuthContext";
import { trackAction } from "@/api/audit";
import { useTimezone } from "@/contexts/TimezoneContext";
import { formatTimestamp, formatRelativeDateTime } from "@/lib/format";
import { getServerTools, refreshServerTools, invokeServerTool } from "@/api/mcp";
import { listApprovalPolicies } from "@/api/approvals";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { SortButton, loadSortDirection, toggleSortDirection, type SortDirection } from "./SortableCardGrid";
import type { McpTool, ToolInvokeResult, ApprovalPolicy } from "@/api/types";

/** Does an approval policy's tool_match_rules entry match this tool name?
 *  Rules are globs such as "delete_*", so only "*" is special. */
function matchesRule(rule: string, toolName: string): boolean {
  const pattern = rule
    .split("*")
    .map((part) => part.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"))
    .join(".*");
  return new RegExp(`^${pattern}$`, "i").test(toolName);
}

/** Collapsible wrapper for nested arrays/objects in tool results. */
function CollapsibleValue({ label, summary, children }: { label?: string; summary: string; children: React.ReactNode }) {
  const [open, setOpen] = useState(true);
  // Increment generation on re-expand so children remount in their default (expanded) state
  const [generation, setGeneration] = useState(0);
  return (
    <div className="text-xs">
      <button
        type="button"
        onClick={() => {
          if (!open) setGeneration((g) => g + 1);
          setOpen(!open);
        }}
        className="flex items-center gap-0.5 text-muted-foreground hover:text-foreground transition-colors"
      >
        {open ? <ChevronDown className="h-3 w-3 shrink-0" /> : <ChevronRight className="h-3 w-3 shrink-0" />}
        {label && <span className="text-muted-foreground/70">{label}:</span>}
        {!open && <span className="ml-0.5 text-muted-foreground/50">{summary}</span>}
      </button>
      {open && <div key={generation}>{children}</div>}
    </div>
  );
}

interface McpToolListProps {
  serverId: number;
  readOnly?: boolean;
}

export function McpToolList({ serverId, readOnly }: McpToolListProps) {
  const { timezone } = useTimezone();
  const { user, browserSessionId } = useAuth();
  const [tools, setTools] = useState<McpTool[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [sortDir, setSortDir] = useState<SortDirection>(() => loadSortDirection(`mcp-tools-${serverId}`));

  // Tool invocation state
  const [selectedTool, setSelectedTool] = useState<McpTool | null>(null);
  const [invokeArgs, setInvokeArgs] = useState("");
  const [invoking, setInvoking] = useState(false);
  const [invokeResult, setInvokeResult] = useState<ToolInvokeResult | null>(null);
  const [filter, setFilter] = useState("");
  const [segment, setSegment] = useState<"all" | "approval">("all");
  const [showAll, setShowAll] = useState(false);
  const [policies, setPolicies] = useState<ApprovalPolicy[]>([]);

  // Approval policies are what make a tool "needs approval". Best-effort: the
  // list still renders if the caller lacks the scope to read them.
  useEffect(() => {
    listApprovalPolicies().then(setPolicies).catch(() => setPolicies([]));
  }, []);

  const fetchTools = useCallback(async () => {
    try {
      const data = await getServerTools(serverId);
      setTools(data);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Failed to fetch tools");
    } finally {
      setLoading(false);
    }
  }, [serverId]);

  useEffect(() => {
    void fetchTools();
  }, [fetchTools]);

  const handleRefresh = async () => {
    if (user && browserSessionId) trackAction(user.username ?? user.sub, browserSessionId, 'mcp', 'test_connection', String(serverId));
    setRefreshing(true);
    try {
      const data = await refreshServerTools(serverId);
      setTools(data);
      toast.success("Tools refreshed");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Failed to refresh tools");
    } finally {
      setRefreshing(false);
    }
  };

  const coerceArgs = (args: Record<string, unknown>, schema: Record<string, unknown> | null): Record<string, unknown> => {
    if (!schema) return args;
    const properties = schema.properties as Record<string, Record<string, unknown>> | undefined;
    if (!properties) return args;
    const coerced: Record<string, unknown> = { ...args };
    for (const [key, value] of Object.entries(coerced)) {
      if (typeof value !== "string" || !(key in properties)) continue;
      const propType = properties[key]?.type;
      if (propType === "integer" || propType === "number") {
        const num = Number(value);
        if (!isNaN(num) && value.trim() !== "") coerced[key] = propType === "integer" ? Math.trunc(num) : num;
      } else if (propType === "boolean") {
        if (value === "true") coerced[key] = true;
        else if (value === "false") coerced[key] = false;
      } else if (propType === "array" || propType === "object") {
        try { coerced[key] = JSON.parse(value); } catch { /* keep as string */ }
      }
    }
    return coerced;
  };

  const handleInvoke = async () => {
    if (!selectedTool) return;
    let parsedArgs: Record<string, unknown> = {};
    if (invokeArgs.trim()) {
      try {
        parsedArgs = JSON.parse(invokeArgs);
      } catch {
        toast.error("Invalid JSON arguments");
        return;
      }
    }
    parsedArgs = coerceArgs(parsedArgs, selectedTool.input_schema);
    if (user && browserSessionId) trackAction(user.username ?? user.sub, browserSessionId, 'mcp', 'invoke_tool', selectedTool.tool_name);
    setInvoking(true);
    setInvokeResult(null);
    try {
      const result = await invokeServerTool(serverId, {
        tool_name: selectedTool.tool_name,
        arguments: parsedArgs,
      });
      setInvokeResult(result);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Invocation failed");
    } finally {
      setInvoking(false);
    }
  };

  const handleSelectTool = (tool: McpTool) => {
    setSelectedTool(tool);
    setInvokeResult(null);
    // Pre-populate arguments from schema with type-appropriate defaults
    if (tool.input_schema?.properties) {
      const props = tool.input_schema.properties as Record<string, Record<string, unknown>>;
      const stub: Record<string, unknown> = {};
      for (const [key, prop] of Object.entries(props)) {
        switch (prop?.type) {
          case "integer": case "number": stub[key] = 0; break;
          case "boolean": stub[key] = false; break;
          case "array": stub[key] = []; break;
          case "object": stub[key] = {}; break;
          default: stub[key] = "";
        }
      }
      setInvokeArgs(JSON.stringify(stub, null, 2));
    } else {
      setInvokeArgs("{}");
    }
  };

  const lastRefreshed = tools.length > 0
    ? tools.reduce((latest, t) => {
        if (!t.last_refreshed_at) return latest;
        if (!latest) return t.last_refreshed_at;
        return t.last_refreshed_at > latest ? t.last_refreshed_at : latest;
      }, null as string | null)
    : null;

  if (loading) {
    return (
      <div className="space-y-3">
        {Array.from({ length: 3 }).map((_, i) => (
          <Skeleton key={i} className="h-12" />
        ))}
      </div>
    );
  }

  // Tool detail / invoke view
  if (selectedTool) {
    return (
      <div className="space-y-4">
        <div>
          <Button variant="ghost" size="sm" onClick={() => { setSelectedTool(null); setInvokeResult(null); }}>
            <ArrowLeft className="h-3.5 w-3.5 mr-1" />
            Back to tools
          </Button>
          <h4 className="text-sm font-semibold mt-1">{selectedTool.tool_name}</h4>
          {selectedTool.description && (
            <p className="text-xs text-muted-foreground mt-0.5">{selectedTool.description}</p>
          )}
        </div>

        {selectedTool.input_schema && (
          <div className="space-y-1">
            <button
              type="button"
              onClick={() => {
                const el = document.getElementById("tool-schema-section");
                if (el) el.classList.toggle("hidden");
              }}
              className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
            >
              <ChevronRight className="h-3 w-3 tool-schema-chevron" />
              Input Schema
            </button>
            <div id="tool-schema-section" className="hidden">
              <pre className="text-[11px] bg-input-bg rounded border p-2 overflow-x-auto">
                <code>{JSON.stringify(selectedTool.input_schema, null, 2)}</code>
              </pre>
            </div>
          </div>
        )}

        <div className="space-y-2">
          <label className="text-xs font-medium text-muted-foreground">Arguments (JSON)</label>
          <Textarea
            value={invokeArgs}
            onChange={(e) => setInvokeArgs(e.target.value)}
            placeholder="{}"
            rows={5}
            className="text-sm font-mono"
          />
          <Button size="sm" onClick={handleInvoke} disabled={invoking || readOnly}>
            {invoking ? (
              <>
                <Loader2 className="h-3.5 w-3.5 mr-1 animate-spin" />
                Invoking...
              </>
            ) : (
              <>
                <Play className="h-3.5 w-3.5 mr-1" />
                Invoke Tool
              </>
            )}
          </Button>
        </div>

        {invokeResult && (
          <div className="space-y-4">
            {/* Formatted content */}
            <div className="space-y-1">
              <h5 className="text-xs font-medium text-muted-foreground">
                Result {invokeResult.success ? (
                  <span className="text-green-600 dark:text-green-400">(success)</span>
                ) : (
                  <span className="text-red-600 dark:text-red-400">(error)</span>
                )}
              </h5>
              {invokeResult.success ? (
                <div className="rounded border bg-input-bg p-3 space-y-2">
                  {(() => {
                    const renderValue = (value: unknown, depth: number, label?: string): React.ReactNode => {
                      if (value === null || value === undefined) {
                        return label
                          ? <div className="text-xs"><span className="text-muted-foreground/70">{label}:</span> <span className="text-muted-foreground/50">null</span></div>
                          : <span className="text-muted-foreground/50">null</span>;
                      }
                      if (typeof value !== "object") {
                        return label
                          ? <div className="text-xs"><span className="text-muted-foreground/70">{label}:</span> {String(value)}</div>
                          : <span>{String(value)}</span>;
                      }
                      if (depth >= 3) {
                        return label
                          ? <div className="text-xs"><span className="text-muted-foreground/70">{label}:</span> <span className="font-mono">{JSON.stringify(value)}</span></div>
                          : <span className="font-mono">{JSON.stringify(value)}</span>;
                      }
                      if (Array.isArray(value)) {
                        if (value.length === 0) {
                          return label
                            ? <div className="text-xs"><span className="text-muted-foreground/70">{label}:</span> <span className="text-muted-foreground/50">[]</span></div>
                            : <span className="text-muted-foreground/50">[]</span>;
                        }
                        const content = (
                          <div className="pl-3 border-l border-border space-y-1 mt-0.5">
                            {value.map((item, j) => (
                              <div key={j}>{renderValue(item, depth + 1)}</div>
                            ))}
                          </div>
                        );
                        return depth > 0 ? (
                          <CollapsibleValue label={label} summary={`[${value.length} items]`}>{content}</CollapsibleValue>
                        ) : (
                          <>{label && <div className="text-xs text-muted-foreground/70">{label}: [{value.length} items]</div>}{content}</>
                        );
                      }
                      // object
                      const entries = Object.entries(value as Record<string, unknown>);
                      const keys = entries.map(([k]) => k);
                      const content = (
                        <div className={depth > 0 ? "pl-3 border-l border-border space-y-0.5 mt-0.5" : "space-y-0.5"}>
                          {entries.map(([k, v]) => (
                            <div key={k}>{renderValue(v, depth + 1, k)}</div>
                          ))}
                        </div>
                      );
                      if (depth > 0) {
                        const preview = keys.length <= 3 ? `{${keys.join(", ")}}` : `{${keys.slice(0, 3).join(", ")}, ...}`;
                        return <CollapsibleValue label={label} summary={preview}>{content}</CollapsibleValue>;
                      }
                      return content;
                    };

                    const content = (invokeResult.result as Record<string, unknown>)?.content;
                    if (!Array.isArray(content) || content.length === 0) {
                      return <p className="text-xs text-muted-foreground italic">No content returned</p>;
                    }
                    return content.map((item: Record<string, unknown>, i: number) => {
                      const text = typeof item.text === "string" ? item.text : JSON.stringify(item);
                      try {
                        const parsed = JSON.parse(text);
                        if (typeof parsed === "object" && parsed !== null) {
                          return <div key={i}>{renderValue(parsed, 0)}</div>;
                        }
                      } catch {
                        // not JSON, render as text
                      }
                      return <p key={i} className="text-xs whitespace-pre-wrap">{text}</p>;
                    });
                  })()}
                </div>
              ) : (
                <div className="rounded border border-red-200 dark:border-red-900/50 bg-red-50 dark:bg-red-900/10 p-3">
                  <p className="text-xs text-red-700 dark:text-red-400">{invokeResult.error}</p>
                </div>
              )}
            </div>

            {/* Raw request/response */}
            <div className="space-y-1">
              <button
                type="button"
                onClick={() => {
                  const el = document.getElementById("raw-request-section");
                  if (el) el.classList.toggle("hidden");
                }}
                className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
              >
                <ChevronRight className="h-3 w-3" />
                Raw Request
              </button>
              <div id="raw-request-section" className="hidden">
                <pre className="text-[11px] bg-input-bg rounded border p-3 overflow-x-auto">
                  <code>{JSON.stringify(invokeResult.request, null, 2)}</code>
                </pre>
              </div>
            </div>
            <div className="space-y-1">
              <button
                type="button"
                onClick={() => {
                  const el = document.getElementById("raw-response-section");
                  if (el) el.classList.toggle("hidden");
                }}
                className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
              >
                <ChevronRight className="h-3 w-3" />
                Raw Response
              </button>
              <div id="raw-response-section" className="hidden">
                <pre className="text-[11px] bg-input-bg rounded border p-3 overflow-x-auto">
                  <code>
                    {invokeResult.success
                      ? JSON.stringify(invokeResult.result, null, 2)
                      : invokeResult.error}
                  </code>
                </pre>
              </div>
            </div>
          </div>
        )}
      </div>
    );
  }

  const approvalRule = (tool: McpTool): string | null => {
    for (const policy of policies) {
      if (!policy.enabled) continue;
      for (const rule of policy.tool_match_rules ?? []) {
        if (matchesRule(rule, tool.tool_name)) return rule;
      }
    }
    return null;
  };

  const approvalCount = tools.filter((t) => approvalRule(t) !== null).length;
  const query = filter.trim().toLowerCase();
  const filtered = tools
    .filter((t) => (segment === "all" ? true : approvalRule(t) !== null))
    .filter((t) =>
      !query ||
      t.tool_name.toLowerCase().includes(query) ||
      (t.description ?? "").toLowerCase().includes(query)
    )
    .sort((a, b) =>
      sortDir === "desc"
        ? b.tool_name.localeCompare(a.tool_name)
        : a.tool_name.localeCompare(b.tool_name)
    );

  // Long tool lists are mostly scanned for one name, so only the first page is
  // rendered until asked for the rest.
  const VISIBLE_ROWS = 7;
  const shown = showAll ? filtered : filtered.slice(0, VISIBLE_ROWS);
  const hidden = filtered.length - shown.length;

  const segmentClass = (active: boolean) =>
    `rounded-[5px] px-2.5 py-1 transition-colors ${
      active ? "bg-card shadow-sm" : "text-muted-foreground hover:text-foreground"
    }`;

  return (
    <Card className="gap-0 overflow-hidden p-0">
      <div className="flex flex-wrap items-center gap-2.5 border-b px-3.5 py-2.5">
        <Input
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          placeholder="Filter tools…"
          className="h-8 max-w-[280px] flex-1 text-[13px]"
        />
        {approvalCount > 0 && (
          <div className="flex gap-1 rounded-[7px] bg-muted p-[3px] text-xs">
            <button type="button" onClick={() => setSegment("all")} className={segmentClass(segment === "all")}>
              All
            </button>
            <button
              type="button"
              onClick={() => setSegment("approval")}
              className={segmentClass(segment === "approval")}
            >
              Needs approval <span className="font-mono">{approvalCount}</span>
            </button>
          </div>
        )}
        <div className="ml-auto flex items-center gap-2">
          <span
            className="text-xs text-muted-foreground"
            title={lastRefreshed ? formatTimestamp(lastRefreshed, timezone) : undefined}
          >
            {tools.length} tool{tools.length === 1 ? "" : "s"}
            {lastRefreshed && ` · Refreshed ${formatRelativeDateTime(lastRefreshed, timezone)}`}
          </span>
          <SortButton
            direction={sortDir}
            onClick={() => setSortDir(toggleSortDirection(`mcp-tools-${serverId}`, sortDir))}
          />
          {!readOnly && (
            <Button size="sm" variant="outline" onClick={handleRefresh} disabled={refreshing}>
              {refreshing ? (
                <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" />
              ) : (
                <RefreshCw className="mr-1 h-3.5 w-3.5" />
              )}
              Refresh tools
            </Button>
          )}
        </div>
      </div>

      {tools.length === 0 ? (
        <p className="px-4 py-6 text-sm text-muted-foreground">
          No tools discovered. Use &apos;Refresh tools&apos; to fetch them from the MCP server.
        </p>
      ) : filtered.length === 0 ? (
        <p className="px-4 py-6 text-sm text-muted-foreground">No tools match that filter.</p>
      ) : (
        <>
          <Table className="table-fixed">
            <TableHeader>
              <TableRow className="hover:bg-transparent">
                <TableHead className="w-[220px] font-mono text-[10px] tracking-[0.12em] uppercase">Tool</TableHead>
                <TableHead className="font-mono text-[10px] tracking-[0.12em] uppercase">Description</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {shown.map((tool) => {
                const rule = approvalRule(tool);
                return (
                  <TableRow
                    key={tool.id}
                    onClick={() => handleSelectTool(tool)}
                    className={`cursor-pointer align-top ${rule ? "bg-warning-bg/50" : ""}`}
                  >
                    <TableCell className="w-[220px] align-top whitespace-normal break-words">
                      <div className="flex flex-col items-start gap-1.5">
                        <span className="font-mono text-[13px] font-medium">{tool.tool_name}</span>
                        {rule && (
                          <span className="rounded-[5px] border border-destructive/40 bg-destructive/10 px-1.5 py-0.5 text-[10px] font-medium tracking-wide uppercase text-destructive">
                            Destructive · needs approval
                          </span>
                        )}
                      </div>
                    </TableCell>
                    <TableCell className="align-top text-[13px] leading-[1.55] break-words whitespace-normal text-muted-foreground">
                      {/* Gated tools show in full: the policy is the reason the
                          row is tinted, so truncating it hides the explanation. */}
                      <span className={rule ? undefined : "line-clamp-2"}>
                        {tool.description ?? <span className="italic">No description provided.</span>}
                      </span>
                      {rule && (
                        <>
                          {" "}
                          Gated by approval policy{" "}
                          <code className="rounded-[4px] bg-muted px-1.5 py-0.5 font-mono text-xs">{rule}</code>, so a
                          person has to approve each call before it runs.
                        </>
                      )}
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
          {hidden > 0 && (
            <button
              type="button"
              onClick={() => setShowAll(true)}
              className="w-full px-4 py-2.5 text-left text-[12.5px] text-primary hover:underline"
            >
              Show {hidden} more tool{hidden === 1 ? "" : "s"}
            </button>
          )}
        </>
      )}
    </Card>
  );
}
