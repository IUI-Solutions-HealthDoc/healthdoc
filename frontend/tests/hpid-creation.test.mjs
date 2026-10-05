import assert from "node:assert/strict";
import test from "node:test";
import { compile, componentHarness, content, flush, nodes } from "./helpers/component-harness.mjs";

/** HPID creation (ABDM M4 HPR-002 to 011). Synthetic transport shaped like the
 * sandbox's answers; no Aadhaar number or OTP ever passes through this screen. */
class TestApiError extends Error {
  constructor(code, message) { super(message); this.code = code; }
}
const source = new URL("../src/features/admin/HpidCreation.tsx", import.meta.url);
const find = (tree, predicate) => nodes(tree).find(predicate);
const button = (tree, text) => find(tree, (n) => n.type === "button" && content(n).replace(/\s+/g, " ").trim().startsWith(text));
const field = (tree, name) => find(tree, (n) => (n.type === "input" || n.type === "select") && n.props.name === name);
const NHA_PAGE = "https://healthidbeta.abdm.gov.in/abdm/aadhaar/gateway/auth?l=synthetic";
const KYC = { name: "Asha Kumari Verma", first_name: "Asha", middle_name: "Kumari", last_name: "Verma", gender: "F",
  birth_date: "", year_of_birth: "1990", address: "", state_name: "Maharashtra", district_name: "Pune", pincode: "",
  email: "", photo: "cGhvdG8=" };

