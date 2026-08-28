export function apiErrorCode(value) {
  if (!value || typeof value !== "object") return undefined;
  if (typeof value.code === "string") return value.code;
  return apiErrorCode(value.detail) ?? apiErrorCode(value.message);
}

/**
 * Convert an API status + diagnostic payload into stable UI copy. The raw
 * payload remains on ApiError for logs and field mapping; it is never toast
 * text.
 *
 * @param {number} code
 * @param {unknown} [payload]
 */
export function userFacingApiError(code, payload) {
  const domainCode = apiErrorCode(payload);
  const domainMessages = {
    module_disabled: "This module is not enabled for your facility.",
    stale_write: "This record changed after you opened it. Reload and try again.",
    self_approval: "You cannot approve or reject your own request.",
    self_approval_not_allowed: "You cannot approve your own request.",
    self_unmerge_not_allowed: "The approving user cannot also undo this merge.",
    not_pending: "This request has already been decided.",
    username_taken: "That username is already in use.",
    patient_not_found: "The requested patient was not found.",
    account_request_not_found: "The account request was not found.",
  };
  if (domainCode && Object.hasOwn(domainMessages, domainCode)) {
    return domainMessages[domainCode];
  }

  if (code === 400 || code === 422) {
    return "Please check the highlighted fields and try again.";
  }
  if (code === 401) return "Your session has expired. Sign in again.";
  if (code === 403) return "You do not have permission to perform this action.";
  if (code === 404) return "The requested record was not found.";
  if (code === 409) {
    return "This request conflicts with the record's current state. Reload and try again.";
  }
  if (code === 429) return "Too many requests. Wait a moment and try again.";
  if (code >= 500) return "The service is temporarily unavailable. Try again shortly.";
  return "The request could not be completed. Please try again.";
}
