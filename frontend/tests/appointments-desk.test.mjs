import assert from "node:assert/strict";
import test from "node:test";

import { compile } from "./helpers/component-harness.mjs";

const { localToday } = compile(new URL("../src/lib/dates.ts", import.meta.url), {});

const validation = compile(
  new URL("../src/features/receptionist/patientValidation.ts", import.meta.url),
  {},
);
let keyCounter = 0;
const desk = compile(new URL("../src/features/appointments/deskLogic.ts", import.meta.url), {
  "@/lib/api": { newIdempotencyKey: () => `key-${++keyCounter}` },
  "@/features/receptionist/patientValidation": validation,
});

test("localToday is the facility's date, not the UTC date", () => {
  // 01:00 IST on 29 Sep is still 28 Sep in UTC.
  assert.equal(localToday(new Date("2026-09-28T19:30:00Z")), "2026-09-29");
  assert.equal(localToday(new Date("2026-09-28T18:29:00Z")), "2026-09-28");
  assert.equal(localToday(new Date("2026-09-28T19:30:00Z"), "UTC"), "2026-09-28");
});

test("patient search is routed by what was typed", () => {
  assert.deepEqual(desk.classifyPatientQuery("98765 43210"), {
    kind: "mobile",
    criteria: { mobile: "+919876543210" },
  });
  assert.deepEqual(desk.classifyPatientQuery("+91 9876543210"), {
    kind: "mobile",
    criteria: { mobile: "+919876543210" },
  });
  assert.deepEqual(desk.classifyPatientQuery(" in-rj-jpr001-2026-000001-7 "), {
    kind: "identifier",
    criteria: { uhid: "IN-RJ-JPR001-2026-000001-7" },
  });
  assert.deepEqual(desk.classifyPatientQuery("TH-JPR001-260928-0001"), {
    kind: "identifier",
    criteria: { uhid: "TH-JPR001-260928-0001" },
  });
  for (const junk of ["", "   ", "Asha", "12345", "5876543210"]) {
    assert.deepEqual(desk.classifyPatientQuery(junk), { kind: "invalid" }, junk);
  }
});

test("desk actions follow the server's transition table", () => {
  const all = { confirm: true, checkIn: true, reschedule: true, cancel: true };
  assert.deepEqual(desk.appointmentActions("booked"), all);
  assert.deepEqual(desk.appointmentActions("confirmed"), { ...all, confirm: false });
  const none = { confirm: false, checkIn: false, reschedule: false, cancel: false };
  for (const status of ["checked_in", "completed", "cancelled", "no_show", "rescheduled"]) {
    assert.deepEqual(desk.appointmentActions(status), none, status);
  }
});

test("a check-in without a token is a warning, never 'Token: Issued'", () => {
  const base = { appointment_id: "a", status: "checked_in", visit_id: "v", visit_number: "V-1" };
  assert.deepEqual(
    desk.checkInOutcome({ ...base, token_status: "issued", token_display: "GEN-004", token_id: "t" }),
    { tone: "success", visit: "V-1", token: "GEN-004" },
  );
  assert.deepEqual(
    desk.checkInOutcome({ ...base, token_status: "not_issued", token_not_issued_reason: "no_open_queue" }),
    { tone: "warning", visit: "V-1", reason: "no_open_queue", known: true },
  );
  assert.deepEqual(
    desk.checkInOutcome({ ...base, token_status: "not_issued", token_not_issued_reason: "queue_closed" }),
    { tone: "warning", visit: "V-1", reason: "queue_closed", known: false },
  );
  assert.equal(
    desk.checkInOutcome({ ...base, token_status: "issued", token_display: null }).tone,
    "warning",
    "an 'issued' status with nothing to show the patient is not a success",
  );
});

test("retry keys replay an unchanged action and renew only on change or success", () => {
  const keys = desk.createRetryKeys();
  const first = keys.keyFor("book", { slot: "09:00" });
  assert.equal(keys.keyFor("book", { slot: "09:00" }), first, "a retry after a timeout reuses the key");
  assert.notEqual(keys.keyFor("check-in:a", {}), first, "scopes do not share keys");
  const changed = keys.keyFor("book", { slot: "09:15" });
  assert.notEqual(changed, first, "an edited booking is a new write");
  keys.settle("book");
  assert.notEqual(keys.keyFor("book", { slot: "09:15" }), changed, "a confirmed success frees the scope");
});
