import { useState, useEffect, useRef } from "react";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Button } from "@/components/ui/button";
import { ChevronDown, ChevronRight, ChevronUp } from "lucide-react";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { SearchableSelect } from "@/components/ui/searchable-select";
import { PolicyViewer } from "@/components/PolicyViewer";
import { JsonConfigSection } from "@/components/JsonConfigSection";
import * as agentsApi from "@/api/agents";
import * as securityApi from "@/api/security";
import * as settingsApi from "@/api/settings";
import { listMcpServers } from "@/api/mcp";
import { listA2aAgents } from "@/api/a2a";
import { useAuth } from "@/contexts/AuthContext";
import { listMemories } from "@/api/memories";
import { ResourceTagFields } from "@/components/ResourceTagFields";
import type { AgentDeployRequest, AgentHarnessDeployRequest, ModelOption, ManagedRole, AuthorizerConfigResponse, TagProfile, McpServer, A2aAgent, MemoryResponse, VpcConfig, VpcConfigDetail } from "@/api/types";
import { groupModels } from "@/lib/models";
import { toast } from "sonner";

function formatSgPort(r: { protocol: string; from_port: number | null; to_port: number | null }): string {
  if (r.protocol === "All") return "All";
  if (r.from_port === null && r.to_port === null) return "All";
  if (r.from_port === r.to_port) return String(r.from_port);
  return `${r.from_port}–${r.to_port}`;
}

