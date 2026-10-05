import assert from "node:assert/strict";
import test from "node:test";
import { compile, componentHarness, content, flush, nodes } from "./helpers/component-harness.mjs";

/** HPID creation in HealthDoc (ABDM M4 HPR-002 to 011): NHA's consent, a
 * captcha and the Aadhaar OTP on HealthDoc's own screen. Synthetic transport. */
class TestApiError extends Error {
  constructor(code, message, requestId, payload) { super(message); this.code = code; this.payload = payload; }
}
const source = new URL("../src/features/admin/HpidCreation.tsx", import.meta.url);
const find = (tree, predicate) => nodes(tree).find(predicate);
const button = (tree, text) => find(tree, (n) => n.type === "button" && content(n).replace(/\s+/g, " ").trim().startsWith(text));
const field = (tree, name) => find(tree, (n) => (n.type === "input" || n.type === "select") && n.props.name === name);
const CONSENT = "I, hereby declare that I am voluntarily sharing my Aadhaar Number / Virtual ID ... Healthcare Professional ID.";
const KYC = { name: "Asha Kumari Verma", first_name: "Asha", middle_name: "Kumari", last_name: "Verma", gender: "F",
  birth_date: "1990-04-07", address: "1 Synthetic Lane, Pune", state_name: "Maharashtra", district_name: "Pune",
  pincode: "411001", email: "", photo: "cGhvdG8=", mobile_hint: "4321" };

