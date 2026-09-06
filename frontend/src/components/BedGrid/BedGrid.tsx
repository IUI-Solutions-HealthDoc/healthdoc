import { BED_STATUS_STYLES } from "./constants";
import { Bed, BED_STATUS_LABELS, type BedStatus } from "./BedGrid.types";

type BedGridProps = {
  beds: Bed[];
  /** Highlights the selected bed. Used as a bed picker in the admission and transfer forms. */
  selectedBedId?: string | null;
  onBedClick?: (bed: Bed) => void;
};

export default function BedGrid({
  beds,
  selectedBedId = null,
  onBedClick,
}: BedGridProps) {
  if (beds.length === 0) {
    return (
      <div className="surface-card p-6">
        <p className="text-sm text-muted-foreground">
          No beds available.
        </p>
      </div>
    );
  }

  const selectable = typeof onBedClick === "function";

  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
      {beds.map((bed) => {
        const isSelected = bed.bed_id === selectedBedId;
        // An occupant is proof of occupancy; `status` is a mirror that can
        // drift from it. Printing "Vacant" in the corner of a card that names
        // the patient lying in the bed is never the more useful of the two.
        const effectiveStatus: BedStatus =
          bed.occupant !== null && bed.status !== "occupied" ? "occupied" : bed.status;

        return (
          <div
            key={bed.bed_id}
            // A button when it does something, a div when it does not — a card
            // that looks clickable and is not is worse than a plain one.
            role={selectable ? "button" : undefined}
            tabIndex={selectable ? 0 : undefined}
            aria-pressed={selectable ? isSelected : undefined}
            onClick={selectable ? () => onBedClick?.(bed) : undefined}
            onKeyDown={
              selectable
                ? (event) => {
                    if (event.key === "Enter" || event.key === " ") {
                      event.preventDefault();
                      onBedClick?.(bed);
                    }
                  }
                : undefined
            }
            className={[
              "surface-card p-4 transition-all",
              selectable
                ? "cursor-pointer hover:-translate-y-0.5 hover:shadow-md focus:outline-none focus-visible:ring-2 focus-visible:ring-offset-2"
                : "",
              isSelected ? "ring-2 ring-primary" : "",
            ]
              .filter(Boolean)
              .join(" ")}
          >
            <div className="flex items-center justify-between">
              <h3 className="text-base font-semibold">{bed.bed_number}</h3>

              <span
                className={`rounded-full px-2 py-1 text-xs font-medium ${BED_STATUS_STYLES[effectiveStatus]}`}
              >
                {BED_STATUS_LABELS[effectiveStatus]}
              </span>
            </div>

            <div className="mt-3">
              <p className="text-sm text-muted-foreground">Patient</p>

              <p className="mt-1 text-sm font-medium">
                {bed.occupant?.patient_name ?? "Not assigned"}
              </p>

              {/* UHID, not the name alone: two patients on a ward share a name
                  more often than anyone expects, and the bed board is where a
                  drug is about to be given to one of them. */}
              {bed.occupant?.uhid && (
                <p className="text-xs text-muted-foreground">
                  {bed.occupant.uhid}
                </p>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}
