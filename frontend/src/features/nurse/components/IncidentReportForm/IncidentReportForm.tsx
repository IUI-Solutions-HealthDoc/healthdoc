import { useState } from "react";
import { useLocale } from "@/lib/i18n";
import { reportIncident } from "@/features/nurse/api/nursing";
import { INCIDENT_TYPES, SEVERITIES } from "./constants";
import { IncidentType, IncidentSeverity, IncidentReportFormProps } from "./IncidentReportForm.types";

export default function IncidentReportForm({
  patientId,
  admissionId,
  departmentId,
  wardId,
  onSuccess,
}: IncidentReportFormProps) {
  const { t } = useLocale();
  const [incidentType, setIncidentType] = useState<IncidentType | "">("");
  const [severity, setSeverity] = useState<IncidentSeverity | "">("");
  const [occurredAt, setOccurredAt] = useState("");
  const [description, setDescription] = useState("");
  const [immediateAction, setImmediateAction] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setSuccess(false);

    if (!incidentType || !severity || !occurredAt || !description.trim() || !immediateAction.trim()) {
      setError("Please fill all required fields.");
      return;
    }

    setSubmitting(true);
    try {
      await reportIncident({
        incident_type: incidentType,
        severity,
        occurred_at: new Date(occurredAt).toISOString(),
        description: description.trim(),
        immediate_action: immediateAction.trim(),
        patient_id: patientId ?? null,
        admission_id: admissionId ?? null,
        department_id: departmentId ?? null,
        ward_id: wardId ?? null,
      });
      setSuccess(true);
      setIncidentType("");
      setSeverity("");
      setOccurredAt("");
      setDescription("");
      setImmediateAction("");
      onSuccess?.();
    } catch (err) {
      setError(err instanceof Error ? err.message : t("nurse.incident.errFile"));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <form onSubmit={handleSubmit} className="surface-card space-y-4 p-6">
      <h2 className="text-lg font-semibold">Report a Clinical Incident</h2>
      <p className="text-sm text-muted-foreground">
        NABH DHS register (`clinical_incidents`). Patient is optional — staff/equipment
        events may have none. Severity is harm that reached the patient; near-miss is a type.
      </p>

      {success && (
        <p className="rounded bg-green-50 p-2 text-sm text-green-700">
          Incident reported successfully.
        </p>
      )}
      {error && (
        <p className="rounded bg-red-50 p-2 text-sm text-red-700">{error}</p>
      )}

      <div>
        <label className="mb-1 block text-sm font-medium">Incident Type *</label>
        <select
          value={incidentType}
          onChange={(e) => setIncidentType(e.target.value as IncidentType)}
          className="w-full rounded border border-border p-2 text-sm"
          required
        >
          <option value="">Select type</option>
          {INCIDENT_TYPES.map((t) => (
            <option key={t.value} value={t.value}>{t.label}</option>
          ))}
        </select>
      </div>

      <div>
        <label className="mb-1 block text-sm font-medium">Severity *</label>
        <select
          value={severity}
          onChange={(e) => setSeverity(e.target.value as IncidentSeverity)}
          className="w-full rounded border border-border p-2 text-sm"
          required
        >
          <option value="">Select severity</option>
          {SEVERITIES.map((s) => (
            <option key={s.value} value={s.value}>{s.label}</option>
          ))}
        </select>
      </div>

      <div>
        <label className="mb-1 block text-sm font-medium">Occurred At *</label>
        <input
          type="datetime-local"
          value={occurredAt}
          onChange={(e) => setOccurredAt(e.target.value)}
          className="w-full rounded border border-border p-2 text-sm"
          required
        />
      </div>

      <div>
        <label className="mb-1 block text-sm font-medium">Description *</label>
        <textarea
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          rows={3}
          className="w-full rounded border border-border p-2 text-sm"
          required
        />
      </div>

      <div>
        <label className="mb-1 block text-sm font-medium">Immediate Action Taken *</label>
        <textarea
          value={immediateAction}
          onChange={(e) => setImmediateAction(e.target.value)}
          rows={3}
          className="w-full rounded border border-border p-2 text-sm"
          required
        />
      </div>

      <button
        type="submit"
        disabled={submitting}
        className="rounded bg-primary px-4 py-2 text-sm font-medium text-primary-foreground disabled:opacity-50"
      >
        {submitting ? t("nurse.incident.submitting") : t("nurse.incident.submitReport")}
      </button>
    </form>
  );
}
