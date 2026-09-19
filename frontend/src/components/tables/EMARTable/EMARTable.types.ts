/**
 * Mirrors `MedicationAdministrationOut` from
 * `GET /nursing/admissions/{admission_id}/medication-administrations`.
 *
 * The imported version had "Scheduled" | "Administered" | "Missed" | "Held".
 * Three things were wrong with that:
 *
 *  - `refused` had nowhere to go. The backend separates *held* (a clinical
 *    decision by staff — parameters out of range, procedure pending) from
 *    *refused* (the patient declined), and requires a reason for each, because
 *    an adverse-event review has to reconstruct which it was. Collapsing a
 *    refusal into "Missed" or "Held" states something that did not happen.
 *  - `Scheduled` and `Missed` do not exist server-side. A dose nobody has acted
 *    on is a prescription item with no administration row — an absence, not a
 *    status. Rendering it as one invites a row that claims a nurse recorded
 *    something.
 *  - Casing. The API sends lowercase.
 */
export type MedicationStatus = "given" | "held" | "refused";

export const MEDICATION_STATUS_LABELS: Record<MedicationStatus, string> = {
  given: "Given",
  held: "Held",
  refused: "Refused",
};

export interface MedicationRecord {
  id: string;
  prescription_item_id: string;
  admission_id: string;
  patient_id: string;

  /** Denormalised from prescription_items; null if the item is gone. */
  medicine_name: string | null;
  /** What was PRESCRIBED. */
  dosage: string | null;
  route: string | null;
  priority?: "routine" | "urgent" | "stat" | "prn" | string | null;

  scheduled_at: string | null;
  administered_at: string;
  status: MedicationStatus;

  /** What the nurse actually recorded giving — not always `dosage`. */
  dose_given: string | null;
  /** Required by the API for held and refused. Never render these without it. */
  reason: string | null;
  notes: string | null;

  /** Dose correction audit trail (HD-17) */
  correction_of_id?: string | null;
  is_correction?: boolean;
  correction_reason?: string | null;

  /** Urgency & clinician acknowledgement (HD-20) */
  requires_acknowledgement?: boolean;
  acknowledged_by?: string | null;
  acknowledged_at?: string | null;

  created_by: string;
  created_at: string;
}

