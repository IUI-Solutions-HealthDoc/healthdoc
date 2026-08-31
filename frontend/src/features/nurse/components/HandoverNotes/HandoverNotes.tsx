import { HandoverNotesProps } from "./HandoverNotes.types";

const SHIFT_LABELS: Record<string, string> = {
  morning: "Morning",
  evening: "Evening",
  night: "Night",
};

function actorId(value?: string): string {
  return value ? value.slice(0, 8) : "Unknown";
}

export default function HandoverNotes({
  admissionId,
  notes,
}: HandoverNotesProps) {
  if (!admissionId) {
    return (
      <div className="surface-card p-6">
        <p className="text-sm text-muted-foreground">
          Select a patient to view handover notes.
        </p>
      </div>
    );
  }

  if (notes.length === 0) {
    return (
      <div className="surface-card p-6">
        <p className="text-sm text-muted-foreground">
          Handover notes are not available for this ward yet.
        </p>
      </div>
    );
  }

  return (
    <section className="surface-card p-6">
      <div className="mb-6">
        <h2 className="text-xl font-semibold">Handover Notes</h2>
        <p className="text-sm text-muted-foreground">
          Shift handover information for the selected patient.
        </p>
      </div>

      <div className="space-y-5">
        {notes.map((note) => (
          <div key={note.id} className="rounded-xl border border-border p-5">
            <div className="flex items-center justify-between">
              <h3 className="font-semibold">
                {SHIFT_LABELS[note.shift] ?? note.shift} Shift
              </h3>

              {note.created_at && (
                <span className="text-xs text-muted-foreground" suppressHydrationWarning>
                  {new Date(note.created_at).toLocaleString()}
                </span>
              )}
            </div>

            <div className="mt-4 grid gap-4 md:grid-cols-2">
              <div>
                <p className="text-xs text-muted-foreground">Handed Over By</p>
                <p className="font-mono text-sm">{actorId(note.created_by)}</p>
              </div>

              <div>
                <p className="text-xs text-muted-foreground">Handed Over To</p>
                <p className="font-mono text-sm">{actorId(note.handed_over_to)}</p>
              </div>
            </div>

            <div className="mt-5 space-y-3">
              <div className="rounded-lg bg-muted p-4">
                <p className="text-xs text-muted-foreground">Situation</p>
                <p className="mt-1 text-sm leading-6">{note.situation ?? "—"}</p>
              </div>

              <div className="rounded-lg bg-muted p-4">
                <p className="text-xs text-muted-foreground">Background</p>
                <p className="mt-1 text-sm leading-6">{note.background ?? "—"}</p>
              </div>

              <div className="rounded-lg bg-muted p-4">
                <p className="text-xs text-muted-foreground">Assessment</p>
                <p className="mt-1 text-sm leading-6">{note.assessment ?? "—"}</p>
              </div>

              <div className="rounded-lg bg-muted p-4">
                <p className="text-xs text-muted-foreground">Recommendation</p>
                <p className="mt-1 text-sm leading-6">{note.recommendation ?? "—"}</p>
              </div>
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}
