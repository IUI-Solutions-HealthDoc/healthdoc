import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import ts from "typescript";

import { apiErrorCode } from "../src/lib/api-error-policy.mjs";
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
  const view = componentHarness((runtime) =>
    compile(new URL("../src/features/receptionist/StartVisit.tsx", import.meta.url), {
      ...runtime,
      "next/link": { __esModule: true, default: "a" },
      "@/lib/api": { ApiError, newIdempotencyKey: () => `key-${++keyCounter}` },
      "@/lib/api-error-policy.mjs": { apiErrorCode },
      "@/lib/auth/routes": { canRoleAccessPath: () => false },
      "@/providers/auth-provider": { useAuth: () => ({ user: { role: "receptionist" } }) },
      "./api": {
        createVisit: request("createVisit"),
        getVisit: request("getVisit"),
        issueToken: request("issueToken"),
        listQueues: request("listQueues"),
      },
      "./types": {
        BED_OCCUPYING_VISIT_TYPES: ["ipd", "day_care"],
        TOKEN_ISSUING_VISIT_TYPES: ["opd"],
        VISIT_TYPE_LABELS: { opd: "OPD", ipd: "IPD" },
      },
    }).StartVisit,
  );
  const take = (name) => {
    const index = calls.findIndex((call) => call.name === name);
    assert.notEqual(index, -1, `expected a ${name} call`);
    return calls.splice(index, 1)[0];
  };
  return { view, calls, take };
}

const patientA = { id: "patient-a", full_name: "Asha", uhid: "IN-A", thid: null };
const patientB = { id: "patient-b", full_name: "Bala", uhid: null, thid: "TH-B" };
const queues = [
  { id: "q1", doctor_name: "Dr One", room_number: null, waiting_count: 0 },
  { id: "q2", doctor_name: "Dr Two", room_number: null, waiting_count: 3 },
];

function button(tree, label) {
  const found = nodes(tree).find((node) => node.type === "button" && content(node).includes(label));
  assert.ok(found, `button "${label}" not rendered`);
  return found;
}
const selects = (tree) => nodes(tree).filter((node) => node.type === "select");

async function renderWithQueues(view, take, patient) {
  view.render({ patient });
  view.effects();
  take("listQueues").resolve(queues);
  await flush();
  return view.render({ patient });
}

test("a patient switch never reuses the previous patient's visit key", async () => {
  const { view, take } = setup();
  let tree = await renderWithQueues(view, take, patientA);
  button(tree, "Create visit").props.onClick();
  const first = take("createVisit");
  assert.equal(first.args[0].patient_id, "patient-a");
  assert.equal("visit_date" in first.args[0], false, "the server stamps the visit date");
  first.reject(new TypeError("network"));
  await flush();

  tree = view.render({ patient: patientB });
  button(tree, "Create visit").props.onClick();
  const second = take("createVisit");
  assert.equal(second.args[0].patient_id, "patient-b");
  assert.notEqual(second.args[1], first.args[1]);
});

test("after a token failure the desk can pick another doctor and retry with a new key", async () => {
  const { view, take, calls } = setup();
  let tree = await renderWithQueues(view, take, patientA);
  button(tree, "Create visit").props.onClick();
  take("createVisit").resolve({ id: "visit-1", visit_number: "VST-1" });
  await flush();
  const firstToken = take("issueToken");
  assert.equal(firstToken.args[0].queue_id, "q1");
  firstToken.reject(new ApiError(409, "Queue is closed"));
  await flush();

  tree = view.render({ patient: patientA });
  const [, doctor, priority] = selects(tree);
  assert.equal(doctor.props.disabled, false, "doctor stays selectable after the visit exists");
  assert.equal(priority.props.disabled, false);
  assert.match(content(tree), /Visits Awaiting Token/);

  doctor.props.onChange({ target: { value: "q2" } });
  tree = view.render({ patient: patientA });
  button(tree, "Retry token issue").props.onClick();
  const retry = take("issueToken");
  assert.equal(retry.args[0].queue_id, "q2");
  assert.equal(retry.args[0].visit_id, "visit-1");
  assert.notEqual(retry.args[1], firstToken.args[1], "a different queue is a different request");
  assert.equal(calls.some((call) => call.name === "createVisit"), false, "no second visit");
});

test("an open visit already on file is reused instead of opening a second one", async () => {
  const { view, take } = setup();
  const tree = await renderWithQueues(view, take, patientA);
  button(tree, "Create visit").props.onClick();
  take("createVisit").reject(
    new ApiError(409, "open", undefined, { code: "open_visit_exists", visit_id: "visit-existing" }),
  );
  await flush();
  const lookup = take("getVisit");
  assert.equal(lookup.args[0], "visit-existing");
  lookup.resolve({ id: "visit-existing", visit_number: "VST-9" });
  await flush();
  const token = take("issueToken");
  assert.equal(token.args[0].visit_id, "visit-existing");
  token.resolve({ token_display: "GEN-001" });
  await flush();
  assert.match(content(view.render({ patient: patientA })), /GEN-001/);
});

test("the desk no longer offers vitals entry", () => {
  const source = readFileSync(new URL("../src/features/receptionist/StartVisit.tsx", import.meta.url), "utf8");
  for (const removed of ["deskPulse", "deskBpSys", "Desk Observations", "useDeskCounter"]) {
    assert.equal(source.includes(removed), false, removed);
  }
});

test("every StartVisit and AbhaIdentityPanel mount is keyed by the patient", () => {
  const files = [
    "../src/app/receptionist/patient-search/page.tsx",
    "../src/app/receptionist/registration/page.tsx",
    "../src/features/receptionist/RegistrationForm.tsx",
    "../src/features/receptionist/ScanShareDeskModal.tsx",
  ];
  let checked = 0;
  for (const file of files) {
    const source = readFileSync(new URL(file, import.meta.url), "utf8");
    const sf = ts.createSourceFile(file, source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
    const visit = (node) => {
      if (ts.isJsxSelfClosingElement(node) || ts.isJsxOpeningElement(node)) {
        const name = node.tagName.getText(sf);
        if (name === "StartVisit" || name === "AbhaIdentityPanel") {
          checked++;
          const hasKey = node.attributes.properties.some(
            (attr) => ts.isJsxAttribute(attr) && attr.name.getText(sf) === "key",
          );
          assert.ok(hasKey, `${name} in ${file} must be keyed by the patient`);
        }
      }
      ts.forEachChild(node, visit);
    };
    visit(sf);
  }
  assert.ok(checked >= 5, `expected at least five mounts, found ${checked}`);
});
