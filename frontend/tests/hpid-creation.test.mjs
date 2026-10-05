import assert from "node:assert/strict";
import test from "node:test";
import { compile, componentHarness, content, flush, nodes } from "./helpers/component-harness.mjs";

/** HPID creation (ABDM M4 HPR-002 to 011): the Aadhaar is verified on NHA's
 * own page, then HealthDoc takes the details HPR asks for. Synthetic transport. */
class TestApiError extends Error {
  constructor(code, message, requestId, payload) { super(message); this.code = code; this.payload = payload; }
}
const source = new URL("../src/features/admin/HpidCreation.tsx", import.meta.url);
const find = (tree, predicate) => nodes(tree).find(predicate);
const button = (tree, text) => find(tree, (n) => n.type === "button" && content(n).replace(/\s+/g, " ").trim().startsWith(text));
const field = (tree, name) => find(tree, (n) => (n.type === "input" || n.type === "select") && n.props.name === name);
const NHA_PAGE = "https://healthidbeta.abdm.gov.in/abdm/aadhaar/gateway/auth?l=synthetic";
const KYC = { name: "Asha Kumari Verma", first_name: "Asha", middle_name: "Kumari", last_name: "Verma", gender: "F",
  birth_date: "1990-04-07", address: "1 Synthetic Lane, Pune", state_name: "Maharashtra", district_name: "Pune",
  pincode: "411001", email: "", photo: "cGhvdG8=", mobile_hint: "4321" };

function panel(overrides = {}) {
  const calls = [];
  let signedIn = 0;
  let checks = 0;
  const stubs = {
    startHpidLink: async () => ({ session_id: "session-1", url: NHA_PAGE }),
    checkHpidLink: async () => (checks++ === 0 ? { authenticated: false }
      : { authenticated: true, existing: false, kyc: KYC, suggestions: ["asha.verma"], mobile_verified: false }),
    verifyHpidMobile: async () => ({ mobile_verified: false, otp_sent: true }),
    confirmHpidMobile: async () => ({ mobile_verified: true }),
    createHpid: async () => ({ hpr_id: "asha.verma@hpr.abdm", hpr_id_number: "71-0000-0000-0002", logged_in: true, expires_at: 0 }),
    hprCategories: async () => [{ code: "1", label: "Doctor", subcategories: [{ code: "1", label: "Modern Medicine" }] }],
    hprStates: async () => [{ code: "20", label: "Maharashtra" }],
    hprDistricts: async () => [{ code: "499", label: "Washim" }],
    ...overrides,
  };
  const api = Object.fromEntries(Object.entries(stubs).map(([name, impl]) =>
    [name, async (...args) => { calls.push({ name, args }); return impl(...args); }]));
  const h = componentHarness((runtime) => compile(source, {
    ...runtime, "@/lib/api": { ApiError: TestApiError }, "./api/hpr": api,
  }).HpidCreation);
  const render = () => { const tree = h.render({ onSignedIn: () => { signedIn += 1; } }); h.effects(); return tree; };
  return { calls, render, signedIn: () => signedIn };
}

async function settle(d) { for (let i = 0; i < 3; i += 1) { d.render(); await flush(); } return d.render(); }
const type = (tree, name, value) => field(tree, name).props.onChange({ target: { value } });

async function opened(d) {
  const tree = d.render();
  await button(tree, "Verify Aadhaar on NHA's page").props.onClick();
  return settle(d);
}

async function verified(d) {
  let tree = await opened(d);
  await button(tree, "I have verified on NHA's page").props.onClick(); tree = await settle(d);
  await button(tree, "I have verified on NHA's page").props.onClick();
  return settle(d);
}

test("the Aadhaar is verified on NHA's own page, never typed here (HPR-002 to 007)", async () => {
  const d = panel();
  let tree = d.render();
  assert.equal(nodes(tree).some((n) => n.type === "input"), false, "nothing to type before NHA's page");
  tree = await opened(d);
  const link = find(tree, (n) => n.type === "a");
  assert.equal(link.props.href, NHA_PAGE);
  assert.equal(link.props.target, "_blank");
  assert.match(link.props.rel, /noopener/);
  await button(tree, "I have verified on NHA's page").props.onClick(); tree = await settle(d);
  assert.match(content(tree), /NHA has not confirmed the Aadhaar verification yet/);
});

