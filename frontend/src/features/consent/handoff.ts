/**
 * The patient a desk screen sends to Consent ("Record consent" after a token).
 *
 * Held in module memory, which survives Next's client-side navigation and
 * nothing else: no URL (an identifier in a query string lands in history and
 * access logs) and no browser storage. A reload simply falls back to search.
 */
export interface ConsentHandoff {
  id: string;
  full_name: string;
}

let pending: ConsentHandoff | null = null;

export function handPatientToConsent(patient: ConsentHandoff): void {
  pending = { id: patient.id, full_name: patient.full_name };
}

/** Returns the handed-over patient once; later calls return null. */
export function takeConsentHandoff(): ConsentHandoff | null {
  const out = pending;
  pending = null;
  return out;
}
