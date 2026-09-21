import assert from "node:assert/strict";
import test from "node:test";
import { compile, componentHarness, content, flush, nodes } from "./helpers/component-harness.mjs";
import { clinicalWrite } from "./helpers/clinical-write.mjs";

/** Failed reads must read as failures; ambiguous searches must not pick a patient;
 * background refreshes must not unmount a draft; late reads must not replace a draft. */

const source = (path) => new URL(`../src/${path}`, import.meta.url);
const icons = (...names) => Object.fromEntries(names.map((name) => [name, "icon"]));
const deferred = () => { let resolve, reject; const promise = new Promise((res, rej) => { resolve = res; reject = rej; }); return { promise, resolve, reject }; };
const find = (tree, predicate) => nodes(tree).find(predicate);
const button = (tree, label) => find(tree, (n) => n.type === "button" && content(n).trim() === label);
// JSX text fragments are joined with spaces by the harness ("UHID: " + uhid), so
// assertions read a normalized rendering instead of relying on exact spacing.
const flat = (node) => content(node).replace(/\s+/g, " ").replace(/\(\s+/g, "(").replace(/\s+\)/g, ")").replace(/:\s+/g, ": ").trim();
const alerts = (tree) => nodes(tree).filter((n) => n.props?.role === "alert").map(flat).join(" | ");

function formsPage({ definitions, orderSets, submissions, search }) {
  const editors = [];
  const modals = {};
  const h = componentHarness((runtime) => compile(source("features/forms/FormsPage.tsx"), {
    ...runtime,
    "lucide-react": icons("AlertCircle", "FileCheck", "FileSpreadsheet", "FileText", "History", "Layers", "RefreshCw", "Search"),
    "./api": { fetchFormDefinitions: definitions, fetchOrderSets: orderSets, fetchPatientSubmissions: submissions },
    "./components/ClinicalOrderSetsModal": { ClinicalOrderSetsModal() { return null; } },
    "./components/CsvAdministrationModal": { CsvAdministrationModal(props) { modals.csv = props; return null; } },
    "./components/DynamicFormRenderer": { DynamicFormRenderer(props) { editors.push(props); return { type: "editor", props: { patient: props.patientId, form: props.formDef } }; } },
    "@/lib/api": { api: search, formatDateTime: (iso) => iso },
  }).FormsPage);
  const render = () => h.render({});
  const searchFor = async (tree, term) => {
    find(tree, (n) => n.type === "input" && n.props.placeholder?.startsWith("Search patient by")).props.onChange({ target: { value: term } });
    await find(render(), (n) => n.type === "form").props.onSubmit({ preventDefault() {} });
    await flush();
    return render();
  };
  return { h, render, searchFor, editors, modals };
}

test("forms page: zero or multiple matches never select a patient, and a failed search is shown", async () => {
  const responses = [];
  const page = formsPage({
    definitions: async () => [{ id: "f1", code: "F1", title: "Form one", version: 1, fields_schema: [] }],
    orderSets: async () => [],
    submissions: async () => [],
    search: async () => { const next = responses.shift(); if (next instanceof Error) throw next; return next; },
  });
  let tree = page.render(); page.h.effects(); await flush(); tree = page.render();
  assert.equal(find(tree, (n) => n.type === "input").props.placeholder, "Search patient by exact UHID or mobile number...");

  responses.push({ items: [{ id: "A", uhid: "UHID-A", full_name: "Patient A" }, { id: "B", uhid: "UHID-B", full_name: "Patient B" }] });
  tree = await page.searchFor(tree, "9999999999");
  assert.match(alerts(tree), /2 patients share that identifier/);
  assert.doesNotMatch(flat(tree), /UHID: UHID-/);
  assert.equal(find(tree, (n) => n.type === "editor"), undefined, "no editor may open for an ambiguous match");

  responses.push({ items: [] });
  tree = await page.searchFor(tree, "UHID-NONE");
  assert.match(alerts(tree), /No patient matched/);

  responses.push(new Error("Patient search failed (403)"));
  tree = await page.searchFor(tree, "UHID-X");
  assert.match(alerts(tree), /Patient search failed \(403\)/);

  responses.push({ items: [{ id: "A", uhid: "UHID-A", full_name: "Patient A" }] });
  tree = await page.searchFor(tree, "UHID-A");
  assert.equal(alerts(tree), "");
  assert.match(flat(tree), /UHID: UHID-A/);
  assert.equal(find(tree, (n) => n.type === "editor").props.patient, "A");
});

