import { useState, useEffect, useCallback, useRef } from "react";
import type { SSESessionStart, SSESessionEnd, SSEApprovalRequest, SSEApprovalResolved, SSEElicitationRequest, SSETokenInfo } from "@/api/types";
import { invokeAgentStream, invokeAgentWs, type WsInvokeController } from "@/api/invocations";
import { friendlyInvokeError } from "@/lib/errors";

/**
 * Module-level store so that in-flight streams survive component
 * unmount/remount (e.g. navigating away from the agent detail page
 * and coming back).  Keyed by agentId.
 */

export type StreamSegment =
  | { type: "text"; content: string }
  | { type: "tool_use"; name: string; index: number; total: number; timestamp: number }
  | { type: "approval_request"; data: SSEApprovalRequest }
  | { type: "approval_resolved"; data: SSEApprovalResolved }
  | { type: "elicitation_request"; data: SSEElicitationRequest; resolvedSummary?: string };

interface InvokeSnapshot {
  streamedText: string;
  segments: StreamSegment[];
  sessionStart: SSESessionStart | null;
  sessionEnd: SSESessionEnd | null;
  isStreaming: boolean;
  currentToolName: string | null;
  toolNames: string[];
  error: string | null;
  rawError: string | null;
  tokenInfos: SSETokenInfo[];
}

const EMPTY: InvokeSnapshot = {
  streamedText: "",
  segments: [],
  sessionStart: null,
  sessionEnd: null,
  isStreaming: false,
  currentToolName: null,
  toolNames: [],
  error: null,
  rawError: null,
  tokenInfos: [],
};

type Listener = () => void;

const _state = new Map<number, InvokeSnapshot>();
const _controllers = new Map<number, AbortController>();
const _wsControllers = new Map<number, WsInvokeController>();
const _listeners = new Map<number, Set<Listener>>();

function _get(agentId: number): InvokeSnapshot {
  return _state.get(agentId) ?? EMPTY;
}

function _update(agentId: number, partial: Partial<InvokeSnapshot>) {
  const current = _state.get(agentId) ?? { ...EMPTY };
  _state.set(agentId, { ...current, ...partial });
  _listeners.get(agentId)?.forEach((fn) => fn());
}

function _subscribe(agentId: number, listener: Listener): () => void {
  if (!_listeners.has(agentId)) _listeners.set(agentId, new Set());
  _listeners.get(agentId)!.add(listener);
  return () => {
    _listeners.get(agentId)?.delete(listener);
  };
}

