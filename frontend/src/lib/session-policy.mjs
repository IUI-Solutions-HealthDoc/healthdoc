const DEFAULT_IDLE_MINUTES = 15;
const MAX_IDLE_MINUTES = 12 * 60;

export function idleTimeoutMs(rawMinutes) {
  const parsed = Number(rawMinutes);
  const minutes = Number.isFinite(parsed) && parsed > 0
    ? Math.min(parsed, MAX_IDLE_MINUTES)
    : DEFAULT_IDLE_MINUTES;
  return minutes * 60_000;
}

export function sessionExpiredPath(pathname, search = "", hash = "") {
  const current = `${pathname || "/"}${search || ""}${hash || ""}`;
  const params = new URLSearchParams({ reason: "session-expired" });
  if (pathname !== "/login") params.set("redirect", current);
  return `/login?${params.toString()}`;
}