test("forms page: only one search runs at a time and its verdict is applied once it returns", async () => {
  const pending = [];
  const page = formsPage({
    definitions: async () => [{ id: "f1", code: "F1", title: "Form one", version: 1, fields_schema: [] }],
    orderSets: async () => [], submissions: async () => [],
    search: () => { const d = deferred(); pending.push(d); return d.promise; },
  });
  let tree = page.render(); page.h.effects(); await flush(); tree = page.render();
  find(tree, (n) => n.type === "input").props.onChange({ target: { value: "UHID-A" } });
  const first = find(page.render(), (n) => n.type === "form").props.onSubmit({ preventDefault() {} });
  tree = page.render();
  assert.equal(button(tree, "Searching…").props.disabled, true);
  await find(tree, (n) => n.type === "form").props.onSubmit({ preventDefault() {} });
  assert.equal(pending.length, 1, "a second submit while searching must not start another request");
  pending[0].resolve({ items: [{ id: "A", uhid: "UHID-A", full_name: "Patient A" }] });
  await first; await flush();
  tree = page.render();
  assert.match(flat(tree), /UHID: UHID-A/);
  assert.equal(button(tree, "Find").props.disabled, false);
});

test("forms page: a failed history read is reported and never rendered as an empty history", async () => {
  const page = formsPage({
    definitions: async () => [{ id: "f1", code: "F1", title: "Form one", version: 1, fields_schema: [] }],
    orderSets: async () => [],
    submissions: async () => { throw new Error("history unavailable (502)"); },
    search: async () => ({ items: [{ id: "A", uhid: "UHID-A", full_name: "Patient A" }] }),
  });
  let tree = page.render(); page.h.effects(); await flush(); tree = page.render();
  tree = await page.searchFor(tree, "UHID-A"); page.h.effects(); await flush(); tree = page.render();
  assert.match(flat(tree), /history unavailable/);
  assert.doesNotMatch(flat(tree), /0 completed records/);
  find(tree, (n) => n.type === "button" && content(n).includes("Patient Submissions")).props.onClick();
  tree = page.render();
  assert.match(alerts(tree), /Previous submissions could not be loaded: history unavailable \(502\)/);
  assert.doesNotMatch(flat(tree), /No form submissions recorded/);
});

test("forms page: a refresh after CSV import keeps the open editor and its definition mounted", async () => {
  const loads = [];
  const page = formsPage({
    definitions: () => { const d = deferred(); loads.push(d); return d.promise; },
    orderSets: async () => [], submissions: async () => [],
    search: async () => ({ items: [{ id: "A", uhid: "UHID-A", full_name: "Patient A" }] }),
  });
  let tree = page.render(); page.h.effects();
  assert.match(flat(tree), /Loading clinical forms/);
  const original = { id: "f1", code: "F1", title: "Form one", version: 1, fields_schema: [] };
  loads[0].resolve([original]); await flush();
  tree = await page.searchFor(page.render(), "UHID-A");
  const editor = find(tree, (n) => n.type === "editor");
  assert.equal(editor.props.form, original);

  page.modals.csv.onSuccess(); // CSV import completed → background refresh
  tree = page.render();
  assert.doesNotMatch(flat(tree), /Loading clinical forms/, "a refresh must not blank the workspace");
  assert.ok(find(tree, (n) => n.type === "editor"), "the open editor must stay mounted during a refresh");
  loads[1].resolve([{ ...original }, { id: "f2", code: "F2", title: "Form two", version: 1, fields_schema: [] }]); await flush();
  tree = page.render();
  assert.equal(find(tree, (n) => n.type === "editor").props.form, original, "a refresh must not swap the definition under a draft");
  assert.match(flat(tree), /Available Clinical Forms \(2\)/);
});

