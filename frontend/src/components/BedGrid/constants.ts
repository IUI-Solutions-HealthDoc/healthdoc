import { BedStatus } from "./BedGrid.types";

export const BED_STATUS_STYLES: Record<BedStatus, string> = {
  occupied: "bg-danger-muted text-danger",
  vacant: "bg-success-muted text-success",
  reserved: "bg-info-muted text-info",
  // Out of service, not "being cleaned" — this bed is not about to free up.
  maintenance: "bg-warning-muted text-warning",
  // Vacated and waiting for housekeeping: frees up once the turnover is done.
  cleaning: "bg-info-muted text-info",
};
