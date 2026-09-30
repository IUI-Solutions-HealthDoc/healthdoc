/** Consent DTOs aligned to BE ConsentRecordOut + ConsentPurposeOut (0004). */

export type ConsentStatus =
  | "requested"
  | "granted"
  | "denied"
  | "revoked"
  | "expired";

export type ConsentChannel =
  | "verbal"
  | "written"
  | "digital_otp"
  | "abdm_consent_manager";

export type GrantedByType = "patient" | "guardian" | "nominee";

/** data_access_log access_channel */
export type AccessChannel = "ui" | "api" | "abdm_hiu" | "export";

export type ConsentPurpose = {
  id: string;
  purpose_code: string;
  description: string | null;
  default_expiry_days: number | null;
  requires_explicit_consent: boolean;
  is_active: boolean;
};

/** Mirrors ConsentRecordOut — purpose_id FK, not purpose_code on the row. */
export type ConsentRecord = {
  id: string;
  patient_id: string;
  visit_id: string | null;
  purpose_id: string;
  granted_by_type: GrantedByType | string;
  granted_by_user_id: string | null;
  guardian_name: string | null;
  guardian_relationship: string | null;
  granted_at: string;
  expires_at: string | null;
  scope: string[] | null;
  channel: ConsentChannel | string;
  consent_artefact_id: string | null;
  consent_artefact_signature: string | null;
  status: ConsentStatus;
  status_changed_at: string;
  created_by: string;
  updated_by: string | null;
  created_at: string;
  updated_at: string;
  /** FE join helpers (not on ConsentRecordOut) */
  patient?: { uhid: string; name: string };
  purpose_code?: string;
  purpose_label?: string;
};

export type ConsentRecordCreate = {
  purpose_id: string;
  visit_id?: string | null;
  granted_by_type: GrantedByType;
  guardian_name?: string | null;
  guardian_relationship?: string | null;
  expires_at?: string | null;
  scope?: string[] | null;
  channel: ConsentChannel;
  consent_artefact_id?: string | null;
  consent_artefact_signature?: string | null;
  status?: "granted" | "requested";
};

export type ConsentStatusTransitionIn = {
  status: "granted" | "denied";
  reason?: string | null;
};

export type ConsentWithdrawalCreate = {
  withdrawn_by_type: GrantedByType;
  reason?: string | null;
};

/** Mirrors ConsentWithdrawalOut. */
export type ConsentWithdrawal = {
  id: string;
  consent_id: string;
  withdrawn_by_type: string;
  withdrawn_by_user_id: string | null;
  withdrawn_at: string;
  reason: string | null;
  cascaded_actions: Record<string, string> | null;
  cascade_deadline: string | null;
  cascade_completed_at: string | null;
};

export type DataAccessLog = {
  id: string;
  accessed_at: string;
  consent_id: string | null;
  user_id: string;
  role: string | null;
  resource_type: string;
  resource_id: string | null;
  patient_id: string | null;
  purpose_code: string | null;
  access_channel: AccessChannel;
  emergency_access: boolean;
  consent_required: boolean;
  consent_verified: boolean;
  user_display?: string;
};

export type ConsentListFilters = {
  /** When set, mirrors GET /consent/patients/{patient_id}/records */
  patient_id?: string;
  query?: string;
  status?: ConsentStatus | "all";
};

export type DataAccessFilters = {
  consent_id?: string;
  patient_id?: string;
  query?: string;
};