test("forms page: a failed definitions read is a failure with retry, not zero forms", async () => {
  let attempts = 0;
  const page = formsPage({
    definitions: async () => { if (attempts++ === 0) throw new Error("forms service down"); return [{ id: "f1", code: "F1", title: "Form one", version: 1, fields_schema: [] }]; },
    orderSets: async () => [], submissions: async () => [], search: async () => ({ items: [] }),
  });
  let tree = page.render(); page.h.effects(); await flush(); tree = page.render();
  assert.match(alerts(tree), /Clinical forms could not be loaded: forms service down/);
  assert.doesNotMatch(flat(tree), /Available Clinical Forms \(0\)/);
  await button(tree, "Retry loading forms").props.onClick(); await flush();
  tree = page.render();
  assert.equal(alerts(tree), "");
  assert.match(flat(tree), /Available Clinical Forms \(1\)/);
});

test("forms page: a late receipt for the previous patient does not enter the current patient's history", async () => {
  const page = formsPage({
    definitions: async () => [{ id: "f1", code: "F1", title: "Form one", version: 1, fields_schema: [] }],
    orderSets: async () => [], submissions: async () => [],
    search: async (_path, init) => { const body = JSON.parse(init.body); return { items: [{ id: body.uhid, uhid: body.uhid, full_name: `Patient ${body.uhid}` }] }; },
  });
  let tree = page.render(); page.h.effects(); await flush();
  tree = await page.searchFor(page.render(), "A");
  const onSuccessForA = find(tree, (n) => n.type === "editor").props.onSuccess ?? page.editors.at(-1).onSuccess;
  tree = await page.searchFor(tree, "B"); page.h.effects(); await flush(); tree = page.render();
  onSuccessForA({ id: "sub-a", patient_id: "A", form_id: "f1", form_data: {} });
  tree = page.render();
  assert.match(flat(tree), /0 completed records/);
  page.editors.at(-1).onSuccess({ id: "sub-b", patient_id: "B", form_id: "f1", form_data: {} });
  assert.match(flat(page.render()), /1 completed records/);
});

function csvModal({ validate, doImport }) {
  const readers = [];
  const FileReader = class { readAsText(file) { this.file = file; readers.push(this); } };
  const h = componentHarness((runtime) => compile(source("features/forms/components/CsvAdministrationModal.tsx"), {
    ...runtime, "@/lib/useClinicalWrite": clinicalWrite(runtime),
    "lucide-react": icons("AlertCircle", "CheckCircle2", "Download", "FileSpreadsheet", "ShieldAlert", "ShieldCheck", "Upload", "X"),
    "../api": { downloadCsv: async () => new Blob(), validateCsv: validate, importCsv: doImport },
  }).CsvAdministrationModal);
  const props = { isOpen: true, onClose() {}, onSuccess() {} };
  const render = () => h.render(props);
  const textarea = (tree) => find(tree, (n) => n.type === "textarea");
  return { h, render, readers, FileReader, textarea, props };
}

test("csv modal: a file read that finishes after the draft locked cannot change the retry body", async () => {
  const modal = csvModal({
    validate: async () => ({ valid: true, row_count: 1, columns: ["code", "name"], warnings: [], errors: [] }),
    doImport: async () => { throw new TypeError("Network failed after the server may have imported"); },
  });
  const previous = globalThis.FileReader; globalThis.FileReader = modal.FileReader;
  try {
    let tree = modal.render();
    modal.textarea(tree).props.onChange({ target: { value: "code,name\nA,Alpha" } });
    tree = modal.render();
    await button(tree, "Validate Security").props.onClick(); await flush();
    tree = modal.render();
    assert.match(flat(tree), /Safe to Ingest/);
    find(tree, (n) => n.type === "input" && n.props.type === "file").props.onChange({ target: { files: [{ name: "late.csv" }] } });
    assert.equal(modal.readers.length, 1);
    await button(tree, "Execute Import").props.onClick(); await flush();
    tree = modal.render();
    assert.match(flat(tree), /Retry unchanged import/);
    assert.equal(modal.textarea(tree).props.disabled, true);
    modal.readers[0].onload({ target: { result: "code,name\nZ,Zulu" } });
    tree = modal.render();
    assert.equal(modal.textarea(tree).props.value, "code,name\nA,Alpha", "the locked draft is the retry body and must not change");
    assert.equal(find(tree, (n) => n.type === "input" && n.props.type === "file").props.disabled, true);
  } finally {
    globalThis.FileReader = previous;
  }
});

