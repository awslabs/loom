import { useState, useEffect, useRef } from "react";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Button } from "@/components/ui/button";
import { ChevronDown, ChevronRight } from "lucide-react";
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
import { listRegistryRecords } from "@/api/registry";
import { ResourceTagFields } from "@/components/ResourceTagFields";
import type { AgentDeployRequest, AgentHarnessDeployRequest, ModelOption, Provider, ManagedRole, AuthorizerConfigResponse, TagProfile, McpServer, A2aAgent, MemoryResponse, RegistryRecord, VpcConfig, VpcConfigDetail } from "@/api/types";
import { groupModels } from "@/lib/models";
import { toast } from "sonner";

function humanizeSeconds(value: string): string {
  const seconds = parseInt(value, 10);
  if (!seconds || Number.isNaN(seconds)) return "";
  if (seconds % 3600 === 0) return `${seconds / 3600} hr`;
  if (seconds % 60 === 0) return `${seconds / 60} min`;
  return `${seconds}s`;
}

function isEmbeddingModel(m: { model_id: string; display_name: string }): boolean {
  return /embed/i.test(m.model_id) || /embed/i.test(m.display_name);
}

/** Drops the vendor word already implied by the group header (e.g. "Claude
 * Opus 4.8" in the Anthropic group -> "Opus 4.8") so chips don't repeat it. */
function chipLabel(displayName: string): string {
  return displayName.replace(/^Claude\s+/, "");
}

function estimateTokens(text: string): number {
  return Math.round(text.length / 4);
}

// Mirrors backend/app/services/deployment.py's MAX_SYSTEM_PROMPT_BYTES — a
// custom-deploy agent's system prompt shares AgentCore Runtime V2's 1536-byte
// total environmentVariables budget with fixed OTEL/workload-identity vars
// and the AGENT_CONFIG_JSON skeleton, so it's capped well below 1536 itself.
// Only applies to deploymentType === "custom" (CreateAgentRuntime) — managed/
// harness agents pass their system prompt via CreateHarness's dedicated
// systemPrompt field instead and aren't subject to this limit.
const MAX_SYSTEM_PROMPT_BYTES = 500;

function utf8ByteLength(text: string): number {
  return new TextEncoder().encode(text).length;
}

function truncateMiddle(value: string, keep = 8): string {
  if (value.length <= keep * 2 + 1) return value;
  return `${value.slice(0, keep)}…${value.slice(-keep)}`;
}

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
  /** Manifest JSON to apply immediately, then jump straight to the review step (R6). */
  pendingImportJson?: string;
  /** Called once pendingImportJson has been applied (successfully or not). */
  onImportConsumed?: () => void;
  /** Called when the user abandons the wizard entirely (header Cancel). */
  onCancel?: () => void;
}

const WIZARD_STEPS = [
  { key: "runtime", label: "Runtime" },
  { key: "identity", label: "Prompt & models" },
  { key: "access", label: "Access" },
  { key: "tools", label: "Tools & memory" },
  { key: "lifecycle", label: "Lifecycle & tags" },
] as const;
const REVIEW_STEP = WIZARD_STEPS.length;

