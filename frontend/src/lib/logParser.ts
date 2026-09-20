import type { LogEvent } from "@/api/types";

export type LogLevel = "DEBUG" | "INFO" | "WARN" | "ERROR";

export interface ParsedLogLine {
  level: LogLevel | null;
  logger: string | null;
  text: string;
  json: unknown | null;
}

export interface MergedLogEntry {
  event: LogEvent;
  parsed: ParsedLogLine;
  detailJson: unknown | null;
}

const LEVEL_ALIASES: Record<string, LogLevel> = {
  DEBUG: "DEBUG",
  INFO: "INFO",
  WARN: "WARN",
  WARNING: "WARN",
  ERROR: "ERROR",
  CRITICAL: "ERROR",
  FATAL: "ERROR",
};

const LEVEL_PATTERN = "(DEBUG|INFO|WARNING|WARN|ERROR|CRITICAL|FATAL)";

/** Best-effort parse of a raw CloudWatch log line — level/logger aren't structured fields from the API, just conventions in the text. Falls back to the raw message untouched if nothing matches. */
export function parseLogLine(message: string): ParsedLogLine {
  const trimmed = message.trim();

  if ((trimmed.startsWith("{") && trimmed.endsWith("}")) || (trimmed.startsWith("[") && trimmed.endsWith("]"))) {
    try {
      const json = JSON.parse(trimmed);
      return { level: null, logger: null, text: message, json };
    } catch {
      // not actually valid JSON — fall through to text parsing
    }
  }

  let m = new RegExp(`^${LEVEL_PATTERN}:([\\w.]+):(.*)$`, "s").exec(trimmed);
  if (m) {
    return { level: LEVEL_ALIASES[m[1]!.toUpperCase()] ?? null, logger: m[2] ?? null, text: (m[3] ?? "").trim(), json: null };
  }

  m = new RegExp(`^([\\w.]+):${LEVEL_PATTERN}:(.*)$`, "s").exec(trimmed);
  if (m) {
    return { level: LEVEL_ALIASES[m[2]!.toUpperCase()] ?? null, logger: m[1] ?? null, text: (m[3] ?? "").trim(), json: null };
  }

  m = new RegExp(`^\\[?${LEVEL_PATTERN}\\]?[\\s:-]+(.*)$`, "s").exec(trimmed);
  if (m) {
    return { level: LEVEL_ALIASES[m[1]!.toUpperCase()] ?? null, logger: null, text: (m[2] ?? "").trim(), json: null };
  }

  return { level: null, logger: null, text: message, json: null };
}

/** Merge an adjacent (text, JSON) pair sharing a timestamp into one entry — the two-line "formatted + raw JSON dump" duplicate pattern common in structured logging. */
export function mergeLogEvents(events: LogEvent[]): MergedLogEntry[] {
  const parsed = events.map((e) => ({ event: e, parsed: parseLogLine(e.message) }));
  const result: MergedLogEntry[] = [];
  let i = 0;
  while (i < parsed.length) {
    const cur = parsed[i]!;
    const next = parsed[i + 1];
    if (cur.parsed.json === null && next && next.event.timestamp_ms === cur.event.timestamp_ms && next.parsed.json !== null) {
      result.push({ event: cur.event, parsed: cur.parsed, detailJson: next.parsed.json });
      i += 2;
      continue;
    }
    result.push({ event: cur.event, parsed: cur.parsed, detailJson: null });
    i += 1;
  }
  return result;
}
