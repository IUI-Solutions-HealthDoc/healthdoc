import assert from "node:assert/strict";
import test from "node:test";
import { compile, componentHarness, content, flush, nodes } from "./helpers/component-harness.mjs";

const source = (path) => new URL(`../src/${path}`, import.meta.url);
const mui = Object.fromEntries(
  ["Box", "Button", "Dialog", "DialogActions", "DialogContent", "DialogTitle", "Stack", "TextField", "Typography"]
    .map((name) => [`@mui/material/${name}`, { default: name }]),
);

function harness({ withdraw, transition }) {
  const toasts = [];
  const updates = [];
  let keys = 0;
  const h = componentHarness((runtime) => {
    const { ConsentRecordDetail } = compile(source("features/consent/components/ConsentRecordDetail.tsx"), {
      ...runtime, ...mui, "@/styles/theme": { meridian: {} },
      "@/components/ui/StatusChip": { StatusChip: "StatusChip" },
      "@/components/ui/toast": { toast: { success: (m) => toasts.push(["ok", m]), error: (m) => toasts.push(["error", m]) } },
      "@/lib/api": { newIdempotencyKey: () => `key-${++keys}` },
      "../api/consent": { withdrawConsent: withdraw, transitionConsentStatus: transition },
      "@/lib/i18n": { useLocale: () => ({ t: (key) => key }) },
      "../i18nLabels": { consentStatusLabel: () => "", consentChannelLabel: () => "", consentPurposeLabel: () => "" },
      "../lib/formatters": { formatDate: () => "", formatDateTime: () => "" },
      "./ConsentAccessHistory": { ConsentAccessHistory: "ConsentAccessHistory" },
    });
    return function Probe({ record }) {
      return { type: ConsentRecordDetail, props: { record, onRecordUpdated: (next) => updates.push(next) } };
    };
  });
  return { h, toasts, updates };
}

const byText = (tree, type, text) => nodes(tree).find((n) => n.type === type && content(n) === text);

test("a failed withdrawal retries with the same key; a new reason gets a new key", async () => {
  const calls = [];
  let fail = true;
  const withdraw = async (id, body, key) => {
    calls.push({ id, body, key });
    if (fail) throw new Error("network");
    return { id: "w-1", consent_id: id, withdrawn_at: "2026-09-30T05:00:00Z" };
  };
  const record = { id: "c-1", patient_id: "p-1", status: "granted" };
  const { h, updates } = harness({ withdraw, transition: async () => record });
  let tree = h.render({ record }); h.effects();

  const typeReason = (text) => {
    nodes(tree).find((n) => n.type === "TextField").props.onChange({ target: { value: text } });
    tree = h.render({ record });
  };
  const confirm = async () => {
    byText(tree, "Button", "consent.confirmWithdrawal").props.onClick();
    await flush();
    tree = h.render({ record });
  };

  typeReason("patient asked");
  await confirm();
  await confirm();
  typeReason("patient asked twice");
  fail = false;
  await confirm();

  assert.deepEqual(calls.map((c) => c.key), ["key-1", "key-1", "key-2"]);
  assert.deepEqual(calls[2].body, { withdrawn_by_type: "patient", reason: "patient asked twice" });
  assert.equal("withdrawn_by_user_id" in calls[2].body, false);
  assert.deepEqual(updates, [{ ...record, status: "revoked", status_changed_at: "2026-09-30T05:00:00Z" }]);
});

test("a second click while a decision is in flight sends nothing", async () => {
  const calls = [];
  let resolve;
  const transition = (id, body, key) => {
    calls.push({ id, body, key });
    return new Promise((r) => { resolve = r; });
  };
  const record = { id: "c-2", patient_id: "p-1", status: "requested" };
  const { h } = harness({ withdraw: async () => ({}), transition });
  const tree = h.render({ record }); h.effects();

  const approve = byText(tree, "Button", "consent.approve");
  approve.props.onClick();
  approve.props.onClick();
  resolve({ ...record, status: "granted" });
  await flush();

  assert.equal(calls.length, 1);
  assert.deepEqual(calls[0], { id: "c-2", body: { status: "granted" }, key: "key-1" });
});
