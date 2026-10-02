"use client";

import type { AbhaDeclaration } from "./types";

/** Required statements ticked and "a document other than Aadhaar" not. */
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
export function AbhaConsentDeclaration({ declaration, error, ticks, onTick }: {
  declaration: AbhaDeclaration | null;
  error: string | null;
  ticks: Record<string, boolean>;
  onTick: (id: string, checked: boolean) => void;
}) {
  return (
    <fieldset className="space-y-2 rounded-md border border-border p-3 text-sm">
      <legend className="px-1 font-medium">ABHA consent</legend>
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
          {ticks.other_document ? (
            <p role="alert" className="text-warning">The patient chose a document other than Aadhaar. No Aadhaar request is sent while this is ticked.</p>
          ) : null}
          <p className="text-xs text-muted-foreground">NHA advises showing this consent to the patient on a screen facing them.</p>
        </>
      )}
    </fieldset>
  );
}
