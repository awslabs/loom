import { apiFetch, BASE_URL, getAuthToken, tryRefreshToken } from "./client";
import type {
  InvokeRequest,
  InvocationResponse,
  SessionResponse,
  SSESessionStart,
  SSEChunk,
  SSEToolUse,
  SSESessionEnd,
  SSEError,
  SSEApprovalRequest,
  SSEApprovalResolved,
  SSEElicitationRequest,
  SSETokenInfo,
} from "./types";

export function listSessions(agentId: number, userId?: string): Promise<SessionResponse[]> {
  const params = userId ? `?user_id=${encodeURIComponent(userId)}` : "";
  return apiFetch<SessionResponse[]>(`/api/agents/${agentId}/sessions${params}`);
}

export function getInvocation(
  agentId: number,
  sessionId: string,
  invocationId: string,
): Promise<InvocationResponse> {
  return apiFetch<InvocationResponse>(
    `/api/agents/${agentId}/sessions/${sessionId}/invocations/${invocationId}`,
  );
}

export function getSession(
  agentId: number,
  sessionId: string,
): Promise<SessionResponse> {
  return apiFetch<SessionResponse>(
    `/api/agents/${agentId}/sessions/${sessionId}`,
  );
}

export function hideSession(agentId: number, sessionId: string): Promise<void> {
  return apiFetch<void>(`/api/agents/${agentId}/sessions/${sessionId}`, {
    method: "DELETE",
  });
}

export interface StreamCallbacks {
  onSessionStart?: (data: SSESessionStart) => void;
  onChunk?: (data: SSEChunk) => void;
  onToolUse?: (data: SSEToolUse) => void;
  onSessionEnd?: (data: SSESessionEnd) => void;
  onError?: (data: SSEError) => void;
  onApprovalRequest?: (data: SSEApprovalRequest) => void;
  onApprovalResolved?: (data: SSEApprovalResolved) => void;
  onElicitationRequest?: (data: SSEElicitationRequest) => void;
  onTokenInfo?: (data: SSETokenInfo) => void;
}

export async function invokeAgentStream(
  agentId: number,
  request: InvokeRequest,
  callbacks: StreamCallbacks,
  signal?: AbortSignal,
): Promise<void> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  const token = getAuthToken();
  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }

  let response = await fetch(`${BASE_URL}/api/agents/${agentId}/invoke`, {
    method: "POST",
    headers,
    body: JSON.stringify(request),
    signal,
  });

  // On 401, attempt token refresh and retry once (mirrors apiFetch behavior)
  if (response.status === 401) {
    const newToken = await tryRefreshToken();
    if (newToken) {
      headers["Authorization"] = `Bearer ${newToken}`;
      response = await fetch(`${BASE_URL}/api/agents/${agentId}/invoke`, {
        method: "POST",
        headers,
        body: JSON.stringify(request),
        signal,
      });
    }
  }

  if (!response.ok) {
    let detail = `HTTP ${response.status}`;
    try {
      const body = (await response.json()) as { detail?: string };
      if (body.detail) detail = body.detail;
    } catch {
      // use default detail
    }
    callbacks.onError?.({ message: detail });
    return;
  }

  const reader = response.body?.getReader();
  if (!reader) {
    callbacks.onError?.({ message: "No response body" });
    return;
  }

  const decoder = new TextDecoder();
  let buffer = "";

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });

      // Process complete SSE messages (separated by double newlines)
      const parts = buffer.split("\n\n");
      // Keep the last part as it may be incomplete
      buffer = parts.pop() ?? "";

      for (const part of parts) {
        if (!part.trim()) continue;

        let eventType = "";
        let eventData = "";

        for (const line of part.split("\n")) {
          if (line.startsWith("event:")) {
            eventType = line.slice(6).trim();
          } else if (line.startsWith("data:")) {
            eventData = line.slice(5).trim();
          }
        }

        if (!eventType || !eventData) continue;

        try {
          const parsed: unknown = JSON.parse(eventData);
          switch (eventType) {
            case "session_start":
              callbacks.onSessionStart?.(parsed as SSESessionStart);
              break;
            case "chunk":
              callbacks.onChunk?.(parsed as SSEChunk);
              break;
            case "tool_use":
              callbacks.onToolUse?.(parsed as SSEToolUse);
              break;
            case "session_end":
              callbacks.onSessionEnd?.(parsed as SSESessionEnd);
              break;
            case "error":
              callbacks.onError?.(parsed as SSEError);
              break;
            case "approval_request":
              callbacks.onApprovalRequest?.(parsed as SSEApprovalRequest);
              break;
            case "approval_resolved":
              callbacks.onApprovalResolved?.(parsed as SSEApprovalResolved);
              break;
            case "elicitation_request":
              callbacks.onElicitationRequest?.(parsed as SSEElicitationRequest);
              break;
            case "token_info":
              callbacks.onTokenInfo?.(parsed as SSETokenInfo);
              break;
          }
        } catch {
          // Skip malformed JSON
        }
      }
    }
  } finally {
    reader.releaseLock();
  }
}

/**
 * WebSocket-based agent invocation for MCP elicitation support.
 *
 * Returns a controller object that allows sending elicitation responses
 * back to the agent while it's running.
 */
export interface WsInvokeCallbacks {
  onSessionStart?: (data: { session_id: string }) => void;
  onText?: (text: string) => void;
  onToolUse?: (data: SSEToolUse) => void;
  onElicitation?: (data: { id: string; message: string }) => void;
  onResult?: (content: string) => void;
  onError?: (message: string) => void;
  onClose?: () => void;
}

export interface WsInvokeController {
  sendElicitationResponse: (id: string, action: "accept" | "decline" | "cancel", content?: Record<string, unknown>) => void;
  close: () => void;
}

export function invokeAgentWs(
  agentId: number,
  request: InvokeRequest & { connector_ids?: number[] },
  callbacks: WsInvokeCallbacks,
): WsInvokeController {
  const token = getAuthToken();
  const wsProtocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  const wsBase = BASE_URL.replace(/^http/, "ws");
  const wsUrl = `${wsBase || `${wsProtocol}//${window.location.host}`}/api/agents/${agentId}/ws`;

  const ws = new WebSocket(wsUrl);

  ws.onopen = () => {
    // Send auth + prompt as first message
    ws.send(JSON.stringify({
      type: "prompt",
      token,
      prompt: request.prompt,
      qualifier: request.qualifier,
      session_id: request.session_id,
      model_id: request.model_id,
      connector_ids: request.connector_ids,
    }));
  };

  ws.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data);
      switch (data.type) {
        case "session_start":
          callbacks.onSessionStart?.(data);
          break;
        case "text":
          callbacks.onText?.(data.content);
          break;
        case "tool_use":
          callbacks.onToolUse?.(data);
          break;
        case "elicitation":
          callbacks.onElicitation?.(data);
          break;
        case "result":
          callbacks.onResult?.(data.content);
          break;
        case "error":
          callbacks.onError?.(data.content);
          break;
      }
    } catch {
      // Skip malformed messages
    }
  };

  ws.onerror = () => {
    callbacks.onError?.("WebSocket connection error");
  };

  ws.onclose = () => {
    callbacks.onClose?.();
  };

  return {
    sendElicitationResponse(id, action, content) {
      if (ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: "elicitation_response", id, action, content: content ?? {} }));
      }
    },
    close() {
      ws.close();
    },
  };
}
