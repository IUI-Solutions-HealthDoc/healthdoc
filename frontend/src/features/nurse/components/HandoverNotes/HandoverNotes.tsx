import { HandoverNotesProps } from "./HandoverNotes.types";
import { useLocale, translate } from "@/lib/i18n";

const SHIFT_LABELS: Record<string, string> = {
  get morning() { return translate("patientPortal.appt.morning"); },
  get evening() { return translate("hod.roster.shift.evening"); },
  get night() { return translate("hod.roster.shift.night"); },
};

/** Prefer the resolved name; the id prefix is the fallback when a user row has
 *  since been removed. A truncated UUID tells a nurse nothing about who took
 *  the patient. */
function actorLabel(name?: string | null, id?: string): string {
  if (name) return name;
  return id ? id.slice(0, 8) : translate("mch.sex.unknown");
}

export default function HandoverNotes({
  admissionId,
  notes,
}: HandoverNotesProps) {
  const { t } = useLocale();
  if (!admissionId) {
    return (
      <div className="surface-card p-6">
        <p className="text-sm text-muted-foreground">{t("nurse.ui.selectAPatientToViewHandover")}</p>
      </div>
    );
  }

  if (notes.length === 0) {
    return (
      <div className="surface-card p-6">
        <p className="text-sm text-muted-foreground">{t("nurse.ui.handoverNotesAreNotAvailableFor")}</p>
      </div>
    );
  }

  return (
    <section className="surface-card p-6">
      <div className="mb-6">
        <h2 className="text-xl font-semibold">{t("nurse.ui.handoverNotes")}</h2>
        <p className="text-sm text-muted-foreground">{t("nurse.ui.shiftHandoverInformationForTheSelected")}</p>
      </div>

      <div className="space-y-5">
        {notes.map((note) => (
          <div key={note.id} className="rounded-xl border border-border p-5">
            <div className="flex items-center justify-between">
              <h3 className="font-semibold">{t("nurse.ui.shiftShift", { shift: SHIFT_LABELS[note.shift] ?? note.shift })}</h3>

              {note.created_at && (
                <span className="text-xs text-muted-foreground" suppressHydrationWarning>
                  {new Date(note.created_at).toLocaleString()}
                </span>
              )}
            </div>

            <div className="mt-4 grid gap-4 md:grid-cols-2">
              <div>
                <p className="text-xs text-muted-foreground">{t("nurse.ui.handedOverBy")}</p>
                <p className="text-sm">{actorLabel(note.created_by_name, note.created_by)}</p>
              </div>

              <div>
                <p className="text-xs text-muted-foreground">{t("nurse.ui.handedOverTo")}</p>
                <p className="text-sm">{actorLabel(note.handed_over_to_name, note.handed_over_to)}</p>
              </div>
            </div>

            <div className="mt-5 space-y-3">
              <div className="rounded-lg bg-muted p-4">
                <p className="text-xs text-muted-foreground">{t("nurse.handoverSituation")}</p>
                <p className="mt-1 text-sm leading-6">{note.situation ?? "—"}</p>
              </div>

              <div className="rounded-lg bg-muted p-4">
                <p className="text-xs text-muted-foreground">{t("nurse.handoverBackground")}</p>
                <p className="mt-1 text-sm leading-6">{note.background ?? "—"}</p>
              </div>

              <div className="rounded-lg bg-muted p-4">
                <p className="text-xs text-muted-foreground">{t("doctor.soapAssessment")}</p>
                <p className="mt-1 text-sm leading-6">{note.assessment ?? "—"}</p>
              </div>

              <div className="rounded-lg bg-muted p-4">
                <p className="text-xs text-muted-foreground">{t("nurse.handoverRecommendation")}</p>
                <p className="mt-1 text-sm leading-6">{note.recommendation ?? "—"}</p>
              </div>
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}