function VpcDetailTables({ detail }: { detail: VpcConfigDetail }) {
  return (
    <div className="space-y-3">
      <div className="space-y-1.5">
        <p className="text-xs font-medium text-muted-foreground">Subnets ({detail.subnets.length})</p>
        <table className="text-xs w-full border-collapse border border-border rounded">
          <thead>
            <tr className="bg-accent text-muted-foreground">
              <th className="text-left font-medium px-2 py-1 border border-border">Subnet ID</th>
              <th className="text-left font-medium px-2 py-1 border border-border">Availability Zone / ID</th>
              <th className="text-left font-medium px-2 py-1 border border-border">CIDR</th>
              <th className="text-left font-medium px-2 py-1 border border-border">Available IPs</th>
            </tr>
          </thead>
          <tbody>
            {detail.subnets.map((s) => (
              <tr key={s.subnet_id} className="bg-background">
                <td className="px-2 py-0.5 font-mono border border-border">
                  {s.subnet_id}{s.name && <span className="ml-1 text-muted-foreground">({s.name})</span>}
                </td>
                <td className="px-2 py-0.5 font-mono border border-border">
                  {s.availability_zone ?? "—"}
                  {s.availability_zone_id && (
                    <span className="ml-1 text-muted-foreground">({s.availability_zone_id})</span>
                  )}
                </td>
                <td className="px-2 py-0.5 font-mono border border-border">{s.cidr_block ?? "—"}</td>
                <td className="px-2 py-0.5 border border-border text-muted-foreground">{s.available_ips ?? "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {detail.security_groups.map((sg) => (
        <div key={sg.sg_id} className="space-y-2">
          <p className="text-xs font-medium text-muted-foreground">{sg.sg_id}{sg.name ? ` — ${sg.name}` : ""}</p>
          {(["ingress", "egress"] as const).map((dir) => (
            <div key={dir} className="space-y-1">
              <p className="text-[10px] uppercase tracking-wide text-muted-foreground">{dir === "ingress" ? "Inbound" : "Outbound"} rules</p>
              <table className="text-xs w-full border-collapse border border-border rounded table-fixed">
                <colgroup>
                  <col className="w-20" />
                  <col className="w-24" />
                  <col className="w-[25%]" />
                  <col />
                </colgroup>
                <thead>
                  <tr className="bg-accent text-muted-foreground">
                    <th className="text-left font-medium px-2 py-1 border border-border">Protocol</th>
                    <th className="text-left font-medium px-2 py-1 border border-border">Port</th>
                    <th className="text-left font-medium px-2 py-1 border border-border">Source / Destination</th>
                    <th className="text-left font-medium px-2 py-1 border border-border">Description</th>
                  </tr>
                </thead>
                <tbody>
                  {sg[dir].length === 0 ? (
                    <tr className="bg-background">
                      <td colSpan={4} className="px-2 py-1 border border-border text-muted-foreground italic">No rules</td>
                    </tr>
                  ) : sg[dir].map((r, i) => (
                    <tr key={i} className="bg-background align-top">
                      <td className="px-2 py-0.5 font-mono border border-border">{r.protocol}</td>
                      <td className="px-2 py-0.5 font-mono border border-border">{formatSgPort(r)}</td>
                      <td className="px-2 py-0.5 font-mono border border-border break-all">
                        {r.cidr ?? (r.source_sg_id ? (r.source_sg_name ? `${r.source_sg_id} (${r.source_sg_name})` : r.source_sg_id) : "—")}
                      </td>
                      <td className="px-2 py-0.5 border border-border text-muted-foreground break-words">{r.description ?? ""}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ))}
        </div>
      ))}
    </div>
  );
}

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
            <span
              key={v}
              className="inline-flex items-center gap-1 rounded bg-accent px-2 py-0.5 text-xs"
            >
              {v}
              <button
                type="button"
                onClick={() => remove(v)}
                className="text-muted-foreground hover:text-foreground"
              >
                &times;
              </button>
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

type Mode = "register" | "deploy";
type DeploymentType = "custom" | "managed";

interface AgentRegistrationFormProps {
  mode: Mode;
  onRegister: (arn: string, modelId?: string) => Promise<void>;
  onDeploy?: (request: AgentDeployRequest) => Promise<void>;
  onDeployHarness?: (request: AgentHarnessDeployRequest) => Promise<void>;
  isLoading: boolean;
  groupRestriction?: string;
  ownerRestriction?: string;
  exportAgentId?: number;
}

export function AgentRegistrationForm({ mode, onRegister, onDeploy, onDeployHarness, isLoading, groupRestriction, ownerRestriction, exportAgentId }: AgentRegistrationFormProps) {
  const { hasScope } = useAuth();

  // Deployment type (Custom Agent vs Managed Agent)
  const [deploymentType, setDeploymentType] = useState<DeploymentType>("custom");

  // Register state
  const [arn, setArn] = useState("");

  // Deploy state
  const [name, setName] = useState("");
  const [nameError, setNameError] = useState("");
  const [description, setDescription] = useState("");
  const [systemPrompt, setSystemPrompt] = useState("");
  const [modelId, setModelId] = useState("");
  const [selectedAllowedModelIds, setSelectedAllowedModelIds] = useState<string[]>([]);
  const [selectedRoleId, setSelectedRoleId] = useState<string>("");
  const [protocol] = useState("HTTP");
  const [networkMode, setNetworkMode] = useState("PUBLIC");
  const [vpcConfigId, setVpcConfigId] = useState<string>("");
  const [vpcConfigs, setVpcConfigs] = useState<VpcConfig[]>([]);

  // Security config state (pre-configured by Security Admin)
  const [selectedAuthConfigId, setSelectedAuthConfigId] = useState<string>("");

  // Permission request state
  const [showRolePerms, setShowRolePerms] = useState(false);
  const [showVpcDetail, setShowVpcDetail] = useState(false);
  const [vpcDetail, setVpcDetail] = useState<VpcConfigDetail | "loading" | null>(null);
  const [showPermRequest, setShowPermRequest] = useState(false);
  const [permActions, setPermActions] = useState<string[]>([]);
  const [permResources, setPermResources] = useState<string[]>([]);
  const [permJustification, setPermJustification] = useState("");

  // Lifecycle state
  const [idleTimeout, setIdleTimeout] = useState("");
  const [maxLifetime, setMaxLifetime] = useState("");
  const [idleTimeoutError, setIdleTimeoutError] = useState("");
  const [maxLifetimeError, setMaxLifetimeError] = useState("");

  // Integrations state
  const [selectedMcpServerIds, setSelectedMcpServerIds] = useState<number[]>([]);
  const [selectedA2aAgentIds, setSelectedA2aAgentIds] = useState<number[]>([]);
  const [selectedMemoryIds, setSelectedMemoryIds] = useState<number[]>([]);
  const [codeInterpreterEnabled, setCodeInterpreterEnabled] = useState(false);
  const [codeInterpreterRegion, setCodeInterpreterRegion] = useState("us-east-1");
  const [codeInterpreterNetworkMode, setCodeInterpreterNetworkMode] = useState("SANDBOX");
  const [codeInterpreterRoleId, setCodeInterpreterRoleId] = useState<string>("");
  const [mcpServers, setMcpServers] = useState<McpServer[]>([]);
  const [a2aAgents, setA2aAgents] = useState<A2aAgent[]>([]);
  const [memories, setMemories] = useState<MemoryResponse[]>([]);

  // Tag state (populated by ResourceTagFields via profile selection)
  const [tagValues, setTagValues] = useState<Record<string, string>>({});
  const [tagProfiles, setTagProfiles] = useState<TagProfile[]>([]);
  const [selectedTagProfileId, setSelectedTagProfileId] = useState<string | undefined>(undefined);

  // Harness-specific state
  const [harnessMaxIterations, setHarnessMaxIterations] = useState("");
  const [harnessMaxTokens, setHarnessMaxTokens] = useState("");
  const [enableHumanConfirmation, setEnableHumanConfirmation] = useState(false);
  const [confirmationPolicy, setConfirmationPolicy] = useState("Ask the user to confirm before performing any destructive, irreversible, or high-impact action. Always call this tool before deleting data, modifying production resources, or executing financial transactions.");

  // Discovery data
  const [models, setModels] = useState<ModelOption[]>([]);
  const [managedRoles, setManagedRoles] = useState<ManagedRole[]>([]);
  const [authConfigs, setAuthConfigs] = useState<AuthorizerConfigResponse[]>([]);
  const [defaults, setDefaults] = useState<agentsApi.LoomDefaults>({ idle_timeout_seconds: 300, max_lifetime_seconds: 3600, region: "us-east-1" });

  const [dataLoaded, setDataLoaded] = useState(false);
  useEffect(() => {
    void agentsApi.fetchModels().then(setModels).catch(() => {});
    void agentsApi.fetchDefaults().then(setDefaults).catch(() => {});
    if (mode === "deploy") {
      Promise.all([
        securityApi.listManagedRoles().then(setManagedRoles).catch(() => {}),
        securityApi.listAuthorizerConfigs().then(setAuthConfigs).catch(() => {}),
        settingsApi.listTagProfiles().then(setTagProfiles).catch(() => {}),
        settingsApi.listVpcConfigs().then(setVpcConfigs).catch(() => {}),
        listMcpServers().then(setMcpServers).catch(() => {}),
        listA2aAgents().then(setA2aAgents).catch(() => {}),
        listMemories().then(setMemories).catch(() => {}),
      ]).then(() => setDataLoaded(true));
    }
  }, [mode]);

  // Auto-populate form when editing an existing agent
  const [loadedAgentId, setLoadedAgentId] = useState<number | undefined>(undefined);
  const pendingVpcConfigName = useRef<string | null>(null);
  useEffect(() => {
    if (!exportAgentId || !hasScope("admin:write")) return;
    if (exportAgentId === loadedAgentId) return;
    if (models.length === 0 || !dataLoaded) return;
    setLoadedAgentId(exportAgentId);
    void agentsApi.exportAgent(exportAgentId).then((parsed) => {
      if (parsed.deployment_type === "custom" || parsed.deployment_type === "managed") {
        setDeploymentType(parsed.deployment_type as DeploymentType);
      }
      if (parsed.name) setName(parsed.name as string);
      if (parsed.description) setDescription(parsed.description as string);
      if (parsed.system_prompt) setSystemPrompt(parsed.system_prompt as string);
      else if (parsed.persona) setSystemPrompt(parsed.persona as string);
      if (parsed.model) {
        const match = models.find((m) => m.model_id === parsed.model || m.display_name === parsed.model);
        if (match) setModelId(match.model_id);
      }
      if (Array.isArray(parsed.allowed_models)) {
        const validIds = models.map((m) => m.model_id);
        setSelectedAllowedModelIds((parsed.allowed_models as string[]).filter((id) => validIds.includes(id)));
      }
      if (parsed.role) {
        const match = managedRoles.find((r) => r.role_name === parsed.role || r.role_arn === parsed.role);
        if (match) setSelectedRoleId(match.id.toString());
      }
      if (parsed.vpc && typeof parsed.vpc === "object") {
        const vpc = parsed.vpc as Record<string, unknown>;
        if (typeof vpc.mode === "string") setNetworkMode(vpc.mode);
        if (typeof vpc.config === "string") {
          const match = vpcConfigs.find((c) => c.name === vpc.config || c.id.toString() === vpc.config);
          if (match) {
            setVpcConfigId(match.id.toString());
          } else {
            // vpcConfigs may not be loaded yet — store name for deferred resolution
            pendingVpcConfigName.current = vpc.config;
          }
        }
      }
      if (parsed.authorizer) {
        const match = authConfigs.find((c) => c.name === parsed.authorizer || c.id.toString() === parsed.authorizer);
        if (match) setSelectedAuthConfigId(match.id.toString());
      }
      if (parsed.tags) {
        const match = tagProfiles.find((p) => p.name === parsed.tags);
        if (match) setSelectedTagProfileId(match.id.toString());
      }
      if (Array.isArray(parsed.mcp_servers)) {
        const ids = (parsed.mcp_servers as (string | number)[])
          .map((s) => {
            if (typeof s === "number") return s;
            const match = mcpServers.find((m) => m.name === s);
            return match?.id;
          })
          .filter((id): id is number => id !== undefined);
        setSelectedMcpServerIds(ids);
      }
      if (Array.isArray(parsed.a2a_agents)) {
        const ids = (parsed.a2a_agents as (string | number)[])
          .map((s) => {
            if (typeof s === "number") return s;
            const match = a2aAgents.find((a) => a.name === s);
            return match?.id;
          })
          .filter((id): id is number => id !== undefined);
        setSelectedA2aAgentIds(ids);
      }
      if (Array.isArray(parsed.memories)) {
        const ids = (parsed.memories as (string | number)[])
          .map((s) => {
            if (typeof s === "number") return s;
            const match = memories.find((m) => m.name === s);
            return match?.id;
          })
          .filter((id): id is number => id !== undefined);
        setSelectedMemoryIds(ids);
      }
      if (parsed.code_interpreter != null) {
        const ci = typeof parsed.code_interpreter === "object" ? parsed.code_interpreter as Record<string, unknown> : null;
        if (ci) {
          setCodeInterpreterEnabled(!!ci.enabled);
          if (ci.region) setCodeInterpreterRegion(ci.region as string);
          if (ci.network_mode) setCodeInterpreterNetworkMode(ci.network_mode as string);
          if (ci.role) {
            const ciRole = managedRoles.find((r) => r.role_name === ci.role || r.role_arn === ci.role);
            if (ciRole) setCodeInterpreterRoleId(ciRole.id.toString());
          }
        } else {
          setCodeInterpreterEnabled(!!parsed.code_interpreter);
        }
      }
      if (parsed.max_iterations != null) setHarnessMaxIterations(String(parsed.max_iterations));
      if (parsed.max_tokens != null) setHarnessMaxTokens(String(parsed.max_tokens));
      if (parsed.human_confirmation != null) setEnableHumanConfirmation(!!parsed.human_confirmation);
      if (parsed.confirmation_policy != null) setConfirmationPolicy(parsed.confirmation_policy as string);
    }).catch(() => {});
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [exportAgentId, models.length, dataLoaded]);

  // Deferred VPC config resolution: if vpcConfigs wasn't loaded when the export ran,
  // resolve the pending name once vpcConfigs becomes available.
  useEffect(() => {
    if (!pendingVpcConfigName.current || vpcConfigs.length === 0) return;
    const match = vpcConfigs.find((c) => c.name === pendingVpcConfigName.current || c.id.toString() === pendingVpcConfigName.current);
    if (match) {
      setVpcConfigId(match.id.toString());
      pendingVpcConfigName.current = null;
    }
  }, [vpcConfigs]);

  const selectedRole = managedRoles.find((r) => r.id.toString() === selectedRoleId);
  const selectedAuthConfig = authConfigs.find((c) => c.id.toString() === selectedAuthConfigId);
  const selectedVpcConfig = vpcConfigs.find((c) => c.id.toString() === vpcConfigId);

  const validateName = (value: string) => {
    if (!value) {
      setNameError("");
      return;
    }
    const pattern = /^[a-zA-Z][a-zA-Z0-9_]{0,47}$/;
    if (!pattern.test(value)) {
      setNameError("Must start with a letter, use only letters, digits, and underscores (max 48 chars)");
    } else {
      setNameError("");
    }
  };

  const validateLifecycle = (field: "idle" | "max", value: string) => {
    if (!value) {
      if (field === "idle") setIdleTimeoutError("");
      else setMaxLifetimeError("");
      return;
    }
    const num = parseInt(value, 10);
    const error = num < 60 || num > 28800 ? "Must be between 60 and 28800 seconds" : "";
    if (field === "idle") setIdleTimeoutError(error);
    else setMaxLifetimeError(error);
  };

  const handleIdleTimeoutChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    let value = e.target.value;
    if (idleTimeout === "" && value !== "") {
      value = String(defaults.idle_timeout_seconds);
      e.target.value = value;
    }
    setIdleTimeout(value);
    validateLifecycle("idle", value);
  };

  const handleMaxLifetimeChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    let value = e.target.value;
    if (maxLifetime === "" && value !== "") {
      value = String(defaults.max_lifetime_seconds);
      e.target.value = value;
    }
    setMaxLifetime(value);
    validateLifecycle("max", value);
  };

  const hasValidationErrors = nameError !== "" || idleTimeoutError !== "" || maxLifetimeError !== "";

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (mode === "register") {
      if (!arn.trim()) return;
      await onRegister(arn.trim(), modelId || undefined);
      setArn("");
    } else if (deploymentType === "managed") {
      if (!name.trim() || !modelId || !selectedRoleId || !onDeployHarness || hasValidationErrors) return;

      const roleArn = selectedRole?.role_arn ?? "";
      const authConfig = selectedAuthConfig;
      const request: AgentHarnessDeployRequest = {
        source: "harness",
        name: name.trim(),
        description: description.trim(),
        agent_description: systemPrompt.trim(),
        behavioral_guidelines: "",
        output_expectations: "",
        model_id: modelId,
        allowed_model_ids: selectedAllowedModelIds.length > 0
          ? (selectedAllowedModelIds.includes(modelId) ? selectedAllowedModelIds : [modelId, ...selectedAllowedModelIds])
          : undefined,
        role_arn: roleArn,
        network_mode: networkMode,
        vpc_config_id: networkMode === "VPC" && vpcConfigId ? parseInt(vpcConfigId, 10) : null,
        idle_timeout: idleTimeout ? parseInt(idleTimeout, 10) : null,
        max_lifetime: maxLifetime ? parseInt(maxLifetime, 10) : null,
        authorizer_type: authConfig?.authorizer_type ?? null,
        authorizer_pool_id: authConfig?.pool_id ?? null,
        authorizer_discovery_url: authConfig?.discovery_url ?? null,
        authorizer_allowed_audience: authConfig?.allowed_audience ?? [],
        authorizer_allowed_clients: authConfig?.allowed_clients ?? [],
        authorizer_allowed_scopes: authConfig?.allowed_scopes ?? [],
        authorizer_client_id: authConfig?.client_id ?? null,
        authorizer_client_secret: null,
        mcp_servers: selectedMcpServerIds,
        memory_ids: selectedMemoryIds,
        tags: Object.fromEntries(
          Object.entries(tagValues).filter(([, v]) => v.trim() !== "")
        ),
        harness_max_iterations: harnessMaxIterations ? parseInt(harnessMaxIterations, 10) : null,
        harness_max_tokens: harnessMaxTokens ? parseInt(harnessMaxTokens, 10) : null,
        code_interpreter_enabled: codeInterpreterEnabled,
        code_interpreter_region: codeInterpreterRegion,
        code_interpreter_network_mode: codeInterpreterNetworkMode,
        code_interpreter_role_id: codeInterpreterRoleId ? parseInt(codeInterpreterRoleId) : null,
        harness_tools: enableHumanConfirmation ? [{
          name: "user_confirmation",
          type: "inline_function",
          config: {
            inlineFunction: {
              description: confirmationPolicy,
              inputSchema: {
                type: "object",
                properties: {
                  action_summary: { type: "string", description: "Brief description of what you are about to do" },
                  risk_level: { type: "string", enum: ["low", "medium", "high"], description: "Risk level of the action" },
                  details: { type: "string", description: "Additional context about impact and scope" },
                },
                required: ["action_summary"],
              },
            },
          },
        }] : undefined,
      };
      await onDeployHarness(request);
    } else {
      if (!name.trim() || !modelId || !selectedRoleId || !onDeploy || hasValidationErrors) return;

      // Resolve managed role to role_arn
      const roleArn = selectedRole?.role_arn ?? null;

      // Resolve authorizer config to raw fields
      const authConfig = selectedAuthConfig;
      const request: AgentDeployRequest = {
        source: "deploy",
        name: name.trim(),
        description: description.trim(),
        agent_description: systemPrompt.trim(),
        behavioral_guidelines: "",
        output_expectations: "",
        model_id: modelId,
        allowed_model_ids: selectedAllowedModelIds.length > 0
          ? (selectedAllowedModelIds.includes(modelId) ? selectedAllowedModelIds : [modelId, ...selectedAllowedModelIds])
          : undefined,
        role_arn: roleArn,
        protocol,
        network_mode: networkMode,
        vpc_config_id: networkMode === "VPC" && vpcConfigId ? parseInt(vpcConfigId, 10) : null,
        idle_timeout: idleTimeout ? parseInt(idleTimeout, 10) : defaults.idle_timeout_seconds,
        max_lifetime: maxLifetime ? parseInt(maxLifetime, 10) : defaults.max_lifetime_seconds,
        authorizer_type: authConfig?.authorizer_type ?? null,
        authorizer_pool_id: authConfig?.pool_id ?? null,
        authorizer_discovery_url: authConfig?.discovery_url ?? null,
        authorizer_allowed_audience: authConfig?.allowed_audience ?? [],
        authorizer_allowed_clients: authConfig?.allowed_clients ?? [],
        authorizer_allowed_scopes: authConfig?.allowed_scopes ?? [],
        authorizer_client_id: authConfig?.client_id ?? null,
        authorizer_client_secret: null,
        memory_enabled: selectedMemoryIds.length > 0,
        memory_ids: selectedMemoryIds,
        mcp_servers: selectedMcpServerIds,
        a2a_agents: selectedA2aAgentIds,
        code_interpreter_enabled: codeInterpreterEnabled,
        code_interpreter_region: codeInterpreterRegion,
        code_interpreter_network_mode: codeInterpreterNetworkMode,
        code_interpreter_role_id: codeInterpreterRoleId ? parseInt(codeInterpreterRoleId) : null,
        tags: Object.fromEntries(
          Object.entries(tagValues).filter(([, v]) => v.trim() !== "")
        ),
      };
      await onDeploy(request);
      setName("");
      setDescription("");
      setSystemPrompt("");
      setModelId("");
      setSelectedAllowedModelIds([]);
      setSelectedRoleId("");
      setNetworkMode("PUBLIC");
      setSelectedAuthConfigId("");
      setIdleTimeout("");
      setMaxLifetime("");
      setIdleTimeoutError("");
      setMaxLifetimeError("");
      setTagValues({});
      setSelectedMcpServerIds([]);
      setSelectedA2aAgentIds([]);
      setSelectedMemoryIds([]);
      setCodeInterpreterEnabled(false);
      setCodeInterpreterRegion("us-east-1");
      setCodeInterpreterNetworkMode("SANDBOX");
      setCodeInterpreterRoleId("");
    }
  };

  // Filter resources by group if restricted
  const registryActive = mcpServers.some(s => s.registry_status) || a2aAgents.some(a => a.registry_status);
  const filteredMcpServers = registryActive
    ? mcpServers.filter(s => !s.registry_status || s.registry_status === "APPROVED")
    : mcpServers;
  const filteredA2aAgents = registryActive
    ? a2aAgents.filter(a => !a.registry_status || a.registry_status === "APPROVED")
    : a2aAgents;
  const filteredMemories = groupRestriction
    ? memories.filter((m) => m.tags?.["loom:group"] === groupRestriction)
    : memories;
  const filteredRoles = (groupRestriction
    ? managedRoles.filter((r) => r.tags?.["loom:group"] === groupRestriction)
    : managedRoles
  ).filter((r) => r.role_type !== "code_interpreter");

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      {mode === "register" ? (
            <div className="flex gap-3 items-end">
              <div className="flex-1 min-w-0">
                <label className="text-xs text-muted-foreground">AgentCore Runtime ARN</label>
                <Input
                  placeholder="arn:aws:bedrock-agentcore:region:account:runtime/id"
                  value={arn}
                  onChange={(e) => setArn(e.target.value)}
                />
              </div>
              <div className="w-1/4 min-w-0">
                <label className="text-xs text-muted-foreground">Model Used</label>
                <SearchableSelect
                  options={models.map((m) => ({ value: m.model_id, label: m.display_name, group: m.group }))}
                  value={modelId}
                  onValueChange={setModelId}
                  placeholder="Select model..."
                />
              </div>
              <Button type="submit" disabled={isLoading || !arn.trim()} className="min-w-[120px]">
                {isLoading ? "Registering..." : "Register"}
              </Button>
            </div>
      ) : (
          <div className="space-y-5">
              {/* JSON Import / Export */}
              <JsonConfigSection
                onApply={(json) => {
                  try {
                    const parsed = JSON.parse(json);
                    if (parsed.deployment_type === "custom" || parsed.deployment_type === "managed") {
                      setDeploymentType(parsed.deployment_type);
                    }
                    if (parsed.name) setName(parsed.name);
                    if (parsed.description) setDescription(parsed.description);
                    if (parsed.system_prompt) setSystemPrompt(parsed.system_prompt);
                    else if (parsed.persona) setSystemPrompt(parsed.persona);
                    if (parsed.model) {
                      const match = models.find((m) => m.model_id === parsed.model || m.display_name === parsed.model);
                      if (match) setModelId(match.model_id);
                    }
                    if (Array.isArray(parsed.allowed_models)) {
                      const validIds = models.map((m) => m.model_id);
                      setSelectedAllowedModelIds(parsed.allowed_models.filter((id: string) => validIds.includes(id)));
                    }
                    if (parsed.role) {
                      const match = managedRoles.find((r) => r.role_name === parsed.role || r.role_arn === parsed.role);
                      if (match) setSelectedRoleId(match.id.toString());
                    }
                    if (parsed.vpc && typeof parsed.vpc === "object") {
                      const vpc = parsed.vpc as Record<string, unknown>;
                      if (typeof vpc.mode === "string") setNetworkMode(vpc.mode);
                      if (typeof vpc.config === "string") {
                        const match = vpcConfigs.find((c) => c.name === vpc.config || c.id.toString() === vpc.config);
                        if (match) setVpcConfigId(match.id.toString());
                      }
                    }
                    if (parsed.authorizer) {
                      const match = authConfigs.find((c) => c.name === parsed.authorizer || c.id.toString() === parsed.authorizer);
                      if (match) setSelectedAuthConfigId(match.id.toString());
                    }
                    if (parsed.tags) {
                      const match = tagProfiles.find((p) => p.name === parsed.tags);
                      if (match) setSelectedTagProfileId(match.id.toString());
                    }
                    if (Array.isArray(parsed.mcp_servers)) {
                      const ids = parsed.mcp_servers
                        .map((s: string | number) => {
                          if (typeof s === "number") return s;
                          const match = mcpServers.find((m) => m.name === s);
                          return match?.id;
                        })
                        .filter((id: number | undefined): id is number => id !== undefined);
                      setSelectedMcpServerIds(ids);
                    }
                    if (Array.isArray(parsed.a2a_agents)) {
                      const ids = parsed.a2a_agents
                        .map((s: string | number) => {
                          if (typeof s === "number") return s;
                          const match = a2aAgents.find((a) => a.name === s);
                          return match?.id;
                        })
                        .filter((id: number | undefined): id is number => id !== undefined);
                      setSelectedA2aAgentIds(ids);
                    }
                    if (Array.isArray(parsed.memories)) {
                      const ids = parsed.memories
                        .map((s: string | number) => {
                          if (typeof s === "number") return s;
                          const match = memories.find((m) => m.name === s);
                          return match?.id;
                        })
                        .filter((id: number | undefined): id is number => id !== undefined);
                      setSelectedMemoryIds(ids);
                    }
                    if (parsed.code_interpreter != null) {
                      const ci = typeof parsed.code_interpreter === "object" ? parsed.code_interpreter as Record<string, unknown> : null;
                      if (ci) {
                        setCodeInterpreterEnabled(!!ci.enabled);
                        if (ci.region) setCodeInterpreterRegion(ci.region as string);
                        if (ci.network_mode) setCodeInterpreterNetworkMode(ci.network_mode as string);
                        if (ci.role) {
                          const ciRole = managedRoles.find((r) => r.role_name === ci.role || r.role_arn === ci.role);
                          if (ciRole) setCodeInterpreterRoleId(ciRole.id.toString());
                        }
                      } else {
                        setCodeInterpreterEnabled(!!parsed.code_interpreter);
                      }
                    }
                    if (parsed.max_iterations != null) setHarnessMaxIterations(String(parsed.max_iterations));
                    if (parsed.max_tokens != null) setHarnessMaxTokens(String(parsed.max_tokens));
                    if (parsed.human_confirmation != null) setEnableHumanConfirmation(!!parsed.human_confirmation);
                    if (parsed.confirmation_policy != null) setConfirmationPolicy(parsed.confirmation_policy);
                    return null;
                  } catch {
                    return "Invalid JSON. Please check the format and try again.";
                  }
                }}
                onExport={async () => {
                  if (exportAgentId && hasScope("admin:write")) {
                    const data = await agentsApi.exportAgent(exportAgentId);
                    return JSON.stringify(data, null, 2);
                  }
                  const result: Record<string, unknown> = {};
                  result.deployment_type = deploymentType;
                  if (name) result.name = name;
                  if (description) result.description = description;
                  if (systemPrompt) result.system_prompt = systemPrompt;
                  if (modelId) result.model = modelId;
                  if (selectedAllowedModelIds.length > 0) {
                    result.allowed_models = selectedAllowedModelIds;
                  }
                  if (networkMode && networkMode !== "PUBLIC") {
                    const vpcBlock: Record<string, string> = { mode: networkMode };
                    if (networkMode === "VPC" && vpcConfigId) {
                      const cfg = vpcConfigs.find((c) => c.id.toString() === vpcConfigId);
                      if (cfg) vpcBlock.config = cfg.name;
                    }
                    result.vpc = vpcBlock;
                  }
                  if (selectedRoleId) {
                    const role = managedRoles.find((r) => r.id.toString() === selectedRoleId);
                    if (role) result.role = role.role_name;
                  }
                  if (selectedTagProfileId) {
                    const profile = tagProfiles.find((p) => p.id.toString() === selectedTagProfileId);
                    if (profile) result.tags = profile.name;
                  }
                  if (selectedAuthConfigId) {
                    const auth = authConfigs.find((c) => c.id.toString() === selectedAuthConfigId);
                    if (auth) result.authorizer = auth.name;
                  }
                  if (deploymentType === "managed") {
                    if (harnessMaxIterations) result.max_iterations = parseInt(harnessMaxIterations, 10);
                    if (harnessMaxTokens) result.max_tokens = parseInt(harnessMaxTokens, 10);
                    if (enableHumanConfirmation) {
                      result.human_confirmation = true;
                      result.confirmation_policy = confirmationPolicy;
                    }
                  }
                  if (selectedMcpServerIds.length > 0) {
                    result.mcp_servers = selectedMcpServerIds.map((id) => {
                      const server = mcpServers.find((s) => s.id === id);
                      return server?.name ?? id;
                    });
                  }
                  if (selectedA2aAgentIds.length > 0) {
                    result.a2a_agents = selectedA2aAgentIds.map((id) => {
                      const agent = a2aAgents.find((a) => a.id === id);
                      return agent?.name ?? id;
                    });
                  }
                  if (selectedMemoryIds.length > 0) {
                    result.memories = selectedMemoryIds.map((id) => {
                      const mem = memories.find((m) => m.id === id);
                      return mem?.name ?? id;
                    });
                  }
                  if (codeInterpreterEnabled) {
                    const ciObj: Record<string, unknown> = {
                      enabled: true,
                      region: codeInterpreterRegion || "us-east-1",
                      network_mode: codeInterpreterNetworkMode,
                    };
                    if (codeInterpreterRoleId) {
                      const ciRole = managedRoles.find((r) => r.id.toString() === codeInterpreterRoleId);
                      if (ciRole) ciObj.role = ciRole.role_name;
                    }
                    result.code_interpreter = ciObj;
                  }
                  return JSON.stringify(result, null, 2);
                }}
                placeholder='{"deployment_type": "custom|managed", "name": "...", "system_prompt": "...", "model": "...", "role": "...", "mcp_servers": ["..."], "a2a_agents": ["..."], "memories": ["..."], "code_interpreter": {"enabled": true, "region": "us-east-1", "network_mode": "SANDBOX", "role": "..."}}'
              />

              {/* Deployment Type Selector */}
              <section className="space-y-2">
                <h4 className="text-xs font-medium text-muted-foreground uppercase tracking-wide">Deployment Type</h4>
                <div className="flex gap-3">
                  <label className="flex items-center gap-2 text-sm cursor-pointer">
                    <input
                      type="radio"
                      name="deploymentType"
                      value="custom"
                      checked={deploymentType === "custom"}
                      onChange={() => setDeploymentType("custom")}
                      className="h-3.5 w-3.5"
                    />
                    <span>Custom Agent</span>
                    <span className="text-[10px] text-muted-foreground">Deploys your agent code into AgentCore Runtime</span>
                  </label>
                  <label className="flex items-center gap-2 text-sm cursor-pointer">
                    <input
                      type="radio"
                      name="deploymentType"
                      value="managed"
                      checked={deploymentType === "managed"}
                      onChange={() => setDeploymentType("managed")}
                      className="h-3.5 w-3.5"
                    />
                    <span>Managed Agent</span>
                    <span className="text-[10px] text-muted-foreground">Fully managed agent loop via AgentCore Harness</span>
                  </label>
                </div>
              </section>

              {/* Agent Identity */}
              <section className="space-y-3">
                <h4 className="text-xs font-medium text-muted-foreground uppercase tracking-wide">Agent Identity</h4>
                <div className="flex gap-3">
                  <div className="w-1/3 min-w-0">
                    <Input
                      placeholder="Agent name"
                      value={name}
                      onChange={(e) => {
                        setName(e.target.value);
                        validateName(e.target.value);
                      }}
                      required
                      className={nameError ? "border-red-500" : ""}
                    />
                    {nameError && (
                      <p className="text-xs text-red-500 mt-1">{nameError}</p>
                    )}
                  </div>
                  <Input
                    placeholder="Description (optional)"
                    value={description}
                    onChange={(e) => setDescription(e.target.value)}
                    className="flex-1 min-w-0"
                  />
                </div>
              </section>

              {/* Agent Behavior (System Prompt) */}
              <section className="space-y-3">
                <h4 className="text-xs font-medium text-muted-foreground uppercase tracking-wide">Agent Behavior (System Prompt)</h4>
                <Textarea
                  placeholder={"Persona: You are a helpful customer support agent that resolves billing inquiries for an e-commerce platform.\n\nInstructions: Look up the customer's order history, identify the issue, and provide a resolution within company policy.\n\nGuidelines: Use a friendly and professional tone, never share internal system details, and escalate to a human agent if the customer requests it."}
                  value={systemPrompt}
                  onChange={(e) => setSystemPrompt(e.target.value)}
                  rows={5}
                  className="text-sm"
                />
              </section>

              {/* Model, Protocol, Network, IAM Role */}
              <div className="flex gap-3">
                <section className="w-[20%] min-w-0 space-y-2">
                  <h4 className="text-xs font-medium text-muted-foreground uppercase tracking-wide">Default Model</h4>
                  <SearchableSelect
                    options={models.map((m) => ({ value: m.model_id, label: m.display_name, group: m.group }))}
                    value={modelId}
                    onValueChange={setModelId}
                    placeholder="Select model..."
                  />
                </section>
                {deploymentType === "custom" && (
                  <section className="w-[10%] min-w-0 space-y-2">
                    <h4 className="text-xs font-medium text-muted-foreground uppercase tracking-wide">Protocol</h4>
                    <Select value={protocol} onValueChange={() => {}}>
                      <SelectTrigger className="w-full text-sm">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="HTTP">HTTP</SelectItem>
                        <SelectItem value="MCP" disabled>MCP (coming soon)</SelectItem>
                        <SelectItem value="A2A" disabled>A2A (coming soon)</SelectItem>
                      </SelectContent>
                    </Select>
                  </section>
                )}
                <section className="w-[10%] min-w-0 space-y-2">
                  <h4 className="text-xs font-medium text-muted-foreground uppercase tracking-wide">Network</h4>
                  <Select value={networkMode} onValueChange={setNetworkMode}>
                    <SelectTrigger className="w-full text-sm">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="PUBLIC">PUBLIC</SelectItem>
                      <SelectItem value="VPC">VPC</SelectItem>
                    </SelectContent>
                  </Select>
                </section>
                <section className="flex-1 min-w-0 space-y-2">
                  <h4 className="text-xs font-medium text-muted-foreground uppercase tracking-wide">IAM Role</h4>
                  <SearchableSelect
                    options={filteredRoles.map((r) => ({
                      value: r.id.toString(),
                      label: r.role_name,
                    }))}
                    value={selectedRoleId}
                    onValueChange={setSelectedRoleId}
                    placeholder="Select managed role..."
                  />
                </section>
              </div>

              {/* IAM Role Permissions (read-only) */}
              {selectedRole && (
                <section className="space-y-3">
                  <div className="flex items-center justify-between">
                    <button
                      type="button"
                      onClick={() => setShowRolePerms(!showRolePerms)}
                      className="flex items-center gap-1 text-xs font-medium text-muted-foreground uppercase tracking-wide hover:text-foreground"
                    >
                      {showRolePerms ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}
                      Role Permissions (read-only)
                    </button>
                    {showRolePerms && (
                      <button
                        type="button"
                        onClick={() => setShowPermRequest(!showPermRequest)}
                        className="text-xs text-primary hover:underline flex items-center gap-1"
                      >
                        Request Additional Permissions
                        {showPermRequest ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
                      </button>
                    )}
                  </div>
                  {showRolePerms && (
                    <div className="rounded border p-3 bg-muted/30">
                      <p className="text-xs text-muted-foreground mb-2">{selectedRole.role_arn}</p>
                      <PolicyViewer policy={selectedRole.policy_document} />
                    </div>
                  )}
                  {showRolePerms && showPermRequest && (
                    <div className="rounded border border-dashed p-3 space-y-3">
                      <h5 className="text-xs font-medium text-muted-foreground">Request Additional Permissions</h5>
                      <div className="grid grid-cols-2 gap-3">
                        <div className="space-y-1.5">
                          <label className="text-xs text-muted-foreground">AWS Actions (press Enter to add)</label>
                          <TagInput
                            values={permActions}
                            onChange={setPermActions}
                            placeholder="e.g. s3:PutObject"
                          />
                        </div>
                        <div className="space-y-1.5">
                          <label className="text-xs text-muted-foreground">Resource ARNs (press Enter to add)</label>
                          <TagInput
                            values={permResources}
                            onChange={setPermResources}
                            placeholder="e.g. arn:aws:s3:::my-bucket/*"
                          />
                        </div>
                      </div>
                      <div className="space-y-1.5">
                        <label className="text-xs text-muted-foreground">Justification</label>
                        <Textarea
                          placeholder="Explain why these permissions are needed..."
                          value={permJustification}
                          onChange={(e) => setPermJustification(e.target.value)}
                          rows={2}
                          className="text-sm"
                        />
                      </div>
                      <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        disabled={permActions.length === 0 || permResources.length === 0 || !permJustification.trim()}
                        onClick={async () => {
                          try {
                            await securityApi.createPermissionRequest({
                              managed_role_id: selectedRole.id,
                              requested_actions: permActions,
                              requested_resources: permResources,
                              justification: permJustification.trim(),
                            });
                            toast.success("Permission request submitted");
                            setPermActions([]);
                            setPermResources([]);
                            setPermJustification("");
                            setShowPermRequest(false);
                          } catch {
                            toast.error("Failed to submit permission request");
                          }
                        }}
                      >
                        Submit Request
                      </Button>
                    </div>
                  )}
                </section>
              )}

              {/* VPC Configuration */}
              {networkMode === "VPC" && (
                <section className="space-y-2">
                  <h4 className="text-xs font-medium text-muted-foreground uppercase tracking-wide">VPC Configuration</h4>
                  <SearchableSelect
                    options={vpcConfigs.map((c) => ({ value: c.id.toString(), label: c.name, description: `${c.vpc_id} · ${c.subnet_ids.length} subnets · ${c.sg_ids.length} SGs` }))}
                    value={vpcConfigId}
                    onValueChange={(v) => {
                      setVpcConfigId(v);
                      setShowVpcDetail(false);
                      setVpcDetail(null);
                    }}
                    placeholder="Select VPC configuration..."
                  />
                  {vpcConfigs.length === 0 && (
                    <p className="text-xs text-muted-foreground">No VPC configurations available. Add one in Settings → Networking.</p>
                  )}
                  {selectedVpcConfig && (
                    <div className="space-y-2">
                      <button
                        type="button"
                        onClick={() => {
                          const next = !showVpcDetail;
                          setShowVpcDetail(next);
                          if (next && !vpcDetail) {
                            setVpcDetail("loading");
                            settingsApi.getVpcConfigDetail(selectedVpcConfig.id)
                              .then(setVpcDetail)
                              .catch(() => setVpcDetail(null));
                          }
                        }}
                        className="flex items-center gap-1 text-xs font-medium text-muted-foreground uppercase tracking-wide hover:text-foreground"
                      >
                        {showVpcDetail ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}
                        VPC Details (read-only)
                      </button>
                      {showVpcDetail && (
                        <div className="rounded border p-3 bg-muted/30 space-y-3">
                          {vpcDetail === "loading" ? (
                            <p className="text-xs text-muted-foreground">Loading…</p>
                          ) : vpcDetail ? (
                            <>
                              <p className="text-xs text-muted-foreground font-mono">{vpcDetail.vpc_id}</p>
                              <VpcDetailTables detail={vpcDetail} />
                            </>
                          ) : (
                            <p className="text-xs text-muted-foreground">Could not load VPC details.</p>
                          )}
                        </div>
                      )}
                    </div>
                  )}
                </section>
              )}

              {/* Allowed Models for Runtime Selection */}
              {modelId && models.length > 0 && (
                <section className="space-y-2">
                  <h4 className="text-xs font-medium text-muted-foreground uppercase tracking-wide">Allowed Models (runtime selection)</h4>
                  <p className="text-xs text-muted-foreground">Users can choose from these models when invoking the agent. The deploy model is always included.</p>
                  <div className="space-y-1.5">
                    {groupModels(models).map(([group, groupedModels]) => (
                      <div key={group} className="flex flex-wrap gap-x-4 gap-y-1 items-center">
                        <span className="text-[10px] font-medium text-muted-foreground w-16 shrink-0">{group}</span>
                        {groupedModels.map((m) => (
                          <label key={m.model_id} className="flex items-center gap-2 text-xs cursor-pointer">
                            <input
                              type="checkbox"
                              className="h-3.5 w-3.5 shrink-0"
                              checked={m.model_id === modelId || selectedAllowedModelIds.includes(m.model_id)}
                              disabled={m.model_id === modelId}
                              onChange={(e) => {
                                if (e.target.checked) {
                                  setSelectedAllowedModelIds((prev) => [...prev, m.model_id]);
                                } else {
                                  setSelectedAllowedModelIds((prev) => prev.filter((id) => id !== m.model_id));
                                }
                              }}
                            />
                            <span>{m.display_name}</span>
                            {m.model_id === modelId && (
                              <span className="text-[10px] text-muted-foreground bg-accent px-1 rounded">default</span>
                            )}
                          </label>
                        ))}
                      </div>
                    ))}
                  </div>
                </section>
              )}

              {/* Authorizer */}
              <section className="space-y-3">
                <h4 className="text-xs font-medium text-muted-foreground uppercase tracking-wide">Authorizer</h4>
                <div className="w-1/4">
                  <SearchableSelect
                    options={[
                      { value: "", label: "None" },
                      ...authConfigs.map((c) => ({
                        value: c.id.toString(),
                        label: c.name,
                      })),
                    ]}
                    value={selectedAuthConfigId}
                    onValueChange={setSelectedAuthConfigId}
                    placeholder="Select authorizer config..."
                  />
                </div>
                {selectedAuthConfig && (
                  <div className="rounded border bg-input-bg p-3 text-xs space-y-1">
                    <p><span className="text-muted-foreground">Type:</span> {selectedAuthConfig.authorizer_type}</p>
                    {selectedAuthConfig.pool_id && <p><span className="text-muted-foreground">Pool:</span> {selectedAuthConfig.pool_id}</p>}
                    {selectedAuthConfig.discovery_url && <p><span className="text-muted-foreground">Discovery URL:</span> {selectedAuthConfig.discovery_url}</p>}
                    {selectedAuthConfig.allowed_audience.length > 0 && (
                      <p><span className="text-muted-foreground">Allowed Audience:</span> {selectedAuthConfig.allowed_audience.join(", ")}</p>
                    )}
                    {selectedAuthConfig.allowed_clients.length > 0 && (
                      <p><span className="text-muted-foreground">Allowed Clients:</span> {selectedAuthConfig.allowed_clients.join(", ")}</p>
                    )}
                    {selectedAuthConfig.allowed_scopes.length > 0 && (
                      <p><span className="text-muted-foreground">Allowed Scopes:</span> {selectedAuthConfig.allowed_scopes.join(", ")}</p>
                    )}
                  </div>
                )}
              </section>

              {/* Harness Parameters (Managed Agent only) */}
              {deploymentType === "managed" && (
                <section className="space-y-3">
                  <h4 className="text-xs font-medium text-muted-foreground uppercase tracking-wide">Harness Parameters</h4>
                  <div className="grid grid-cols-2 gap-3">
                    <div className="space-y-1">
                      <label className="text-xs text-muted-foreground">Max Iterations</label>
                      <Input
                        type="number"
                        placeholder="Defaults to 75"
                        value={harnessMaxIterations}
                        onChange={(e) => setHarnessMaxIterations(e.target.value)}
                        min={1}
                      />
                    </div>
                    <div className="space-y-1">
                      <label className="text-xs text-muted-foreground">Max Tokens</label>
                      <Input
                        type="number"
                        placeholder="Model default"
                        value={harnessMaxTokens}
                        onChange={(e) => setHarnessMaxTokens(e.target.value)}
                        min={1}
                      />
                    </div>
                  </div>
                  <div className="space-y-2 pt-2">
                    <div className="flex items-center gap-2">
                      <input
                        type="checkbox"
                        id="enable-human-confirmation"
                        checked={enableHumanConfirmation}
                        onChange={(e) => setEnableHumanConfirmation(e.target.checked)}
                        className="h-4 w-4 rounded border-border"
                      />
                      <label htmlFor="enable-human-confirmation" className="text-xs text-muted-foreground">
                        Enable human confirmation (inline function HITL)
                      </label>
                    </div>
                    {enableHumanConfirmation && (
                      <div className="space-y-1">
                        <label className="text-xs text-muted-foreground">Confirmation Policy</label>
                        <Textarea
                          placeholder="Describe when the agent should ask for human confirmation..."
                          value={confirmationPolicy}
                          onChange={(e) => setConfirmationPolicy(e.target.value)}
                          rows={3}
                          className="text-xs"
                        />
                      </div>
                    )}
                  </div>
                </section>
              )}

              {/* Lifecycle */}
              <section className="space-y-3">
                <h4 className="text-xs font-medium text-muted-foreground uppercase tracking-wide">Lifecycle</h4>
                <div className="grid grid-cols-2 gap-3">
                  <div className="space-y-1">
                    <label className="text-xs text-muted-foreground">Idle Timeout (seconds)</label>
                    <Input
                      type="number"
                      placeholder={`Defaults to ${defaults.idle_timeout_seconds} (${Math.round(defaults.idle_timeout_seconds / 60)} min)`}
                      value={idleTimeout}
                      onChange={handleIdleTimeoutChange}
                      min={60}
                      max={28800}
                      step={60}
                    />
                    {idleTimeoutError && (
                      <p className="text-[10px] text-destructive">{idleTimeoutError}</p>
                    )}
                  </div>
                  <div className="space-y-1">
                    <label className="text-xs text-muted-foreground">Max Lifetime (seconds)</label>
                    <Input
                      type="number"
                      placeholder={`Defaults to ${defaults.max_lifetime_seconds} (${Math.round(defaults.max_lifetime_seconds / 3600)} hr)`}
                      value={maxLifetime}
                      onChange={handleMaxLifetimeChange}
                      min={60}
                      max={28800}
                      step={60}
                    />
                    {maxLifetimeError && (
                      <p className="text-[10px] text-destructive">{maxLifetimeError}</p>
                    )}
                  </div>
                </div>
              </section>

              {/* Resource Tags */}
              <ResourceTagFields onChange={setTagValues} profileId={selectedTagProfileId} groupRestriction={groupRestriction} ownerRestriction={ownerRestriction} />

              {/* Integrations */}
              {/* Memory Resources */}
              <section className="space-y-3">
                <h4 className="text-xs font-medium text-muted-foreground uppercase tracking-wide">Memory Resources</h4>
                <div className="space-y-1.5">
                  {filteredMemories.length === 0 ? (
                    <p className="text-xs text-muted-foreground italic">No memory resources available{groupRestriction ? " for your group" : ""}. Create one on the Memory page first.</p>
                  ) : (
                    <div className="space-y-1">
                      {filteredMemories.map((mem) => (
                        <label key={mem.id} className="flex items-center gap-2 text-xs cursor-pointer">
                          <input
                            type="checkbox"
                            className="h-3.5 w-3.5"
                            checked={selectedMemoryIds.includes(mem.id)}
                            onChange={(e) => {
                              if (e.target.checked) {
                                setSelectedMemoryIds((prev) => [...prev, mem.id]);
                              } else {
                                setSelectedMemoryIds((prev) => prev.filter((id) => id !== mem.id));
                              }
                            }}
                          />
                          <span>{mem.name}</span>
                          {mem.status !== "ACTIVE" && (
                            <span className="text-[10px] text-muted-foreground bg-accent px-1 rounded">{mem.status}</span>
                          )}
                        </label>
                      ))}
                    </div>
                  )}
                </div>
              </section>

              {/* MCP Servers */}
              <section className="space-y-3">
                <h4 className="text-xs font-medium text-muted-foreground uppercase tracking-wide">MCP Servers{deploymentType === "managed" ? " (Remote MCP Tools)" : ""}</h4>
                <div className="space-y-3">
                  <div className="space-y-1.5">
                    {filteredMcpServers.length === 0 ? (
                      <p className="text-xs text-muted-foreground italic">No MCP servers available. Register servers on the MCP Servers page first.</p>
                    ) : (
                      <div className="space-y-1">
                        {filteredMcpServers.map((server) => (
                          <label key={server.id} className="flex items-center gap-2 text-xs cursor-pointer min-w-0">
                            <input
                              type="checkbox"
                              className="h-3.5 w-3.5 shrink-0"
                              checked={selectedMcpServerIds.includes(server.id)}
                              onChange={(e) => {
                                if (e.target.checked) {
                                  setSelectedMcpServerIds((prev) => [...prev, server.id]);
                                } else {
                                  setSelectedMcpServerIds((prev) => prev.filter((id) => id !== server.id));
                                }
                              }}
                            />
                            <span className="shrink-0">{server.name}</span>
                            {server.auth_type === "oauth2" && (
                              <span className="text-[10px] text-muted-foreground bg-accent px-1 rounded shrink-0">OAuth2</span>
                            )}
                            {server.auth_type === "oauth2" && server.delegation_mode === "obo" && (
                              <span className="text-[10px] text-blue-700 dark:text-blue-300 bg-blue-100 dark:bg-blue-950 px-1 rounded shrink-0">OBO</span>
                            )}
                            {server.auth_type === "oauth2" && server.delegation_mode !== "obo" && (
                              <span className="text-[10px] text-muted-foreground bg-accent px-1 rounded shrink-0">M2M</span>
                            )}
                            <span className="relative group text-muted-foreground/60 shrink-0">
                              {(() => { try { return new URL(server.endpoint_url).host; } catch { return server.endpoint_url; } })()}
                              <span className="absolute left-0 top-full mt-1 z-50 hidden group-hover:block text-[10px] text-foreground bg-popover border border-border px-2 py-1 rounded shadow-md whitespace-nowrap">{server.endpoint_url}</span>
                            </span>
                          </label>
                        ))}
                      </div>
                    )}
                  </div>
                </div>
              </section>

              {/* A2A Agents (Custom Agent only) */}
              {deploymentType === "custom" && (
              <section className="space-y-3">
                <h4 className="text-xs font-medium text-muted-foreground uppercase tracking-wide">A2A Agents</h4>
                <div className="space-y-1.5">
                  {filteredA2aAgents.length === 0 ? (
                    <p className="text-xs text-muted-foreground italic">No A2A agents available. Register agents on the A2A Agents page first.</p>
                  ) : (
                    <div className="space-y-1">
                      {filteredA2aAgents.map((agent) => (
                        <label key={agent.id} className="flex items-center gap-2 text-xs cursor-pointer min-w-0">
                          <input
                            type="checkbox"
                            className="h-3.5 w-3.5 shrink-0"
                            checked={selectedA2aAgentIds.includes(agent.id)}
                            onChange={(e) => {
                              if (e.target.checked) {
                                setSelectedA2aAgentIds((prev) => [...prev, agent.id]);
                              } else {
                                setSelectedA2aAgentIds((prev) => prev.filter((id) => id !== agent.id));
                              }
                            }}
                          />
                          <span className="shrink-0">{agent.name}</span>
                          {agent.auth_type === "oauth2" && (
                            <span className="text-[10px] text-muted-foreground bg-accent px-1 rounded shrink-0">OAuth2</span>
                          )}
                          {agent.auth_type === "oauth2" && agent.delegation_mode === "obo" && (
                            <span className="text-[10px] text-blue-700 dark:text-blue-300 bg-blue-100 dark:bg-blue-950 px-1 rounded shrink-0">OBO</span>
                          )}
                          {agent.auth_type === "oauth2" && agent.delegation_mode !== "obo" && (
                            <span className="text-[10px] text-muted-foreground bg-accent px-1 rounded shrink-0">M2M</span>
                          )}
                          <span className="relative group text-muted-foreground/60 shrink-0">
                            {(() => { try { return new URL(agent.base_url).host; } catch { return agent.base_url; } })()}
                            <span className="absolute left-0 top-full mt-1 z-50 hidden group-hover:block text-[10px] text-foreground bg-popover border border-border px-2 py-1 rounded shadow-md whitespace-nowrap">{agent.base_url}</span>
                          </span>
                        </label>
                      ))}
                    </div>
                  )}
                </div>
              </section>
              )}

              {/* Code Interpreter (Custom Agent only) */}
              <section className="space-y-3">
                <h4 className="text-xs font-medium text-muted-foreground uppercase tracking-wide">Code Interpreter</h4>
                <label className="flex items-center gap-2 text-xs cursor-pointer">
                  <input
                    type="checkbox"
                    className="h-3.5 w-3.5"
                    checked={codeInterpreterEnabled}
                    onChange={(e) => setCodeInterpreterEnabled(e.target.checked)}
                  />
                  <span>Enable</span>
                </label>
                {codeInterpreterEnabled && (
                  <div className="flex items-center gap-2">
                    <Select value={codeInterpreterNetworkMode} onValueChange={setCodeInterpreterNetworkMode}>
                      <SelectTrigger className="text-sm w-36 shrink-0">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="SANDBOX">Sandbox</SelectItem>
                        <SelectItem value="PUBLIC">Public</SelectItem>
                        <SelectItem value="VPC" disabled>VPC (coming soon)</SelectItem>
                      </SelectContent>
                    </Select>
                    <Select value={codeInterpreterRegion} onValueChange={setCodeInterpreterRegion}>
                      <SelectTrigger className="text-sm w-52 shrink-0">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="us-east-1">us-east-1 — N. Virginia</SelectItem>
                        <SelectItem value="us-west-2">us-west-2 — Oregon</SelectItem>
                        <SelectItem value="eu-west-1">eu-west-1 — Ireland</SelectItem>
                      </SelectContent>
                    </Select>
                    <SearchableSelect
                      className="flex-1 min-w-0"
                      options={managedRoles.filter((r) => r.role_type === "code_interpreter").map((r) => ({
                        value: r.id.toString(),
                        label: r.role_name,
                      }))}
                      value={codeInterpreterRoleId}
                      onValueChange={setCodeInterpreterRoleId}
                      placeholder="Execution role (optional)"
                    />
                  </div>
                )}
              </section>

              <div className="space-y-1.5">
              <p className="text-[10px] text-muted-foreground italic">
                {deploymentType === "managed" ? "Harness creation typically takes ~1 minute" : "Deployment typically takes ~1 minute"}
              </p>
              <div className="flex items-center gap-2">
                <Button
                  type="submit"
                  size="sm"
                  className="min-w-[120px]"
                  disabled={isLoading || !name.trim() || !modelId || !selectedRoleId || (deploymentType === "custom" ? !onDeploy : !onDeployHarness) || hasValidationErrors}
                >
                  {isLoading ? "Deploying..." : (exportAgentId ? "Update Agent" : (deploymentType === "managed" ? "Deploy Harness" : "Deploy"))}
                </Button>
                <Button
                  type="button"
                  size="sm"
                  variant="ghost"
                  onClick={() => {
                    setName("");
                    setDescription("");
                    setSystemPrompt("");
                    setModelId("");
                    setSelectedRoleId("");
                    setNetworkMode("PUBLIC");
                    setSelectedAuthConfigId("");
                    setIdleTimeout("");
                    setMaxLifetime("");
                    setIdleTimeoutError("");
                    setMaxLifetimeError("");
                    setTagValues({});
                    setSelectedMcpServerIds([]);
                    setSelectedA2aAgentIds([]);
                    setSelectedMemoryIds([]);
                    setCodeInterpreterEnabled(false);
                    setCodeInterpreterRegion("us-east-1");
                    setCodeInterpreterNetworkMode("SANDBOX");
                    setCodeInterpreterRoleId("");
                  }}
                  disabled={isLoading}
                >
                  Cancel
                </Button>
              </div>
              </div>
          </div>
      )}
    </form>
  );
}
