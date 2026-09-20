import { useState, useEffect } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { toast } from "sonner";
import { Copy, Check, Globe, Lock } from "lucide-react";
import { getAgentIntegration } from "@/api/agents";
import { CopyField } from "@/components/CopyField";
import type { IntegrationInfoResponse, IntegrationAuthSigV4, IntegrationAuthOAuth2 } from "@/api/types";

interface ExternalIntegrationSectionProps {
  agentId: number;
}

/** Dark, theme-independent code block with a titled bar — same visual regardless of light/dark mode. */
function CodeBlock({ code, title }: { code: string; title: string }) {
  const [copied, setCopied] = useState(false);
  const handleCopy = () => {
    navigator.clipboard.writeText(code);
    toast.success("Copied to clipboard");
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };
  return (
    <div className="overflow-hidden rounded-[9px] border border-white/10">
      <div className="flex items-center gap-2 bg-[#181b20] px-2.5 py-1.5">
        <span className="font-mono text-[10px] tracking-wide text-[#9aa1ab] uppercase">{title}</span>
        <button
          type="button"
          onClick={handleCopy}
          className="ml-auto flex items-center gap-1 font-mono text-[10.5px] text-[#b5bcc5] hover:text-white"
        >
          {copied ? <Check className="h-3 w-3" /> : <Copy className="h-3 w-3" />}
          {copied ? "copied" : "copy"}
        </button>
      </div>
      <pre className="overflow-x-auto whitespace-pre-wrap bg-[#101217] px-3.5 py-3 font-mono text-[11.5px] leading-[1.75] text-[#dfe3e8]">
        {code}
      </pre>
    </div>
  );
}

function SigV4AuthSection({ auth }: { auth: IntegrationAuthSigV4 }) {
  return (
    <div className="flex flex-col gap-3.5">
      <Badge variant="outline" className="w-fit text-[10px]">AWS IAM (SigV4)</Badge>
      <CopyField label="IAM action" value={auth.iam_action} />
      <CopyField label="Resource ARN" value={auth.resource_arn} />
      {auth.execution_role_arn && <CopyField label="Execution role" value={auth.execution_role_arn} />}
      <CodeBlock title="JSON · Example IAM policy" code={JSON.stringify(auth.example_policy, null, 2)} />
      <CodeBlock title="Python · Example (boto3)" code={auth.example_boto3} />
      <CodeBlock title="Bash · Example (AWS CLI)" code={auth.example_cli} />
    </div>
  );
}

function OAuth2AuthSection({ auth }: { auth: IntegrationAuthOAuth2 }) {
  return (
    <div className="flex flex-col gap-3.5">
      <div className="flex items-center gap-2">
        <Badge variant="outline" className="text-[10px]">OAuth2 / JWT</Badge>
        <Badge variant="secondary" className="text-[10px]">{auth.authorizer_type}</Badge>
      </div>
      <div className="grid grid-cols-2 gap-3.5">
        {auth.discovery_url && <CopyField label="Discovery URL" value={auth.discovery_url} />}
        {auth.token_endpoint && <CopyField label="Token endpoint" value={auth.token_endpoint} />}
      </div>
      {auth.allowed_client_ids.length > 0 && (
        <div className="flex flex-col gap-1.5">
          <span className="font-mono text-[9.5px] tracking-wide text-muted-foreground uppercase">Allowed client IDs</span>
          <div className="flex flex-wrap items-center gap-1.5">
            {auth.allowed_client_ids.map((id) => (
              <span key={id} className="rounded-md border bg-muted px-2 py-0.5 font-mono text-[11.5px]">{id}</span>
            ))}
            <span className="text-[11.5px] text-muted-foreground">Client secrets come from your IdP.</span>
          </div>
        </div>
      )}
      {auth.allowed_scopes.length > 0 && (
        <div className="flex flex-col gap-1.5">
          <span className="font-mono text-[9.5px] tracking-wide text-muted-foreground uppercase">Allowed scopes</span>
          <div className="flex flex-wrap gap-1.5">
            {auth.allowed_scopes.map((s) => (
              <span key={s} className="rounded-md border bg-muted px-2 py-0.5 font-mono text-[11.5px]">{s}</span>
            ))}
          </div>
        </div>
      )}
      <CodeBlock title="Bash · Obtain token" code={auth.example_token_request} />
      <CodeBlock title="Bash · Invoke agent" code={auth.example_invocation} />
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

  if (error || !info) return null;

  const isSigV4 = info.auth.method === "SigV4";

  return (
    <>
      <Card className="gap-0 py-0">
        <CardHeader className="flex-row items-center gap-2.5 border-b px-[18px] py-3.5 [.border-b]:pb-3.5">
          <CardTitle className="text-[13.5px] font-semibold">Endpoint</CardTitle>
          <Badge variant="outline" className="gap-1 text-[10px]">
            {info.network_mode === "PUBLIC" ? <Globe className="h-3 w-3" /> : <Lock className="h-3 w-3" />}
            {info.protocol} · {info.network_mode}
          </Badge>
        </CardHeader>
        <CardContent className="flex flex-col gap-3.5 px-[18px] py-4">
          {info.network_mode === "VPC" && (
            <p className="text-[11.5px] text-muted-foreground italic">
              This endpoint requires VPC connectivity. Callers must have network access to the VPC.
            </p>
          )}
          <CopyField label="Runtime ARN" value={info.runtime_arn} />
          {info.endpoints.map((ep) => (
            <div key={ep.qualifier} className="flex flex-col gap-3.5">
              <CopyField
                label="Invoke URL"
                value={ep.invocation_url}
                annotation={<Badge variant="outline" className="text-[9.5px] px-1.5 py-0 font-mono">{ep.qualifier}</Badge>}
              />
              {ep.protocol_url && <CopyField label={ep.protocol_url_label ?? "Protocol URL"} value={ep.protocol_url} />}
            </div>
          ))}
          {info.protocol === "HTTP" && (
            <p className="text-[11.5px] text-muted-foreground">Request/response invocation via the AgentCore Runtime API or direct HTTPS.</p>
          )}
          {info.protocol === "MCP" && (
            <p className="text-[11.5px] text-muted-foreground">Streamable HTTP transport. External MCP clients connect to the protocol URL above.</p>
          )}
          {info.protocol === "A2A" && (
            <p className="text-[11.5px] text-muted-foreground">Agent-to-agent protocol. External agents discover capabilities via the agent card URL above.</p>
          )}
        </CardContent>
      </Card>

      <Card className="gap-0 py-0">
        <CardHeader className="flex-row items-center gap-2.5 border-b px-[18px] py-3.5 [.border-b]:pb-3.5">
          <CardTitle className="text-[13.5px] font-semibold">Authentication</CardTitle>
        </CardHeader>
        <CardContent className="px-[18px] py-4">
          {isSigV4 ? <SigV4AuthSection auth={info.auth as IntegrationAuthSigV4} /> : <OAuth2AuthSection auth={info.auth as IntegrationAuthOAuth2} />}
        </CardContent>
      </Card>
    </>
  );
}
