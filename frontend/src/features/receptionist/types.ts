/**
 * Mirrors the patients API. Field names are the wire's — no mapping layer.
 *
 * Contracts read from backend/app/patients/schemas.py rather than guessed; the
 * eMAR and bed-grid rework earlier in this project came from doing it the other
 * way round.
 */

/** POST /patients — `Idempotency-Key` header is mandatory. */
export interface PatientCreate {
  full_name: string;
  sex: "male" | "female" | "other" | "unknown";
  /** Exactly one of dob / age_years is required by the server. */
  dob?: string | null;
  age_years?: number | null;
  mobile?: string | null;
  abha_number?: string | null;
  aadhaar_number?: string | null;
}

export interface Patient {
  id: string;
  uhid: string | null;
  thid: string | null;
  full_name: string;
  sex: string;
  dob: string | null;
  age_years: number | null;
  mobile: string | null;
  abha_number: string | null;
  identity_path: string;
  identity_status: string;
  photo_file_id: string | null;
  facility_id: string;
  created_at: string;
}

/** POST /patients/search — at least one criterion required. */
export interface PatientSearchRequest {
  full_name?: string;
  dob?: string;
  mobile?: string;
  uhid?: string;
  aadhaar_number?: string;
  abha_number?: string;
  page?: number;
  page_size?: number;
}

export interface PatientSearchResult {
  id: string;
  uhid: string | null;
  full_name: string;
  sex: string;
  age_years: number | null;
  /** The server masks it. Never ask for or display the full number in a list. */
  mobile_masked: string | null;
  match_score: number;
  /** "aadhaar" | "abha" | "uhid" | "mobile" | "name_dob" */
  matched_on: string;
}

export interface PatientSearchResponse {
  items: PatientSearchResult[];
  page: number;
  page_size: number;
  total: number;
}

/**
 * How confident a match is, in words.
 *
 * `matched_on` matters more than the score: an Aadhaar or UHID hit is an
 * identity match, while a name+DOB hit is a guess that happens to score well.
 * A receptionist choosing between two similar names needs to see which kind
 * they are looking at — this is the difference between attaching a visit to the
 * right chart and merging two people's histories.
 */
export const MATCH_LABELS: Record<string, string> = {
  aadhaar: "Aadhaar match",
  abha: "ABHA match",
  uhid: "UHID match",
  mobile: "Mobile match",
  name_dob: "Name + date of birth",
};

export function isIdentityMatch(matchedOn: string): boolean {
  return ["aadhaar", "abha", "uhid"].includes(matchedOn);
}

/* ------------------------------------------------------------------ visits */

/**
 * POST /visits. `Idempotency-Key` mandatory.
 *
 * facility_id and created_by are deliberately absent: the server takes both
 * from the token and refuses a body facility_id that disagrees. Sending them
 * would be sending values the server ignores at best and rejects at worst.
 */
/** Mirrors backend VisitType (common/enums.py) and migration 0056's CHECK. */
export type VisitType = "opd" | "ipd" | "day_care" | "emergency" | "teleconsult";

/** Visit types that take a ward bed — kept beside the union so the two cannot
 *  drift. Mirrors VisitType.bed_occupying() on the backend. */
export const BED_OCCUPYING_VISIT_TYPES: readonly VisitType[] = ["ipd", "day_care"];

export const VISIT_TYPE_LABELS: Record<VisitType, string> = {
  opd: "OPD — outpatient",
  ipd: "IPD — admitted",
  day_care: "Day care — bed, same-day discharge",
  emergency: "Emergency",
  teleconsult: "Teleconsult",
};

export interface VisitCreate {
  patient_id: string;
  visit_type: VisitType;
  visit_date: string;
  department_id?: string | null;
}

export interface Visit {
  id: string;
  visit_number: string;
  patient_id: string;
  facility_id: string;
  department_id: string | null;
  visit_type: string;
  status: string;
  visit_date: string;
  created_at: string;
  updated_at: string;
}

/* ------------------------------------------------------------------ queues */

/** GET /queue/queues — today's queues at the caller's facility. */
export interface QueueSummary {
  id: string;
  department_id: string;
  doctor_user_id: string;
  doctor_name: string | null;
  room_id: string | null;
  room_number: string | null;
  display_label: string | null;
  service_date: string;
  is_open: boolean;
  waiting_count: number;
  now_serving: string | null;
}

export interface QueueOpeningOption {
  roster_id: string;
  staff_user_id: string;
  staff_name: string;
  department_id: string;
  department_name: string;
  room_id: string | null;
  room_number: string | null;
  shift: string;
}

export interface QueueOpeningOptions {
  service_date: string;
  items: QueueOpeningOption[];
}

export interface QueueCreate {
  department_id: string;
  doctor_user_id: string;
  room_id: string | null;
  display_label: string | null;
  service_date: string;
}

export interface QueueCreated extends QueueCreate {
  id: string;
  is_open: boolean;
}

export interface QueueTokenCreate {
  queue_id: string;
  visit_id: string;
  priority?: string;
}

export interface QueueToken {
  id: string;
  queue_id: string;
  visit_id: string | null;
  sequence: number;
  token_display: string;
  status: string;
  priority: string;
  created_at: string;
  called_at: string | null;
  completed_at: string | null;
}

export interface QueueTokenListItem extends QueueToken {
  doctor_name: string;
  room_number: string | null;
  patient_name: string | null;
  patient_identifier: string | null;
}

export interface TokenPriorityUpdate {
  priority: "senior_citizen" | "pregnant" | "follow_up_recall";
  reason: string;
}

export interface QueueTokenList {
  waiting_count: number;
  now_serving: string | null;
  items: QueueTokenListItem[];
}
