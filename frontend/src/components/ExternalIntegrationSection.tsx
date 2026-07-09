import { useState, useEffect } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Copy, Check, Globe, Lock, ExternalLink } from "lucide-react";
import { getAgentIntegration } from "@/api/agents";
import type { IntegrationInfoResponse, IntegrationAuthSigV4, IntegrationAuthOAuth2 } from "@/api/types";

interface ExternalIntegrationSectionProps {
  agentId: number;
}

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  const handleCopy = () => {
    navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };
  return (
    <Button variant="ghost" size="icon" className="h-5 w-5 shrink-0" onClick={handleCopy}>
      {copied ? <Check className="h-3 w-3 text-green-500" /> : <Copy className="h-3 w-3" />}
    </Button>
  );
}

function CodeBlock({ code, language }: { code: string; language?: string }) {
  return (
    <div className="relative group">
      <div className="absolute right-1 top-1 opacity-0 group-hover:opacity-100 transition-opacity">
        <CopyButton text={code} />
      </div>
      <pre className="overflow-x-auto rounded bg-white dark:bg-white/10 border border-border p-3 text-xs font-mono whitespace-pre-wrap">
        {language && <span className="text-[10px] text-muted-foreground/60 block mb-1">{language}</span>}
        {code}
      </pre>
    </div>
  );
}

function CopyableField({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center gap-1.5 text-xs">
      <span className="font-medium text-muted-foreground shrink-0">{label}:</span>
      <code className="rounded bg-white dark:bg-white/10 border border-border px-1.5 py-0.5 font-mono text-xs break-all">{value}</code>
      <CopyButton text={value} />
    </div>
  );
}

function SigV4AuthSection({ auth }: { auth: IntegrationAuthSigV4 }) {
  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2">
        <Badge variant="outline" className="text-[10px]">AWS IAM (SigV4)</Badge>
      </div>
      <CopyableField label="IAM Action" value={auth.iam_action} />
      <CopyableField label="Resource ARN" value={auth.resource_arn} />
      {auth.execution_role_arn && (
        <CopyableField label="Execution Role" value={auth.execution_role_arn} />
      )}

      <div className="space-y-1">
        <p className="text-xs font-medium text-muted-foreground">Example IAM Policy</p>
        <CodeBlock code={JSON.stringify(auth.example_policy, null, 2)} language="json" />
      </div>

      <div className="space-y-1">
        <p className="text-xs font-medium text-muted-foreground">Example (boto3)</p>
        <CodeBlock code={auth.example_boto3} language="python" />
      </div>

      <div className="space-y-1">
        <p className="text-xs font-medium text-muted-foreground">Example (AWS CLI)</p>
        <CodeBlock code={auth.example_cli} language="bash" />
      </div>
    </div>
  );
}

function OAuth2AuthSection({ auth }: { auth: IntegrationAuthOAuth2 }) {
  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2">
        <Badge variant="outline" className="text-[10px]">OAuth2 / JWT</Badge>
        <Badge variant="secondary" className="text-[10px]">{auth.authorizer_type}</Badge>
      </div>
      {auth.discovery_url && (
        <CopyableField label="Discovery URL" value={auth.discovery_url} />
      )}
      {auth.token_endpoint && (
        <CopyableField label="Token Endpoint" value={auth.token_endpoint} />
      )}
      {auth.allowed_client_ids.length > 0 && (
        <div className="text-xs">
          <span className="font-medium text-muted-foreground">Allowed Client IDs:</span>
          <div className="flex flex-wrap gap-1 mt-1">
            {auth.allowed_client_ids.map((id) => (
              <Badge key={id} variant="outline" className="text-[10px] font-mono">{id}</Badge>
            ))}
          </div>
        </div>
      )}
      {auth.allowed_scopes.length > 0 && (
        <div className="text-xs">
          <span className="font-medium text-muted-foreground">Allowed Scopes:</span>
          <div className="flex flex-wrap gap-1 mt-1">
            {auth.allowed_scopes.map((s) => (
              <Badge key={s} variant="outline" className="text-[10px] font-mono">{s}</Badge>
            ))}
          </div>
        </div>
      )}
      <p className="text-[10px] text-muted-foreground/70 italic">
        Client secrets must be obtained from your identity provider administrator.
      </p>

      <div className="space-y-1">
        <p className="text-xs font-medium text-muted-foreground">Obtain Token</p>
        <CodeBlock code={auth.example_token_request} language="bash" />
      </div>

      <div className="space-y-1">
        <p className="text-xs font-medium text-muted-foreground">Invoke Agent</p>
        <CodeBlock code={auth.example_invocation} language="bash" />
      </div>
    </div>
  );
}