function panel(overrides = {}) {
  const calls = [];
  let created = 0;
  const stubs = {
    startHpid: async () => ({ session_id: "session-1", url: NHA_PAGE }),
    checkHpid: async () => ({ authenticated: true, kyc: KYC, aadhaar_mobile_hint: "4321", suggestions: ["asha.verma"], mobile_verified: false }),
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
  const render = () => { const tree = h.render({ onCreated: () => { created += 1; } }); h.effects(); return tree; };
  return { calls, render, created: () => created };
}

async function settle(d) { d.render(); await flush(); d.render(); await flush(); return d.render(); }
const type = (tree, name, value) => field(tree, name).props.onChange({ target: { value } });

async function verified(d) {
  let tree = d.render();
  await button(tree, "Start").props.onClick(); tree = await settle(d);
  await button(tree, "I have verified on NHA's page").props.onClick();
  return settle(d);
}

test("the Aadhaar is verified on NHA's page, never typed here", async () => {
  const d = panel({ checkHpid: async () => ({ authenticated: false }) });
  let tree = d.render();
  assert.equal(nodes(tree).some((n) => n.type === "input"), false, "nothing to type before NHA's page");
  await button(tree, "Start").props.onClick(); tree = await settle(d);
  const link = find(tree, (n) => n.type === "a");
  assert.equal(link.props.href, NHA_PAGE);
  assert.equal(link.props.target, "_blank");
  assert.match(link.props.rel, /noopener/);
  await button(tree, "I have verified on NHA's page").props.onClick(); tree = await settle(d);
  assert.match(content(tree), /NHA has not confirmed the Aadhaar verification yet/);
});

test("an Aadhaar that already has an HPID is sent to sign in", async () => {
  const d = panel({ checkHpid: async () => ({ authenticated: true, existing_hpr_id: "71-0000-0000-0001" }) });
  const tree = await verified(d);
  assert.match(content(tree), /already holds the HPR ID\s*71-0000-0000-0001/);
  assert.equal(d.calls.some((c) => c.name === "createHpid"), false);
});

test("the KYC name is shown, not editable, and the mobile is verified by OTP", async () => {
  const d = panel();
  let tree = await verified(d);
  assert.match(content(tree), /Asha Kumari Verma/);
  assert.equal(field(tree, "hpid_first_name"), undefined, "no field edits the Aadhaar name");
  assert.match(content(tree), /ending\s*4321/);
  assert.equal(field(tree, "hpid_password"), undefined, "the HPID form waits for the mobile");
  type(tree, "hpid_mobile", "9876543210"); tree = d.render();
  await button(tree, "Verify mobile").props.onClick(); tree = await settle(d);
  assert.deepEqual(d.calls.find((c) => c.name === "verifyHpidMobile").args, ["session-1", "9876543210"]);
  type(tree, "hpid_mobile_otp", "123456"); tree = d.render();
  await button(tree, "Verify OTP").props.onClick(); tree = await settle(d);
  assert.match(content(tree), /Communication mobile verified/);
});

test("Create HPID waits for HPR's rules, then signs the professional in", async () => {
  const d = panel({ verifyHpidMobile: async () => ({ mobile_verified: true, otp_sent: false }) });
  let tree = await verified(d);
  type(tree, "hpid_mobile", "9876543210"); tree = d.render();
  await button(tree, "Verify mobile").props.onClick(); tree = await settle(d);
  assert.equal(field(tree, "hpid_id").props.value, "asha.verma", "HPR's suggestion is offered first");
  type(tree, "hpid_email", "asha@example.org"); tree = d.render();
  type(tree, "hpid_password", "Verma#Strong1"); tree = d.render();
  type(tree, "hpid_confirm", "Verma#Strong1"); tree = d.render();
  type(tree, "hpid_category", "1"); tree = d.render();
  type(tree, "hpid_subcategory", "1"); tree = d.render();
  type(tree, "hpid_state", "20"); tree = await settle(d);
  type(tree, "hpid_district", "499"); tree = d.render();
  assert.match(content(tree), /The password contains their name/);
  assert.equal(button(tree, "Create HPID").props.disabled, true);
  type(tree, "hpid_password", "Synthetic#Pass9"); tree = d.render();
  type(tree, "hpid_confirm", "Synthetic#Pass9"); tree = d.render();
  assert.equal(button(tree, "Create HPID").props.disabled, false);
  await button(tree, "Create HPID").props.onClick(); tree = await settle(d);
  assert.deepEqual(d.calls.find((c) => c.name === "createHpid").args[0], {
    session_id: "session-1", hpr_id: "asha.verma", email: "asha@example.org", password: "Synthetic#Pass9",
    category_code: 1, subcategory_code: 1, state_code: "20", district_code: "499" });
  assert.deepEqual(d.calls.find((c) => c.name === "hprDistricts").args, ["20"], "districts are HPR's, by HPR state id");
  assert.match(content(tree), /HPID created successfully/);
  assert.match(content(tree), /asha\.verma@hpr\.abdm/);
  assert.equal(d.created(), 1, "the HPR login panel is told to reload");
});

test("a mistyped mobile can be changed and the OTP sent to the new one", async () => {
  const d = panel();
  let tree = await verified(d);
  type(tree, "hpid_mobile", "9876543210"); tree = d.render();
  await button(tree, "Verify mobile").props.onClick(); tree = await settle(d);
  assert.match(content(tree), /OTP sent to\s*9876543210/);
  button(tree, "Change mobile").props.onClick(); tree = d.render();
  assert.equal(field(tree, "hpid_mobile").props.value, "9876543210", "the number is kept to correct");
  type(tree, "hpid_mobile", "9876543211"); tree = d.render();
  await button(tree, "Verify mobile").props.onClick(); tree = await settle(d);
  const sent = d.calls.filter((c) => c.name === "verifyHpidMobile").map((c) => c.args[1]);
  assert.deepEqual(sent, ["9876543210", "9876543211"]);
  assert.match(content(tree), /OTP sent to\s*9876543211/);
});

test("the password can be shown and hidden, and empty lists say what to choose first", async () => {
  const d = panel({ verifyHpidMobile: async () => ({ mobile_verified: true, otp_sent: false }) });
  let tree = await verified(d);
  type(tree, "hpid_mobile", "9876543210"); tree = d.render();
  await button(tree, "Verify mobile").props.onClick(); tree = await settle(d);
  assert.equal(field(tree, "hpid_password").props.type, "password");
  const show = find(tree, (n) => n.type === "button" && n.props["aria-label"] === "Show hpr password");
  show.props.onClick(); tree = d.render();
  assert.equal(field(tree, "hpid_password").props.type, "text");
  assert.equal(field(tree, "hpid_confirm").props.type, "password", "each field toggles on its own");
  assert.match(content(field(tree, "hpid_subcategory")), /Choose the category first/);
  assert.match(content(field(tree, "hpid_district")), /Choose the state first/);
});
