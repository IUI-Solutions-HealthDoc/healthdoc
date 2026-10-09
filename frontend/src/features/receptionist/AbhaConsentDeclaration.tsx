"use client";

import type { AbhaDeclaration, ConsentLanguage } from "./types";

/** Required statements ticked; the statement the method excludes left unticked. */
export function declarationAccepted(declaration: AbhaDeclaration | null, ticks: Record<string, boolean>): boolean {
  return declaration !== null && declaration.statements.every((statement) =>
    statement.required === true ? ticks[statement.id] === true
      : statement.required === false ? ticks[statement.id] !== true
        : true);
}

/** NHA's published starting ticks: statements 1, 3, 4 and 5; confirmations empty. */
export function defaultTicks(declaration: AbhaDeclaration): Record<string, boolean> {
  return Object.fromEntries(declaration.statements.map((statement) => [statement.id, statement.ticked]));
}

/** NHA's published ABHA consent (M1 CRT_ABHA_102/302), exactly as the server rendered it. */
export function AbhaConsentDeclaration({ declaration, error, ticks, onTick, language, onLanguage }: {
  declaration: AbhaDeclaration | null;
  error: string | null;
  ticks: Record<string, boolean>;
  onTick: (id: string, checked: boolean) => void;
  language: ConsentLanguage;
  /** A new language reloads the text; the ticks start again from NHA's defaults. */
  onLanguage: (language: ConsentLanguage) => void;
}) {
  return (
    <fieldset className="space-y-2 rounded-md border border-border p-3 text-sm">
      <legend className="px-1 font-medium">ABHA consent</legend>
      <div className="flex gap-2" role="group" aria-label="Consent language">
        {([["en", "English"], ["hi", "हिन्दी"]] as const).map(([code, label]) => (
          <button key={code} type="button" aria-pressed={language === code} onClick={() => onLanguage(code)}
            className={`rounded-md border px-2 py-1 text-xs ${language === code ? "border-primary bg-primary/10" : "border-border"}`}>{label}</button>
        ))}
      </div>
      {declaration?.notice ? <p className="text-xs text-muted-foreground">{declaration.notice}</p> : null}
      {error ? (
        <p role="alert" className="text-danger">{error}</p>
      ) : !declaration ? (
        <p role="status" className="text-muted-foreground">Loading the ABHA consent…</p>
      ) : (
        <>
          <p>{declaration.intro}</p>
          {declaration.statements.map((statement) => (
            <label key={statement.id} className={`flex items-start gap-2 ${statement.id === "health_worker" || statement.id === "beneficiary" ? "pl-6" : ""}`}>
              <input
                type="checkbox"
                name={statement.id}
                checked={ticks[statement.id] === true}
                onChange={(event) => onTick(statement.id, event.target.checked)}
              />
              <span>{statement.text}</span>
            </label>
          ))}
          {ticks.other_document && declaration.method !== "document" ? (
            <p role="alert" className="text-warning">The patient chose a document other than Aadhaar. No Aadhaar request is sent while this is ticked.</p>
          ) : null}
          {ticks.aadhaar_sharing && declaration.method === "document" ? (
            <p role="alert" className="text-warning">The patient chose Aadhaar. A driving-licence enrolment shares no Aadhaar; untick it or use an Aadhaar flow.</p>
          ) : null}
          <p className="text-xs text-muted-foreground">NHA advises showing this consent to the patient on a screen facing them.</p>
        </>
      )}
    </fieldset>
  );
}
