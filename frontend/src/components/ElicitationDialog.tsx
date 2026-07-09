import { useState, useEffect } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { MessageSquare, CheckCircle, XCircle, Clock } from "lucide-react";
import { submitApprovalDecision } from "@/api/approvals";
import type { SSEElicitationRequest } from "@/api/types";

interface ElicitationRequestBubbleProps {
  data: SSEElicitationRequest;
  onRespond?: (elicitationId: string, action: "accept" | "decline", content?: Record<string, unknown>) => void;
  resolved?: boolean;
  resolvedSummary?: string;
}

export function ElicitationRequestBubble({
  data,
  onRespond,
  resolved,
  resolvedSummary,
}: ElicitationRequestBubbleProps) {
  const [response, setResponse] = useState<Record<string, string>>({});
  const [submitted, setSubmitted] = useState(resolved ?? false);
  const [submittedSummary, setSubmittedSummary] = useState<string | null>(resolvedSummary ?? null);
  const [selectedChoice, setSelectedChoice] = useState<string | null>(null);
  const [elapsed, setElapsed] = useState(0);

  useEffect(() => {
    if (submitted) return;
    const start = Date.now();
    const id = setInterval(() => setElapsed(Math.floor((Date.now() - start) / 1000)), 1000);
    return () => clearInterval(id);
  }, [submitted]);

  const properties = (data.schema?.properties ?? {}) as Record<
    string,
    { type?: string; description?: string; enum?: string[] }
  >;
  const fields = Object.entries(properties);

  const isSingleBoolApproval = fields.length === 1 && fields[0]![1].type === "boolean";
  const isSimpleChoice = (!data.schema && data.message) || isSingleBoolApproval;

  const handleAccept = (content?: Record<string, unknown>) => {
    setSubmitted(true);
    if (content) {
      const summary = Object.entries(content)
        .map(([k, v]) => `${k}: ${v}`)
        .join(", ");
      setSubmittedSummary(summary);
    } else {
      setSubmittedSummary("Approved");
    }
    if (data.request_id) {
      submitApprovalDecision(data.request_id, "approved", undefined, content);
    }
    onRespond?.(data.elicitation_id, "accept", content);
  };

  const handleDecline = () => {
    setSubmitted(true);
    setSubmittedSummary("Declined");
    if (data.request_id) {
      submitApprovalDecision(data.request_id, "rejected");
    }
    onRespond?.(data.elicitation_id, "decline");
  };

  const handleSubmitFields = () => {
    handleAccept(response);
  };

  const handleChoiceSubmit = (choice: string) => {
    setSelectedChoice(choice);
    setSubmitted(true);
    setSubmittedSummary(choice === "yes" ? "Yes" : "No");
    if (data.request_id) {
      if (choice === "yes") {
        submitApprovalDecision(data.request_id, "approved", undefined, { approved: true });
      } else {
        submitApprovalDecision(data.request_id, "rejected");
      }
    }
    onRespond?.(data.elicitation_id, choice === "yes" ? "accept" : "decline", { response: choice });
  };

  return (
    <div className="flex justify-start">
      <div className="max-w-full rounded-2xl px-4 py-3 text-sm bg-purple-50 dark:bg-purple-950/30 border border-purple-200 dark:border-purple-800">
        <div className="flex items-center gap-2 text-purple-700 dark:text-purple-300 mb-1">
          <MessageSquare className="h-4 w-4 shrink-0" />
          <span className="font-medium text-xs uppercase tracking-wide">Input Required</span>
          {data.server_name && (
            <span className="text-xs text-muted-foreground">{data.server_name}</span>
          )}
          {!submitted && (
            <span className="text-xs text-muted-foreground ml-auto flex items-center gap-1">
              <Clock className="h-3 w-3" />
              {elapsed}s / 300s
            </span>
          )}
        </div>
        {data.message && <p className="text-xs mb-2 whitespace-pre-wrap">{data.message}</p>}

        {submitted ? (
          <div className="flex items-center gap-1.5 text-xs text-purple-700 dark:text-purple-400 font-medium">
            <CheckCircle className="h-3.5 w-3.5" />
            {submittedSummary ?? (selectedChoice ? `Responded: ${selectedChoice}` : "Response submitted")}
          </div>
        ) : isSimpleChoice ? (
          <div className="flex items-center gap-2 mt-2">
            <Button
              size="sm"
              className="h-7 text-xs"
              disabled={submitted}
              onClick={() => handleChoiceSubmit("yes")}
            >
              Yes
            </Button>
            <Button
              size="sm"
              variant="outline"
              className="h-7 text-xs"
              disabled={submitted}
              onClick={() => handleChoiceSubmit("no")}
            >
              No
            </Button>
            <Button
              size="sm"
              variant="ghost"
              className="h-7 text-xs text-muted-foreground"
              disabled={submitted}
              onClick={handleDecline}
            >
              <XCircle className="h-3 w-3 mr-1" />
              Cancel
            </Button>
          </div>
        ) : fields.length > 0 ? (
          <div className="space-y-2">
            {fields.map(([key, prop]) => (
              <div key={key} className="space-y-0.5">
                <Label className="text-xs">{prop.description ?? key}</Label>
                {prop.enum ? (
                  <div className="flex gap-1.5">
                    {prop.enum.map((opt) => (
                      <Button
                        key={opt}
                        size="sm"
                        variant={response[key] === opt ? "default" : "outline"}
                        className="h-7 text-xs"
                        onClick={() => setResponse({ ...response, [key]: opt })}
                      >
                        {opt}
                      </Button>
                    ))}
                  </div>
                ) : (
                  <Input
                    className="text-xs h-7"
                    placeholder={key}
                    value={response[key] ?? ""}
                    onChange={(e) =>
                      setResponse({ ...response, [key]: e.target.value })
                    }
                  />
                )}
              </div>
            ))}
            <div className="flex gap-2 pt-1">
              <Button
                size="sm"
                className="h-7 text-xs"
                disabled={submitted}
                onClick={handleSubmitFields}
              >
                Submit
              </Button>
              <Button
                size="sm"
                variant="ghost"
                className="h-7 text-xs text-muted-foreground"
                disabled={submitted}
                onClick={handleDecline}
              >
                Cancel
              </Button>
            </div>
          </div>
        ) : (
          <div className="flex items-center gap-2 mt-2">
            <Button
              size="sm"
              className="h-7 text-xs"
              disabled={submitted}
              onClick={() => handleAccept()}
            >
              Approve
            </Button>
            <Button
              size="sm"
              variant="ghost"
              className="h-7 text-xs text-muted-foreground"
              disabled={submitted}
              onClick={handleDecline}
            >
              Decline
            </Button>
          </div>
        )}
      </div>
    </div>
  );
}
