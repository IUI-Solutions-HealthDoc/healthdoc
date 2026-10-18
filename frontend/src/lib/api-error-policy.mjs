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
    actor_not_provisioned: "Sign-in succeeded, but this account is not linked to a HealthDoc staff profile. Ask your facility administrator to check account provisioning.",
    user_deactivated: "Your HealthDoc staff account is deactivated. Contact your facility administrator.",
    abdm_rejected: "ABDM declined this request. Check the details before retrying; contact support if it continues.",
    // ABDM-1203: the licence record (Sarathi) did not match what was entered.
    abha_licence_rejected: "ABDM did not match these details to the driving licence record. Enter the licence number, name, date of birth and gender exactly as printed on the licence.",
    duplicate_abha: "This ABHA number is already linked to another patient. Open that record instead of linking it here.",
    abha_link_unavailable: "This ABHA number cannot be linked at this facility. Contact your facility administrator.",
    consent_manager_decision_forbidden: "Only an admin or doctor can record a consent manager's decision.",
    enrolment_consent_required: "Confirm the patient's enrolment consent before creating an ABHA.",
    enrolment_consent_refused: "ABHA enrolment stops when the patient does not consent.",
    enrolment_consent_language_unavailable: "Hindi enrolment consent is not available until an approved translation is loaded.",
    abha_address_refused: "ABDM did not accept this ABHA address. Choose another suggestion.",
    abha_address_invalid: "That is not a valid ABHA address. Choose one of the addresses ABDM suggested.",
    otp_rejected: "ABDM did not accept this OTP. It may be wrong, expired or over the attempt limit. Check the code and try again, or request a new OTP.",
    // Demographic creation (CRT_ABHA_301-309): refusals the desk cannot see
    // as a highlighted field, so each needs its own words.
    abdm_demographic_not_enabled: "Creating an ABHA from Aadhaar demographics is not enabled for this facility. NHA must grant the demographic-authentication role and benefit name first. Use Create ABHA (Aadhaar OTP) instead.",
    abdm_demographic_not_permitted: "ABDM refused demographic ABHA creation for this facility. Contact your ABDM administrator.",
    abha_demographics_rejected: "ABDM did not accept these details for this Aadhaar number. Check name, date of birth and gender against the Aadhaar card.",
    lgd_code_unknown: "Choose the state and district again from the lists.",
    // NHA's own wording for VRFY_ABHA_302 and VRFY_ABHA_403.
    abha_not_found_for_mobile: "ABHA Number not found. We did not find any ABHA number linked to this mobile number. Please use ABHA linked mobile number.",
    abha_not_found_for_aadhaar: "No ABHA user is registered with this Aadhaar number.",
    // Releasing a chart PDF as a Health Document (HealthDocumentRecord).
    document_not_pdf: "Only a PDF can be released. Convert an image to PDF and upload that.",
    document_too_large: "A released document must be 1 MB or smaller.",
    document_already_released: "This file has already been released.",
    document_date_in_future: "The document date cannot be in the future.",
    document_title_required: "Give the document a title.",
    file_erased: "This file has been erased and cannot be released.",
    file_not_found: "That file is not on this patient's chart.",
    aadhaar_invalid: "ABDM did not accept this Aadhaar number. Check the 12 digits and try again.",
    abdm_auth_failed: "ABDM did not accept this OTP. It may be wrong, expired or over the attempt limit. Check the code and try again, or request a new OTP.",
    abha_mobile_required: "Enter the patient's 10-digit mobile number. ABDM needs it to create the ABHA.",
    abha_mobile_rejected: "ABDM did not accept this mobile number for the ABHA. Check the 10-digit number and try again.",
    // ABDM-1206: ABDM is up but cannot reach UIDAI, so no Aadhaar OTP can be sent.
    aadhaar_service_unavailable: "ABDM cannot reach the Aadhaar (UIDAI) service right now, so Aadhaar OTPs cannot be sent. Try again later, or verify with the ABHA-linked mobile instead.",
    abha_profile_unavailable: "The NHA ABHA card is not available until enrolment or login stores a profile credential.",
    abdm_account_selection_required: "ABDM returned more than one account. Do not continue until the patient chooses one.",
    abdm_requester_required: "Ask your facility administrator to verify your name, registration number, identifier type and issuing registry URI before requesting ABDM records.",
    invalid_abdm_requester_profile: "Enter the real registration number, identifier type and issuing registry URI together, or clear all three registration fields.",
  };
  if (domainCode && Object.hasOwn(domainMessages, domainCode)) {
    return domainMessages[domainCode];
  }

  // HealthDoc's own refusals carry a sentence written for the person at the
  // screen ("Choose a date from today to 60 days ahead"). Replacing it with
  // "check the highlighted fields" when nothing is highlighted, or "reload"
  // when reloading cannot help, hid the real reason (QA 12 Oct 2026). Text
  // relayed from ABDM is still never shown: it can carry upstream detail.
  const own = ownRefusalMessage(code, payload, domainCode);
  if (own) return own;
  const coded = codeOnlyMessage(code, payload, domainCode);
  if (coded) return coded;
  const plain = plainDetailMessage(code, payload);
  if (plain) return plain;

  if (code === 400 || code === 422) {
    return validationSummary(payload) ?? "Please check the highlighted fields and try again.";
  }
  if (code === 401) return "Your session has expired. Sign in again.";
  if (code === 403) return "You do not have permission to perform this action.";
  if (code === 404) return "The requested record was not found.";
  if (code === 409) {
    return "This request conflicts with the record's current state. Reload and try again.";
  }
  if (code === 429) return "Too many requests. Wait a moment and try again.";
  // Only the gateway statuses mean "not reachable right now". A 500 is a
  // server fault; calling it an outage sends the desk into a retry loop
  // instead of to the people who can fix it.
  if (code === 502 || code === 503 || code === 504) {
    return "The service is temporarily unavailable. Try again shortly.";
  }
  if (code >= 500) return "Something went wrong on the server. Report it to IT if it happens again.";
  return "The request could not be completed. Please try again.";
}