async function _startInvoke(
  agentId: number,
  prompt: string,
  qualifier: string,
  authorizerName: string | undefined,
  sessionId?: string,
  credentialId?: number,
  bearerToken?: string,
  modelId?: string,
  connectorIds?: number[],
  useLinkedToken?: boolean,
  useWebSocket?: boolean,
) {
  // Abort any in-flight stream/ws for this agent
  _controllers.get(agentId)?.abort();
  _wsControllers.get(agentId)?.close();
  const controller = new AbortController();
  _controllers.set(agentId, controller);

  _update(agentId, {
    streamedText: "",
    segments: [],
    sessionStart: null,
    sessionEnd: null,
    isStreaming: true,
    currentToolName: null,
    toolNames: [],
    error: null,
    rawError: null,
    tokenInfos: [],
  });

  if (useWebSocket) {
    _startInvokeWs(agentId, prompt, qualifier, authorizerName, sessionId, modelId, connectorIds);
    return;
  }

  try {
    await invokeAgentStream(
      agentId,
      {
        prompt,
        qualifier,
        ...(sessionId ? { session_id: sessionId } : {}),
        ...(credentialId ? { credential_id: credentialId } : {}),
        ...(bearerToken ? { bearer_token: bearerToken } : {}),
        ...(modelId ? { model_id: modelId } : {}),
        ...(connectorIds && connectorIds.length > 0 ? { connector_ids: connectorIds } : {}),
        ...(useLinkedToken ? { use_linked_token: true } : {}),
      },
      {
        onSessionStart: (data) => _update(agentId, { sessionStart: data }),
        onChunk: (data) => {
          const cur = _get(agentId);
          const segs = [...cur.segments];
          const last = segs[segs.length - 1];
          if (last && last.type === "text") {
            segs[segs.length - 1] = { type: "text", content: last.content + data.text };
          } else {
            segs.push({ type: "text", content: data.text });
          }
          _update(agentId, { streamedText: cur.streamedText + data.text, segments: segs, currentToolName: null });
        },
        onToolUse: (data) => {
          const cur = _get(agentId);
          const newToolNames = [...cur.toolNames, data.name];
          const newTotal = newToolNames.length;
          const segs: StreamSegment[] = cur.segments.map((s) =>
            s.type === "tool_use" ? { ...s, total: newTotal } : s,
          );
          segs.push({ type: "tool_use", name: data.name, index: newTotal, total: newTotal, timestamp: Date.now() });
          _update(agentId, { currentToolName: data.name, toolNames: newToolNames, segments: segs });
        },
        onApprovalRequest: (data) => {
          const cur = _get(agentId);
          const segs = [...cur.segments, { type: "approval_request" as const, data }];
          _update(agentId, { segments: segs });
        },
        onApprovalResolved: (data) => {
          const cur = _get(agentId);
          const segs = [...cur.segments, { type: "approval_resolved" as const, data }];
          _update(agentId, { segments: segs });
        },
        onElicitationRequest: (data) => {
          const cur = _get(agentId);
          const segs = [...cur.segments, { type: "elicitation_request" as const, data }];
          _update(agentId, { segments: segs });
        },
        onTokenInfo: (data) => {
          const cur = _get(agentId);
          _update(agentId, { tokenInfos: [...cur.tokenInfos, data] });
        },
        onSessionEnd: (data) => {
          _update(agentId, { sessionEnd: data, isStreaming: false, currentToolName: null });
        },
        onError: (data) => {
          _update(agentId, {
            error: friendlyInvokeError(data.message, authorizerName),
            rawError: data.message,
            isStreaming: false,
            currentToolName: null,
          });
        },
      },
      controller.signal,
    );
    // Stream finished — clear isStreaming even if no session_end was received
    _update(agentId, { isStreaming: false, currentToolName: null });
  } catch (e) {
    if (e instanceof DOMException && e.name === "AbortError") return;
    const msg = e instanceof Error ? e.message : "Invocation failed";
    _update(agentId, {
      error: friendlyInvokeError(msg, authorizerName),
      rawError: msg,
      isStreaming: false,
    });
  }
}

function _startInvokeWs(
  agentId: number,
  prompt: string,
  qualifier: string,
  authorizerName: string | undefined,
  sessionId?: string,
  modelId?: string,
  connectorIds?: number[],
) {
  const wsCtrl = invokeAgentWs(
    agentId,
    {
      prompt,
      qualifier,
      ...(sessionId ? { session_id: sessionId } : {}),
      ...(modelId ? { model_id: modelId } : {}),
      ...(connectorIds && connectorIds.length > 0 ? { connector_ids: connectorIds } : {}),
    },
    {
      onSessionStart: (data) => {
        _update(agentId, { sessionStart: { session_id: data.session_id, invocation_id: "", client_invoke_time: Date.now() } });
      },
      onText: (text) => {
        const cur = _get(agentId);
        const segs = [...cur.segments];
        const last = segs[segs.length - 1];
        if (last && last.type === "text") {
          segs[segs.length - 1] = { type: "text", content: last.content + text };
        } else {
          segs.push({ type: "text", content: text });
        }
        _update(agentId, { streamedText: cur.streamedText + text, segments: segs, currentToolName: null });
      },
      onToolUse: (data) => {
        const cur = _get(agentId);
        const newToolNames = [...cur.toolNames, data.name];
        const newTotal = newToolNames.length;
        const segs: StreamSegment[] = cur.segments.map((s) =>
          s.type === "tool_use" ? { ...s, total: newTotal } : s,
        );
        segs.push({ type: "tool_use", name: data.name, index: newTotal, total: newTotal, timestamp: Date.now() });
        _update(agentId, { currentToolName: data.name, toolNames: newToolNames, segments: segs });
      },
      onElicitation: (data) => {
        const cur = _get(agentId);
        const elicitData: SSEElicitationRequest = {
          elicitation_id: data.id,
          message: data.message,
        };
        const segs = [...cur.segments, { type: "elicitation_request" as const, data: elicitData }];
        _update(agentId, { segments: segs });
      },
      onResult: (content) => {
        const cur = _get(agentId);
        const segs = [...cur.segments];
        const last = segs[segs.length - 1];
        if (last && last.type === "text") {
          segs[segs.length - 1] = { type: "text", content: last.content + content };
        } else {
          segs.push({ type: "text", content });
        }
        const now = Date.now();
        const startTime = cur.sessionStart?.client_invoke_time ?? now;
        const sessionId = cur.sessionStart?.session_id ?? "";
        _update(agentId, {
          streamedText: cur.streamedText + content,
          segments: segs,
          sessionEnd: {
            session_id: sessionId,
            invocation_id: "",
            request_id: null,
            qualifier: "DEFAULT",
            client_invoke_time: startTime,
            client_done_time: now,
            client_duration_ms: now - startTime,
            cold_start_latency_ms: null,
            agent_start_time: null,
            input_tokens: null,
            output_tokens: null,
            estimated_cost: null,
            compute_cost: null,
            compute_cpu_cost: null,
            compute_memory_cost: null,
            idle_timeout_cost: null,
            idle_cpu_cost: null,
            idle_memory_cost: null,
            memory_retrievals: null,
            memory_events_sent: null,
            memory_estimated_cost: null,
            stm_cost: null,
            ltm_cost: null,
          },
          isStreaming: false,
          currentToolName: null,
        });
      },
      onError: (message) => {
        _update(agentId, {
          error: friendlyInvokeError(message, authorizerName),
          rawError: message,
          isStreaming: false,
          currentToolName: null,
        });
      },
      onClose: () => {
        const cur = _get(agentId);
        if (cur.isStreaming) {
          _update(agentId, { isStreaming: false, currentToolName: null });
        }
      },
    },
  );
  _wsControllers.set(agentId, wsCtrl);
}

