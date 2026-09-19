import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const files = {
  printCss: "src/styles/print-document.css",
  portalApi: "src/features/patientPortal/api.ts",
  portalTab: "src/features/patientPortal/components/ReleasedDocumentsTab.tsx",
  portalPage: "src/app/patient-portal/page.tsx",
  doctorApi: "src/features/doctor/api/index.ts",
  specialtyPanel: "src/features/doctor/components/SpecialtyEncounterPanel.tsx",
  consultationWorkspace: "src/features/doctor/components/ConsultationWorkspace.tsx",
  receptionistApi: "src/features/receptionist/api.ts",
  scanShareModal: "src/features/receptionist/ScanShareDeskModal.tsx",
  receptionQueuePage: "src/app/receptionist/queue/page.tsx",
};

const source = Object.fromEntries(
  await Promise.all(
    Object.entries(files).map(async ([name, path]) => [name, await readFile(path, "utf8")]),
  ),
);

test("HD-35: Unified print-document.css defines A4 portrait and 80mm thermal slip", () => {
  assert.match(source.printCss, /@page\s*{[^}]*size:\s*A4 portrait;/);
  assert.match(source.printCss, /#portal-document-print-root/);
  assert.match(source.printCss, /#scan-share-slip-print-root/);
  assert.match(source.printCss, /\.thermal-slip/);
  assert.match(source.printCss, /break-inside:\s*avoid/);
  assert.match(source.printCss, /\.print-signature-block/);
});

test("HD-33: Patient portal documents API and tab support all 5 clinical categories", () => {
  assert.match(source.portalApi, /getPortalDocuments/);
  assert.match(source.portalApi, /getPortalDocumentDetail/);
  assert.match(source.portalTab, /prescription/);
  assert.match(source.portalTab, /lab_report/);
  assert.match(source.portalTab, /radiology/);
  assert.match(source.portalTab, /discharge_summary/);
  assert.match(source.portalTab, /vaccine/);
  assert.match(source.portalTab, /portal-document-print-root/);
  assert.match(source.portalTab, /window\.print\(\)/);
  assert.match(source.portalPage, /ReleasedDocumentsTab/);
  assert.match(source.portalPage, /documents/);
});

test("HD-34: Doctor workspace integrates multi-system terminology and specialty templates", () => {
  assert.match(source.doctorApi, /searchTerminology/);
  assert.match(source.doctorApi, /getSpecialtyTemplates/);
  assert.match(source.doctorApi, /saveEncounterSpecialty/);
  assert.match(source.specialtyPanel, /pediatric/);
  assert.match(source.specialtyPanel, /cardiology/);
  assert.match(source.specialtyPanel, /obstetrics/);
  assert.match(source.consultationWorkspace, /SpecialtyEncounterPanel/);
});

test("HD-36: Receptionist dashboard integrates ABDM M1 Scan & Share ticket flow", () => {
  assert.match(source.receptionistApi, /listScanShareTickets/);
  assert.match(source.receptionistApi, /getScanShareTicket/);
  assert.match(source.receptionistApi, /checkInScanShareTicket/);
  assert.match(source.scanShareModal, /scan-share-slip-print-root/);
  assert.match(source.scanShareModal, /checkInScanShareTicket/);
  assert.match(source.receptionQueuePage, /ScanShareDeskModal/);
  assert.match(source.receptionQueuePage, /ABDM Scan &amp; Share/);
});