const RELAYED_PREFIXES = ["abdm", "abha", "aadhaar", "hip_", "hiu_", "gateway"];

function domainMessageText(value) {
  if (!value || typeof value !== "object") return undefined;
  if (typeof value.code === "string" && typeof value.message === "string") return value.message;
  return domainMessageText(value.detail);
}

function isPlainSentence(text) {
  return text.length > 0 && text.length <= 300 && !/[{}\[\]<>]|Traceback|Exception|SELECT |\bnull\b/.test(text);
}

function ownRefusalMessage(code, payload, domainCode) {
  if (![400, 404, 409, 422].includes(code) || !domainCode) return undefined;
  if (RELAYED_PREFIXES.some((prefix) => domainCode.toLowerCase().startsWith(prefix))) return undefined;
  const text = domainMessageText(payload);
  return typeof text === "string" && isPlainSentence(text.trim()) ? text.trim() : undefined;
}

/**
 * FastAPI's 422 list, reduced to the field and the reason. The submitted
 * value (`input`) is never echoed: it may be an identifier.
 */
/**
 * A refusal that carries only a code (`{"code": "insufficient_stock",
 * "short_by": "9"}`) used to become "check the highlighted fields" with
 * nothing highlighted (QA 16-17 Oct 2026). Known codes get a sentence built
 * from their numeric parameters; any other HealthDoc code is read as words.
 */
const CODE_SENTENCES = {
  insufficient_stock: (p) =>
    p.short_by
      ? `Not enough stock: short by ${p.short_by}. Reduce the quantity or tick partial fulfilment.`
      : p.available !== undefined && p.requested !== undefined
        ? `Not enough stock: ${p.available} available, ${p.requested} requested. Reduce the quantity or tick partial fulfilment.`
        : "Not enough stock for this quantity.",
  batch_expired: () => "This batch has expired and cannot be dispensed. Choose another batch.",
  allergy_conflict: () => "The patient has a recorded allergy to this medicine. Review the allergy before dispensing.",
  drug_interaction_conflict: () => "This medicine interacts with another on the prescription. Review the prescription first.",
  sample_not_ready_for_result: () => "The sample has not been received in the lab yet, so a result cannot be entered.",
  result_already_exists: () => "A result has already been entered for this test.",
  idempotency_key_reuse: () => "This form was already submitted with different values. Reload the page and enter it again.",
  invoice_not_found: () => "The invoice was not found.",
  consent_manager_inactive: () => "This consent manager is not active.",
  prescription_item_mismatch: () => "This line does not belong to the prescription being dispensed.",
  substitute_matches_prescribed_item: () => "The substitute is the same medicine as the one prescribed.",
};

