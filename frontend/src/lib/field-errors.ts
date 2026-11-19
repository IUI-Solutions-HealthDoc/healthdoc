import { ApiError, apiErrorCode } from "./api";

/**
 * The form fields a refusal is about, so a screen can mark them instead of
 * saying "check the highlighted fields" with nothing highlighted (QA 16-17
 * Oct 2026).
 *
 * FastAPI's 422 list names each field in `loc`. A domain refusal names none,
 * so callers pass a map from its code to the fields it concerns.
 */
export function fieldsFromError(reason: unknown, byCode: Record<string, string[]> = {}): Set<string> {
  const fields = new Set<string>();
  if (!(reason instanceof ApiError)) return fields;
  const payload = reason.payload;
  const items = Array.isArray(payload)
    ? payload
    : payload && typeof payload === "object" && Array.isArray((payload as { detail?: unknown }).detail)
      ? (payload as { detail: unknown[] }).detail
      : [];
  for (const item of items) {
    const loc = item && typeof item === "object" ? (item as { loc?: unknown }).loc : undefined;
    if (!Array.isArray(loc)) continue;
    const named = loc.filter((part): part is string => typeof part === "string" && part !== "body");
    if (named.length) fields.add(named[named.length - 1]);
  }
  const code = apiErrorCode(payload);
  for (const name of (code && byCode[code]) || []) fields.add(name);
  return fields;
}
