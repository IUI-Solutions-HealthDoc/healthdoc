import VitalRow from "./VitalsRow";
import { VitalRecord } from "./VitalsTimeline.types";
import { useLocale } from "@/lib/i18n";

type VitalsTimelineProps = {
  records: VitalRecord[];
};

export default function VitalsTimeline({
  records,
}: VitalsTimelineProps) {
  const { t } = useLocale();
  if (records.length === 0) {
    return (
      <div className="surface-card p-6">
        <p className="text-sm text-muted-foreground">{t("common.ui.noVitalRecordsAvailable")}</p>
      </div>
    );
  }

  return (
    <div className="surface-card overflow-hidden">
      <div className="border-b border-border px-6 py-4">
        <h2 className="text-lg font-semibold">{t("common.ui.vitalsTimeline")}</h2>

        <p className="mt-1 text-sm text-muted-foreground">{t("common.ui.patientVitalRecordings")}</p>
      </div>

      <div className="overflow-x-auto">
        <table className="min-w-full border-collapse">
          <thead className="bg-muted">
            <tr>
              <th className="px-4 py-3 text-left">{t("common.ui.time")}</th>

              <th className="px-4 py-3 text-left">{t("common.ui.temp")}</th>

              <th className="px-4 py-3 text-left">{t("doctor.vitalPulse")}</th>

              <th className="px-4 py-3 text-left">{t("common.ui.rr")}</th>

              <th className="px-4 py-3 text-left">{t("mch.bp")}</th>

              <th className="px-4 py-3 text-left">{t("doctor.vitalSpo2")}</th>

              {/* Pain replaces "Recorded By": the API returns created_by as a
                  user id, and pain_score is a vital this chart was dropping. */}
              <th className="px-4 py-3 text-left">{t("common.ui.pain")}</th>
            </tr>
          </thead>

          <tbody>
            {records.map((record) => (
              <VitalRow
                key={record.id}
                record={record}
              />
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}