/**
 * The facility's calendar date as YYYY-MM-DD.
 *
 * `new Date().toISOString().slice(0, 10)` is the UTC date, which in India is
 * still yesterday until 05:30 — an early desk would book, list and check in
 * against the wrong day. The backend decides "today" in the facility's zone,
 * so the browser must agree with it rather than with UTC.
 */
export const FACILITY_TIME_ZONE = "Asia/Kolkata";

export function localToday(now: Date = new Date(), timeZone: string = FACILITY_TIME_ZONE): string {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(now);
  const part = (type: string) => parts.find((p) => p.type === type)?.value ?? "";
  return `${part("year")}-${part("month")}-${part("day")}`;
}

/**
 * "Now" as a datetime-local value (browser time, minute precision). Admitted
 * At and Discharged At started blank, so every admission needed the time typed
 * in by hand (QA 16 Oct 2026).
 */
export function localDateTimeNow(now: Date = new Date()): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}T${pad(now.getHours())}:${pad(now.getMinutes())}`;
}

/**
 * A calendar date ("2026-10-18", or the date part of a timestamp) as
 * "18 Oct 2026". Screens printed the raw ISO value beside forms that take
 * dd-mm-yyyy (QA 16-17 Oct 2026). A date has no time zone, so it is not
 * converted; a full timestamp should use formatDateTime.
 */
export function formatDate(value: string | null | undefined): string {
  if (!value) return "—";
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(value);
  if (!match) return value;
  const [, y, m, d] = match;
  const months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  return `${Number(d)} ${months[Number(m) - 1] ?? m} ${y}`;
}