test("Cancel asks for a new NHA page; otherwise the waiting one comes back", async () => {
  const d = panel();
  let tree = await opened(d);
  assert.deepEqual(d.calls.find((c) => c.name === "startHpidLink").args, [false]);
  await button(tree, "Cancel").props.onClick(); tree = await settle(d);
  await button(tree, "Verify Aadhaar on NHA's page").props.onClick(); await settle(d);
  assert.deepEqual(d.calls.filter((c) => c.name === "startHpidLink").map((c) => c.args), [[false], [true]]);
});

test("HPR's own reason is shown when it refuses", async () => {
  const d = panel({ startHpidLink: async () => {
    throw new TestApiError(400, "generic", undefined, { code: "hpr_refused", message: "HPR is busy; try again" });
  } });
  const tree = await opened(d);
  assert.match(content(tree), /HPR is busy; try again/);
});

test("an Aadhaar that already has an HPID signs that professional in", async () => {
  const d = panel({ checkHpidLink: async () => ({ authenticated: true, existing: true, signed_in: true,
    hpr_id: "suprabha@hpr.abdm", hpr_id_number: "71-8847-0813-4805", kyc: KYC }) });
  let tree = await opened(d);
  await button(tree, "I have verified on NHA's page").props.onClick(); tree = await settle(d);
  assert.match(content(tree), /already has an HPID/);
  assert.match(content(tree), /suprabha@hpr\.abdm/);
  assert.match(content(tree), /signed in to HPR above, with their Aadhaar details/);
  assert.equal(d.signedIn(), 1, "the HPR login panel is told to reload");
});

test("the KYC is shown, the mobile verified, and the HPID created with HPR's ids", async () => {
  const d = panel();
  let tree = await verified(d);
  assert.match(content(tree), /Asha Kumari Verma/);
  assert.match(content(tree), /1 Synthetic Lane, Pune/);
  type(tree, "hpid_mobile", "9876543210"); tree = d.render();
  await button(tree, "Verify mobile").props.onClick(); tree = await settle(d);
  button(tree, "Change mobile").props.onClick(); tree = d.render();
  type(tree, "hpid_mobile", "9876543211"); tree = d.render();
  await button(tree, "Verify mobile").props.onClick(); tree = await settle(d);
  assert.deepEqual(d.calls.filter((c) => c.name === "verifyHpidMobile").map((c) => c.args[1]), ["9876543210", "9876543211"]);
  type(tree, "hpid_mobile_otp", "654321"); tree = d.render();
  await button(tree, "Verify OTP").props.onClick(); tree = await settle(d);
  assert.equal(field(tree, "hpid_id").props.value, "asha.verma");
  type(tree, "hpid_email", "asha@example.org"); tree = d.render();
  type(tree, "hpid_password", "Synthetic#Pass9"); tree = d.render();
  type(tree, "hpid_confirm", "Synthetic#Pass9"); tree = d.render();
  type(tree, "hpid_category", "1"); tree = d.render();
  type(tree, "hpid_subcategory", "1"); tree = d.render();
  type(tree, "hpid_state", "20"); tree = await settle(d);
  type(tree, "hpid_district", "499"); tree = d.render();
  await button(tree, "Create HPID").props.onClick(); tree = await settle(d);
  assert.deepEqual(d.calls.find((c) => c.name === "createHpid").args[0], {
    session_id: "session-1", hpr_id: "asha.verma", email: "asha@example.org", password: "Synthetic#Pass9",
    category_code: 1, subcategory_code: 1, state_id: "20", district_id: "499", role: "PROFESSIONAL" });
  assert.match(content(tree), /HPID created successfully/);
  assert.equal(d.signedIn(), 1);
});

test("the password can be shown and hidden, and empty lists say what to choose first", async () => {
  const d = panel({ verifyHpidMobile: async () => ({ mobile_verified: true, otp_sent: false }) });
  let tree = await verified(d);
  type(tree, "hpid_mobile", "9876543210"); tree = d.render();
  await button(tree, "Verify mobile").props.onClick(); tree = await settle(d);
  assert.equal(field(tree, "hpid_password").props.type, "password");
  find(tree, (n) => n.type === "button" && n.props["aria-label"] === "Show hpr password").props.onClick(); tree = d.render();
  assert.equal(field(tree, "hpid_password").props.type, "text");
  assert.equal(field(tree, "hpid_confirm").props.type, "password");
  assert.match(content(field(tree, "hpid_subcategory")), /Choose the category first/);
  assert.match(content(field(tree, "hpid_district")), /Choose the state first/);
});