function panel(overrides = {}) {
  const calls = [];
  let signedIn = 0;
  const stubs = {
    hpidConsent: async () => ({ version: "nha-hpid-consent-2026-10-05", text: CONSENT }),
    hpidCaptcha: async () => ({ captcha_id: `cap-${calls.filter((c) => c.name === "hpidCaptcha").length}`, image: "data:image/png;base64,AA==" }),
    sendHpidAadhaarOtp: async () => ({ session_id: "session-1", masked_mobile: "******4321" }),
    resendHpidAadhaarOtp: async () => ({ masked_mobile: "******4321" }),
    verifyHpidAadhaarOtp: async () => ({ existing: false, kyc: KYC, suggestions: ["asha.verma"], mobile_verified: false }),
    verifyHpidMobile: async () => ({ mobile_verified: false, otp_sent: true }),
    confirmHpidMobile: async () => ({ mobile_verified: true }),
    createHpid: async () => ({ hpr_id: "asha.verma@hpr.abdm", hpr_id_number: "71-0000-0000-0002", logged_in: true, expires_at: 0 }),
    hprCategories: async () => [{ code: "1", label: "Doctor", subcategories: [{ code: "1", label: "Modern Medicine" }] }],
    hprStates: async () => [{ code: "20", label: "Maharashtra" }],
    hprDistricts: async () => [{ code: "499", label: "Washim" }],
    startHpidLink: async () => ({ session_id: "link-1", url: "https://healthidbeta.abdm.gov.in/x" }),
    checkHpidLink: async () => ({ authenticated: false }),
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
const tick = (tree, name, checked = true) => field(tree, name).props.onChange({ target: { checked } });

async function aadhaarForm(d) {
  const tree = d.render();
  button(tree, "Start with Aadhaar").props.onClick();
  return settle(d);
}

async function otpSent(d) {
  let tree = await aadhaarForm(d);
  type(tree, "hpid_aadhaar", "2345 6789 0123"); tree = d.render();
  tick(tree, "hpid_consent"); tree = d.render();
  type(tree, "hpid_captcha", "AB3CD"); tree = d.render();
  await button(tree, "Send OTP").props.onClick();
  return settle(d);
}

async function verified(d) {
  let tree = await otpSent(d);
  type(tree, "hpid_aadhaar_otp", "123456"); tree = d.render();
  await button(tree, "Verify OTP").props.onClick();
  return settle(d);
}

test("the Aadhaar is taken in HealthDoc, with NHA's consent and a captcha (HPR-002 to 007)", async () => {
  const d = panel();
  let tree = await aadhaarForm(d);
  assert.equal(find(tree, (n) => n.type === "a"), undefined, "no redirect to NHA's page");
  assert.match(content(tree), /voluntarily sharing my Aadhaar Number/);
  assert.equal(field(tree, "hpid_aadhaar").props.type, "password", "masked until shown");
  type(tree, "hpid_aadhaar", "234567890123"); tree = d.render();
  type(tree, "hpid_captcha", "AB3CD"); tree = d.render();
  assert.equal(button(tree, "Send OTP").props.disabled, true, "not without consent");
  tick(tree, "hpid_consent"); tree = d.render();
  assert.equal(button(tree, "Send OTP").props.disabled, false);
  await button(tree, "Send OTP").props.onClick(); tree = await settle(d);
  assert.deepEqual(d.calls.find((c) => c.name === "sendHpidAadhaarOtp").args[0], {
    aadhaar: "234567890123", consent_accepted: true, consent_version: "nha-hpid-consent-2026-10-05",
    captcha_id: "cap-1", captcha_answer: "AB3CD" });
  assert.match(content(tree), /OTP sent to the mobile linked with this Aadhaar/);
});

test("an invalid Aadhaar never leaves the screen", async () => {
  const d = panel();
  let tree = await aadhaarForm(d);
  type(tree, "hpid_aadhaar", "123456789012"); tree = d.render();
  tick(tree, "hpid_consent"); tree = d.render();
  type(tree, "hpid_captcha", "AB3CD"); tree = d.render();
  assert.equal(button(tree, "Send OTP").props.disabled, true);
  assert.match(content(tree), /Enter the 12-digit Aadhaar number/);
});

test("a refused attempt brings a new captcha, as each is spent", async () => {
  const d = panel({ sendHpidAadhaarOtp: async () => { throw new TestApiError(400, "Aadhaar Number/Virtual ID is invalid."); } });
  const tree = await otpSent(d);
  assert.match(content(tree), /Aadhaar Number\/Virtual ID is invalid/);
  assert.equal(d.calls.filter((c) => c.name === "hpidCaptcha").length, 2);
});

test("the OTP can be resent (HPR-008)", async () => {
  const d = panel();
  let tree = await otpSent(d);
  await button(tree, "Resend OTP").props.onClick(); tree = await settle(d);
  assert.deepEqual(d.calls.find((c) => c.name === "resendHpidAadhaarOtp").args, ["session-1"]);
});

test("an Aadhaar that already has an HPID signs that professional in", async () => {
  const d = panel({ verifyHpidAadhaarOtp: async () => ({ existing: true, signed_in: true, hpr_id: "suprabha@hpr.abdm",
    hpr_id_number: "71-8847-0813-4805", kyc: KYC }) });
  const tree = await verified(d);
  assert.match(content(tree), /already has an HPID/);
  assert.match(content(tree), /suprabha@hpr\.abdm/);
  assert.match(content(tree), /signed in to HPR above, with their Aadhaar details/);
  assert.equal(d.signedIn(), 1, "the HPR login panel is told to reload");
  assert.equal(d.calls.some((c) => c.name === "createHpid"), false);
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

test("when HPR cannot verify in HealthDoc, NHA's page takes over on the same card", async () => {
  let checks = 0;
  const d = panel({
    verifyHpidAadhaarOtp: async () => {
      throw new TestApiError(400, "generic", undefined, { code: "hpid_inapp_unavailable",
        message: "HPR could not verify this OTP in HealthDoc (NHA's in-app verification is not working). Verify on NHA's page instead." });
    },
    checkHpidLink: async () => (checks++ === 0 ? { authenticated: false }
      : { authenticated: true, existing: true, signed_in: true, hpr_id: "suprabha@hpr.abdm", hpr_id_number: "71-8847-0813-4805", kyc: KYC }),
  });
  let tree = await verified(d);
  assert.match(content(tree), /NHA's in-app verification is not working/);
  await button(tree, "Verify on NHA's page instead").props.onClick(); tree = await settle(d);
  const link = find(tree, (n) => n.type === "a");
  assert.equal(link.props.href, "https://healthidbeta.abdm.gov.in/x");
  assert.match(link.props.rel, /noopener/);
  await button(tree, "I have verified on NHA's page").props.onClick(); tree = await settle(d);
  assert.match(content(tree), /NHA has not confirmed/);
  await button(tree, "I have verified on NHA's page").props.onClick(); tree = await settle(d);
  assert.match(content(tree), /already has an HPID/);
  assert.equal(d.signedIn(), 1);
});
