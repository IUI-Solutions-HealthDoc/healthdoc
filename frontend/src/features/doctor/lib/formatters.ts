import { FREQUENCY_OPTIONS, ROUTE_OPTIONS } from "../constants";

/** "34 yrs · Male" style demographics line; "Age unknown" when there is none. */
export { formatAgeSex } from "@/lib/format-age";

export function formatTime(iso: string): string {
  return new Date(iso).toLocaleString(undefined, {
    hour: "2-digit",
    minute: "2-digit",
    day: "2-digit",
    month: "short",
  });
}

/**
 * Timestamps arrive as ISO-8601 UTC with Z and are displayed in IST
 * (schema §4.2). Pinned explicitly so a workstation with a wrong locale
 * cannot mis-stamp a clinical result.
 */
export function formatDateTime(iso: string): string {
  return new Date(iso).toLocaleString("en-IN", {
    timeZone: "Asia/Kolkata",
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
    hour12: true,
  });
}

/**
 * "1:47:22" — time left on a break-glass grant. Takes milliseconds already
 * measured against the server's expires_at; it never decides the deadline.
 */
export function formatCountdown(ms: number): string {
  const total = Math.max(0, Math.floor(ms / 1000));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${h}:${pad(m)}:${pad(s)}`;
}

const FREQUENCY_LABELS = Object.fromEntries(
  FREQUENCY_OPTIONS.map((o) => [o.value, o.label]),
) as Record<string, string>;

const ROUTE_LABELS = Object.fromEntries(
  ROUTE_OPTIONS.map((o) => [o.value, o.label]),
) as Record<string, string>;

export const frequencyLabel = (f: string): string => FREQUENCY_LABELS[f] ?? f;
export const routeLabel = (r: string): string => ROUTE_LABELS[r] ?? r;

/** BMI from height/weight, or undefined if either is missing. Preview only. */
export function computeBmi(height_cm?: number, weight_kg?: number): number | undefined {
  if (!height_cm || !weight_kg) return undefined;
  const m = height_cm / 100;
  if (m <= 0) return undefined;
  return Math.round((weight_kg / (m * m)) * 10) / 10;
}

/** Waist-to-hip ratio, or undefined if either is missing. Preview only. */
export function computeWhr(waist_cm?: number, hip_cm?: number): number | undefined {
  if (!waist_cm || !hip_cm) return undefined;
  return Math.round((waist_cm / hip_cm) * 100) / 100;
}