test("csv modal: a superseded file read is ignored and a verdict for changed text is discarded", async () => {
  const validations = [];
  const modal = csvModal({ validate: () => { const d = deferred(); validations.push(d); return d.promise; }, doImport: async () => ({ imported_count: 0, message: "" }) });
  const previous = globalThis.FileReader; globalThis.FileReader = modal.FileReader;
  try {
    let tree = modal.render();
    const fileInput = (t) => find(t, (n) => n.type === "input" && n.props.type === "file");
    fileInput(tree).props.onChange({ target: { files: [{ name: "first.csv" }] } });
    fileInput(tree).props.onChange({ target: { files: [{ name: "second.csv" }] } });
    modal.readers[0].onload({ target: { result: "code,name\nFIRST,First" } });
    assert.equal(modal.textarea(modal.render()).props.value, "", "an older read must not overwrite the newer selection");
    modal.readers[1].onload({ target: { result: "code,name\nSECOND,Second" } });
    tree = modal.render();
    assert.equal(modal.textarea(tree).props.value, "code,name\nSECOND,Second");

    const validating = button(tree, "Validate Security").props.onClick();
    modal.textarea(modal.render()).props.onChange({ target: { value: "code,name\nEDITED,Edited" } });
    validations[0].resolve({ valid: true, row_count: 1, columns: ["code", "name"], warnings: [], errors: [] });
    await validating; await flush();
    tree = modal.render();
    assert.doesNotMatch(flat(tree), /Safe to Ingest/, "a verdict for superseded text must not be shown");
    assert.equal(button(tree, "Execute Import"), undefined);
    assert.equal(button(tree, "Validate Security").props.disabled, false);
  } finally {
    globalThis.FileReader = previous;
  }
});

test("blood bank: a failed read is a failure with retry, not an empty inventory, and refreshes do not blank the page", async () => {
  const unitLoads = [];
  let grid;
  const h = componentHarness((runtime) => compile(source("features/blood-bank/BloodBankPage.tsx"), {
    ...runtime, "lucide-react": icons("AlertCircle", "Droplets", "Heart", "Package", "RefreshCw"),
    "./api": { fetchBloodUnits: () => { const d = deferred(); unitLoads.push(d); return d.promise; }, fetchBloodDonors: async () => [] },
    "./components/BloodCrossmatchModal": { BloodCrossmatchModal() { return null; } },
    "./components/BloodDonorRegistry": { BloodDonorRegistry() { return null; } },
    "./components/BloodInventoryGrid": { BloodInventoryGrid(props) { grid = props; return { type: "grid", props: { units: props.units } }; } },
  }).BloodBankPage);
  let tree = h.render({}); h.effects();
  assert.match(flat(tree), /Unit Inventory \(—\)/);
  unitLoads[0].reject(new Error("inventory read refused (403)")); await flush();
  tree = h.render({});
  assert.match(alerts(tree), /Blood bank data could not be loaded: inventory read refused \(403\)/);
  assert.doesNotMatch(flat(tree), /Unit Inventory \(0\)/);
  assert.equal(find(tree, (n) => n.type === "grid"), undefined);
  await button(tree, "Retry loading blood bank data").props.onClick();
  unitLoads[1].resolve([{ id: "u1", bag_number: "BAG-1" }]); await flush();
  tree = h.render({});
  assert.equal(alerts(tree), "");
  assert.match(flat(tree), /Unit Inventory \(1\)/);
  assert.equal(find(tree, (n) => n.type === "grid").props.units.length, 1);

  void grid.onRefresh();
  tree = h.render({});
  assert.doesNotMatch(flat(tree), /Loading blood bank data/, "a refresh must not replace the grid with a spinner");
  assert.ok(find(tree, (n) => n.type === "grid"));
  unitLoads[2].reject(new Error("refresh timed out")); await flush();
  tree = h.render({});
  assert.match(alerts(tree), /latest refresh failed: refresh timed out/);
  assert.equal(find(tree, (n) => n.type === "grid").props.units.length, 1, "known data stays visible with the failure stated");
});

