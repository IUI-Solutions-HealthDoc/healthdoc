import { AdmissionStatusProps } from "./AdmissionStatus.types";
import { useLocale, translate } from "@/lib/i18n";

const STATUS_LABELS: Record<string, string> = {
  get admitted() { return translate("monitor.kind.admitted"); },
  get transferred() { return translate("nurse.msg.transferred"); },
  get discharged() { return translate("monitor.kind.discharged"); },
  dama: "DAMA",
  get deceased() { return translate("nurse.msg.deceased"); },
  get absconded() { return translate("nurse.msg.absconded"); },
};

const STATUS_STYLES: Record<string, string> = {
  admitted: "bg-info-muted text-info",
  transferred: "bg-warning-muted text-warning",
  discharged: "bg-success-muted text-success",
  dama: "bg-danger-muted text-danger",
  deceased: "bg-danger-muted text-danger",
  absconded: "bg-danger-muted text-danger",
};

export default function AdmissionStatus({
  admissionId,
  record,
}: AdmissionStatusProps) {
  const { t } = useLocale();
  if (!admissionId) {
    return (
      <div className="surface-card p-6">
        <p className="text-sm text-muted-foreground">{t("nurse.ui.selectAPatientToViewAdmission")}</p>
      </div>
    );
  }

  if (!record) {
    return (
      <div className="surface-card p-6">
        <p className="text-sm text-muted-foreground">{t("nurse.ui.noAdmissionStatusAvailable")}</p>
      </div>
    );
  }

  return (
    <section className="surface-card p-6">
      <h2 className="text-xl font-semibold">{t("nurse.ui.admissionStatus")}</h2>
      <p className="mt-1 text-sm text-muted-foreground">{t("nurse.ui.currentAdmissionWorkflowStatus")}</p>

      <div className="mt-4 flex items-center justify-between rounded-lg border border-border p-4">
        <span
          className={`rounded-full px-3 py-1 text-sm font-medium ${STATUS_STYLES[record.status]}`}
        >
          {STATUS_LABELS[record.status]}
        </span>

        {record.updated_at && (
          <span className="text-xs text-muted-foreground" suppressHydrationWarning>
            {new Date(record.updated_at).toLocaleString()}
          </span>
        )}
      </div>
    </section>
  );
}
