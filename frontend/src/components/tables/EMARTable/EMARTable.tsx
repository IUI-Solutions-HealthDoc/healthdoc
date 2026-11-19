import MedicationRow from "./MedicationRow";
import { MedicationRecord } from "./EMARTable.types";
import { useLocale } from "@/lib/i18n";

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
  const { t } = useLocale();
  if (medications.length === 0) {
    return (
      <div className="surface-card p-6">
        <p className="text-sm text-muted-foreground">{t("common.ui.noMedicationRecordsAvailable")}</p>
      </div>
    );
  }

  return (
    <div className="surface-card overflow-hidden">
      <div className="border-b border-border px-6 py-4">
        <h2 className="text-lg font-semibold">{t("common.ui.medicationAdministrationRecord")}</h2>

        <p className="mt-1 text-sm text-muted-foreground">{t("common.ui.scheduledAndAdministeredMedications")}</p>
      </div>

      <div className="overflow-x-auto">
        <table className="min-w-full border-collapse">
          <thead className="bg-muted">
            <tr>
              <th className="px-4 py-3 text-left">{t("nurse.actionMedication")}</th>

              <th className="px-4 py-3 text-left">{t("common.ui.dosage")}</th>

              <th className="px-4 py-3 text-left">{t("immunization.col.route")}</th>

              <th className="px-4 py-3 text-left">{t("common.ui.scheduled")}</th>

              {/* "Administered at", not "Administered by": the API returns
                  created_by as a user id, and a raw UUID in a clinical record
                  is worse than the column not being there. Resolving it to a
                  name needs a users lookup this endpoint does not do. */}
              <th className="px-4 py-3 text-left">{t("common.ui.administered")}</th>

              <th className="px-4 py-3 text-left">{t("common.status")}</th>

              <th className="px-4 py-3 text-right">{t("common.actions")}</th>
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