function codeParams(value) {
  if (!value || typeof value !== "object") return {};
  if (typeof value.code === "string") return value;
  return codeParams(value.detail);
}

function codeOnlyMessage(code, payload, domainCode) {
  if (![400, 404, 409, 422].includes(code) || !domainCode) return undefined;
  if (RELAYED_PREFIXES.some((prefix) => domainCode.toLowerCase().startsWith(prefix))) return undefined;
  const params = {};
  for (const [key, val] of Object.entries(codeParams(payload))) {
    // Only quantities travel into the sentence; ids and free text never do.
    if (typeof val === "string" && /^-?\d+(\.\d+)?$/.test(val)) params[key] = val;
    if (typeof val === "number" && Number.isFinite(val)) params[key] = String(val);
  }
  if (Object.hasOwn(CODE_SENTENCES, domainCode)) return CODE_SENTENCES[domainCode](params);
  return codeAsSentence(domainCode);
}

function codeAsSentence(value) {
  if (!/^[a-z][a-z0-9]*(_[a-z0-9]+)+$/.test(value)) return undefined;
  const words = value.replace(/_/g, " ");
  return `${words.charAt(0).toUpperCase()}${words.slice(1)}.`;
}

const UUID_RE = /[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/i;

/**
 * FastAPI's `HTTPException(422, "Verifier must be different from the person
 * who entered the result")` arrives as a bare string. It is HealthDoc's own
 * sentence, so it is shown; a bare code is read as words. Anything carrying
 * an id, markup or a stack is not.
 */
function plainDetailMessage(code, payload) {
  if (![400, 404, 409, 422].includes(code)) return undefined;
  const text = typeof payload === "string" ? payload : payload && typeof payload === "object" && typeof payload.detail === "string" ? payload.detail : undefined;
  if (!text) return undefined;
  const trimmed = text.trim();
  const asCode = codeAsSentence(trimmed);
  if (asCode) return asCode;
  if (UUID_RE.test(trimmed) || /=|Keycloak|object storage|DETAIL:|psycopg|asyncpg/i.test(trimmed)) return undefined;
  if (!isPlainSentence(trimmed) || !/\s/.test(trimmed)) return undefined;
  return /[.!?]$/.test(trimmed) ? trimmed : `${trimmed}.`;
}

function validationSummary(payload) {
  // api() hands over the envelope's `error.message`, which for a FastAPI 422
  // is the bare list; tests and older callers pass `{detail: [...]}`.
  const items = Array.isArray(payload)
    ? payload
    : payload && typeof payload === "object" && Array.isArray(payload.detail) ? payload.detail : null;
  if (!items) return undefined;
  const parts = [];
  for (const item of items.slice(0, 3)) {
    if (!item || typeof item !== "object") continue;
    const loc = Array.isArray(item.loc) ? item.loc.filter((part) => typeof part === "string" && part !== "body") : [];
    const field = loc.length ? loc[loc.length - 1].replace(/_/g, " ") : "";
    if (!item || typeof item.msg !== "string") {
      // Still name the field: "check the highlighted fields" with nothing
      // highlighted left people guessing (QA 17 Oct 2026).
      if (field) parts.push(`${field}: check this value`);
      continue;
    }
    const reason = item.msg.replace(/^Value error, /, "").replace(/\b([a-z]+)_([a-z_]+)\b/g, (m) => m.replace(/_/g, " "));
    if (!isPlainSentence(reason)) {
      if (field) parts.push(`${field}: check this value`);
      continue;
    }
    parts.push(field ? `${field}: ${reason}` : reason);
  }
  if (!parts.length) return undefined;
  const text = parts.join("; ");
  return `${text.charAt(0).toUpperCase()}${text.slice(1)}${/[.!?]$/.test(text) ? "" : "."}`;
}
