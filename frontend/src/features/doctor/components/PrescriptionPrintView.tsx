"use client";

import { frequencyLabel, formatAgeSex, routeLabel } from "../lib/formatters";
import type { DraftPrescriptionItem, EncounterContext } from "../types";
import { useLocale } from "@/lib/i18n";

export interface PrescriptionPrintViewProps {
  context: EncounterContext;
  items: DraftPrescriptionItem[];
  notes?: string;
  /** Active allergy substance names for the printed Rx header. */
  allergyNames?: string[];
  facilityName: string;
}

/**
 * Hidden by default; visible only in @media print (see prescription-print.css).
 * Rendered plain HTML so the printed Rx is clean B/W, not the app chrome.
 */
export function PrescriptionPrintView({ context, items, notes, allergyNames = [], facilityName }: PrescriptionPrintViewProps) {
  const { t } = useLocale();
  const now = new Date().toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });

  return (
    <div className="rx-print" aria-hidden="true">
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
        <div>
          <div style={{ fontSize: 18, fontWeight: 800 }}>{facilityName}</div>
          <div style={{ fontSize: 12 }}>{context.department}</div>
        </div>
        <div style={{ fontSize: 28, fontWeight: 800 }}>℞</div>
      </div>

      <hr style={{ margin: "10px 0", border: "none", borderTop: "1px solid #000" }} />

      <div style={{ display: "flex", justifyContent: "space-between", fontSize: 12 }}>
        <div>
          <div><strong>{context.patient_name}</strong></div>
          <div>{formatAgeSex(context.age_years, context.sex)}</div>
          <div>{t("doctor.ui.uhidUhidTokenTokenDisplay", { uhid: context.uhid, token_display: context.token_display })}</div>
        </div>
        <div style={{ textAlign: "right" }}>
          <div>{context.provider_name}</div>
          <div>{t("doctor.ui.visitValue", { value: context.visit_number ?? "—" })}</div>
          <div>{now}</div>
        </div>
      </div>

      {allergyNames.length > 0 && (
        <div style={{ fontSize: 12, marginTop: 8 }}>
          <strong>{t("doctor.ui.knownAllergies")}</strong> {allergyNames.join(", ")}
        </div>
      )}

      <table>
        <thead>
          <tr>
            <th style={{ width: 24 }}>#</th>
            <th>{t("pharmacy.expiry.col.medicine")}</th>
            <th>{t("common.ui.dosage")}</th>
            <th>{t("doctor.ui.frequency")}</th>
            <th>{t("immunization.col.route")}</th>
            <th>{t("doctor.ui.duration")}</th>
            <th>{t("doctor.ui.instructions")}</th>
          </tr>
        </thead>
        <tbody>
          {items.map((it, i) => (
            <tr key={it.tempId}>
              <td>{i + 1}</td>
              <td>
                {it.medicine_name}
                {it.strength ? ` (${it.strength})` : ""}
              </td>
              <td>{it.dosage || "—"}</td>
              <td>{frequencyLabel(it.frequency)}</td>
              <td>{routeLabel(it.route)}</td>
              <td>{it.duration_days ? `${it.duration_days} days` : t("doctor.ui.asNeeded")}</td>
              <td>{it.instructions || "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>

      {notes && (
        <div style={{ fontSize: 12, marginTop: 12 }}>
          <strong>{t("pharmacy.dispense.notes")}</strong> {notes}
        </div>
      )}

      <div style={{ marginTop: 48, textAlign: "right", fontSize: 12 }}>
        <div>_____________________________</div>
        <div>{context.provider_name}</div>
      </div>
    </div>
  );
}
