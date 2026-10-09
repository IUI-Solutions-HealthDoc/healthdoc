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
  // Only the gateway statuses mean "not reachable right now". A 500 is a
  // server fault; calling it an outage sends the desk into a retry loop
  // instead of to the people who can fix it.
  if (code === 502 || code === 503 || code === 504) {
    return "The service is temporarily unavailable. Try again shortly.";
  }
  if (code >= 500) return "Something went wrong on the server. Report it to IT if it happens again.";
  return "The request could not be completed. Please try again.";
}
