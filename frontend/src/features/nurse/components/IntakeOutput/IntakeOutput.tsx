import { IntakeOutputProps, EntryType } from "./IntakeOutput.types";
import { useLocale } from "@/lib/i18n";

const ENTRY_TYPE_LABELS: Record<EntryType, string> = {
  intake_oral: "Oral Intake",
  intake_iv: "IV Intake",
  output_urine: "Urine Output",
  output_drain: "Drain Output",
  output_other: "Other Output",
};

function isIntake(entryType: EntryType): boolean {
  return entryType.startsWith("intake_");
}

export default function IntakeOutput({
  admissionId,
  records,
}: IntakeOutputProps) {
  const { t } = useLocale();
  if (!admissionId) {
    return (
      <div className="surface-card p-6">
        <p className="text-sm text-muted-foreground">{t("nurse.ui.selectAPatientToViewIntake")}</p>
      </div>
    );
  }

  if (records.length === 0) {
    return (
      <div className="surface-card p-6">
        <p className="text-sm text-muted-foreground">{t("nurse.ui.noIntakeOutputRecordsAvailable")}</p>
      </div>
    );
  }

  // UI-only aggregate — not a stored field. Each row is a single intake or
  // output entry (per schema), so totals are computed here for a quick summary.
  const totalIntake = records
    .filter((r) => isIntake(r.entry_type))
    .reduce((sum, r) => sum + r.volume_ml, 0);

  const totalOutput = records
    .filter((r) => !isIntake(r.entry_type))
    .reduce((sum, r) => sum + r.volume_ml, 0);

  return (
    <section className="surface-card overflow-hidden">
      <div className="border-b border-border p-6">
        <h2 className="text-xl font-semibold">{t("nurse.ui.intakeOutput")}</h2>
        <p className="mt-1 text-sm text-muted-foreground">{t("nurse.ui.fluidBalanceForTheSelectedPatient")}</p>

        <div className="mt-4 flex gap-6 text-sm">
          <span>{t("nurse.ui.totalIntake")}{" "}<span className="font-semibold">{t("nurse.ui.totalintakeMl", { totalIntake })}</span>
          </span>
          <span>{t("nurse.ui.totalOutput")}{" "}<span className="font-semibold">{t("nurse.ui.totaloutputMl", { totalOutput })}</span>
          </span>
          <span>{t("nurse.ui.netBalance")}{" "}
            <span className="font-semibold">{t("nurse.ui.totaloutputMl", { totalOutput: totalIntake - totalOutput })}</span>
          </span>
        </div>
      </div>

      <div className="overflow-x-auto">
        <table className="min-w-full">
          <thead className="bg-muted">
            <tr>
              <th className="px-4 py-3 text-left text-sm font-semibold">{t("common.ui.time")}</th>
              <th className="px-4 py-3 text-left text-sm font-semibold">{t("equipment.category")}</th>
              <th className="px-4 py-3 text-left text-sm font-semibold">{t("nurse.ui.volumeMl")}</th>
              <th className="px-4 py-3 text-left text-sm font-semibold">{t("mch.notes")}</th>
            </tr>
          </thead>

          <tbody>
            {records.map((record) => (
              <tr key={record.id} className="border-t border-border">
                <td className="px-4 py-4" suppressHydrationWarning>
                  {new Date(record.recorded_at).toLocaleString()}
                </td>

                <td className="px-4 py-4">
                  <span
                    className={
                      isIntake(record.entry_type)
                        ? "rounded-full bg-info-muted px-2 py-1 text-xs font-medium text-info"
                        : "rounded-full bg-warning-muted px-2 py-1 text-xs font-medium text-warning"
                    }
                  >
                    {ENTRY_TYPE_LABELS[record.entry_type]}
                  </span>
                </td>

                <td className="px-4 py-4 font-medium">{record.volume_ml}</td>

                <td className="px-4 py-4 text-muted-foreground">
                  {record.notes ?? "-"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
