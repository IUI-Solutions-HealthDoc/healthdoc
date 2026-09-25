import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import { compile, componentHarness, content, flush, nodes } from "./helpers/component-harness.mjs";
import { clinicalWrite } from "./helpers/clinical-write.mjs";

const source = (path) => new URL(`../src/${path}`, import.meta.url);
const returnUrls = compile(source("lib/auth/return-url.ts"), {});

test("return URL preserves the exact internal route and rejects redirect attacks", () => {
  const origin = "https://healthdoc.test";
  for (const path of ["/doctor/queue?status=waiting#patient", "/patients?q=Jane%20Doe"])
    assert.equal(returnUrls.safeReturnUrl(path, origin), origin + path);
  for (const bad of ["https://evil.test/", "//evil.test/", "/\\evil.test", "/%5cevil.test", "/%0a/evil", "javascript:alert(1)", "https://healthdoc.test@evil.test/", "/auth/realms/other"])
    assert.equal(returnUrls.safeReturnUrl(bad, origin), origin + "/", bad);
});

test("native PKCE login uses current origin and does not save tokens or collect passwords", async () => {
  const oldWindow = globalThis.window;
  const oldUrl = process.env.NEXT_PUBLIC_KEYCLOAK_URL;
  process.env.NEXT_PUBLIC_KEYCLOAK_URL = "https://old-lan.invalid/auth";
  globalThis.window = { location: { origin: "https://healthdoc.test", href: "https://healthdoc.test/doctor/queue?q=1#row" } };
  const calls = [];
  class Keycloak {
    constructor(config) { calls.push(["config", config]); }
    async init(options) { calls.push(["init", options]); return false; }
    async login(options) { calls.push(["login", options]); }
  }
  try {
    const roles = ["SUPERADMIN", "ADMIN", "HOD", "SUPERVISOR", "AUDITOR", "DOCTOR", "NURSE", "PHARMACIST", "LAB_TECH", "RADIOLOGY_TECH", "EMERGENCY", "BILLING", "RECEPTIONIST", "PATIENT"];
    const auth = compile(source("lib/auth/keycloak.ts"), {
      "keycloak-js": { default: Keycloak }, "@/config/roles": { ROLES: Object.fromEntries(roles.map((r) => [r, r.toLowerCase()])) },
      "@/lib/api": { setAccessToken() {} }, "@/lib/auth/return-url": returnUrls,
    });
    await auth.loginWithKeycloak();
    assert.equal(calls[0][1].url, "https://healthdoc.test/auth");
    assert.equal(calls[1][1].pkceMethod, "S256");
    assert.equal(calls[2][1].redirectUri, window.location.href);
    await auth.loginWithKeycloak("https://evil.test");
    assert.equal(calls[3][1].redirectUri, "https://healthdoc.test/");
    const authText = readFileSync(source("lib/auth/keycloak.ts"), "utf8");
    assert.doesNotMatch(authText, /grant_type:\s*["']password|[Ss]torage\.setItem|loginWithCredentials/);
    const realm = JSON.parse(readFileSync(new URL("../../infra/keycloak/realm-healthdoc.json", import.meta.url)));
    assert.equal(realm.clients.find((c) => c.clientId === "healthdoc-frontend").directAccessGrantsEnabled, false);
  } finally {
    globalThis.window = oldWindow;
    if (oldUrl === undefined) delete process.env.NEXT_PUBLIC_KEYCLOAK_URL; else process.env.NEXT_PUBLIC_KEYCLOAK_URL = oldUrl;
  }
});

for (const kind of ["list", "detail"]) test(`consent ${kind}: retained callbacks cannot fetch or overwrite another patient`, async () => {
  let current;
  const requests = [];
  const api = (...args) => new Promise((resolve) => requests.push({ args, resolve }));
  const h = componentHarness((runtime) => {
    const mod = compile(source(`features/consent/hooks/${kind === "list" ? "useConsentRecords" : "useConsentDetail"}.ts`), {
      ...runtime, "../api": kind === "list" ? { listConsentRecords: api } : { getConsent: api },
    });
    return function Probe({ patient }) {
      current = kind === "list" ? mod.useConsentRecords({ patient_id: patient, status: "all" }) : mod.useConsentDetail(patient, "same-consent-id");
      return null;
    };
  });
  const render = (patient) => { h.render({ patient }); h.render({ patient }); };
  render("A"); h.effects();
  const oldRefresh = current.refresh;
  render("B"); h.effects();
  const count = requests.length;
  void oldRefresh();
  assert.equal(requests.length, count, "stale callback must not start a new request");
  requests.at(-1).resolve(kind === "list" ? [{ patient_id: "B" }] : { patient_id: "B" });
  requests[0].resolve(kind === "list" ? [{ patient_id: "A" }] : { patient_id: "A" });
  await flush(); render("B");
  assert.equal(kind === "list" ? current.rows[0].patient_id : current.record.patient_id, "B");
  render("A"); h.effects();
  const countAgain = requests.length;
  void oldRefresh();
  assert.equal(requests.length, countAgain, "A → B → A must still reject original callbacks");
});

test("record immunization submits backend code, timestamp and required expiry", async () => {
  const calls = [];
  const catalogue = [{ id: "vac-id", code: "BCG", name: "BCG", standard_doses: 1, route: "intradermal", site: "arm" }];
  const h = componentHarness((runtime) => compile(source("features/immunization/components/RecordImmunizationModal.tsx"), {
    ...runtime, "lucide-react": { AlertCircle: "icon", CheckCircle: "icon", X: "icon" },
    "@/lib/useClinicalWrite": clinicalWrite(runtime),
    "../api": { recordImmunization: async (payload) => calls.push(payload) },
  }).RecordImmunizationModal);
  const props = { isOpen: true, patientId: "patient-A", catalogue, onClose() {}, onSuccess() {} };
  let tree = h.render(props);
  const batch = nodes(tree).find((n) => n.type === "input" && n.props.placeholder?.startsWith("e.g. BATCH"));
  batch.props.onChange({ target: { value: "BATCH-REAL" } });
  nodes(tree).find((n) => n.type === "input" && n.props.type === "date").props.onChange({ target: { value: "2099-01-01" } });
  tree = h.render(props);
  await nodes(tree).find((n) => n.type === "form").props.onSubmit({ preventDefault() {} });
  assert.equal(calls.length, 1);
  assert.equal(calls[0].vaccine_code, "BCG");
  assert.ok(calls[0].administered_at.endsWith("Z"));
  assert.equal(calls[0].expiry_date, "2099-01-01");
  assert.equal(calls[0].vaccine_id, undefined);
  assert.equal(calls[0].administered_date, undefined);
});

test("consent access history discards late records and stale refresh callbacks", async () => {
  let current;
  const requests = [];
  const h = componentHarness((runtime) => {
    const mod = compile(source("features/consent/hooks/useDataAccessLogs.ts"), {
      ...runtime, "../api": { listDataAccessLogs: (args) => new Promise((resolve) => requests.push({ args, resolve })) },
    });
    return function Probe({ id }) { current = mod.useDataAccessLogs(id); return null; };
  });
  h.render({ id: "A" }); h.effects();
  const oldRefresh = current.refresh;
  requests[0].resolve([{ consent_id: "A" }]); await flush(); h.render({ id: "A" });
  assert.equal(current.rows[0].consent_id, "A");
  h.render({ id: "B" });
  assert.deepEqual(current.rows, [], "previous rows must be hidden before effects run");
  h.effects();
  const count = requests.length;
  void oldRefresh();
  assert.equal(requests.length, count);
  requests.at(-1).resolve([{ consent_id: "B" }]); await flush(); h.render({ id: "B" });
  assert.equal(current.rows[0].consent_id, "B");
});

test("late consent creation cannot select the previous patient's record in the new workspace", () => {
  const selections = [];
  const h = componentHarness((runtime) => compile(source("features/consent/components/ConsentDashboard.tsx"), {
    ...runtime, "@mui/material/Box": { default: "Box" }, "@mui/material/Typography": { default: "Typography" },
    "@/features/receptionist/PatientSearch": { PatientSearch: "PatientSearch" }, "@/styles/theme": { meridian: {} },
    "../hooks/useConsentRecords": { useConsentRecords: () => ({ rows: [], filters: {}, refresh() {} }) },
    "../hooks/useConsentDetail": { useConsentDetail: (patient, selected) => { selections.push([patient, selected]); return {}; } },
    "./ConsentListPanel": { ConsentListPanel: "ConsentListPanel" },
    "./ConsentRecordDetail": { ConsentRecordDetail: "ConsentRecordDetail" },
    "./ConsentGrantForm": { ConsentGrantForm: "ConsentGrantForm" },
  }).ConsentDashboard);
  let tree = h.render({});
  nodes(tree).find((n) => n.type === "PatientSearch").props.onSelect({ id: "A", full_name: "Test A" });
  tree = h.render({});
  const oldCreated = nodes(tree).find((n) => n.type === "ConsentGrantForm").props.onCreated;
  nodes(tree).find((n) => n.type === "button" && content(n).includes("change patient")).props.onClick();
  tree = h.render({});
  nodes(tree).find((n) => n.type === "PatientSearch").props.onSelect({ id: "B", full_name: "Test B" });
  tree = h.render({});
  oldCreated({ id: "consent-A", patient_id: "A" });
  tree = h.render({});
  assert.deepEqual(selections.at(-1), ["B", null]);
  nodes(tree).find((n) => n.type === "ConsentGrantForm").props.onCreated({ id: "consent-B", patient_id: "B" });
  tree = h.render({});
  assert.deepEqual(selections.at(-1), ["B", "consent-B"]);
  assert.equal(nodes(tree).find((n) => n.type === "ConsentRecordDetail").key, "B:consent-B");
});

test("late consent transition cannot show success in a different patient's workspace", async () => {
  let resolve;
  const toasts = [], updates = [];
  const h = componentHarness((runtime) => {
    const mui = Object.fromEntries(["Box", "Button", "Dialog", "DialogActions", "DialogContent", "DialogTitle", "Stack", "TextField", "Typography"].map((name) => [`@mui/material/${name}`, { default: name }]));
    const { ConsentRecordDetail } = compile(source("features/consent/components/ConsentRecordDetail.tsx"), {
      ...runtime, ...mui, "@/styles/theme": { meridian: {} },
      "@/components/ui/StatusChip": { StatusChip: "StatusChip" },
      "@/components/ui/toast": { toast: { success: (...args) => toasts.push(args), error: (...args) => toasts.push(args) } },
      "../api/consent": { transitionConsentStatus: () => new Promise((r) => { resolve = r; }) },
      "@/lib/i18n": {
        useLocale: () => ({
          t: (key) => (key === "consent.approve" ? "Approve" : key),
        }),
      },
      "../i18nLabels": {
        consentStatusLabel: () => "status",
        consentChannelLabel: () => "channel",
        consentPurposeLabel: () => "purpose",
      },
      "../lib/formatters": { formatDate: () => "", formatDateTime: () => "" },
      "./ConsentAccessHistory": { ConsentAccessHistory: "ConsentAccessHistory" },
    });
    return function Probe({ patient }) {
      return { type: ConsentRecordDetail, key: patient, props: {
        record: { id: `consent-${patient}`, patient_id: patient, status: "requested" },
        onRecordUpdated: (record) => updates.push(record),
      } };
    };
  });
  const tree = h.render({ patient: "A" }); h.effects();
  nodes(tree).find((n) => n.type === "Button" && content(n) === "Approve").props.onClick();
  h.render({ patient: "B" }); h.effects();
  resolve({ id: "consent-A", patient_id: "A", status: "granted" }); await flush();
  assert.deepEqual(toasts, []);
  assert.deepEqual(updates, []);
});

test("blood crossmatch uses the backend unit_id and clears compatibility when the recipient changes", async () => {
  const writes = [];
  const h = componentHarness((runtime) => compile(source("features/blood-bank/components/BloodCrossmatchModal.tsx"), {
    "@/lib/useClinicalWrite": clinicalWrite(runtime),
    ...runtime,
    "lucide-react": Object.fromEntries(["AlertTriangle", "CheckCircle2", "Droplet", "FileCheck", "Search", "TestTube", "X"].map((key) => [key, "icon"])),
    "../api": { crossmatchBlood: async (payload) => { writes.push(payload); return { id: "xm-A", ...payload }; } },
    "../types": { formatBloodGroup: () => "O+" },
    "@/lib/api": { api: async () => ({ items: [{ id: "A", uhid: "UHID-A", full_name: "Test A" }] }) },
  }).BloodCrossmatchModal);
  const props = { isOpen: true, unit: { id: "unit-A", blood_group: "O+" }, onClose() {}, onSuccess() {} };
  let tree = h.render(props); h.effects();
  nodes(tree).find((n) => n.type === "input" && n.props.placeholder?.startsWith("Enter exact")).props.onChange({ target: { value: "UHID-A" } });
  tree = h.render(props);
  await nodes(tree).find((n) => n.props["aria-label"] === "Search patient").props.onClick();
  tree = h.render(props);
  assert.equal(nodes(tree).find((n) => n.type === "button" && n.props.type === "submit").props.disabled, true);
  nodes(tree).find((n) => n.type === "input" && n.props.value === "compatible").props.onChange();
  tree = h.render(props);
  nodes(tree).find((n) => n.type === "button" && content(n) === "Change").props.onClick();
  tree = h.render(props);
  assert.equal(nodes(tree).find((n) => n.type === "input" && n.props.value === "compatible").props.checked, false);
  await nodes(tree).find((n) => n.props["aria-label"] === "Search patient").props.onClick();
  tree = h.render(props);
  nodes(tree).find((n) => n.type === "input" && n.props.value === "compatible").props.onChange();
  tree = h.render(props);
  await nodes(tree).find((n) => n.type === "form").props.onSubmit({ preventDefault() {} });
  assert.equal(writes.length, 1);
  assert.deepEqual(writes[0], { patient_id: "A", unit_id: "unit-A", compatibility_result: "compatible", notes: null });
});

test("lost blood issue response retries the same issue, without another crossmatch", async () => {
  const matches = [], issues = [];
  const h = componentHarness((runtime) => compile(source("features/blood-bank/components/BloodCrossmatchModal.tsx"), {
    ...runtime, "@/lib/useClinicalWrite": clinicalWrite(runtime),
    "lucide-react": Object.fromEntries(["AlertTriangle", "CheckCircle2", "Droplet", "FileCheck", "Search", "TestTube", "X"].map((key) => [key, "icon"])),
    "../types": { formatBloodGroup: () => "O+" },
    "@/lib/api": { api: async () => ({ items: [{ id: "A", uhid: "UHID-A", full_name: "Test A" }] }) },
    "../api": {
      crossmatchBlood: async (payload, key) => { matches.push({ payload, key }); return { id: "xm-A", ...payload }; },
      issueBloodUnit: async (payload, key) => {
        issues.push({ payload, key });
        if (issues.length === 1) throw new TypeError("Lost issue response");
        return { id: "xm-A", issued_at: "2026-09-21T00:00:00Z" };
      },
    },
  }).BloodCrossmatchModal);
  const props = { isOpen: true, unit: { id: "unit-A", blood_group: "O+" }, onClose() {}, onSuccess() {} };
  let tree = h.render(props); h.effects();
  nodes(tree).find((n) => n.type === "input" && n.props.placeholder?.startsWith("Enter exact")).props.onChange({ target: { value: "UHID-A" } });
  tree = h.render(props);
  await nodes(tree).find((n) => n.props["aria-label"] === "Search patient").props.onClick();
  tree = h.render(props);
  nodes(tree).find((n) => n.props.value === "compatible").props.onChange();
  tree = h.render(props);
  nodes(tree).find((n) => n.props.type === "checkbox").props.onChange({ target: { checked: true } });
  tree = h.render(props);
  await nodes(tree).find((n) => n.type === "form").props.onSubmit({ preventDefault() {} });
  tree = h.render(props);
  assert.match(content(tree), /Retry unchanged save/);
  assert.equal(nodes(tree).find((n) => n.type === "fieldset").props.disabled, true);
  assert.equal(nodes(tree).find((n) => n.props["aria-label"] === "Close crossmatch").props.disabled, true);
  await nodes(tree).find((n) => n.type === "form").props.onSubmit({ preventDefault() {} });
  assert.equal(matches.length, 1);
  assert.equal(issues.length, 2);
  assert.deepEqual(issues[0], issues[1]);
  assert.match(content(h.render(props)), /Blood Unit Issued Successfully/);
});
