import assert from "node:assert/strict";
import test from "node:test";
import { clinicalWrite, TestApiError } from "./helpers/clinical-write.mjs";
import { componentHarness } from "./helpers/component-harness.mjs";

function setup() {
  let write;
  const h = componentHarness((runtime) => {
    const { useClinicalWrite } = clinicalWrite(runtime);
    function Editor() { write = useClinicalWrite(); return null; }
    return function Root({ patient }) { return { type: Editor, key: patient, props: {} }; };
  });
  const render = (patient = "A") => { h.render({ patient }); h.effects(); return write; };
  return { render };
}

test("uncertain clinical write keeps exact body/key and refuses changed data", async () => {
  const { render } = setup(), calls = [];
  let write = render();
  const send = async (body, key) => { calls.push({ body, key }); throw new TypeError("Network failed after server commit"); };
  await assert.rejects(write.run({ patient: "A", value: 1 }, send), /not confirmed/);
  assert.equal(write.isPending(), true, "pending state is readable synchronously, before any re-render");
  write = render();
  assert.equal(write.retryPending, true);
  await assert.rejects(write.run({ patient: "A", value: 2 }, send), /unchanged/);
  assert.equal(calls.length, 1);
  const result = await write.run({ patient: "A", value: 1 }, async (body, key) => {
    calls.push({ body, key }); return "original-row";
  });
  assert.equal(result, "original-row");
  assert.deepEqual(calls[1], calls[0]);
  assert.equal(write.isPending(), false);
  assert.equal(render().retryPending, false);
});

test("synchronous double click cannot dispatch two writes", async () => {
  const { render } = setup(), write = render();
  let resolve, calls = 0;
  const send = () => { calls++; return new Promise((r) => { resolve = r; }); };
  const first = write.run({ value: 1 }, send);
  await assert.rejects(write.run({ value: 1 }, send), /already in progress/);
  assert.equal(calls, 1);
  resolve("saved"); await first;
});

for (const code of [400, 401, 403, 404, 422]) test(`explicit ${code} refusal unlocks a corrected draft`, async () => {
  const { render } = setup(), calls = [];
  await assert.rejects(render().run({ value: 1 }, async (body, key) => {
    calls.push(key); throw new TestApiError(code);
  }), /Explicit refusal/);
  assert.equal(render().retryPending, false);
  await render().run({ value: 2 }, async (body, key) => { calls.push(key); });
  assert.notEqual(calls[0], calls[1]);
});

for (const code of [200, 408, 409, 429, 500, 502]) test(`ambiguous ${code} keeps original request identity`, async () => {
  const { render } = setup();
  await assert.rejects(render().run({ value: 1 }, async () => { throw new TestApiError(code); }), /not confirmed/);
  assert.equal(render().retryPending, true);
});

test("explicit rolled-back constraint rejection unlocks correction, not idempotency conflicts", async () => {
  const { render } = setup();
  await assert.rejects(render().run({ value: 1 }, async () => {
    throw new TestApiError(409, "Refresh the record", { code: "clinical_write_rejected" });
  }), /Refresh/);
  assert.equal(render().retryPending, false);
});

test("patient switch isolates drafts and invalidates old completion callbacks", async () => {
  const { render } = setup(), old = render("A");
  let resolve;
  const pending = old.run({ patient: "A" }, () => new Promise((r) => { resolve = r; }));
  const current = render("B");
  assert.equal(old.isCurrent(), false);
  assert.equal(current.isCurrent(), true);
  assert.equal(current.retryPending, false);
  resolve("A-record"); await pending;
  assert.equal(old.isCurrent(), false);
  assert.equal(render("B").retryPending, false);
});
