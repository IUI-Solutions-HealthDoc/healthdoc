import { PatientAvatar } from "@/components/ui";
import { PatientDetailsProps } from "./PatientDetails.types";

const SEX_LABELS: Record<string, string> = {
  male: "Male",
  female: "Female",
  other: "Other",
  unknown: "Unknown",
};

export default function PatientDetails({ patient }: PatientDetailsProps) {
  if (!patient) {
    return (
      <div className="surface-card p-6">
        <p className="text-sm text-muted-foreground">
          Select a bed to view patient details.
        </p>
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
              {patient.uhid ?? patient.thid ?? "No UHID"}
            </p>
          </div>
        </div>
        {patient.guardian_name ? (
          <div className="text-right text-xs text-muted-foreground">
            <span className="font-medium text-foreground">Guardian:</span> {patient.guardian_name}
            {patient.guardian_relationship ? ` (${patient.guardian_relationship})` : ""}
          </div>
        ) : null}
      </div>

      <div className="grid gap-6 md:grid-cols-3">
        <div>
          <p className="text-sm text-muted-foreground">Patient Name</p>
          <p className="mt-1 font-semibold">{patient.full_name}</p>
        </div>

        <div>
          <p className="text-sm text-muted-foreground">UHID</p>
          <p className="mt-1 font-semibold">{patient.uhid ?? "-"}</p>
        </div>

        <div>
          <p className="text-sm text-muted-foreground">Age</p>
          <p className="mt-1 font-semibold">
            {patient.age_years != null ? `${patient.age_years} Years` : "-"}
          </p>
        </div>

        <div>
          <p className="text-sm text-muted-foreground">Sex</p>
          <p className="mt-1 font-semibold">
            {SEX_LABELS[patient.sex] ?? patient.sex}
          </p>
        </div>

        <div>
          <p className="text-sm text-muted-foreground">Diagnosis</p>
          <p className="mt-1 font-semibold">
            {patient.diagnosis_text ?? "-"}
          </p>
        </div>

        <div>
          <p className="text-sm text-muted-foreground">Admission Date</p>
          <p className="mt-1 font-semibold" suppressHydrationWarning>
            {patient.admitted_at
              ? new Date(patient.admitted_at).toLocaleDateString()
              : "-"}
          </p>
        </div>

        <div>
          <p className="text-sm text-muted-foreground">Ward</p>
          <p className="mt-1 font-semibold">{patient.ward_name ?? "-"}</p>
        </div>

        <div>
          <p className="text-sm text-muted-foreground">Bed</p>
          <p className="mt-1 font-semibold">{patient.bed_number ?? "-"}</p>
        </div>
      </div>
    </section>
  );
}
