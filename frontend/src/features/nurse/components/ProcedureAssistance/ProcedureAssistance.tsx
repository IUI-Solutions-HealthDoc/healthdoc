import { ProcedureAssistanceProps, ProcedureSetting } from "./ProcedureAssistance.types";
import { useLocale, translate } from "@/lib/i18n";

const SETTING_LABELS: Record<ProcedureSetting, string> = {
  opd_minor: "OPD Minor Procedure",
  get bedside() { return translate("doctor.procedureSetting.bedside"); },
  get emergency() { return translate("role.emergency"); },
  get ot() { return translate("nurse.msg.operationTheatre"); },
};

export default function ProcedureAssistance({
  patientId,
  records,
}: ProcedureAssistanceProps) {
  const { t } = useLocale();
  if (!patientId) {
    return (
      <div className="surface-card p-6">
        <p className="text-sm text-muted-foreground">{t("nurse.ui.selectAPatientToViewProcedures")}</p>
      </div>
    );
  }

  if (records.length === 0) {
    return (
      <div className="surface-card p-6">
        <p className="text-sm text-muted-foreground">{t("nurse.ui.noProcedureRecordsAvailable")}</p>
      </div>
    );
  }

  return (
    <section className="surface-card overflow-hidden">
      <div className="border-b border-border p-6">
        <h2 className="text-xl font-semibold">{t("nurse.ui.procedureAssistance")}</h2>
        <p className="mt-1 text-sm text-muted-foreground">{t("nurse.ui.proceduresPerformedForThisPatientWith")}</p>
      </div>

      <div className="space-y-4 p-6">
        {records.map((record) => (
          <div key={record.id} className="rounded-xl border border-border p-5">
            <div className="flex items-center justify-between">
              <h3 className="font-semibold">{record.procedure_name}</h3>
              <span className="rounded-full bg-info-muted px-2 py-1 text-xs font-medium text-info">
                {SETTING_LABELS[record.setting]}
              </span>
            </div>

            {record.procedure_code && (
              <p className="mt-1 text-xs text-muted-foreground">
                {record.procedure_code}
                {record.code_system ? ` (${record.code_system})` : ""}
              </p>
            )}

            <div className="mt-4 grid gap-4 md:grid-cols-2">
              <div>
                <p className="text-xs text-muted-foreground">{t("nurse.ui.performedBy")}</p>
                <p className="font-medium">{record.performed_by}</p>
              </div>

              <div>
                <p className="text-xs text-muted-foreground">{t("nurse.ui.assistedByNurse")}</p>
                <p className="font-medium">{record.assisted_by ?? "-"}</p>
              </div>

              <div>
                <p className="text-xs text-muted-foreground">{t("nurse.ui.started")}</p>
                <p className="font-medium" suppressHydrationWarning>
                  {new Date(record.started_at).toLocaleString()}
                </p>
              </div>

              <div>
                <p className="text-xs text-muted-foreground">{t("nurse.ui.ended")}</p>
                <p className="font-medium" suppressHydrationWarning>
                  {record.ended_at ? new Date(record.ended_at).toLocaleString() : "-"}
                </p>
              </div>

              {record.setting === "ot" && record.ot_schedule_id && (
                <div>
                  <p className="text-xs text-muted-foreground">{t("nurse.ui.otScheduleId")}</p>
                  <p className="font-medium">{record.ot_schedule_id}</p>
                </div>
              )}
            </div>

            {record.outcome && (
              <div className="mt-4 rounded-lg bg-muted p-3">
                <p className="text-xs text-muted-foreground">{t("mch.outcome")}</p>
                <p className="mt-1 text-sm">{record.outcome}</p>
              </div>
            )}

            {record.complications && (
              <div className="mt-3 rounded-lg bg-danger-muted p-3">
                <p className="text-xs text-danger">{t("nurse.ui.complications")}</p>
                <p className="mt-1 text-sm text-danger">{record.complications}</p>
              </div>
            )}
          </div>
        ))}
      </div>
    </section>
  );
}
