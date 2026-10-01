import { newIdempotencyKey } from "@/lib/api";
import {
  isValidUhidInput,
  normaliseIndianMobileInput,
  normaliseUhidInput,
} from "@/features/receptionist/patientValidation";
import type { PatientSearchRequest } from "@/features/receptionist/types";
import type { AppointmentCheckInResult, AppointmentStatus } from "./types";

export type PatientQuery =
  | { kind: "mobile"; criteria: PatientSearchRequest }
  | { kind: "identifier"; criteria: PatientSearchRequest }
  | { kind: "invalid" };

/**
 * Route the desk's single search box by what was typed. Trying UHID first and
 * falling back to mobile sent a phone number to the UHID search and a UHID to
 * the mobile search, and a failure of either read as "no patient found".
 */
export function classifyPatientQuery(term: string): PatientQuery {
  const raw = term.trim();
  if (!raw) return { kind: "invalid" };
  const mobile = normaliseIndianMobileInput(raw);
  if (mobile) return { kind: "mobile", criteria: { mobile } };
  if (isValidUhidInput(raw)) return { kind: "identifier", criteria: { uhid: normaliseUhidInput(raw) } };
  return { kind: "invalid" };
}

export interface AppointmentActions {
  confirm: boolean;
  checkIn: boolean;
  reschedule: boolean;
  cancel: boolean;
}

/** Mirrors the server's transition table; the server still enforces it. */
export function appointmentActions(status: AppointmentStatus): AppointmentActions {
  const open = status === "booked" || status === "confirmed";
  return {
    confirm: status === "booked",
    checkIn: open,
    reschedule: open,
    cancel: open,
  };
}

const KNOWN_TOKEN_REASONS = new Set([
  "no_open_queue",
  "multiple_open_queues",
  "visit_type_not_queued",
  "no_token_at_check_in",
]);

export type CheckInOutcome =
  | { tone: "success"; visit: string; token: string }
  | { tone: "warning"; visit: string; reason: string; known: boolean };

/** A check-in without a token must not be reported as "Token: Issued". */
export function checkInOutcome(result: AppointmentCheckInResult): CheckInOutcome {
  if (result.token_status === "issued" && result.token_display) {
    return { tone: "success", visit: result.visit_number, token: result.token_display };
  }
  const reason = result.token_not_issued_reason ?? "no_token_at_check_in";
  return {
    tone: "warning",
    visit: result.visit_number,
    reason,
    known: KNOWN_TOKEN_REASONS.has(reason),
  };
}

/**
 * One idempotency key per action scope while its payload is unchanged, so a
 * retry after a timeout replays the first write instead of making a second
 * booking. A changed payload is a new write and gets a new key; a confirmed
 * success releases the scope.
 */
export function createRetryKeys() {
  const attempts = new Map<string, { key: string; body: string }>();
  return {
    keyFor(scope: string, payload: unknown): string {
      const body = JSON.stringify(payload);
      const current = attempts.get(scope);
      if (current && current.body === body) return current.key;
      const next = { key: newIdempotencyKey(), body };
      attempts.set(scope, next);
      return next.key;
    },
    settle(scope: string): void {
      attempts.delete(scope);
    },
  };
}