test("immunization: a failed catalogue read blocks dose entry with a retry, and searches report zero/multiple/failed results", async () => {
  let catalogueAttempts = 0;
  const responses = [];
  const h = componentHarness((runtime) => compile(source("features/immunization/ImmunizationPage.tsx"), {
    ...runtime, "lucide-react": icons("AlertCircle", "BookOpen", "RefreshCw", "Search", "Syringe"),
    "./api": {
      fetchVaccineCatalogue: async () => { if (catalogueAttempts++ === 0) throw new Error("catalogue unavailable (500)"); return [{ id: "v1", code: "BCG", name: "BCG", target_disease: "TB", min_age_days: 0, standard_doses: 1, route: "intradermal", site: null }]; },
      fetchImmunizationCertificate: async () => { throw new Error("certificate render failed"); },
    },
    "./components/ImmunizationCertificateModal": { ImmunizationCertificateModal() { return null; } },
    "./components/ImmunizationScheduleView": { ImmunizationScheduleView(props) { return { type: "schedule", props: { patient: props.patientId, open: props.onOpenCertificateModal } }; } },
    "./components/RecordImmunizationModal": { RecordImmunizationModal() { return { type: "record-modal", props: {} }; } },
    "@/lib/api": { api: async () => { const next = responses.shift(); if (next instanceof Error) throw next; return next; } },
  }).ImmunizationPage);
  let tree = h.render({}); h.effects(); await flush(); tree = h.render({});
  assert.match(alerts(tree), /vaccine catalogue could not be loaded: catalogue unavailable \(500\)/);
  assert.equal(find(tree, (n) => n.type === "record-modal"), undefined, "no dose can be recorded without a catalogue");
  assert.doesNotMatch(flat(tree), /Vaccine Catalogue \(0\)/);
  await button(tree, "Retry loading catalogue").props.onClick(); await flush();
  tree = h.render({});
  assert.match(flat(tree), /Vaccine Catalogue \(1\)/);
  assert.equal(find(tree, (n) => n.type === "input").props.placeholder, "Search patient by exact UHID or mobile number...");

  const search = async (term) => {
    find(h.render({}), (n) => n.type === "input").props.onChange({ target: { value: term } });
    await find(h.render({}), (n) => n.type === "form").props.onSubmit({ preventDefault() {} });
    await flush();
    return h.render({});
  };
  responses.push({ items: [{ id: "A", uhid: "UHID-A" }, { id: "B", uhid: "UHID-B" }] });
  tree = await search("9999999999");
  assert.match(alerts(tree), /2 patients share that identifier/);
  assert.equal(find(tree, (n) => n.type === "schedule"), undefined);
  responses.push({ items: [] });
  assert.match(alerts(await search("UHID-NONE")), /No patient matched/);
  responses.push(new Error("search refused (403)"));
  assert.match(alerts(await search("UHID-X")), /search refused \(403\)/);
  responses.push({ items: [{ id: "A", uhid: "UHID-A", full_name: "Patient A" }] });
  tree = await search("UHID-A");
  assert.equal(alerts(tree), "");
  assert.equal(find(tree, (n) => n.type === "schedule").props.patient, "A");
  await find(tree, (n) => n.type === "schedule").props.open(); await flush();
  assert.match(alerts(h.render({})), /certificate render failed/);
});