export function AgentRegistrationForm({ mode, onRegister, onDeploy, onDeployHarness, isLoading, groupRestriction, ownerRestriction, exportAgentId, pendingImportJson, onImportConsumed, onCancel }: AgentRegistrationFormProps) {
  const { hasScope } = useAuth();

  // Wizard step (R2/R3/R4): 0..4 walk the guided sections, REVIEW_STEP is the
  // shared review/deploy page reached by either the guided path or import (R7).
  const [step, setStep] = useState<number>(exportAgentId ? REVIEW_STEP : 0);
  const [importApplied, setImportApplied] = useState(false);

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
  const [selectedProvider, setSelectedProvider] = useState<string>("bedrock");
  const [providerApiKey, setProviderApiKey] = useState("");
  const [providerBaseUrl, setProviderBaseUrl] = useState("");
  const [selectedRoleId, setSelectedRoleId] = useState<string>("");
  const [protocol] = useState("HTTP");
  const [networkMode, setNetworkMode] = useState("PUBLIC");
  const [agentFramework, setAgentFramework] = useState<string>("strands");
  const [vpcConfigId, setVpcConfigId] = useState<string>("");
  const [vpcConfigs, setVpcConfigs] = useState<VpcConfig[]>([]);

  // Security config state (pre-configured by Security Admin)
  const [selectedAuthConfigId, setSelectedAuthConfigId] = useState<string>("");

  // Role/VPC detail disclosure toggles
  const [showRolePerms, setShowRolePerms] = useState(false);
  const [showVpcDetail, setShowVpcDetail] = useState(false);
  const [vpcDetail, setVpcDetail] = useState<VpcConfigDetail | "loading" | null>(null);

  // Prompt & models step UI (16b)
  const [systemPromptExpanded, setSystemPromptExpanded] = useState(false);
  const [modelFilter, setModelFilter] = useState("");
  const [showAllProviderGroups, setShowAllProviderGroups] = useState(false);

  // Lifecycle state
  const [idleTimeout, setIdleTimeout] = useState("");
  const [maxLifetime, setMaxLifetime] = useState("");
  const [idleTimeoutError, setIdleTimeoutError] = useState("");
  const [maxLifetimeError, setMaxLifetimeError] = useState("");

  // Integrations state
  const [selectedMcpServerIds, setSelectedMcpServerIds] = useState<number[]>([]);
  const [selectedA2aAgentIds, setSelectedA2aAgentIds] = useState<number[]>([]);
  const [selectedMemoryIds, setSelectedMemoryIds] = useState<number[]>([]);
  const [selectedSkillIds, setSelectedSkillIds] = useState<string[]>([]);
  const [codeInterpreterEnabled, setCodeInterpreterEnabled] = useState(false);
  const [codeInterpreterRegion, setCodeInterpreterRegion] = useState("us-east-1");
  const [codeInterpreterNetworkMode, setCodeInterpreterNetworkMode] = useState("SANDBOX");
  const [codeInterpreterRoleId, setCodeInterpreterRoleId] = useState<string>("");
  const [mcpServers, setMcpServers] = useState<McpServer[]>([]);
  const [a2aAgents, setA2aAgents] = useState<A2aAgent[]>([]);
  const [memories, setMemories] = useState<MemoryResponse[]>([]);
  const [skills, setSkills] = useState<RegistryRecord[]>([]);

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
  const [litellmModels, setLitellmModels] = useState<ModelOption[]>([]);
  const [litellmModelsLoaded, setLitellmModelsLoaded] = useState(false);
  const [providers, setProviders] = useState<Provider[]>([]);
  const [managedRoles, setManagedRoles] = useState<ManagedRole[]>([]);
  const [authConfigs, setAuthConfigs] = useState<AuthorizerConfigResponse[]>([]);
  const [defaults, setDefaults] = useState<agentsApi.LoomDefaults>({ idle_timeout_seconds: 300, max_lifetime_seconds: 3600, region: "us-east-1" });

  const [dataLoaded, setDataLoaded] = useState(false);
  useEffect(() => {
    void agentsApi.fetchModels().then(setModels).catch(() => {});
    void agentsApi.fetchProviders().then(setProviders).catch(() => {});
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
        hasScope("registry:read")
          ? listRegistryRecords({ status: "APPROVED", descriptorType: "SKILL" }).then(setSkills).catch(() => {})
          : Promise.resolve(),
      ]).then(() => setDataLoaded(true));
    }
  }, [mode]);

  // 16g: lifecycle fields should hold the real default value, not a
  // placeholder that only reads like one — prefill once, and only if the
  // user (or an import/export apply) hasn't already set a value.
  useEffect(() => {
    setIdleTimeout((prev) => prev || String(defaults.idle_timeout_seconds));
    setMaxLifetime((prev) => prev || String(defaults.max_lifetime_seconds));
  }, [defaults]);

  // Auto-populate form when editing an existing agent
  const [loadedAgentId, setLoadedAgentId] = useState<number | undefined>(undefined);
  const pendingVpcConfigName = useRef<string | null>(null);
  const promptGutterRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!exportAgentId || !hasScope("admin:write")) return;
    if (exportAgentId === loadedAgentId) return;
    if (models.length === 0 || !dataLoaded) return;
    setLoadedAgentId(exportAgentId);
    void agentsApi.exportAgent(exportAgentId).then((parsed) => {
      if (parsed.deployment_type === "custom" || parsed.deployment_type === "managed") {
        setDeploymentType(parsed.deployment_type as DeploymentType);
      }
      if (typeof parsed.agent_framework === "string") setAgentFramework(parsed.agent_framework);
      if (parsed.name) setName(parsed.name as string);
      if (parsed.description) setDescription(parsed.description as string);
      if (parsed.system_prompt) setSystemPrompt(parsed.system_prompt as string);
      else if (parsed.persona) setSystemPrompt(parsed.persona as string);
      if (typeof parsed.provider === "string") setSelectedProvider(parsed.provider);
      if (typeof parsed.base_url === "string") setProviderBaseUrl(parsed.base_url);
      const importedAllowedModels = Array.isArray(parsed.allowed_models) ? (parsed.allowed_models as string[]) : undefined;
      if (parsed.provider === "litellm") {
        loadLitellmModels(typeof parsed.model === "string" ? parsed.model : undefined, importedAllowedModels);
      } else {
        if (parsed.model) {
          const match = models.find((m) => m.model_id === parsed.model || m.display_name === parsed.model);
          if (match) setModelId(match.model_id);
        }
        if (importedAllowedModels) {
          const validIds = models.map((m) => m.model_id);
          setSelectedAllowedModelIds(importedAllowedModels.filter((id) => validIds.includes(id)));
        }
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
      if (Array.isArray(parsed.skills)) {
        const ids = (parsed.skills as string[])
          .map((s) => skills.find((sk) => sk.name === s || sk.record_id === s)?.record_id)
          .filter((id): id is string => id !== undefined);
        setSelectedSkillIds(ids);
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
  const selectedProviderInfo = providers.find((p) => p.id === selectedProvider);
  const providerModels = selectedProvider === "litellm"
    ? litellmModels
    : models.filter((m) => !m.provider || m.provider === selectedProvider);
  // The catalog API returns models in whatever order the backend stored
  // them, not by recency — sort before handing them to any dropdown/list.
  const sortedProviderModels = groupModels(providerModels).flatMap(([, groupedModels]) => groupedModels);

  // LiteLLM models are only fetched on demand (when the provider is
  // selected, or an imported/edited manifest references it) — the endpoint
  // reflects exactly what's configured on the deployed proxy and shouldn't
  // be fetched eagerly alongside Bedrock's list on page load.
  const loadLitellmModels = (matchModelName?: string, matchAllowedModelIds?: string[]) => {
    setLitellmModelsLoaded(false);
    void agentsApi.fetchLitellmModels().then((list) => {
      setLitellmModels(list);
      setLitellmModelsLoaded(true);
      if (matchModelName) {
        const match = list.find((m) => m.model_id === matchModelName || m.display_name === matchModelName);
        if (match) setModelId(match.model_id);
      }
      if (matchAllowedModelIds) {
        const validIds = list.map((m) => m.model_id);
        setSelectedAllowedModelIds(matchAllowedModelIds.filter((id) => validIds.includes(id)));
      }
    }).catch(() => {
      setLitellmModels([]);
      setLitellmModelsLoaded(true);
    });
  };

  // A provider without harness support can only run as a Custom Agent —
  // fail fast in the UI instead of letting the backend reject it after deploy.
  useEffect(() => {
    if (selectedProviderInfo && !selectedProviderInfo.harness_supported && deploymentType === "managed") {
      setDeploymentType("custom");
    }
  }, [selectedProviderInfo, deploymentType]);

  const handleProviderChange = (providerId: string) => {
    setSelectedProvider(providerId);
    // Previous model/credentials may not apply under the new provider.
    setModelId("");
    setSelectedAllowedModelIds([]);
    setProviderApiKey("");
    setProviderBaseUrl("");
    if (providerId === "litellm") {
      loadLitellmModels();
    }
  };

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
  // Only custom-deploy agents share AgentCore Runtime V2's environmentVariables
  // budget for their system prompt — managed/harness agents pass it via
  // CreateHarness's dedicated systemPrompt field and aren't capped by this.
  const systemPromptBytes = utf8ByteLength(systemPrompt);
  const systemPromptTooLarge = deploymentType === "custom" && systemPromptBytes > MAX_SYSTEM_PROMPT_BYTES;
  // loom:group is what authorization is keyed on, so the API refuses a create
  // without it — block the deploy rather than surface a 400.
  const missingGroupTag = !tagValues["loom:group"];

  // Shared by the "View / Paste JSON" disclosure and manifest import (R5/R6):
  // parses a manifest and applies it to form state. Returns an error string on
  // failure (invalid JSON), or null on success.
  const applyManifestJson = (json: string): string | null => {
    try {
      const parsed = JSON.parse(json);
      if (parsed.deployment_type === "custom" || parsed.deployment_type === "managed") {
        setDeploymentType(parsed.deployment_type);
      }
      if (typeof parsed.agent_framework === "string") setAgentFramework(parsed.agent_framework);
      if (parsed.name) setName(parsed.name);
      if (parsed.description) setDescription(parsed.description);
      if (parsed.system_prompt) setSystemPrompt(parsed.system_prompt);
      else if (parsed.persona) setSystemPrompt(parsed.persona);
      // provider may be a flat string (legacy manifests / backend export) or
      // a nested { id, base_url, api_key } object (current manifest format).
      let providerId: string | undefined;
      if (typeof parsed.provider === "string") {
        providerId = parsed.provider;
        if (typeof parsed.base_url === "string") setProviderBaseUrl(parsed.base_url);
        if (typeof parsed.api_key === "string") setProviderApiKey(parsed.api_key);
      } else if (parsed.provider && typeof parsed.provider === "object") {
        const providerBlock = parsed.provider as Record<string, unknown>;
        if (typeof providerBlock.id === "string") providerId = providerBlock.id;
        if (typeof providerBlock.base_url === "string") setProviderBaseUrl(providerBlock.base_url);
        if (typeof providerBlock.api_key === "string") setProviderApiKey(providerBlock.api_key);
      }
      if (providerId) setSelectedProvider(providerId);
      const importedAllowedModels = Array.isArray(parsed.allowed_models) ? (parsed.allowed_models as string[]) : undefined;
      if (providerId === "litellm") {
        loadLitellmModels(typeof parsed.model === "string" ? parsed.model : undefined, importedAllowedModels);
      } else {
        if (parsed.model) {
          const match = models.find((m) => m.model_id === parsed.model || m.display_name === parsed.model);
          if (match) setModelId(match.model_id);
        }
        if (importedAllowedModels) {
          const validIds = models.map((m) => m.model_id);
          setSelectedAllowedModelIds(importedAllowedModels.filter((id: string) => validIds.includes(id)));
        }
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
      if (Array.isArray(parsed.skills)) {
        const ids = parsed.skills
          .map((s: string) => skills.find((sk) => sk.name === s || sk.record_id === s)?.record_id)
          .filter((id: string | undefined): id is string => id !== undefined);
        setSelectedSkillIds(ids);
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
  };

  // R6: a manifest handed in from the import chooser is applied once the
  // reference data (models, roles, MCP servers, ...) needed to resolve its
  // names is loaded, then the form jumps straight to the review step.
  useEffect(() => {
    if (!pendingImportJson || importApplied) return;
    if (models.length === 0 || !dataLoaded) return;
    setImportApplied(true);
    const error = applyManifestJson(pendingImportJson);
    if (error) {
      toast.error(error);
    } else {
      setStep(REVIEW_STEP);
    }
    onImportConsumed?.();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pendingImportJson, importApplied, models.length, dataLoaded]);

  // R3: per-step validation gating the wizard's Next button. Rail navigation
  // (jumping directly to a step) stays unrestricted — steps show state, not gates.
  const stepValid = (i: number): boolean => {
    switch (i) {
      case 1: return !!name.trim() && !nameError && !!modelId && !systemPromptTooLarge;
      case 2: return !!selectedRoleId;
      case 4: return !idleTimeoutError && !maxLifetimeError;
      default: return true;
    }
  };

  // R2/16a: a short current-value subline under each rail label, so the
  // whole agent can be scanned without stepping through it.
  const stepSummary = (i: number): string => {
    switch (i) {
      case 0: return deploymentType === "managed" ? "managed" : `custom · ${agentFramework}`;
      case 1: return (models.find((m) => m.model_id === modelId)?.display_name ?? litellmModels.find((m) => m.model_id === modelId)?.display_name ?? modelId) || "no model";
      case 2: return `${networkMode.toLowerCase()}${selectedRole ? ` · ${selectedRole.role_name}` : ""}`;
      case 3: return `${selectedMcpServerIds.length + selectedA2aAgentIds.length} tools · ${selectedMemoryIds.length} memory`;
      case 4: return `${humanizeSeconds(idleTimeout) || "defaults"} idle`;
      default: return "";
    }
  };

  // 16g: a single Cancel action (header) replaces the duplicate that used to
  // also live at the bottom of the review step.
  // Shared by the "View / Paste JSON" export and the review step's "Export
  // manifest" link (16f) — the same object both paths converge on (R7).
  const buildManifestJson = async (): Promise<string> => {
    if (exportAgentId && hasScope("admin:write")) {
      const data = await agentsApi.exportAgent(exportAgentId);
      // base_url/api_key are resolved from the global LiteLLM
      // connection now, not per-agent — drop them from the
      // manifest and just record which provider was used.
      const { base_url: _base_url, api_key: _api_key, ...rest } = data;
      return JSON.stringify(rest, null, 2);
    }
    const result: Record<string, unknown> = {};
    result.deployment_type = deploymentType;
    if (deploymentType === "custom" && agentFramework !== "strands") {
      result.agent_framework = agentFramework;
    }
    if (name) result.name = name;
    if (description) result.description = description;
    if (systemPrompt) result.system_prompt = systemPrompt;
    if (modelId) result.model = modelId;
    if (selectedAllowedModelIds.length > 0) {
      result.allowed_models = selectedAllowedModelIds;
    }
    if (selectedProvider && selectedProvider !== "bedrock") {
      result.provider = selectedProvider;
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
    if (selectedSkillIds.length > 0) {
      result.skills = selectedSkillIds.map((id) => {
        const skill = skills.find((s) => s.record_id === id);
        return skill?.name ?? id;
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
  };

  const resetFormFields = () => {
    setName("");
    setDescription("");
    setSystemPrompt("");
    setModelId("");
    setSelectedProvider("bedrock");
    setProviderApiKey("");
    setProviderBaseUrl("");
    setSelectedRoleId("");
    setNetworkMode("PUBLIC");
    setAgentFramework("strands");
    setSelectedAuthConfigId("");
    setIdleTimeout("");
    setMaxLifetime("");
    setIdleTimeoutError("");
    setMaxLifetimeError("");
    setTagValues({});
    setSelectedMcpServerIds([]);
    setSelectedA2aAgentIds([]);
    setSelectedMemoryIds([]);
    setSelectedSkillIds([]);
    setCodeInterpreterEnabled(false);
    setCodeInterpreterRegion("us-east-1");
    setCodeInterpreterNetworkMode("SANDBOX");
    setCodeInterpreterRoleId("");
    setStep(0);
    setImportApplied(false);
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (mode === "register") {
      if (!arn.trim()) return;
      await onRegister(arn.trim(), modelId || undefined);
      setArn("");
    } else if (deploymentType === "managed") {
      if (!name.trim() || !modelId || !selectedRoleId || !onDeployHarness || hasValidationErrors || missingGroupTag) return;

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
        provider: selectedProvider,
        ...(providerApiKey ? { api_key: providerApiKey } : {}),
        ...(providerBaseUrl ? { base_url: providerBaseUrl } : {}),
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
        skill_ids: selectedSkillIds,
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
      if (!name.trim() || !modelId || !selectedRoleId || !onDeploy || hasValidationErrors || systemPromptTooLarge || missingGroupTag) return;

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
        provider: selectedProvider,
        // Omit empty api_key/base_url so an edit that doesn't touch the
        // credential doesn't overwrite a previously-stored secret.
        ...(providerApiKey ? { api_key: providerApiKey } : {}),
        ...(providerBaseUrl ? { base_url: providerBaseUrl } : {}),
        role_arn: roleArn,
        protocol,
        network_mode: networkMode,
        agent_framework: agentFramework,
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
        skill_ids: selectedSkillIds,
        code_interpreter_enabled: codeInterpreterEnabled,
        code_interpreter_region: codeInterpreterRegion,
        code_interpreter_network_mode: codeInterpreterNetworkMode,
        code_interpreter_role_id: codeInterpreterRoleId ? parseInt(codeInterpreterRoleId) : null,
        tags: Object.fromEntries(
          Object.entries(tagValues).filter(([, v]) => v.trim() !== "")
        ),
      };
      await onDeploy(request);
      setSelectedAllowedModelIds([]);
      resetFormFields();
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
                  options={groupModels(models).flatMap(([, groupedModels]) => groupedModels).map((m) => ({ value: m.model_id, label: m.display_name, group: m.group }))}
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
          <div className="space-y-4">
              {/* Wizard header (R1/R8): title + abandon action. */}
              <div className="flex items-center justify-between">
                <div className="text-sm font-medium">{exportAgentId ? "Edit agent" : "New agent — guided setup"}</div>
                {onCancel && (
                  <Button
                    type="button"
                    size="sm"
                    variant="ghost"
                    disabled={isLoading}
                    onClick={() => { resetFormFields(); onCancel(); }}
                  >
                    Cancel
                  </Button>
                )}
              </div>

              {/* JSON Import / Export (R5): also reachable mid-wizard, e.g. to re-paste a manifest. */}
              <JsonConfigSection
                onApply={applyManifestJson}
                label="View / Paste JSON"
                onExport={buildManifestJson}
                placeholder='{"deployment_type": "custom|managed", "name": "...", "system_prompt": "...", "model": "...", "role": "...", "mcp_servers": ["..."], "a2a_agents": ["..."], "memories": ["..."], "code_interpreter": {"enabled": true, "region": "us-east-1", "network_mode": "SANDBOX", "role": "..."}}'
              />

              {/* R2/R3/R4: step rail + current step's fields, or the shared review step (R7). */}
              <div className="grid grid-cols-[170px_minmax(0,1fr)] gap-4 items-start">
                <div className="space-y-1">
                  {WIZARD_STEPS.map((s, i) => (
                    <button
                      key={s.key}
                      type="button"
                      onClick={() => setStep(i)}
                      className={`flex w-full items-start gap-2 rounded-md px-2.5 py-2 text-left text-xs transition-colors ${
                        step === i ? "bg-accent text-foreground" : "text-muted-foreground hover:bg-accent/50"
                      }`}
                    >
                      <span
                        className={`mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-[10px] ${
                          step === i
                            ? "bg-primary text-primary-foreground"
                            : stepValid(i) && step > i
                              ? "bg-emerald-500/15 text-emerald-600"
                              : "border border-border"
                        }`}
                      >
                        {step > i && stepValid(i) ? "✓" : i + 1}
                      </span>
                      <span className="flex flex-col gap-0.5 min-w-0">
                        <span className={step === i ? "font-medium" : ""}>{s.label}</span>
                        <span className="truncate font-mono text-[10px] text-muted-foreground">{stepSummary(i)}</span>
                      </span>
                    </button>
                  ))}
                  <div className="my-1.5 h-px bg-border" />
                  <button
                    type="button"
                    onClick={() => setStep(REVIEW_STEP)}
                    className={`flex w-full items-center gap-2 rounded-md px-2.5 py-2 text-left text-xs transition-colors ${
                      step === REVIEW_STEP ? "bg-accent font-medium text-foreground" : "text-muted-foreground hover:bg-accent/50"
                    }`}
                  >
                    <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full border border-border text-[10px]">
                      &rarr;
                    </span>
                    Review &amp; deploy
                  </button>
                </div>

                <div className="min-w-0 space-y-5">

              {/* Deployment Type Selector */}
              {step === 0 && (<>
              <div className="rounded-lg border bg-card">
              <div className="space-y-5 p-4">
              <div className="space-y-0.5">
                <h3 className="text-sm font-semibold">Runtime</h3>
                <p className="text-xs text-muted-foreground">Where the agent loop runs and which SDK it&apos;s built on.</p>
              </div>

              <section className="space-y-2">
                <h4 className="text-xs font-medium">Deployment type</h4>
                <div className="grid grid-cols-2 gap-2.5">
                  <label
                    className={`flex cursor-pointer gap-2.5 rounded-md border p-3 text-sm ${
                      deploymentType === "custom" ? "border-primary bg-primary/5 ring-1 ring-primary/20" : "border-border"
                    }`}
                  >
                    <input
                      type="radio"
                      name="deploymentType"
                      value="custom"
                      checked={deploymentType === "custom"}
                      onChange={() => setDeploymentType("custom")}
                      className="mt-0.5 h-3.5 w-3.5 shrink-0"
                    />
                    <span className="space-y-0.5">
                      <span className="block font-medium">Custom agent</span>
                      <span className="block text-xs text-muted-foreground">Deploys your agent code into AgentCore Runtime. You choose the framework.</span>
                    </span>
                  </label>
                  <label
                    className={`flex gap-2.5 rounded-md border p-3 text-sm ${
                      selectedProviderInfo && !selectedProviderInfo.harness_supported ? "cursor-not-allowed opacity-50" : "cursor-pointer"
                    } ${deploymentType === "managed" ? "border-primary bg-primary/5 ring-1 ring-primary/20" : "border-border"}`}
                  >
                    <input
                      type="radio"
                      name="deploymentType"
                      value="managed"
                      checked={deploymentType === "managed"}
                      disabled={selectedProviderInfo ? !selectedProviderInfo.harness_supported : false}
                      onChange={() => setDeploymentType("managed")}
                      className="mt-0.5 h-3.5 w-3.5 shrink-0"
                    />
                    <span className="space-y-0.5">
                      <span className="block font-medium">Managed agent</span>
                      <span className="block text-xs text-muted-foreground">Fully managed agent loop via AgentCore Harness. No framework to pick.</span>
                    </span>
                  </label>
                </div>
              </section>

              {/* Agent Framework Selector (custom-code path only) */}
              {deploymentType === "custom" && (
                <section className="space-y-2">
                  <h4 className="text-xs font-medium">Framework</h4>
                  <div className="inline-flex self-start rounded-md border bg-accent/40 p-0.5">
                    <button
                      type="button"
                      onClick={() => setAgentFramework("strands")}
                      className={`rounded-[5px] px-3 py-1 text-xs font-medium transition-colors ${
                        agentFramework === "strands" ? "bg-background shadow-sm" : "text-muted-foreground"
                      }`}
                    >
                      Strands Agents
                    </button>
                    <button
                      type="button"
                      onClick={() => setAgentFramework("adk")}
                      className={`rounded-[5px] px-3 py-1 text-xs font-medium transition-colors ${
                        agentFramework === "adk" ? "bg-background shadow-sm" : "text-muted-foreground"
                      }`}
                    >
                      Google ADK
                    </button>
                  </div>
                </section>
              )}
              </div>

              <div className="flex items-center gap-2 border-t px-4 py-2.5">
                <span className="font-mono text-[11px] text-muted-foreground">Step 1 of {WIZARD_STEPS.length}</span>
                <Button type="button" size="sm" className="ml-auto" onClick={() => setStep(1)}>
                  Next: Prompt &amp; models &rarr;
                </Button>
              </div>
              </div>
              </>)}

              {/* Prompt & models (16b) */}
              {step === 1 && (
              <div className="rounded-lg border bg-card">
              <div className="space-y-5 p-4">
              <div className="space-y-0.5">
                <h3 className="text-sm font-semibold">Prompt &amp; models</h3>
                <p className="text-xs text-muted-foreground">How the agent is named in the catalog, what it&apos;s told to do, and which models it can use.</p>
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div className="space-y-1.5">
                  <label className="text-sm font-medium">Name</label>
                  <Input
                    placeholder="Agent name"
                    value={name}
                    onChange={(e) => { setName(e.target.value); validateName(e.target.value); }}
                    required
                    disabled={!!exportAgentId}
                    className={nameError ? "border-red-500" : ""}
                  />
                  {nameError ? (
                    <p className="text-xs text-red-500">{nameError}</p>
                  ) : exportAgentId ? (
                    <p className="text-[11px] text-muted-foreground">Locked after deploy.</p>
                  ) : null}
                </div>
                <div className="min-w-0 space-y-1.5">
                  <label className="text-sm font-medium">Description</label>
                  <Input
                    placeholder="Description (optional)"
                    value={description}
                    onChange={(e) => setDescription(e.target.value)}
                  />
                </div>
              </div>

              {/* System prompt: code-editor surface with line numbers + char/token count (16b) */}
              <div className="space-y-1.5">
                <div className="flex items-center gap-2">
                  <label className="text-sm font-medium">System prompt</label>
                  <div className="ml-auto flex items-center gap-3 font-mono text-[10.5px] text-muted-foreground">
                    <span>{systemPrompt.length} chars · ~{estimateTokens(systemPrompt)} tokens</span>
                    {deploymentType === "custom" && (
                      <span className={systemPromptTooLarge ? "text-destructive font-medium" : ""}>
                        {systemPromptBytes} / {MAX_SYSTEM_PROMPT_BYTES} bytes
                      </span>
                    )}
                    <button type="button" onClick={() => setSystemPromptExpanded(!systemPromptExpanded)} className="text-primary hover:underline">
                      {systemPromptExpanded ? "collapse" : "expand"}
                    </button>
                  </div>
                </div>
                {systemPromptTooLarge && (
                  <p className="text-xs text-destructive">
                    System prompt is too large ({systemPromptBytes} bytes, limit {MAX_SYSTEM_PROMPT_BYTES}). AgentCore Runtime V2
                    caps the total environment variable payload at 1536 bytes, shared with fixed config and integrations — shorten the prompt to deploy.
                  </p>
                )}
                <div className={`flex rounded-md border bg-muted/30 ${systemPromptExpanded ? "h-[28rem]" : "h-56"}`}>
                  <div
                    ref={promptGutterRef}
                    aria-hidden
                    className="select-none overflow-hidden border-r bg-muted/60 px-2.5 py-2 text-right font-mono text-[11px] leading-[1.6] text-muted-foreground"
                  >
                    {Array.from({ length: Math.max(systemPrompt.split("\n").length, 1) }, (_, i) => (
                      <div key={i}>{i + 1}</div>
                    ))}
                  </div>
                  <Textarea
                    placeholder={"Persona: You are a helpful customer support agent that resolves billing inquiries for an e-commerce platform.\n\nInstructions: Look up the customer's order history, identify the issue, and provide a resolution within company policy.\n\nGuidelines: Use a friendly and professional tone, never share internal system details, and escalate to a human agent if the customer requests it."}
                    value={systemPrompt}
                    onChange={(e) => setSystemPrompt(e.target.value)}
                    onScroll={(e) => {
                      if (promptGutterRef.current) promptGutterRef.current.scrollTop = e.currentTarget.scrollTop;
                    }}
                    wrap="off"
                    // Line numbers are counted from "\n" alone (one per logical
                    // line) — soft-wrapping would make a long line visually span
                    // multiple rows and desync the gutter, so wrapping is off and
                    // long lines scroll horizontally instead.
                    // Textarea's own base class sets text-base + md:text-sm, which
                    // would otherwise beat our size at the md breakpoint and up —
                    // override both so the font matches the line-number gutter.
                    className="min-h-0 flex-1 resize-none overflow-auto whitespace-pre rounded-none border-0 bg-transparent px-3 py-2 font-mono text-[11px] md:text-[11px] leading-[1.6] shadow-none focus-visible:ring-0 [field-sizing:fixed]!"
                  />
                </div>
              </div>

              <div className="h-px bg-border" />

              <div className="flex items-center gap-2">
                <h4 className="text-sm font-semibold">Models</h4>
                <div className="ml-auto inline-flex rounded-md border bg-accent/40 p-0.5">
                  {providers.map((p) => (
                    <button
                      key={p.id}
                      type="button"
                      disabled={!p.available}
                      title={p.available ? undefined : `Enable ${p.display_name} in Settings → Models first.`}
                      onClick={() => handleProviderChange(p.id)}
                      className={`rounded-[5px] px-3 py-1 text-xs font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-50 ${
                        selectedProvider === p.id ? "bg-background shadow-sm" : "text-muted-foreground"
                      }`}
                    >
                      {p.display_name}
                    </button>
                  ))}
                </div>
              </div>

              {selectedProviderInfo && !selectedProviderInfo.available && (
                <p className="-mt-2 text-[11px] text-muted-foreground">{selectedProviderInfo.display_name} is not enabled — configure it in Settings → Models first.</p>
              )}
              {selectedProviderInfo && !selectedProviderInfo.harness_supported && deploymentType === "custom" && (
                <p className="-mt-2 text-[11px] text-muted-foreground">Managed Agent deployment is not available for {selectedProviderInfo.display_name}.</p>
              )}
              {(selectedProviderInfo?.requires_api_key || selectedProviderInfo?.requires_base_url) && (
                <div className="flex gap-3">
                  {selectedProviderInfo.requires_base_url && (
                    <Input placeholder="Base URL (e.g. https://litellm.example.com)" value={providerBaseUrl} onChange={(e) => setProviderBaseUrl(e.target.value)} className="flex-1 min-w-0" />
                  )}
                  {selectedProviderInfo.requires_api_key && (
                    <Input type="password" placeholder={exportAgentId ? "API key (leave blank to keep current)" : "API key"} value={providerApiKey} onChange={(e) => setProviderApiKey(e.target.value)} className="flex-1 min-w-0" autoComplete="off" />
                  )}
                </div>
              )}
              {selectedProvider === "litellm" && (
                <p className="text-[11px] text-muted-foreground">Base URL and a scoped virtual key are resolved automatically from the LiteLLM connection configured in Settings → Models.</p>
              )}
              {selectedProvider === "litellm" && litellmModelsLoaded && litellmModels.length === 0 && (
                <p className="text-[11px] text-destructive">No LiteLLM models detected — configure the connection in Settings → Models.</p>
              )}

              {/* Default model: a clearly-labeled dropdown, highlighted as the DEFAULT (16b) */}
              <div className="space-y-1.5">
                <label className="text-sm font-medium">Default model</label>
                <div className="flex items-center gap-3 rounded-md border border-primary/35 bg-primary/5 px-3 py-2">
                  <span className="shrink-0 font-mono text-[9.5px] tracking-wide text-primary">DEFAULT</span>
                  <SearchableSelect
                    className="min-w-0 flex-1"
                    options={sortedProviderModels.map((m) => ({ value: m.model_id, label: m.display_name, group: m.group }))}
                    value={modelId}
                    onValueChange={setModelId}
                    placeholder="Select default model..."
                  />
                  {modelId && sortedProviderModels.find((m) => m.model_id === modelId)?.group && (
                    <span className="shrink-0 font-mono text-[11px] text-muted-foreground">{sortedProviderModels.find((m) => m.model_id === modelId)?.group}</span>
                  )}
                </div>
              </div>

              {/* Allowed at runtime: filterable provider chip grid (16b) */}
              {modelId && providerModels.length > 0 && (() => {
                const nonEmbedding = providerModels.filter((m) => !isEmbeddingModel(m));
                const embeddingCount = providerModels.length - nonEmbedding.length;
                const filterText = modelFilter.trim().toLowerCase();
                const groups = groupModels(nonEmbedding);
                const isSelected = (id: string) => id === modelId || selectedAllowedModelIds.includes(id);
                const totalSelected = new Set([modelId, ...selectedAllowedModelIds]).size;
                const visible = groups.filter(([, ms]) => filterText || showAllProviderGroups || ms.some((m) => isSelected(m.model_id)));
                const collapsed = groups.filter(([, ms]) => !(filterText || showAllProviderGroups || ms.some((m) => isSelected(m.model_id))));
                return (
                  <div className="space-y-2">
                    <div className="flex items-center gap-2">
                      <label className="text-sm font-medium">Allowed at runtime</label>
                      <span className="rounded bg-accent px-1.5 py-0.5 font-mono text-[11px] text-muted-foreground">{totalSelected}</span>
                      <Input
                        value={modelFilter}
                        onChange={(e) => setModelFilter(e.target.value)}
                        placeholder="Filter models"
                        className="ml-auto h-7 w-40 text-xs"
                      />
                    </div>
                    <div className="overflow-hidden rounded-md border">
                      {visible.map(([group, ms]) => {
                        const matched = filterText ? ms.filter((m) => m.display_name.toLowerCase().includes(filterText)) : ms;
                        if (filterText && matched.length === 0) return null;
                        const selectedCount = ms.filter((m) => isSelected(m.model_id)).length;
                        return (
                          <div key={group} className="grid grid-cols-[96px_minmax(0,1fr)] gap-2.5 border-b p-2.5 last:border-b-0">
                            <div className="flex items-center gap-1.5 pt-0.5">
                              <span className="text-xs font-medium">{group}</span>
                              <span className="font-mono text-[10px] text-muted-foreground">{selectedCount}/{ms.length}</span>
                            </div>
                            <div className="flex flex-wrap gap-1.5">
                              {matched.map((m) => {
                                const selected = isSelected(m.model_id);
                                const isDefault = m.model_id === modelId;
                                return (
                                  <button
                                    key={m.model_id}
                                    type="button"
                                    disabled={isDefault}
                                    onClick={() => {
                                      if (isDefault) return;
                                      setSelectedAllowedModelIds((prev) => selected ? prev.filter((id) => id !== m.model_id) : [...prev, m.model_id]);
                                    }}
                                    className={`rounded-md px-2 py-1 text-[11.5px] transition-colors ${
                                      selected ? "bg-primary text-primary-foreground" : "border text-foreground hover:bg-accent"
                                    } ${isDefault ? "cursor-default" : ""}`}
                                  >
                                    {chipLabel(m.display_name)}
                                    {isDefault && <span className="ml-1 font-mono text-[9px] opacity-80">default</span>}
                                  </button>
                                );
                              })}
                            </div>
                          </div>
                        );
                      })}
                      {collapsed.length > 0 && (
                        <div className="flex items-center gap-2 bg-muted/40 p-2.5">
                          <span className="text-[11.5px] text-muted-foreground">
                            {collapsed.map(([g]) => g).join(" · ")} · {collapsed.reduce((n, [, ms]) => n + ms.length, 0)} models, 0 selected
                          </span>
                          <button type="button" onClick={() => setShowAllProviderGroups(true)} className="ml-auto text-[11.5px] text-primary hover:underline">
                            Show
                          </button>
                        </div>
                      )}
                    </div>
                    {embeddingCount > 0 && (
                      <p className="text-[11px] text-muted-foreground">{embeddingCount} embedding model{embeddingCount === 1 ? "" : "s"} hidden. They can&apos;t be used for chat.</p>
                    )}
                  </div>
                );
              })()}

              {deploymentType === "managed" && (
                <>
                <div className="h-px bg-border" />
                <div className="space-y-3">
                  <h4 className="text-sm font-medium">Managed agent parameters</h4>
                  <div className="grid grid-cols-2 gap-3">
                    <div className="space-y-1">
                      <label className="text-xs text-muted-foreground">Max Iterations</label>
                      <Input type="number" placeholder="Defaults to 75" value={harnessMaxIterations} onChange={(e) => setHarnessMaxIterations(e.target.value)} min={1} />
                    </div>
                    <div className="space-y-1">
                      <label className="text-xs text-muted-foreground">Max Tokens</label>
                      <Input type="number" placeholder="Model default" value={harnessMaxTokens} onChange={(e) => setHarnessMaxTokens(e.target.value)} min={1} />
                    </div>
                  </div>
                  <div className="space-y-2">
                    <div className="flex items-center gap-2">
                      <input type="checkbox" id="enable-human-confirmation" checked={enableHumanConfirmation} onChange={(e) => setEnableHumanConfirmation(e.target.checked)} className="h-4 w-4 rounded border-border" />
                      <label htmlFor="enable-human-confirmation" className="text-xs text-muted-foreground">Enable human confirmation (inline function HITL)</label>
                    </div>
                    {enableHumanConfirmation && (
                      <div className="space-y-1">
                        <label className="text-xs text-muted-foreground">Confirmation Policy</label>
                        <Textarea placeholder="Describe when the agent should ask for human confirmation..." value={confirmationPolicy} onChange={(e) => setConfirmationPolicy(e.target.value)} rows={3} className="text-xs" />
                      </div>
                    )}
                  </div>
                </div>
                </>
              )}
              </div>

              <div className="flex items-center gap-2 border-t px-4 py-2.5">
                <span className="font-mono text-[11px] text-muted-foreground">Step 2 of {WIZARD_STEPS.length}</span>
                <Button type="button" variant="outline" size="sm" className="ml-auto" onClick={() => setStep(0)}>&larr; Back</Button>
                <Button type="button" size="sm" disabled={!stepValid(1)} onClick={() => setStep(2)}>Next: Access &rarr;</Button>
              </div>
              </div>
              )}

              {/* Access (16c) */}
              {step === 2 && (
              <div className="rounded-lg border bg-card">
              <div className="space-y-5 p-4">
              <div className="space-y-0.5">
                <h3 className="text-sm font-semibold">Access</h3>
                <p className="text-xs text-muted-foreground">Who can call the agent, and what it can reach in AWS.</p>
              </div>

              <section className="space-y-2">
                <h4 className="text-sm font-medium">Network</h4>
                <div className="grid grid-cols-2 gap-2.5">
                  <label
                    className={`flex cursor-pointer gap-2.5 rounded-md border p-3 text-sm ${
                      networkMode === "PUBLIC" ? "border-primary bg-primary/5 ring-1 ring-primary/20" : "border-border"
                    }`}
                  >
                    <input type="radio" name="networkMode" checked={networkMode === "PUBLIC"} onChange={() => setNetworkMode("PUBLIC")} className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                    <span className="space-y-0.5">
                      <span className="block font-medium">Public</span>
                      <span className="block text-xs text-muted-foreground">Internet-reachable, auth required</span>
                    </span>
                  </label>
                  <label
                    className={`flex cursor-pointer gap-2.5 rounded-md border p-3 text-sm ${
                      networkMode === "VPC" ? "border-primary bg-primary/5 ring-1 ring-primary/20" : "border-border"
                    }`}
                  >
                    <input type="radio" name="networkMode" checked={networkMode === "VPC"} onChange={() => setNetworkMode("VPC")} className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                    <span className="space-y-0.5">
                      <span className="block font-medium">VPC</span>
                      <span className="block text-xs text-muted-foreground">Private subnets + security groups</span>
                    </span>
                  </label>
                </div>
                {networkMode === "VPC" && (
                  <div className="space-y-1.5 pt-1">
                    <label className="text-xs text-muted-foreground">VPC configuration</label>
                    <SearchableSelect
                      options={vpcConfigs.map((c) => ({ value: c.id.toString(), label: c.name, description: `${c.vpc_id} · ${c.subnet_ids.length} subnets · ${c.sg_ids.length} SGs` }))}
                      value={vpcConfigId}
                      onValueChange={(v) => { setVpcConfigId(v); setShowVpcDetail(false); setVpcDetail(null); }}
                      placeholder="Select VPC configuration..."
                    />
                    {vpcConfigs.length === 0 && (
                      <p className="text-xs text-muted-foreground">No VPC configurations available. Add one in Settings → Networking.</p>
                    )}
                  </div>
                )}
                {networkMode === "VPC" && selectedVpcConfig && (
                  <div className="space-y-2 pt-1">
                    <button
                      type="button"
                      onClick={() => {
                        const next = !showVpcDetail;
                        setShowVpcDetail(next);
                        if (next && !vpcDetail) {
                          setVpcDetail("loading");
                          settingsApi.getVpcConfigDetail(selectedVpcConfig.id).then(setVpcDetail).catch(() => setVpcDetail(null));
                        }
                      }}
                      className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
                    >
                      {showVpcDetail ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}
                      VPC details (read-only)
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

              <section className="space-y-2">
                <h4 className="text-sm font-medium">Execution role</h4>
                <SearchableSelect
                  className="w-1/2 min-w-0"
                  options={filteredRoles.map((r) => ({ value: r.id.toString(), label: r.role_name }))}
                  value={selectedRoleId}
                  onValueChange={setSelectedRoleId}
                  placeholder="Select managed role..."
                />
                {selectedRole && (
                  <>
                    <div className="flex flex-wrap items-center gap-1.5">
                      {selectedRole.policy_document.Statement?.flatMap((stmt) => Array.isArray(stmt.Action) ? stmt.Action : [stmt.Action])
                        .slice(0, 3)
                        .map((action, i) => (
                          <span key={`${action}-${i}`} className="rounded bg-accent px-1.5 py-0.5 font-mono text-[10.5px] text-muted-foreground">{action}</span>
                        ))}
                      <button type="button" onClick={() => setShowRolePerms(!showRolePerms)} className="text-[10.5px] text-primary hover:underline">
                        {(() => {
                          const total = selectedRole.policy_document.Statement?.flatMap((stmt) => Array.isArray(stmt.Action) ? stmt.Action : [stmt.Action]).length ?? 0;
                          const remaining = total - 3;
                          return remaining > 0 ? `+${remaining} · view policy` : "view policy";
                        })()}
                      </button>
                    </div>
                    {showRolePerms && (
                      <div className="rounded border p-3 bg-muted/30">
                        <p className="text-xs text-muted-foreground mb-2">{selectedRole.role_arn}</p>
                        <PolicyViewer policy={selectedRole.policy_document} />
                      </div>
                    )}
                  </>
                )}
              </section>

              <section className="space-y-2">
                <h4 className="text-sm font-medium">Inbound authorizer</h4>
                <div className="w-1/2 min-w-0 overflow-hidden rounded-md border">
                  <SearchableSelect
                    triggerClassName={selectedAuthConfig ? "rounded-b-none border-b-0" : undefined}
                    options={[{ value: "", label: "None" }, ...authConfigs.map((c) => ({ value: c.id.toString(), label: c.name }))]}
                    value={selectedAuthConfigId}
                    onValueChange={setSelectedAuthConfigId}
                    placeholder="Select authorizer config..."
                  />
                  {selectedAuthConfig && (
                    <div className="grid grid-cols-[84px_minmax(0,1fr)] gap-x-3 gap-y-1.5 bg-muted/40 px-3 py-2.5 font-mono text-[11px]">
                      <div className="text-muted-foreground">TYPE</div><div>{selectedAuthConfig.authorizer_type}</div>
                      {selectedAuthConfig.pool_id && (<><div className="text-muted-foreground">POOL</div><div className="truncate">{selectedAuthConfig.pool_id}</div></>)}
                      {selectedAuthConfig.allowed_clients.length > 0 && (
                        <>
                          <div className="text-muted-foreground">CLIENTS</div>
                          <div className="flex flex-wrap gap-1">
                            {selectedAuthConfig.allowed_clients.map((c) => (
                              <span key={c} className="rounded border bg-background px-1.5 py-0.5">{truncateMiddle(c)}</span>
                            ))}
                          </div>
                        </>
                      )}
                      {selectedAuthConfig.discovery_url && (
                        <>
                          <div className="text-muted-foreground">DISCOVERY</div>
                          <div className="flex min-w-0 items-center gap-2">
                            <span className="truncate">{selectedAuthConfig.discovery_url}</span>
                            <button
                              type="button"
                              onClick={() => {
                                navigator.clipboard.writeText(selectedAuthConfig.discovery_url ?? "");
                                toast.success("Copied discovery URL");
                              }}
                              className="shrink-0 text-[10.5px] text-primary hover:underline"
                            >
                              copy
                            </button>
                          </div>
                        </>
                      )}
                      {selectedAuthConfig.allowed_audience.length > 0 && (<><div className="text-muted-foreground">AUDIENCE</div><div className="truncate">{selectedAuthConfig.allowed_audience.join(", ")}</div></>)}
                      {selectedAuthConfig.allowed_scopes.length > 0 && (<><div className="text-muted-foreground">SCOPES</div><div className="truncate">{selectedAuthConfig.allowed_scopes.join(", ")}</div></>)}
                    </div>
                  )}
                </div>
              </section>
              </div>

              <div className="flex items-center gap-2 border-t px-4 py-2.5">
                <span className="font-mono text-[11px] text-muted-foreground">Step 3 of {WIZARD_STEPS.length}</span>
                <Button type="button" variant="outline" size="sm" className="ml-auto" onClick={() => setStep(1)}>&larr; Back</Button>
                <Button type="button" size="sm" disabled={!stepValid(2)} onClick={() => setStep(3)}>Next: Tools &amp; memory &rarr;</Button>
              </div>
              </div>
              )}

              {/* Tools & memory (16d) */}
              {step === 3 && (
              <div className="rounded-lg border bg-card">
              <div className="space-y-5 p-4">
              <div className="space-y-0.5">
                <h3 className="text-sm font-semibold">Tools &amp; memory</h3>
                <p className="text-xs text-muted-foreground">Everything the agent can call during a turn.</p>
              </div>

              {hasScope("registry:read") && (
                <section className="space-y-2">
                  <div className="flex items-center gap-2">
                    <h4 className="text-sm font-medium">Skills</h4>
                    <span className="font-mono text-[10.5px] text-muted-foreground">{selectedSkillIds.length} of {skills.length}</span>
                  </div>
                  {skills.length === 0 ? (
                    <p className="text-xs italic text-muted-foreground">No approved skills available. Write one on the Skills page first.</p>
                  ) : (
                    <div className="overflow-hidden rounded-md border">
                      {skills.map((skill, i) => (
                        <label key={skill.record_id} className={`grid grid-cols-[16px_110px_minmax(0,1fr)_auto] items-center gap-2.5 px-3 py-2.5 text-xs cursor-pointer ${i > 0 ? "border-t" : ""}`}>
                          <input
                            type="checkbox"
                            className="h-3.5 w-3.5"
                            checked={selectedSkillIds.includes(skill.record_id)}
                            onChange={(e) => setSelectedSkillIds((prev) => e.target.checked ? [...prev, skill.record_id] : prev.filter((id) => id !== skill.record_id))}
                          />
                          <span className="truncate font-mono font-medium">{skill.name}</span>
                          <span className="truncate text-muted-foreground">{skill.description}</span>
                          {skill.record_version && <span className="font-mono text-[10.5px] text-muted-foreground">v{skill.record_version}</span>}
                        </label>
                      ))}
                    </div>
                  )}
                </section>
              )}

              <section className="space-y-2">
                {(() => {
                  const tools = [
                    ...filteredMcpServers.map((s) => ({
                      kind: "MCP" as const, id: s.id, name: s.name,
                      sub: (() => { try { return new URL(s.endpoint_url).host; } catch { return s.endpoint_url; } })(),
                      authType: s.auth_type, delegationMode: s.delegation_mode,
                      selected: selectedMcpServerIds.includes(s.id),
                      toggle: () => setSelectedMcpServerIds((prev) => prev.includes(s.id) ? prev.filter((id) => id !== s.id) : [...prev, s.id]),
                    })),
                    ...(deploymentType === "custom" ? filteredA2aAgents.map((a) => ({
                      kind: "A2A" as const, id: a.id, name: a.name,
                      sub: (() => { try { return new URL(a.base_url).host; } catch { return a.base_url; } })(),
                      authType: a.auth_type, delegationMode: a.delegation_mode,
                      selected: selectedA2aAgentIds.includes(a.id),
                      toggle: () => setSelectedA2aAgentIds((prev) => prev.includes(a.id) ? prev.filter((id) => id !== a.id) : [...prev, a.id]),
                    })) : []),
                  ];
                  const selectedCount = tools.filter((t) => t.selected).length;
                  return (
                    <>
                      <div className="flex items-center gap-2">
                        <h4 className="text-sm font-medium">Connected tools</h4>
                        <span className="font-mono text-[10.5px] text-muted-foreground">{selectedCount} of {tools.length}</span>
                      </div>
                      {tools.length === 0 ? (
                        <p className="text-xs italic text-muted-foreground">No MCP servers or A2A agents registered yet.</p>
                      ) : (
                        <div className="overflow-hidden rounded-md border">
                          {tools.map((t, i) => (
                            <label key={`${t.kind}-${t.id}`} className={`grid grid-cols-[16px_minmax(0,1fr)_auto] items-center gap-2.5 px-3 py-2.5 text-xs cursor-pointer ${i > 0 ? "border-t" : ""}`}>
                              <input type="checkbox" className="h-3.5 w-3.5" checked={t.selected} onChange={t.toggle} />
                              <span className="min-w-0">
                                <span className="flex items-center gap-1.5">
                                  <span className="truncate font-mono font-medium">{t.name}</span>
                                  <span className="rounded bg-accent px-1 font-mono text-[9.5px] tracking-wide text-muted-foreground">{t.kind}</span>
                                </span>
                                <span className="block truncate font-mono text-[10.5px] text-muted-foreground">{t.sub}</span>
                              </span>
                              {t.authType === "oauth2" && (
                                <span className="rounded bg-accent px-1.5 py-0.5 font-mono text-[10px] text-muted-foreground">
                                  OAuth2 · {t.delegationMode === "obo" ? "OBO" : "M2M"}
                                </span>
                              )}
                            </label>
                          ))}
                        </div>
                      )}
                    </>
                  );
                })()}
              </section>

              <section className="rounded-md border px-3 py-2.5 space-y-2.5">
                <div className="flex items-center gap-3">
                  <span className="space-y-0.5">
                    <span className="block text-sm font-medium">Code interpreter</span>
                    <span className="block text-[11.5px] text-muted-foreground">Sandboxed Python execution. Turn on to pick a network mode and role.</span>
                  </span>
                  <button
                    type="button"
                    onClick={() => setCodeInterpreterEnabled(!codeInterpreterEnabled)}
                    className={`ml-auto flex h-[17px] w-[30px] shrink-0 items-center rounded-full px-0.5 transition-colors ${codeInterpreterEnabled ? "justify-end bg-primary" : "justify-start bg-muted"}`}
                  >
                    <span className="h-3.5 w-3.5 rounded-full bg-white shadow" />
                  </button>
                </div>
                {codeInterpreterEnabled && (
                  <div className="grid grid-cols-3 gap-2 border-t pt-2.5">
                    <Select value={codeInterpreterNetworkMode} onValueChange={setCodeInterpreterNetworkMode}>
                      <SelectTrigger className="text-sm"><SelectValue /></SelectTrigger>
                      <SelectContent>
                        <SelectItem value="SANDBOX">Sandbox</SelectItem>
                        <SelectItem value="PUBLIC">Public</SelectItem>
                        <SelectItem value="VPC" disabled>VPC (coming soon)</SelectItem>
                      </SelectContent>
                    </Select>
                    <Select value={codeInterpreterRegion} onValueChange={setCodeInterpreterRegion}>
                      <SelectTrigger className="text-sm font-mono"><SelectValue /></SelectTrigger>
                      <SelectContent>
                        <SelectItem value="us-east-1">us-east-1 — N. Virginia</SelectItem>
                        <SelectItem value="us-west-2">us-west-2 — Oregon</SelectItem>
                        <SelectItem value="eu-west-1">eu-west-1 — Ireland</SelectItem>
                      </SelectContent>
                    </Select>
                    <SearchableSelect
                      options={managedRoles.filter((r) => r.role_type === "code_interpreter").map((r) => ({ value: r.id.toString(), label: r.role_name }))}
                      value={codeInterpreterRoleId}
                      onValueChange={setCodeInterpreterRoleId}
                      placeholder="Execution role (optional)"
                    />
                  </div>
                )}
              </section>

              <section className="space-y-2">
                <div className="flex items-center gap-2">
                  <h4 className="text-sm font-medium">Memory</h4>
                  <span className="font-mono text-[10.5px] text-muted-foreground">{selectedMemoryIds.length} of {filteredMemories.length}</span>
                </div>
                {filteredMemories.length === 0 ? (
                  <p className="text-xs italic text-muted-foreground">No memory resources available{groupRestriction ? " for your group" : ""}. Create one on the Memory page first.</p>
                ) : (
                  <div className="flex flex-wrap gap-1.5">
                    {filteredMemories.map((mem) => {
                      const selected = selectedMemoryIds.includes(mem.id);
                      return (
                        <button
                          key={mem.id}
                          type="button"
                          onClick={() => setSelectedMemoryIds((prev) => selected ? prev.filter((id) => id !== mem.id) : [...prev, mem.id])}
                          className={`rounded-md px-2.5 py-1 font-mono text-[11.5px] transition-colors ${selected ? "bg-primary text-primary-foreground" : "border text-foreground hover:bg-accent"}`}
                        >
                          {mem.name}
                          {mem.status !== "ACTIVE" && <span className="ml-1 text-[9.5px] opacity-80">{mem.status}</span>}
                        </button>
                      );
                    })}
                  </div>
                )}
              </section>
              </div>

              <div className="flex items-center gap-2 border-t px-4 py-2.5">
                <span className="font-mono text-[11px] text-muted-foreground">Step 4 of {WIZARD_STEPS.length}</span>
                <Button type="button" variant="outline" size="sm" className="ml-auto" onClick={() => setStep(2)}>&larr; Back</Button>
                <Button type="button" size="sm" onClick={() => setStep(4)}>Next: Lifecycle &amp; tags &rarr;</Button>
              </div>
              </div>
              )}

              {/* Lifecycle & tags (16e). Always mounted (just hidden off-step) rather
                  than conditionally rendered — ResourceTagFields resolves tagValues
                  from the selected profile in a mount-time effect, and manifest
                  import can jump straight to the review step without this step
                  ever rendering, which left tagValues stuck empty. */}
              <div className={step === 4 ? "rounded-lg border bg-card" : "hidden"}>
              <div className="space-y-5 p-4">
              <div className="space-y-0.5">
                <h3 className="text-sm font-semibold">Lifecycle &amp; tags</h3>
                <p className="text-xs text-muted-foreground">How long an idle or long-running session stays alive, and how AWS resources get tagged.</p>
              </div>

              <section className="space-y-3">
                <div className="grid grid-cols-2 gap-3">
                  <div className="space-y-1.5">
                    <label className="text-sm font-medium">Idle timeout</label>
                    <div className="relative">
                      <Input
                        type="number"
                        value={idleTimeout}
                        onChange={handleIdleTimeoutChange}
                        min={60}
                        max={28800}
                        step={60}
                        className="pr-16"
                      />
                      <span className="absolute right-3 top-1/2 -translate-y-1/2 text-xs text-muted-foreground">
                        sec · {humanizeSeconds(idleTimeout)}
                      </span>
                    </div>
                    <div className="flex gap-1.5">
                      {[["5m", 300], ["15m", 900], ["1h", 3600]].map(([label, seconds]) => (
                        <button
                          key={label}
                          type="button"
                          onClick={() => { setIdleTimeout(String(seconds)); validateLifecycle("idle", String(seconds)); }}
                          className={`rounded px-2 py-0.5 font-mono text-[10.5px] ${
                            idleTimeout === String(seconds) ? "bg-primary/10 text-primary" : "border text-muted-foreground"
                          }`}
                        >
                          {label}
                        </button>
                      ))}
                    </div>
                    {idleTimeoutError && (
                      <p className="text-[10px] text-destructive">{idleTimeoutError}</p>
                    )}
                  </div>
                  <div className="space-y-1.5">
                    <label className="text-sm font-medium">Max lifetime</label>
                    <div className="relative">
                      <Input
                        type="number"
                        value={maxLifetime}
                        onChange={handleMaxLifetimeChange}
                        min={60}
                        max={28800}
                        step={60}
                        className="pr-16"
                      />
                      <span className="absolute right-3 top-1/2 -translate-y-1/2 text-xs text-muted-foreground">
                        sec · {humanizeSeconds(maxLifetime)}
                      </span>
                    </div>
                    <div className="flex gap-1.5">
                      {[["1h", 3600], ["4h", 14400], ["8h", 28800]].map(([label, seconds]) => (
                        <button
                          key={label}
                          type="button"
                          onClick={() => { setMaxLifetime(String(seconds)); validateLifecycle("max", String(seconds)); }}
                          className={`rounded px-2 py-0.5 font-mono text-[10.5px] ${
                            maxLifetime === String(seconds) ? "bg-primary/10 text-primary" : "border text-muted-foreground"
                          }`}
                        >
                          {label}
                        </button>
                      ))}
                    </div>
                    {maxLifetimeError && (
                      <p className="text-[10px] text-destructive">{maxLifetimeError}</p>
                    )}
                  </div>
                </div>
              </section>

              <div className="h-px bg-border" />

              <ResourceTagFields onChange={setTagValues} profileId={selectedTagProfileId} groupRestriction={groupRestriction} ownerRestriction={ownerRestriction} />
              </div>

              <div className="flex items-center gap-2 border-t px-4 py-2.5">
                <span className="font-mono text-[11px] text-muted-foreground">Step 5 of {WIZARD_STEPS.length}</span>
                <Button type="button" variant="outline" size="sm" className="ml-auto" onClick={() => setStep(3)}>&larr; Back</Button>
                <Button type="button" size="sm" disabled={!stepValid(4)} onClick={() => setStep(REVIEW_STEP)}>
                  Review &amp; deploy &rarr;
                </Button>
              </div>
              </div>

              {/* R7/R8: shared review + deploy step for both the guided wizard and manifest import (16f). */}
              {step === REVIEW_STEP && (() => {
                const selectedModel = sortedProviderModels.find((m) => m.model_id === modelId) ?? litellmModels.find((m) => m.model_id === modelId);
                const allowedChips = selectedAllowedModelIds.filter((id) => id !== modelId);
                const totalConnectedTools = selectedMcpServerIds.length + (deploymentType === "custom" ? selectedA2aAgentIds.length : 0);
                const memNames = filteredMemories.filter((m) => selectedMemoryIds.includes(m.id)).map((m) => m.name);
                const tagCount = Object.keys(tagValues).filter((k) => tagValues[k]?.trim()).length;
                const profileName = tagProfiles.find((p) => p.id.toString() === selectedTagProfileId)?.name;

                return (
                  <div className="grid grid-cols-[minmax(0,1fr)_300px] items-start gap-4">
                    <div className="divide-y overflow-hidden rounded-lg border">
                      <div className="grid grid-cols-[130px_minmax(0,1fr)_40px] items-baseline gap-3 px-4 py-3">
                        <div className="text-sm font-semibold">Runtime</div>
                        <div className="flex gap-1.5">
                          <span className="rounded bg-accent px-2 py-0.5 font-mono text-[11px]">{deploymentType === "managed" ? "managed" : "custom"}</span>
                          {deploymentType === "custom" && <span className="rounded bg-accent px-2 py-0.5 font-mono text-[11px]">{agentFramework}</span>}
                        </div>
                        <button type="button" onClick={() => setStep(0)} className="text-right text-xs text-primary hover:underline">Edit</button>
                      </div>

                      <div className="grid grid-cols-[130px_minmax(0,1fr)_40px] items-baseline gap-3 px-4 py-3">
                        <div className="text-sm font-semibold">Prompt &amp; models</div>
                        <div className="min-w-0 space-y-1.5">
                          <div className="truncate text-sm">{name.trim() || <span className="text-muted-foreground">(unnamed)</span>}</div>
                          <div className="flex items-center gap-2">
                            <span className="font-mono text-[9.5px] tracking-wide text-primary">DEFAULT</span>
                            <span className="text-[12.5px] font-medium">{selectedModel?.display_name ?? modelId ?? "no model selected"}</span>
                          </div>
                          {allowedChips.length > 0 && (
                            <div className="flex flex-wrap gap-1">
                              {allowedChips.map((id) => {
                                const m = sortedProviderModels.find((mm) => mm.model_id === id) ?? litellmModels.find((mm) => mm.model_id === id);
                                return <span key={id} className="rounded border px-1.5 py-0.5 text-[11px]">{chipLabel(m?.display_name ?? id)}</span>;
                              })}
                            </div>
                          )}
                          {systemPromptTooLarge && (
                            <p className="text-[11.5px] text-destructive">
                              System prompt is too large ({systemPromptBytes} / {MAX_SYSTEM_PROMPT_BYTES} bytes) — shorten it to deploy.
                            </p>
                          )}
                        </div>
                        <button type="button" onClick={() => setStep(1)} className="text-right text-xs text-primary hover:underline">Edit</button>
                      </div>

                      <div className="grid grid-cols-[130px_minmax(0,1fr)_40px] items-baseline gap-3 px-4 py-3">
                        <div className="text-sm font-semibold">Access</div>
                        <div className="truncate font-mono text-[11.5px]">
                          {networkMode.toLowerCase()}
                          {selectedRole ? ` · ${selectedRole.role_name}` : " · no role selected"}
                          {selectedAuthConfig ? ` · ${selectedAuthConfig.name}` : ""}
                        </div>
                        <button type="button" onClick={() => setStep(2)} className="text-right text-xs text-primary hover:underline">Edit</button>
                      </div>

                      <div className="grid grid-cols-[130px_minmax(0,1fr)_40px] items-baseline gap-3 px-4 py-3">
                        <div className="text-sm font-semibold">Tools &amp; memory</div>
                        <div className="truncate font-mono text-[11.5px]">
                          {memNames.length > 0 ? `memory ${memNames.join(", ")}` : "no memory"}
                          {" · "}{selectedSkillIds.length > 0 ? `${selectedSkillIds.length} skill${selectedSkillIds.length === 1 ? "" : "s"}` : "no skills"}
                          {" · "}{totalConnectedTools > 0 ? `${totalConnectedTools} tool${totalConnectedTools === 1 ? "" : "s"}` : "no tools"}
                          {" · "}CI {codeInterpreterEnabled ? "on" : "off"}
                        </div>
                        <button type="button" onClick={() => setStep(3)} className="text-right text-xs text-primary hover:underline">Edit</button>
                      </div>

                      <div className="grid grid-cols-[130px_minmax(0,1fr)_40px] items-baseline gap-3 px-4 py-3">
                        <div className="text-sm font-semibold">Lifecycle &amp; tags</div>
                        <div className="truncate font-mono text-[11.5px]">
                          idle {humanizeSeconds(idleTimeout) || `${idleTimeout || defaults.idle_timeout_seconds}s`} · max {humanizeSeconds(maxLifetime) || `${maxLifetime || defaults.max_lifetime_seconds}s`}
                          {profileName ? ` · ${profileName}` : ""}
                          {tagCount > 0 && <span className="text-muted-foreground"> ({tagCount} tags)</span>}
                        </div>
                        <button type="button" onClick={() => setStep(4)} className="text-right text-xs text-primary hover:underline">Edit</button>
                      </div>
                    </div>

                    <div className="space-y-3 rounded-lg border bg-card p-4">
                      <div className="text-sm font-semibold">{exportAgentId ? "Update agent" : "Deploy agent"}</div>
                      <div className="space-y-1.5 text-xs text-muted-foreground">
                        <div className="flex items-center gap-2">
                          <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" />
                          {exportAgentId ? "Hot update — no redeploy" : "New deployment"}
                        </div>
                        {exportAgentId && (
                          <div className="flex items-center gap-2">
                            <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" />
                            Active sessions keep old config
                          </div>
                        )}
                      </div>
                      <div className="flex items-center gap-2">
                        <Button type="button" variant="outline" size="sm" onClick={() => setStep(4)}>&larr; Back</Button>
                        <Button
                          type="submit"
                          size="sm"
                          className="flex-1"
                          disabled={isLoading || !name.trim() || !modelId || !selectedRoleId || (deploymentType === "custom" ? !onDeploy : !onDeployHarness) || hasValidationErrors || systemPromptTooLarge || missingGroupTag}
                        >
                          {isLoading ? "Deploying..." : (exportAgentId ? "Update agent" : (deploymentType === "managed" ? "Deploy harness" : "Deploy agent"))}
                        </Button>
                      </div>
                      <div className="flex items-center justify-between font-mono text-[10.5px] text-muted-foreground">
                        <span>~1 min</span>
                        <button
                          type="button"
                          onClick={async () => {
                            const json = await buildManifestJson();
                            const blob = new Blob([json], { type: "application/json" });
                            const url = URL.createObjectURL(blob);
                            const a = document.createElement("a");
                            a.href = url;
                            a.download = `${name.trim() || "agent"}.json`;
                            a.click();
                            URL.revokeObjectURL(url);
                          }}
                          className="text-primary hover:underline"
                        >
                          Export manifest
                        </button>
                      </div>
                    </div>
                  </div>
                );
              })()}

                </div>
              </div>
          </div>
      )}
    </form>
  );
}
