import { PatientMovementProps } from "./PatientMovement.types";
import { useLocale } from "@/lib/i18n";

function resolveWardName(
  wardId: string | null,
  wards?: { id: string; name: string }[]
): string {
  if (!wardId) return "-";
  return wards?.find((w) => w.id === wardId)?.name ?? wardId;
}

function resolveBedNumber(
  bedId: string | null,
  beds?: { bed_id: string; bed_number: string }[]
): string {
  if (!bedId) return "-";
  return beds?.find((b) => b.bed_id === bedId)?.bed_number ?? bedId;
}

export default function PatientMovement({
  admissionId,
  records,
  wards,
  beds,
}: PatientMovementProps) {
  const { t } = useLocale();
  if (!admissionId) {
    return (
      <div className="surface-card p-6">
        <p className="text-sm text-muted-foreground">{t("nurse.ui.selectAPatientToViewMovement")}</p>
      </div>
    );
  }

  if (records.length === 0) {
    return (
      <div className="surface-card p-6">
        <p className="text-sm text-muted-foreground">{t("nurse.ui.noMovementRecordsAvailable")}</p>
      </div>
    );
  }

  return (
    <section className="surface-card overflow-hidden">
      <div className="border-b border-border p-6">
        <h2 className="text-xl font-semibold">{t("nurse.ui.patientMovement")}</h2>
        <p className="mt-1 text-sm text-muted-foreground">{t("nurse.ui.wardBedTransferHistoryForThe")}</p>
      </div>

      <div className="overflow-x-auto">
        <table className="min-w-full">
          <thead className="bg-muted">
            <tr>
              <th className="px-4 py-3 text-left text-sm font-semibold">{t("common.ui.time")}</th>
              <th className="px-4 py-3 text-left text-sm font-semibold">{t("lab.mis.from")}</th>
              <th className="px-4 py-3 text-left text-sm font-semibold">{t("lab.mis.to")}</th>
              <th className="px-4 py-3 text-left text-sm font-semibold">{t("inventory.adjustment.reason")}</th>
              <th className="px-4 py-3 text-left text-sm font-semibold">{t("nurse.ui.movedBy")}</th>
            </tr>
          </thead>

          <tbody>
            {records.map((record) => (
              <tr key={record.id} className="border-t border-border">
                <td className="px-4 py-4" suppressHydrationWarning>
                  {new Date(record.moved_at).toLocaleString()}
                </td>

                <td className="px-4 py-4">
                  {resolveWardName(record.from_ward_id, wards)} /{" "}
                  {resolveBedNumber(record.from_bed_id, beds)}
                </td>

                <td className="px-4 py-4 font-medium">
                  {resolveWardName(record.to_ward_id, wards)} /{" "}
                  {resolveBedNumber(record.to_bed_id, beds)}
                </td>

                <td className="px-4 py-4 text-muted-foreground">
                  {record.reason ?? "-"}
                </td>

                <td className="px-4 py-4 text-muted-foreground">
                  {record.moved_by}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}