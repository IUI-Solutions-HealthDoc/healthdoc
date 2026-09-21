import assert from "node:assert/strict";
import test from "node:test";
import { compile, componentHarness, content, flush, nodes } from "./helpers/component-harness.mjs";

const source = (file) => new URL(`../src/features/receptionist/${file}`, import.meta.url);
const sample = (id, name) => ({
  id, token_number: "123", patient_id: "patient-" + id, patient_name: name,
  patient_uhid: "TEST-" + id, abha_address: "synthetic@sbx", abha_number: null,
  mobile: null, status: "active", counter: null, checked_in_at: null,
  created_at: "2026-09-20T00:00:00Z", expires_at: "2099-01-01T00:00:00Z",
  profile_data: { full_name: name, gender: "unknown" },
});
const props = { isOpen: true, onClose() {} };
const button = (tree, text) => nodes(tree).find((node) => node.type === "button" && content(node).includes(text));
function harness(api) {
  return componentHarness((runtime) => compile(source("ScanShareDeskModal.tsx"), {
    ...runtime, "react-dom": { createPortal: (element) => element },
    "react-qr-code": { default: "QRCode" }, "@/components/ui/Modal": { Modal: "Modal" },
    "@/lib/api": { formatDateTime: (value) => value },
    "./StartVisit": { StartVisit: "StartVisit" }, "./api": api,
  }).ScanShareDeskModal);
}

test("Scan-and-Share adapter accepts the real array and writes the exact counter contract", async () => {
  let result = [sample("ticket-A", "Synthetic A")];
  const calls = [];
  const api = compile(source("api.ts"), {
    "@/lib/api": { api: async (...args) => { calls.push(args); return result; } },
    "./patientValidation": {},
  });
  assert.deepEqual(await api.listScanShareTickets("all"), result);
  assert.match(calls[0][0], /status=all&limit=100$/);
  await api.checkInScanShareTicket("immutable-ticket-id", " Desk A ");
  assert.equal(calls[1][0], "/abdm/scan-share/tickets/immutable-ticket-id/check-in");
  assert.deepEqual(JSON.parse(calls[1][1].body), { counter: "Desk A" });
  result = { items: [] };
  await assert.rejects(api.listScanShareTickets(), /Unexpected reception-ticket response/);
});

test("real ticket fields render, check-in reads back the same ticket, and visit handoff uses its bound patient", async () => {
  const ticket = sample("ticket-A", "Synthetic A"), calls = [];
  let persisted = ticket;
  const h = harness({
    listScanShareTickets: async () => [ticket],
    checkInScanShareTicket: async (...args) => {
      calls.push(args);
      persisted = { ...ticket, status: "checked_in", counter: args[1], checked_in_at: "2026-09-20T01:00:00Z" };
      return { ticket_id: ticket.id };
    },
    getScanShareTicket: async (id) => { assert.equal(id, ticket.id); return persisted; },
  });
  h.render(props); h.effects(); await flush();
  let tree = h.render(props);
  button(tree, "Synthetic A").props.onClick();
  tree = h.render(props);
  assert.match(content(tree), /unknown\s+·\s+Not provided/); // Never fabricate Jan 1 from missing DOB.
  const counter = nodes(tree).find((n) => n.type === "input" && n.props.maxLength === 50);
  counter.props.onChange({ target: { value: "Real Desk" } });
  tree = h.render(props);
  const form = nodes(tree).find((n) => n.type === "form" && content(n).includes("Actual reception counter"));
  await form.props.onSubmit({ preventDefault() {} });
  tree = h.render(props);
  assert.deepEqual(calls, [["ticket-A", "Real Desk"]]);
  const visit = nodes(tree).find((n) => n.type === "StartVisit");
  assert.deepEqual(visit.props.patient, { id: "patient-ticket-A", full_name: "Synthetic A", uhid: "TEST-ticket-A", thid: null });
  assert.match(content(tree), /Reception check-in saved/);
  assert.doesNotMatch(content(tree), /NABH Accredited|ABDM Integrated|Fill Registration Form/);
});

test("late lookup cannot replace a newer selected patient, and reopening discards old state", async () => {
  let resolveLookup;
  const a = sample("A", "Synthetic A"), b = sample("B", "Synthetic B");
  const h = harness({
    listScanShareTickets: async () => [a, b],
    getScanShareTicket: () => new Promise((resolve) => { resolveLookup = resolve; }),
  });
  h.render(props); h.effects(); await flush();
  let tree = h.render(props);
  nodes(tree).find((n) => n.type === "input").props.onChange({ target: { value: "123" } });
  tree = h.render(props);
  const lookup = nodes(tree).find((n) => n.type === "form").props.onSubmit({ preventDefault() {} });
  button(tree, "Synthetic B").props.onClick();
  resolveLookup(a); await lookup;
  tree = h.render(props);
  const selected = nodes(tree).find((n) => n.props["aria-label"] === "Selected reception ticket");
  assert.match(content(selected), /Synthetic B/);
  assert.doesNotMatch(content(selected), /Synthetic A/);
  h.render({ ...props, isOpen: false }); h.effects();
  tree = h.render(props);
  assert.match(content(tree), /Select and confirm the patient/);
});

test("a late old-filter list cannot replace the current queue", async () => {
  const requests = [];
  const h = harness({ listScanShareTickets: (filter) => new Promise((resolve) => requests.push({ filter, resolve })) });
  let tree = h.render(props); h.effects();
  nodes(tree).find((n) => n.type === "select").props.onChange({ target: { value: "checked_in" } });
  h.render(props); h.effects();
  requests[1].resolve([sample("B", "Current Queue")]); await flush();
  requests[0].resolve([sample("A", "Stale Queue")]); await flush();
  tree = h.render(props);
  assert.match(content(tree), /Current Queue/);
  assert.doesNotMatch(content(tree), /Stale Queue/);
});

test("expired tickets cannot check in and read-back failure never claims confirmation", async () => {
  const expired = { ...sample("A", "Expired Patient"), expires_at: "2000-01-01T00:00:00Z" };
  const h = harness({ listScanShareTickets: async () => [expired] });
  h.render(props); h.effects(); await flush();
  let tree = h.render(props);
  button(tree, "Expired Patient").props.onClick();
  tree = h.render(props);
  assert.match(content(tree), /This ticket has expired/);
  assert.equal(button(tree, "Check in"), undefined);

  const active = sample("B", "Active Patient");
  const h2 = harness({
    listScanShareTickets: async () => [active],
    checkInScanShareTicket: async () => ({ ticket_id: active.id }),
    getScanShareTicket: async () => { throw new Error("Network failure"); },
  });
  h2.render(props); h2.effects(); await flush();
  tree = h2.render(props); button(tree, "Active Patient").props.onClick();
  tree = h2.render(props);
  nodes(tree).find((n) => n.type === "input" && n.props.maxLength === 50).props.onChange({ target: { value: "A" } });
  tree = h2.render(props);
  await nodes(tree).find((n) => n.type === "form" && content(n).includes("Actual reception counter")).props.onSubmit({ preventDefault() {} });
  tree = h2.render(props);
  assert.match(content(tree), /was saved but read-back failed/);
  assert.equal(nodes(tree).find((n) => n.type === "StartVisit"), undefined);
});
