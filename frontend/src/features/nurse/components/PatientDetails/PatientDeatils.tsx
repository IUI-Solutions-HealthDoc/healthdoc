import { PatientAvatar } from "@/components/ui";
import { PatientDetailsProps } from "./PatientDetails.types";
import { useLocale, translate } from "@/lib/i18n";

const SEX_LABELS: Record<string, string> = {
  get male() { return translate("mch.sex.male"); },
  get female() { return translate("mch.sex.female"); },
  other: "Other",
  get unknown() { return translate("mch.sex.unknown"); },
};

export default function PatientDetails({ patient }: PatientDetailsProps) {
  const { t } = useLocale();
  if (!patient) {
    return (
      <div className="surface-card p-6">
        <p className="text-sm text-muted-foreground">{t("nurse.ui.selectABedToViewPatient")}</p>
      </div>
    );
  }

  return (
    <section className="surface-card p-6">
      <div className="mb-6 flex flex-wrap items-center justify-between gap-4">
        <div className="flex items-center gap-4">
          <PatientAvatar
            patientId={patient.id}
            photoFileId={patient.photo_file_id}
            name={patient.full_name}
            size="lg"
          />
          <div>
            <h2 className="text-xl font-semibold">{patient.full_name}</h2>
            <p className="font-mono text-sm text-muted-foreground">
              {patient.uhid ?? patient.thid ?? t("receptionist.noUhid")}
            </p>
          </div>
        </div>
        {patient.guardian_name ? (
          <div className="text-right text-xs text-muted-foreground">
            <span className="font-medium text-foreground">{t("nurse.ui.guardian")}</span> {patient.guardian_name}
            {patient.guardian_relationship ? ` (${patient.guardian_relationship})` : ""}
          </div>
        ) : null}
      </div>

      <div className="grid gap-6 md:grid-cols-3">
        <div>
          <p className="text-sm text-muted-foreground">{t("common.ui.patientName")}</p>
          <p className="mt-1 font-semibold">{patient.full_name}</p>
        </div>

        <div>
          <p className="text-sm text-muted-foreground">{t("field.uhid")}</p>
          <p className="mt-1 font-semibold">{patient.uhid ?? "-"}</p>
        </div>

        <div>
          <p className="text-sm text-muted-foreground">{t("field.age")}</p>
          <p className="mt-1 font-semibold">
            {patient.age_years != null ? `${patient.age_years} Years` : "-"}
          </p>
        </div>

        <div>
          <p className="text-sm text-muted-foreground">{t("field.sex")}</p>
          <p className="mt-1 font-semibold">
            {SEX_LABELS[patient.sex] ?? patient.sex}
          </p>
        </div>

        <div>
          <p className="text-sm text-muted-foreground">{t("nurse.ui.diagnosis")}</p>
          <p className="mt-1 font-semibold">
            {patient.diagnosis_text ?? "-"}
          </p>
        </div>

        <div>
          <p className="text-sm text-muted-foreground">{t("nurse.ui.admissionDate")}</p>
          <p className="mt-1 font-semibold" suppressHydrationWarning>
            {patient.admitted_at
              ? new Date(patient.admitted_at).toLocaleDateString()
              : "-"}
          </p>
        </div>

        <div>
          <p className="text-sm text-muted-foreground">{t("monitor.ward")}</p>
          <p className="mt-1 font-semibold">{patient.ward_name ?? "-"}</p>
        </div>

        <div>
          <p className="text-sm text-muted-foreground">{t("ipd.bed")}</p>
          <p className="mt-1 font-semibold">{patient.bed_number ?? "-"}</p>
        </div>
      </div>
    </section>
  );
}
