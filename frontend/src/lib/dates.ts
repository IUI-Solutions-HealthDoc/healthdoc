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
