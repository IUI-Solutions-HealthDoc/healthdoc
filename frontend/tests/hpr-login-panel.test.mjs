import assert from "node:assert/strict";
import test from "node:test";
import { compile, componentHarness, content, flush, nodes } from "./helpers/component-harness.mjs";

/** The facility manager's HPR login (ABDM M4). Synthetic transport only. */
class TestApiError extends Error {
  constructor(code, message) { super(message); this.code = code; }
}
const source = new URL("../src/features/admin/HprLoginPanel.tsx", import.meta.url);
const find = (tree, predicate) => nodes(tree).find(predicate);
const button = (tree, text) => find(tree, (n) => n.type === "button" && content(n).replace(/\s+/g, " ").trim().startsWith(text));
const field = (tree, name) => find(tree, (n) => n.type === "input" && n.props.name === name);
const alerts = (tree) => nodes(tree).filter((n) => n.props?.role === "alert").map(content).join(" ");

function panel(stubs) {
  const calls = [];
  const record = (name, impl) => async (...args) => { calls.push({ name, args }); return impl(...args); };
  const api = Object.fromEntries(Object.entries({
    hprLoginState: async () => ({ logged_in: false }),
    startHprOtp: async () => ({ session_id: "s1", masked_mobile: "******1234" }),
    verifyHprOtp: async () => ({ logged_in: true, hpr_id: "kumar682000@hpr.abdm", hpr_id_number: null, expires_at: 2000000000 }),
    hprPasswordLogin: async () => { throw new Error("unused"); },
    hprLogout: async () => ({ logged_in: false }),
    ...stubs,
  }).map(([name, impl]) => [name, record(name, impl)]));
  const h = componentHarness((runtime) => compile(source, {
    ...runtime, "@/lib/api": { ApiError: TestApiError }, "./api/hfr": api,
  }).HprLoginPanel);
  const render = () => { const tree = h.render({}); h.effects(); return tree; };
  return { calls, render };
}

test("an OTP login sends to HPR and keeps only the session shown", async () => {
  const d = panel({});
  let tree = d.render(); await flush(); tree = d.render();
  field(tree, "hpr_id").props.onChange({ target: { value: "Kumar682000@HPR.abdm" } }); tree = d.render();
  assert.equal(field(tree, "hpr_id").props.value, "kumar682000@hpr.abdm");
  await button(tree, "Send OTP").props.onClick(); await flush(); tree = d.render();
  assert.deepEqual(d.calls.find((c) => c.name === "startHprOtp").args, ["kumar682000@hpr.abdm", "AADHAAR_OTP"]);
  assert.match(content(tree), /OTP sent\s+to\s+\*\*\*\*\*\*1234/);
  assert.equal(button(tree, "Verify").props.disabled, true);
  field(tree, "hpr_otp").props.onChange({ target: { value: "12a3456" } }); tree = d.render();
  assert.equal(field(tree, "hpr_otp").props.value, "123456");
  await button(tree, "Verify").props.onClick(); await flush(); tree = d.render();
  assert.deepEqual(d.calls.find((c) => c.name === "verifyHprOtp").args, ["s1", "123456"]);
  assert.match(content(tree), /Signed in to HPR as\s+kumar682000@hpr\.abdm/);
});

test("an invalid HPR ID cannot start a login", async () => {
  const d = panel({});
  let tree = d.render(); await flush(); tree = d.render();
  field(tree, "hpr_id").props.onChange({ target: { value: "kumar682000" } }); tree = d.render();
  assert.equal(button(tree, "Send OTP").props.disabled, true);
});

test("a refused OTP is shown and no session appears", async () => {
  const d = panel({ verifyHprOtp: async () => { throw new TestApiError(400, "HPR did not accept this OTP"); } });
  let tree = d.render(); await flush(); tree = d.render();
  field(tree, "hpr_id").props.onChange({ target: { value: "kumar682000@hpr.abdm" } }); tree = d.render();
  await button(tree, "Send OTP").props.onClick(); await flush(); tree = d.render();
  field(tree, "hpr_otp").props.onChange({ target: { value: "000000" } }); tree = d.render();
  await button(tree, "Verify").props.onClick(); await flush(); tree = d.render();
  assert.match(alerts(tree), /did not accept this OTP/);
  assert.doesNotMatch(content(tree), /Signed in to HPR/);
});
