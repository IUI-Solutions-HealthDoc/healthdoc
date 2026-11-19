import { translate } from "@/lib/i18n";
/**
 * Mirrors `BedGridOut` from `GET /wards/{ward_id}/beds`.
 *
 * Field names are the wire's, snake_case, matching the per-feature types under
 * `src/features`. No mapping layer: a mapper is where a field quietly stops
 * being copied.
 *
 * The imported version used "Occupied" | "Vacant" | "Reserved" | "Cleaning".
 * The backend's BedStatus enum has no "Cleaning" — it has `maintenance`, which
 * is a bed out of service, not one being turned around. A nurse reading
 * "Cleaning" on a broken bed plans to admit into it in ten minutes.
 */
export type BedStatus = "vacant" | "occupied" | "reserved" | "maintenance";

export const BED_STATUS_LABELS: Record<BedStatus, string> = {
  get vacant() { return translate("common.msg.vacant"); },
  get occupied() { return translate("monitor.occupied"); },
  get reserved() { return translate("bloodBank.status.reserved"); },
  get maintenance() { return translate("admin.ui.outOfService"); },
};

export interface BedOccupant {
  admission_id: string;
  patient_id: string;
  patient_name: string | null;
  uhid: string | null;
  admitted_at: string;
}

export interface Bed {
  bed_id: string;
  bed_number: string;
  status: BedStatus;
  /** null when the bed is not occupied. */
  occupant: BedOccupant | null;

  /**
   * NOT sent per bed by the API — `GET /wards/{ward_id}/beds` is already scoped
   * to one ward and returns it once, at the top of the response.
   *
   * Attached client-side by `flattenBedGrids` when a screen holds beds from
   * several wards at once (a transfer has to offer a bed on another ward).
   * Optional so it cannot be mistaken for something the server vouched for.
   */
  ward_id?: string;
}

/**
 * Flatten several ward responses into one list, stamping each bed with the
 * ward it came from. The only supported way to get a cross-ward bed list.
 */
export function flattenBedGrids(responses: BedGridResponse[]): Bed[] {
  return responses.flatMap((response) =>
    response.items.map((bed) => ({ ...bed, ward_id: response.ward_id })),
  );
}

export interface BedGridResponse {
  ward_id: string;
  items: Bed[];
}
