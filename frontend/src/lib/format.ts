import type { TimezonePreference } from "@/contexts/TimezoneContext";

export function capitalize(value: string): string {
  return value.length === 0 ? value : value.charAt(0).toUpperCase() + value.slice(1);
}

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

/** "Today 10:29 PM" / "Yesterday 4:02 PM" / "Oct 2, 10:29 PM" — never a bare
 * locale date like "10/2/2026" in tables where that reads as noise. */
export function formatRelativeDateTime(
  value: string | null,
  timezone: TimezonePreference,
): string {
  if (!value) return "—";
  const date = new Date(value);
  const tz = timezone === "UTC" ? "UTC" : undefined;
  const dayKey = (d: Date) =>
    d.toLocaleDateString(undefined, { timeZone: tz, year: "numeric", month: "2-digit", day: "2-digit" });
  const now = new Date();
  const yesterday = new Date(now.getTime() - 86_400_000);
  const time = date.toLocaleTimeString(undefined, { timeZone: tz, hour: "numeric", minute: "2-digit" });
  if (dayKey(date) === dayKey(now)) return `Today ${time}`;
  if (dayKey(date) === dayKey(yesterday)) return `Yesterday ${time}`;
  const monthDay = date.toLocaleDateString(undefined, { timeZone: tz, month: "short", day: "numeric" });
  return `${monthDay}, ${time}`;
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
