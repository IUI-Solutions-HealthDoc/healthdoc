import assert from "node:assert/strict";
import test from "node:test";

import { compile, componentHarness, content, flush, nodes } from "./helpers/component-harness.mjs";

class ApiError extends Error {
  constructor(code, message, requestId, payload) {
    super(message);
    this.code = code;
    this.requestId = requestId;
    this.payload = payload;
  }
}

function setup() {
  const calls = [];
  let keyCounter = 0;
  const request = (name) => (...args) =>
    new Promise((resolve, reject) => calls.push({ name, args, resolve, reject }));
  const names = [
    "createQueue", "getStaleVisits", "issueToken", "listQueueOpeningOptions", "listQueueTokens",
    "listQueues", "listVisitsWithoutTokens", "reconcileStaleVisits", "updateTokenPriority",
  ];
  const view = componentHarness((runtime) =>
    compile(new URL("../src/app/receptionist/queue/page.tsx", import.meta.url), {
      ...runtime,
      "@/components/ui/toast": { toast: { success() {} } },
      "@/lib/api": {
        ApiError,
        formatDateTime: (value) => String(value),
        newIdempotencyKey: () => `key-${++keyCounter}`,
      },
      "@/features/receptionist/api": Object.fromEntries(names.map((name) => [name, request(name)])),
      "@/features/receptionist/ScanShareDeskModal": { ScanShareDeskModal: () => null },
      "@/components/common/PageHeading": { PageHeading: () => null },
    }).default,
  );
  const take = (name) => {
    const index = calls.findIndex((call) => call.name === name);
    assert.notEqual(index, -1, `expected a ${name} call`);
    return calls.splice(index, 1)[0];
  };
  const render = () => view.render({});
  return { view, calls, take, render };
}

const queues = [
  { id: "q1", doctor_name: "Dr One", room_number: null, waiting_count: 0, now_serving: null },
  { id: "q2", doctor_name: "Dr Two", room_number: null, waiting_count: 2, now_serving: null },
];
const options = { service_date: "2026-09-28", items: [] };
const visit = {
  visit_id: "visit-1", visit_number: "VST-1", patient_id: "p1", patient_name: "Asha",
  uhid: "IN-1", thid: null, department_name: null, department_name_hi: null,
  visit_type: "opd", visit_date: "2026-09-28T04:00:00Z",
};
const stale = {
  total_stale_count: 2,
  cutoff_date: "2026-09-28",
  candidates: ["s1", "s2"].map((id) => ({
    visit_id: id, visit_number: `VST-${id}`, patient_id: `p-${id}`, patient_name: id,
    patient_uhid: "", visit_date: "2026-09-25T04:00:00Z", current_status: "registered",
    encounter_count: 0, has_active_encounter: false,
    recommended_visit_action: "mark_lwbs", recommended_token_action: null,
  })),
};

async function loaded({ take, view, render }, overrides = {}) {
  render();
  view.effects();
  const outcome = { listQueues: queues, listQueueOpeningOptions: options,
    listVisitsWithoutTokens: [visit], getStaleVisits: stale, ...overrides };
  for (const [name, value] of Object.entries(outcome)) {
    const call = take(name);
    if (value instanceof Error) call.reject(value);
    else call.resolve(value);
  }
  await flush();
  render();
  view.effects();
  return render();
}

function button(tree, label) {
  const found = nodes(tree).find((node) => node.type === "button" && content(node).includes(label));
  assert.ok(found, `button "${label}" not rendered`);
  return found;
}
const alerts = (tree) => nodes(tree).filter((node) => node.props?.role === "alert").map(content);

test("a failed queue load is an error with Retry, not an empty day", async () => {
  const harness = setup();
  let tree = await loaded(harness, { listQueues: new ApiError(503, "Service unavailable") });

  assert.deepEqual(alerts(tree).map((text) => text.includes("Service unavailable")), [true]);
  assert.equal(content(tree).includes("No open queues"), false);

  button(tree, "Retry").props.onClick();
  for (const [name, value] of Object.entries({ listQueues: queues, listQueueOpeningOptions: options,
    listVisitsWithoutTokens: [visit], getStaleVisits: stale })) harness.take(name).resolve(value);
  await flush();
  tree = harness.render();
  assert.deepEqual(alerts(tree), []);
  assert.match(content(tree), /Dr Two/);
});

test("failed side lists say so instead of showing zero", async () => {
  const harness = setup();
  let tree = await loaded(harness, {
    listVisitsWithoutTokens: new TypeError("network"),
    getStaleVisits: new TypeError("network"),
  });
  harness.take("listQueueTokens").resolve({ waiting_count: 0, now_serving: null, items: [] });
  await flush();

  button(tree, "Visits Awaiting Token").props.onClick();
  button(tree, "Stale Visits").props.onClick();
  tree = harness.render();
  const text = alerts(tree).join(" | ");
  assert.match(text, /Could not load visits awaiting a token/);
  assert.match(text, /Could not load stale visits/);
  assert.equal(/\(0\)/.test(content(tree)), false, "no count is shown for a list that failed");
});

test("issuing a token retries with the same key until the request changes", async () => {
  const harness = setup();
  let tree = await loaded(harness);
  harness.take("listQueueTokens").resolve({ waiting_count: 0, now_serving: null, items: [] });
  await flush();

  button(tree, "Visits Awaiting Token").props.onClick();
  tree = harness.render();
  button(tree, "Issue Token").props.onClick();
  tree = harness.render();
  button(tree, "Confirm Token").props.onClick();
  const first = harness.take("issueToken");
  assert.equal(first.args[0].queue_id, "q1");
  first.reject(new TypeError("network"));
  await flush();

  tree = harness.render();
  button(tree, "Confirm Token").props.onClick();
  const retry = harness.take("issueToken");
  assert.equal(retry.args[1], first.args[1], "an unchanged retry replays the first attempt");
  retry.reject(new ApiError(409, "This visit already has a live queue token"));
  await flush();

  tree = harness.render();
  assert.match(content(tree), /already has a live queue token/);
  const queueSelect = nodes(tree).find(
    (node) => node.type === "select" && node.props.value === "q1",
  );
  queueSelect.props.onChange({ target: { value: "q2" } });
  tree = harness.render();
  button(tree, "Confirm Token").props.onClick();
  const other = harness.take("issueToken");
  assert.equal(other.args[0].queue_id, "q2");
  assert.notEqual(other.args[1], first.args[1], "another queue is another request");
});

test("reconciliation needs a reason and sends exactly the reviewed visits", async () => {
  const harness = setup();
  let tree = await loaded(harness);
  harness.take("listQueueTokens").resolve({ waiting_count: 0, now_serving: null, items: [] });
  await flush();

  button(tree, "Stale Visits").props.onClick();
  tree = harness.render();
  button(tree, "Reconcile All (2)").props.onClick();
  tree = harness.render();
  const confirm = button(tree, "Confirm reconciliation");
  assert.equal(confirm.props.disabled, true, "no reason, no reconciliation");

  const reason = nodes(tree).find((node) => node.type === "textarea");
  reason.props.onChange({ target: { value: "  Evening review of visits left open  " } });
  tree = harness.render();
  button(tree, "Confirm reconciliation").props.onClick();
  const sent = harness.take("reconcileStaleVisits");
  assert.deepEqual(sent.args[0], {
    visit_ids: ["s1", "s2"],
    reason: "Evening review of visits left open",
  });
  assert.ok(sent.args[1], "an idempotency key is sent");
  assert.equal(harness.calls.some((call) => call.name === "reconcileStaleVisits"), false);
});
