/**
 * Extract field-level validation errors and a readable summary from an error.
 * Handles FastAPI / Pydantic validation error lists:
 * [ { loc: ["body", "amount"], msg: "Input should be greater than 0", type: "greater_than" } ]
 * or object envelopes with { detail: [...] } or { message: [...] }.
 *
 * @param {unknown} error
 * @returns {{ fieldErrors: Record<string, string>, summary: string | null }}
 */
export function extractValidationErrors(error) {
  const fieldErrors = {};
  let summary = null;

  if (!error) {
    return { fieldErrors, summary };
  }

  const payload =
    error && typeof error === "object" && "payload" in error
      ? error.payload
      : null;

  const rawList = Array.isArray(payload)
    ? payload
    : Array.isArray(payload?.detail)
      ? payload.detail
      : Array.isArray(payload?.message)
        ? payload.message
        : null;

  if (rawList && rawList.length > 0) {
    const summaryParts = [];

    for (const item of rawList) {
      if (!item || typeof item !== "object") continue;
      const loc = Array.isArray(item.loc) ? item.loc : [];
      // The last string element of `loc` is usually the field name: ["body", "amount"] -> "amount"
      const fieldKey = loc.length > 0 ? String(loc[loc.length - 1]) : "";
      let msg = typeof item.msg === "string" ? item.msg : "";

      // Clean up common Pydantic error prefixes
      msg = msg.replace(/^Value error,\s*/i, "").trim();

      if (fieldKey && msg) {
        fieldErrors[fieldKey] = msg;
        const fieldLabel = fieldKey.charAt(0).toUpperCase() + fieldKey.slice(1).replace(/_/g, " ");
        summaryParts.push(`${fieldLabel}: ${msg}`);
      } else if (msg) {
        summaryParts.push(msg);
      }
    }

    if (summaryParts.length > 0) {
      summary = summaryParts.join(". ");
    }
  } else if (payload && typeof payload === "object") {
    if (typeof payload.detail === "string" && payload.detail.trim()) {
      summary = payload.detail.trim();
    } else if (typeof payload.message === "string" && payload.message.trim()) {
      summary = payload.message.trim();
    }
  } else if (typeof payload === "string" && payload.trim() && !payload.startsWith("{") && !payload.startsWith("[")) {
    summary = payload.trim();
  }

  const objectMessage =
    error instanceof Error
      ? error.message
      : error && typeof error === "object" && typeof error.message === "string"
        ? error.message
        : null;

  if (!summary && objectMessage) {
    summary = objectMessage;
  }

  return { fieldErrors, summary: summary || null };
}

/**
 * Get an actionable message suitable for toast or inline error display.
 *
 * @param {unknown} error
 * @param {string} [fallback]
 * @returns {string}
 */
export function getActionableErrorMessage(error, fallback = "The request could not be completed.") {
  const { summary } = extractValidationErrors(error);
  if (summary && summary !== "Please check the highlighted fields and try again.") {
    return summary;
  }
  const objectMessage =
    error instanceof Error
      ? error.message
      : error && typeof error === "object" && typeof error.message === "string"
        ? error.message
        : null;
  if (objectMessage) {
    return objectMessage;
  }
  return fallback;
}