export function sendElicitationResponse(agentId: number, id: string, action: "accept" | "decline" | "cancel", content?: Record<string, unknown>) {
  const wsCtrl = _wsControllers.get(agentId);
  if (wsCtrl) {
    wsCtrl.sendElicitationResponse(id, action, content);
  }
}

function _cancel(agentId: number) {
  _controllers.get(agentId)?.abort();
  _wsControllers.get(agentId)?.close();
  _update(agentId, { isStreaming: false });
}

export function clearInvokeState(agentId: number) {
  _controllers.get(agentId)?.abort();
  _wsControllers.get(agentId)?.close();
  _controllers.delete(agentId);
  _wsControllers.delete(agentId);
  // Reset state to EMPTY and notify subscribers — do NOT delete listeners so
  // the component stays subscribed and sees subsequent invocations.
  _update(agentId, { ...EMPTY });
}

// ---------------------------------------------------------------------------
// React hook — subscribes to the module-level store for a given agentId.
// The stream runs independently of component lifecycle.
// ---------------------------------------------------------------------------

export function useInvoke(agentId: number, authorizerName?: string) {
  const [snapshot, setSnapshot] = useState<InvokeSnapshot>(() => _get(agentId));
  const authorizerRef = useRef(authorizerName);
  authorizerRef.current = authorizerName;

  useEffect(() => {
    // Sync immediately in case state changed while unmounted
    const current = _get(agentId);
    // Clear error when switching to a new agent
    if (current.error) {
      _update(agentId, { error: null, rawError: null });
    }
    setSnapshot(_get(agentId));
    return _subscribe(agentId, () => setSnapshot({ ..._get(agentId) }));
  }, [agentId]);

  const invoke = useCallback(
    async (prompt: string, qualifier: string, sessionId?: string, credentialId?: number, bearerToken?: string, modelId?: string, connectorIds?: number[], useLinkedToken?: boolean, useWebSocket?: boolean) => {
      await _startInvoke(agentId, prompt, qualifier, authorizerRef.current, sessionId, credentialId, bearerToken, modelId, connectorIds, useLinkedToken, useWebSocket);
    },
    [agentId],
  );

  const cancel = useCallback(() => {
    _cancel(agentId);
  }, [agentId]);

  return {
    streamedText: snapshot.streamedText,
    segments: snapshot.segments,
    sessionStart: snapshot.sessionStart,
    sessionEnd: snapshot.sessionEnd,
    isStreaming: snapshot.isStreaming,
    currentToolName: snapshot.currentToolName,
    toolNames: snapshot.toolNames,
    error: snapshot.error,
    rawError: snapshot.rawError,
    tokenInfos: snapshot.tokenInfos,
    invoke,
    cancel,
  };
}
