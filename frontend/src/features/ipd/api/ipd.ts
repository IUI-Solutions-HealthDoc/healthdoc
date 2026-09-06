import { api, newIdempotencyKey } from "@/lib/api";

import type { AddAdmissionSchema } from "@/features/ipd/components/AdmissionForm/validation";
import type { AddDischargeSchema } from "@/features/ipd/components/DischargeForm/validation";
import type { Ward } from "@/features/nurse/components/WardSelector/WardSelector.types";
import type { BedGridResponse } from "@/components/BedGrid/BedGrid.types";

export type AdmissionStatus =
  | "admitted"
  | "transferred"
  | "discharged"
  | "dama"
  | "deceased"
  | "absconded";

export interface Admission {
  id: string;
  visit_id: string;
  patient_id: string;
  ward_id: string;
  bed_id: string;
  admitted_at: string;
  reason?: string | null;
  status: AdmissionStatus;
}

export interface Discharge {
  id: string;
  admission_id: string;
  discharged_at: string;
  discharge_type: "discharged" | "dama" | "deceased" | "absconded" | "transferred";
  discharge_summary: string;
  follow_up_date?: string | null;
}

export interface Movement {
  id: string;
  admission_id: string;
  from_ward_id: string | null;
  from_bed_id: string | null;
  to_ward_id: string;
  to_bed_id: string;
  moved_at: string;
  reason: string | null;
}

export interface DischargeSummary {
  admission: Admission;
  discharge: Discharge | null;
  movements: Movement[];
}

export async function admitPatient(data: AddAdmissionSchema) {
  return api<Admission>("/admissions", {
    method: "POST",
    body: JSON.stringify(data),
    idempotencyKey: newIdempotencyKey(),
  });
}

export async function dischargePatient(data: AddDischargeSchema) {
  const { admission_id, follow_up_date, ...rest } = data;
  const payload = {
    ...rest,
    // Two mismatches, both fatal, both fixed here because this function
    // already owns the wire shape. `DischargeRequest.follow_up_date` is a
    // `date`, but the form collects it with a datetime-local input; and an
    // untouched optional date arrives as "", which is neither a date nor
    // absent. The server answered 422 to every discharge until this, and the
    // screen surfaced no reason.
    follow_up_date: follow_up_date ? follow_up_date.slice(0, 10) : undefined,
  };
  return api<Discharge>(`/admissions/${admission_id}/discharge`, {
    method: "POST",
    body: JSON.stringify(payload),
    idempotencyKey: newIdempotencyKey(),
  });
}

export async function getWards() {
  return api<Ward[]>("/wards", { method: "GET" });
}

export async function getBeds(wardId: string) {
  return api<BedGridResponse>(`/wards/${wardId}/beds`, { method: "GET" });
}

export async function getActiveAdmissions() {
  return api<Admission[]>("/admissions?status=admitted", { method: "GET" });
}

export async function getDischarges() {
  return api<Discharge[]>("/admissions/discharges", { method: "GET" });
}
