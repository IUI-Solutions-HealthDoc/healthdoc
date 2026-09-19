import { MEDICATION_STATUS_STYLES } from "./constants";
import { MedicationRecord, MEDICATION_STATUS_LABELS } from "./EMARTable.types";
import { formatDateTime } from "@/lib/api";

type MedicationRowProps = {
  medication: MedicationRecord;
  onCorrect?: (medication: MedicationRecord) => void;
  onAcknowledge?: (medication: MedicationRecord) => void;
};

function formatTime(iso: string | null): string {
  if (!iso) return "—";
  return formatDateTime(iso);
}

export default function MedicationRow({
  medication,
  onCorrect,
  onAcknowledge,
}: MedicationRowProps) {
  const notGiven = medication.status !== "given";
  const priority = medication.priority?.toLowerCase();

  return (
    <tr className="border-b border-border last:border-none align-top hover:bg-muted/20 transition-colors">
      <td className="px-4 py-3">
        <div className="flex items-center gap-1.5 flex-wrap">
          {priority === "stat" && (
            <span className="rounded bg-danger px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wider text-white">
              STAT
            </span>
          )}
          {priority === "urgent" && (
            <span className="rounded bg-amber-500 px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wider text-white">
              URGENT
            </span>
          )}
          {priority === "prn" && (
            <span className="rounded bg-purple-600 px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wider text-white">
              PRN
            </span>
          )}
          <span className="font-medium text-foreground">
            {medication.medicine_name ?? (
              <span className="text-muted-foreground italic">Unknown medication</span>
            )}
          </span>
        </div>

        {medication.is_correction && (
          <div className="mt-1 rounded bg-blue-500/10 border border-blue-500/30 px-2 py-1 text-xs text-blue-700 dark:text-blue-300">
            <span className="font-semibold">Correction:</span> {medication.correction_reason ?? "Dose record corrected"}
          </div>
        )}
      </td>

      <td className="px-4 py-3">
        <div>{medication.dosage ?? "—"}</div>
        {medication.dose_given && medication.dose_given !== medication.dosage && (
          <div className="text-xs text-muted-foreground">Given: {medication.dose_given}</div>
        )}
      </td>

      <td className="px-4 py-3">{medication.route ?? "—"}</td>

      <td className="px-4 py-3">{formatTime(medication.scheduled_at)}</td>

      <td className="px-4 py-3">{formatTime(medication.administered_at)}</td>

      <td className="px-4 py-3">
        <span
          className={`rounded-full px-2 py-1 text-xs font-medium ${MEDICATION_STATUS_STYLES[medication.status]}`}
        >
          {MEDICATION_STATUS_LABELS[medication.status]}
        </span>

        {/* The reason is the point of a held or refused dose — the API
            requires one, so never show the status without it. */}
        {notGiven && medication.reason && (
          <p className="mt-1 max-w-xs text-xs text-muted-foreground">
            {medication.reason}
          </p>
        )}

        {medication.requires_acknowledgement && (
          <div className="mt-1.5">
            {medication.acknowledged_at ? (
              <span className="inline-flex items-center gap-1 rounded bg-emerald-500/10 px-1.5 py-0.5 text-[10px] font-medium text-emerald-700 dark:text-emerald-300 border border-emerald-500/30">
                ✓ Dr Ack
              </span>
            ) : (
              <div className="flex items-center gap-1.5 flex-wrap">
                <span className="inline-flex items-center rounded bg-amber-500/10 px-1.5 py-0.5 text-[10px] font-medium text-amber-700 dark:text-amber-300 border border-amber-500/30">
                  Ack Required
                </span>
                {onAcknowledge && (
                  <button
                    type="button"
                    onClick={() => onAcknowledge(medication)}
                    className="rounded bg-amber-600 px-1.5 py-0.5 text-[10px] font-medium text-white hover:bg-amber-700"
                  >
                    Acknowledge
                  </button>
                )}
              </div>
            )}
          </div>
        )}
      </td>

      <td className="px-4 py-3 text-right">
        {onCorrect && (
          <button
            type="button"
            onClick={() => onCorrect(medication)}
            className="text-xs text-primary underline hover:text-primary/80"
          >
            Correct dose
          </button>
        )}
      </td>
    </tr>
  );
}

