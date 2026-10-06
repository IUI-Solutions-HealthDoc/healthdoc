import assert from "node:assert/strict";
import test from "node:test";
import { compile, componentHarness, content, flush, nodes } from "./helpers/component-harness.mjs";

/** The official mobile/email verified by OTP before HPR registration (m4-verification). Synthetic transport. */
class TestApiError extends Error {
  constructor(code, message, requestId, payload) { super(message); this.code = code; this.payload = payload; }
}
const source = new URL("../src/features/admin/HprContactVerifier.tsx", import.meta.url);
const find = (tree, predicate) => nodes(tree).find(predicate);
const button = (tree, text) => find(tree, (n) => n.type === "button" && content(n).trim() === text);
const field = (tree, label) => find(tree, (n) => n.type === "input" && n.props["aria-label"] === label);
const NONE = { mobile_verified: false, mobile_hint: null, email_verified: false, email: null };

function verifier(kind, overrides = {}) {
  const calls = [];
  let changed = null;
  const stubs = {
    sendHprMobileOtp: async () => ({ ...NONE, mobile_otp_sent: true }),
    verifyHprMobileOtp: async () => ({ ...NONE, mobile_verified: true, mobile_hint: "6780" }),
    sendHprEmailOtp: async () => ({ ...NONE, email_otp_sent: true }),
    verifyHprEmailOtp: async () => ({ ...NONE, email_verified: true, email: "asha.real@example.org" }),
    ...overrides,
  };
  const api = Object.fromEntries(Object.entries(stubs).map(([name, impl]) =>
    [name, async (...args) => { calls.push({ name, args }); return impl(...args); }]));
  const h = componentHarness((runtime) => compile(source, {
    ...runtime, "@/lib/api": { ApiError: TestApiError }, "./api/hpr": api,
  }).HprContactVerifier);
  let contact = NONE;
  const render = () => { const tree = h.render({ kind, contact, onChange: (c) => { changed = c; contact = c; } }); h.effects(); return tree; };
  return { calls, render, changed: () => changed };
}
async function settle(d) { for (let i = 0; i < 3; i += 1) { d.render(); await flush(); } return d.render(); }

test("a mobile is sent an OTP only when valid, then verified with HPR", async () => {
  const d = verifier("mobile");
  let tree = d.render();
  field(tree, "Official mobile").props.onChange({ target: { value: "12345" } }); tree = await settle(d);
  assert.equal(button(tree, "Send OTP").props.disabled, true);
  field(tree, "Official mobile").props.onChange({ target: { value: "91234 56780" } }); tree = await settle(d);
  await button(tree, "Send OTP").props.onClick(); tree = await settle(d);
  field(tree, "Official mobile OTP").props.onChange({ target: { value: "123456" } }); tree = await settle(d);
  await button(tree, "Verify").props.onClick(); tree = await settle(d);
  assert.deepEqual(d.calls.map((c) => [c.name, ...c.args]), [["sendHprMobileOtp", "9123456780"], ["verifyHprMobileOtp", "123456"]]);
  assert.equal(d.changed().mobile_verified, true);
  assert.match(content(tree), /Official mobile\s+verified\s+\(ending 6780\)/);
});

test("HPR's own refusal of a wrong OTP is shown, and nothing is verified", async () => {
  const d = verifier("email", { verifyHprEmailOtp: async () => {
    throw new TestApiError(400, "generic", undefined, { code: "hpr_refused", message: "Invalid OTP" });
  } });
  let tree = d.render();
  field(tree, "Official email").props.onChange({ target: { value: "asha.real@example.org" } }); tree = await settle(d);
  await button(tree, "Send OTP").props.onClick(); tree = await settle(d);
  field(tree, "Official email OTP").props.onChange({ target: { value: "000000" } }); tree = await settle(d);
  await button(tree, "Verify").props.onClick(); tree = await settle(d);
  assert.match(content(tree), /Invalid OTP/);
  assert.equal(d.changed(), null);
});
