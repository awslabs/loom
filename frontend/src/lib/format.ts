import type { TimezonePreference } from "@/contexts/TimezoneContext";

export function formatTimestamp(
  value: string | null,
  timezone: TimezonePreference,
): string {
  if (!value) return "\u2014";
  const date = new Date(value);
  return date.toLocaleString(undefined, {
    timeZone: timezone === "UTC" ? "UTC" : undefined,
  });
}

export function formatUnixTime(
  epochSeconds: number | null,
  timezone: TimezonePreference,
): string {
  if (epochSeconds === null) return "\u2014";
  const date = new Date(epochSeconds * 1000);
  return date.toLocaleTimeString(undefined, {
    timeZone: timezone === "UTC" ? "UTC" : undefined,
  });
}

export function formatLogTime(
  isoTimestamp: string,
  timezone: TimezonePreference,
): string {
  const date = new Date(isoTimestamp);
  const opts: Intl.DateTimeFormatOptions = {
    timeZone: timezone === "UTC" ? "UTC" : undefined,
    hour12: false,
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  };
  const base = date.toLocaleTimeString(undefined, opts);
  const ms = String(date.getMilliseconds()).padStart(3, "0");
  return `${base}.${ms}`;
}

export function formatMs(ms: number | null): string {
  if (ms === null) return "\u2014";
  return `${ms.toFixed(1)} ms`;
}