export function ExternalIntegrationSection({ agentId }: ExternalIntegrationSectionProps) {
  const [info, setInfo] = useState<IntegrationInfoResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setLoading(true);
    setError(null);
    getAgentIntegration(agentId)
      .then(setInfo)
      .catch((e) => setError(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoading(false));
  }, [agentId]);

  if (loading) {
    return (
      <Card>
        <CardContent className="pt-6 text-center text-xs text-muted-foreground">
          Loading integration info…
        </CardContent>
      </Card>
    );
  }

  if (error || !info) {
    return null;
  }

  const isSigV4 = info.auth.method === "SigV4";

  return (
    <Card>
      <CardHeader className="pb-2">
        <div className="flex items-center gap-2">
          <ExternalLink className="h-4 w-4" />
          <CardTitle className="text-sm font-medium">External Integration</CardTitle>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* Endpoint Info */}
        <div className="space-y-3">
          <div className="flex flex-wrap items-center gap-2">
            <Badge variant="outline" className="text-[10px]">{info.protocol}</Badge>
            <Badge variant={info.network_mode === "PUBLIC" ? "secondary" : "outline"} className="text-[10px] gap-1">
              {info.network_mode === "PUBLIC" ? <Globe className="h-3 w-3" /> : <Lock className="h-3 w-3" />}
              {info.network_mode}
            </Badge>
          </div>

          {info.network_mode === "VPC" && (
            <p className="text-[10px] text-muted-foreground/70 italic">
              This endpoint requires VPC connectivity. Callers must have network access to the VPC.
            </p>
          )}

          <CopyableField label="Runtime ARN" value={info.runtime_arn} />

          {info.endpoints.map((ep) => (
            <div key={ep.qualifier} className="space-y-1.5 pl-2 border-l-2 border-muted-foreground/20">
              <div className="flex items-center gap-1.5">
                <Badge variant="outline" className="text-[10px] font-mono">{ep.qualifier}</Badge>
              </div>
              <CopyableField label="Invoke URL" value={ep.invocation_url} />
              {ep.protocol_url && (
                <CopyableField label={ep.protocol_url_label ?? "Protocol URL"} value={ep.protocol_url} />
              )}
            </div>
          ))}

          {info.protocol === "HTTP" && (
            <p className="text-[10px] text-muted-foreground/70">
              Standard request/response invocation via the AgentCore Runtime API or direct HTTPS endpoint.
            </p>
          )}
          {info.protocol === "MCP" && (
            <p className="text-[10px] text-muted-foreground/70">
              Streamable HTTP transport. External MCP clients connect to the protocol URL above.
            </p>
          )}
          {info.protocol === "A2A" && (
            <p className="text-[10px] text-muted-foreground/70">
              Agent-to-agent protocol. External agents discover capabilities via the agent card URL above.
            </p>
          )}
        </div>

        {/* Divider */}
        <div className="border-t" />

        {/* Auth Info */}
        <div>
          <p className="text-xs font-medium mb-3">Authentication</p>
          {isSigV4 ? (
            <SigV4AuthSection auth={info.auth as IntegrationAuthSigV4} />
          ) : (
            <OAuth2AuthSection auth={info.auth as IntegrationAuthOAuth2} />
          )}
        </div>
      </CardContent>
    </Card>
  );
}
