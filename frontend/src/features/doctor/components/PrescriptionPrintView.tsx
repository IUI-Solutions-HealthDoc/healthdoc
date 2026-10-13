"use client";

import { frequencyLabel, formatAgeSex, routeLabel } from "../lib/formatters";
import type { DraftPrescriptionItem, EncounterContext } from "../types";

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
          <div>UHID: {context.uhid} · Token: {context.token_display}</div>
        </div>
        <div style={{ textAlign: "right" }}>
          <div>{context.provider_name}</div>
          <div>Visit: {context.visit_number ?? "—"}</div>
          <div>{now}</div>
        </div>
      </div>

      {allergyNames.length > 0 && (
        <div style={{ fontSize: 12, marginTop: 8 }}>
          <strong>Known allergies:</strong> {allergyNames.join(", ")}
        </div>
      )}

      <table>
        <thead>
          <tr>
            <th style={{ width: 24 }}>#</th>
            <th>Medicine</th>
            <th>Dosage</th>
            <th>Frequency</th>
            <th>Route</th>
            <th>Duration</th>
            <th>Instructions</th>
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
              <td>{it.duration_days ? `${it.duration_days} days` : "As needed"}</td>
              <td>{it.instructions || "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>

      {notes && (
        <div style={{ fontSize: 12, marginTop: 12 }}>
          <strong>Notes:</strong> {notes}
        </div>
      )}

      <div style={{ marginTop: 48, textAlign: "right", fontSize: 12 }}>
        <div>_____________________________</div>
        <div>{context.provider_name}</div>
      </div>
    </div>
  );
}
