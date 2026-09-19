import MedicationRow from "./MedicationRow";
import { MedicationRecord } from "./EMARTable.types";

type EMARTableProps = {
  medications: MedicationRecord[];
  onCorrect?: (medication: MedicationRecord) => void;
  onAcknowledge?: (medication: MedicationRecord) => void;
};

export default function EMARTable({
  medications,
  onCorrect,
  onAcknowledge,
}: EMARTableProps) {
  if (medications.length === 0) {
    return (
      <div className="surface-card p-6">
        <p className="text-sm text-muted-foreground">
          No medication records available.
        </p>
      </div>
    );
  }

  return (
    <div className="surface-card overflow-hidden">
      <div className="border-b border-border px-6 py-4">
        <h2 className="text-lg font-semibold">
          Medication Administration Record
        </h2>

        <p className="mt-1 text-sm text-muted-foreground">
          Scheduled and administered medications
        </p>
      </div>

      <div className="overflow-x-auto">
        <table className="min-w-full border-collapse">
          <thead className="bg-muted">
            <tr>
              <th className="px-4 py-3 text-left">
                Medication
              </th>

              <th className="px-4 py-3 text-left">
                Dosage
              </th>

              <th className="px-4 py-3 text-left">
                Route
              </th>

              <th className="px-4 py-3 text-left">
                Scheduled
              </th>

              {/* "Administered at", not "Administered by": the API returns
                  created_by as a user id, and a raw UUID in a clinical record
                  is worse than the column not being there. Resolving it to a
                  name needs a users lookup this endpoint does not do. */}
              <th className="px-4 py-3 text-left">
                Administered
              </th>

              <th className="px-4 py-3 text-left">
                Status
              </th>

              <th className="px-4 py-3 text-right">
                Actions
              </th>
            </tr>
          </thead>

          <tbody>
            {medications.map((medication) => (
              <MedicationRow
                key={medication.id}
                medication={medication}
                onCorrect={onCorrect}
                onAcknowledge={onAcknowledge}
              />
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}