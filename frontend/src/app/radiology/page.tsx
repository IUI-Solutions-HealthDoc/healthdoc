"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import { ModuleCapabilityGate } from "@/components/common/ModuleCapabilityGate";
import {
  cancelScan,
  draftRadiologyReport,
  getRadiologyFhirBundle,
  getRadiologyReports,
  listRadiologyWork,
  markScanComplete,
  rescheduleScan,
  scheduleScan,
  signOffRadiologyReport,
} from "@/features/radiology/api";
import type {
  RadiologyOrderItem,
  RadiologyReport,
} from "@/features/radiology/types";
import { ApiError, formatDateTime } from "@/lib/api";

const WORKFLOW: { status: string; label: string; hint: string }[] = [
  { status: "placed", label: "To schedule", hint: "Ordered, not yet booked onto a machine" },
  { status: "scheduled", label: "Booked", hint: "Slot assigned; patient not yet imaged" },
  { status: "scanned", label: "To report", hint: "Imaged, awaiting a radiologist" },
  { status: "reporting", label: "Preliminary", hint: "Drafted, not signed off" },
  { status: "released", label: "Released", hint: "Signed and available to the ordering doctor" },
  { status: "cancelled", label: "Cancelled", hint: "Cancelled before imaging" },
];

function StatusChip({ status }: { status: string }) {
  const tone =
    status === "released"
      ? "bg-success-muted text-success"
      : status === "reporting"
        ? "bg-warning-muted text-warning"
        : status === "cancelled"
          ? "bg-danger-muted text-danger"
          : "bg-muted text-muted-foreground";
  return <span className={`rounded-full px-2 py-1 text-xs font-medium ${tone}`}>{status}</span>;
}

function RadiologyPageContent() {
  const [items, setItems] = useState<RadiologyOrderItem[]>([]);
  const [filter, setFilter] = useState<string>("all");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [selected, setSelected] = useState<RadiologyOrderItem | null>(null);
  const [reports, setReports] = useState<RadiologyReport[]>([]);
  const [busy, setBusy] = useState(false);

  const [slot, setSlot] = useState("");
  const [machine, setMachine] = useState("");
  const [findings, setFindings] = useState("");
  const [impression, setImpression] = useState("");
  const [pacsStudyUid, setPacsStudyUid] = useState("");
  const [rescheduleReason, setRescheduleReason] = useState("");
  const [cancelReason, setCancelReason] = useState("");
  const [rescheduleSlot, setRescheduleSlot] = useState("");
  const [rescheduleMachine, setRescheduleMachine] = useState("");

  const [fhirBundle, setFhirBundle] = useState<Record<string, unknown> | null>(null);
  const [fhirError, setFhirError] = useState<string | null>(null);
  const [fhirLoading, setFhirLoading] = useState(false);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const response = await listRadiologyWork(filter);
      setItems(response.items);
      setError(null);
      return response.items;
    } catch (e) {
      setError(
        e instanceof ApiError && e.isModuleDisabled
          ? "Radiology is not enabled at this facility."
          : e instanceof Error
            ? e.message
            : "Could not load the radiology worklist",
      );
      setItems([]);
      return [];
    } finally {
      setLoading(false);
    }
  }, [filter]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const loadReports = useCallback(async (itemId: string) => {
    try {
      const history = await getRadiologyReports(itemId);
      setReports(history.items);
      const current = history.items.find((r) => r.is_current);
      if (current) {
        setFindings(current.findings);
        setImpression(current.impression);
      }
      return history.items;
    } catch {
      setReports([]);
      return [];
    }
  }, []);

  const openItem = useCallback(
    async (item: RadiologyOrderItem) => {
      setSelected(item);
      setSlot("");
      setMachine(item.machine_id ?? "");
      setFindings("");
      setImpression("");
      setPacsStudyUid(item.pacs_study_uid ?? "");
      setRescheduleReason("");
      setCancelReason("");
      setRescheduleSlot("");
      setRescheduleMachine(item.machine_id ?? "");
      setFhirBundle(null);
      setFhirError(null);
      await loadReports(item.id);
    },
    [loadReports],
  );

  const syncSelected = useCallback(
    async (itemId: string, freshItems?: RadiologyOrderItem[]) => {
      const list = freshItems ?? (await listRadiologyWork(filter)).items;
      setItems(list);
      const updated = list.find((item) => item.id === itemId) ?? null;
      if (updated) setSelected(updated);
      await loadReports(itemId);
    },
    [filter, loadReports],
  );

  const run = useCallback(
    async (action: () => Promise<unknown>, failure: string) => {
      if (!selected) return;
      const itemId = selected.id;
      setBusy(true);
      setError(null);
      try {
        await action();
        const freshItems = await refresh();
        await syncSelected(itemId, freshItems);
      } catch (e) {
        setError(e instanceof Error ? e.message : failure);
      } finally {
        setBusy(false);
      }
    },
    [refresh, selected, syncSelected],
  );

  const loadFhir = useCallback(async () => {
    if (!selected) return;
    setFhirLoading(true);
    setFhirError(null);
    try {
      setFhirBundle(await getRadiologyFhirBundle(selected.id));
    } catch (e) {
      setFhirBundle(null);
      setFhirError(e instanceof ApiError ? e.message : "Could not load FHIR bundle");
    } finally {
      setFhirLoading(false);
    }
  }, [selected]);

  useEffect(() => {
    if (selected && (selected.status === "released" || selected.status === "reporting")) {
      void loadFhir();
    } else {
      setFhirBundle(null);
      setFhirError(null);
    }
  }, [loadFhir, selected]);

  const counts = useMemo(() => {
    const byStatus: Record<string, number> = {};
    for (const item of items) byStatus[item.status] = (byStatus[item.status] ?? 0) + 1;
    return byStatus;
  }, [items]);

  const currentReport = reports.find((r) => r.is_current) ?? null;

  return (
    <main className="space-y-6 p-6">
      <div>
        <h1 className="text-2xl font-semibold">Radiology</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Booked, imaged, reported, signed. Preliminary reads stay visible after a final one
          supersedes them.
        </p>
      </div>

      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          onClick={() => setFilter("all")}
          className={`rounded-md border px-3 py-1 text-sm ${
            filter === "all" ? "border-primary text-primary" : "border-border"
          }`}
        >
          All
        </button>
        {WORKFLOW.map((stage) => (
          <button
            key={stage.status}
            type="button"
            title={stage.hint}
            onClick={() => setFilter(stage.status)}
            className={`rounded-md border px-3 py-1 text-sm ${
              filter === stage.status ? "border-primary text-primary" : "border-border"
            }`}
          >
            {stage.label}
            {counts[stage.status] ? ` (${counts[stage.status]})` : ""}
          </button>
        ))}
      </div>

      {error && (
        <p role="alert" className="text-sm text-danger">
          {error}
        </p>
      )}

      <div className="grid gap-6 lg:grid-cols-[3fr_2fr]">
        <section className="surface-card overflow-hidden">
          {loading ? (
            <p className="p-6 text-sm text-muted-foreground">Loading worklist…</p>
          ) : items.length === 0 ? (
            <p className="p-6 text-sm text-muted-foreground">Nothing in this stage.</p>
          ) : (
            <table className="min-w-full border-collapse">
              <thead className="bg-muted">
                <tr>
                  <th className="px-4 py-3 text-left text-xs">Accession</th>
                  <th className="px-4 py-3 text-left text-xs">Scan</th>
                  <th className="px-4 py-3 text-left text-xs">Slot</th>
                  <th className="px-4 py-3 text-left text-xs">Status</th>
                </tr>
              </thead>
              <tbody>
                {items.map((item) => (
                  <tr
                    key={item.id}
                    onClick={() => void openItem(item)}
                    className={`cursor-pointer border-b border-border ${
                      selected?.id === item.id ? "bg-muted" : ""
                    }`}
                  >
                    <td className="px-4 py-3 font-mono text-xs">{item.accession_number}</td>
                    <td className="px-4 py-3">
                      <div className="text-sm font-medium">{item.scan_type}</div>
                      <div className="text-xs uppercase text-muted-foreground">
                        {item.modality}
                        {item.machine_id ? ` · ${item.machine_id}` : ""}
                      </div>
                    </td>
                    <td className="px-4 py-3 text-xs">
                      {item.scheduled_at ? formatDateTime(item.scheduled_at) : "—"}
                    </td>
                    <td className="px-4 py-3">
                      <StatusChip status={item.status} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </section>

        <section className="surface-card space-y-5 p-5">
          {!selected ? (
            <p className="text-sm text-muted-foreground">
              Select a scan to schedule, complete or report it.
            </p>
          ) : (
            <>
              <div>
                <h2 className="text-lg font-semibold">{selected.scan_type}</h2>
                <p className="text-xs text-muted-foreground">
                  {selected.accession_number} · <StatusChip status={selected.status} />
                </p>
              </div>

              {selected.status === "placed" && (
                <div className="space-y-3">
                  <p className="text-sm font-medium">Book a slot</p>
                  <label className="block space-y-1 text-sm">
                    <span className="text-muted-foreground">Scheduled at</span>
                    <input
                      type="datetime-local"
                      className="w-full rounded-md border border-border px-3 py-2"
                      value={slot}
                      onChange={(e) => setSlot(e.target.value)}
                    />
                  </label>
                  <label className="block space-y-1 text-sm">
                    <span className="text-muted-foreground">Machine</span>
                    <input
                      className="w-full rounded-md border border-border px-3 py-2"
                      value={machine}
                      onChange={(e) => setMachine(e.target.value)}
                      placeholder="e.g. CT-01"
                    />
                  </label>
                  <button
                    type="button"
                    disabled={busy || !slot || !machine.trim()}
                    className="rounded-md bg-primary px-4 py-2 text-sm text-white disabled:opacity-50"
                    onClick={() =>
                      void run(
                        () =>
                          scheduleScan(
                            selected.id,
                            new Date(slot).toISOString(),
                            machine.trim(),
                          ),
                        "Could not schedule",
                      )
                    }
                  >
                    Schedule
                  </button>
                </div>
              )}

              {selected.status === "scheduled" && (
                <div className="space-y-3">
                  <p className="text-sm">
                    Booked for {selected.scheduled_at ? formatDateTime(selected.scheduled_at) : "—"}
                    {selected.machine_id ? ` on ${selected.machine_id}` : ""}.
                  </p>
                  <button
                    type="button"
                    disabled={busy}
                    className="rounded-md bg-primary px-4 py-2 text-sm text-white disabled:opacity-50"
                    onClick={() =>
                      void run(() => markScanComplete(selected.id), "Could not complete")
                    }
                  >
                    Mark scan complete
                  </button>
                  <div className="space-y-3 border-t border-border pt-3">
                    <p className="text-sm font-medium">Reschedule</p>
                    <label className="block space-y-1 text-sm">
                      <span className="text-muted-foreground">New slot</span>
                      <input
                        type="datetime-local"
                        className="w-full rounded-md border border-border px-3 py-2"
                        value={rescheduleSlot}
                        onChange={(event) => setRescheduleSlot(event.target.value)}
                      />
                    </label>
                    <label className="block space-y-1 text-sm">
                      <span className="text-muted-foreground">Machine</span>
                      <input
                        maxLength={50}
                        className="w-full rounded-md border border-border px-3 py-2"
                        value={rescheduleMachine}
                        onChange={(event) => setRescheduleMachine(event.target.value)}
                      />
                    </label>
                    <label className="block space-y-1 text-sm">
                      <span className="text-muted-foreground">Reason</span>
                      <input
                        minLength={5}
                        maxLength={500}
                        className="w-full rounded-md border border-border px-3 py-2"
                        value={rescheduleReason}
                        onChange={(event) => setRescheduleReason(event.target.value)}
                      />
                    </label>
                    <button
                      type="button"
                      disabled={
                        busy ||
                        !rescheduleSlot ||
                        !rescheduleMachine.trim() ||
                        rescheduleReason.trim().length < 5
                      }
                      className="rounded-md border border-primary px-4 py-2 text-sm text-primary disabled:opacity-50"
                      onClick={() =>
                        void run(
                          () =>
                            rescheduleScan(
                              selected.id,
                              new Date(rescheduleSlot).toISOString(),
                              rescheduleMachine.trim(),
                              rescheduleReason.trim(),
                            ),
                          "Could not reschedule",
                        )
                      }
                    >
                      Save new slot
                    </button>
                  </div>
                </div>
              )}

              {(selected.status === "placed" || selected.status === "scheduled") && (
                <div className="space-y-3 border-t border-border pt-4">
                  <p className="text-sm font-medium text-danger">Cancel scan</p>
                  <label className="block space-y-1 text-sm">
                    <span className="text-muted-foreground">Cancellation reason</span>
                    <textarea
                      minLength={5}
                      maxLength={500}
                      rows={2}
                      className="w-full rounded-md border border-border px-3 py-2"
                      value={cancelReason}
                      onChange={(event) => setCancelReason(event.target.value)}
                    />
                  </label>
                  <button
                    type="button"
                    disabled={busy || cancelReason.trim().length < 5}
                    className="rounded-md border border-danger px-4 py-2 text-sm text-danger disabled:opacity-50"
                    onClick={() =>
                      void run(
                        () => cancelScan(selected.id, cancelReason.trim()),
                        "Could not cancel",
                      )
                    }
                  >
                    Cancel scan
                  </button>
                </div>
              )}

              {(selected.status === "scanned" ||
                selected.status === "reporting" ||
                selected.status === "released") && (
                <div className="space-y-3">
                  <p className="text-sm font-medium">
                    {selected.status === "scanned" ? "Draft report" : "Report"}
                  </p>
                  <label className="block space-y-1 text-sm">
                    <span className="text-muted-foreground">Findings</span>
                    <textarea
                      rows={5}
                      className="w-full rounded-md border border-border px-3 py-2"
                      value={findings}
                      onChange={(e) => setFindings(e.target.value)}
                      disabled={selected.status === "released"}
                    />
                  </label>
                  <label className="block space-y-1 text-sm">
                    <span className="text-muted-foreground">Impression</span>
                    <textarea
                      rows={3}
                      className="w-full rounded-md border border-border px-3 py-2"
                      value={impression}
                      onChange={(e) => setImpression(e.target.value)}
                      disabled={selected.status === "released"}
                    />
                  </label>
                  <label className="block space-y-1 text-sm">
                    <span className="text-muted-foreground">PACS study UID</span>
                    <input
                      className="w-full rounded-md border border-border px-3 py-2 font-mono text-xs"
                      value={pacsStudyUid}
                      onChange={(e) => setPacsStudyUid(e.target.value)}
                      disabled={selected.status === "released"}
                      placeholder="Optional DICOM study instance UID"
                    />
                  </label>

                  {selected.status === "scanned" && (
                    <button
                      type="button"
                      disabled={busy || !findings.trim() || !impression.trim()}
                      className="rounded-md bg-primary px-4 py-2 text-sm text-white disabled:opacity-50"
                      onClick={() =>
                        void run(
                          () =>
                            draftRadiologyReport(
                              selected.id,
                              findings,
                              impression,
                              pacsStudyUid,
                            ),
                          "Could not draft",
                        )
                      }
                    >
                      Save preliminary
                    </button>
                  )}

                  {selected.status === "reporting" && (
                    <button
                      type="button"
                      disabled={busy}
                      className="rounded-md bg-primary px-4 py-2 text-sm text-white disabled:opacity-50"
                      onClick={() =>
                        void run(
                          () => signOffRadiologyReport(selected.id, findings, impression),
                          "Could not sign off",
                        )
                      }
                    >
                      Sign off as final
                    </button>
                  )}
                </div>
              )}

              {reports.length > 0 && (
                <div className="border-t border-border pt-4">
                  <p className="text-sm font-medium">Versions</p>
                  <ul className="mt-2 space-y-1">
                    {reports.map((report) => (
                      <li key={report.id} className="text-xs text-muted-foreground">
                        v{report.version} · {report.status}
                        {report.is_current ? " · current" : " · superseded"}
                        {report.tat_minutes != null ? ` · TAT ${report.tat_minutes}m` : ""}
                      </li>
                    ))}
                  </ul>
                  {currentReport && !currentReport.is_current && (
                    <p className="mt-2 text-xs text-warning">
                      You are viewing a superseded version.
                    </p>
                  )}
                </div>
              )}

              {(selected.status === "reporting" || selected.status === "released") && (
                <div className="border-t border-border pt-4">
                  <div className="flex items-center justify-between gap-2">
                    <p className="text-sm font-medium">FHIR bundle</p>
                    <button
                      type="button"
                      className="text-xs underline"
                      disabled={fhirLoading}
                      onClick={() => void loadFhir()}
                    >
                      {fhirLoading ? "Loading…" : "Refresh"}
                    </button>
                  </div>
                  {fhirError ? (
                    <p className="mt-2 text-xs text-danger">{fhirError}</p>
                  ) : fhirBundle ? (
                    <pre className="mt-2 max-h-48 overflow-auto rounded-md bg-muted p-3 text-xs">
                      {JSON.stringify(fhirBundle, null, 2)}
                    </pre>
                  ) : fhirLoading ? (
                    <p className="mt-2 text-xs text-muted-foreground">Loading FHIR bundle…</p>
                  ) : null}
                </div>
              )}

              {selected.pacs_study_uid && (
                <p className="border-t border-border pt-4 font-mono text-xs text-muted-foreground">
                  PACS study UID: {selected.pacs_study_uid}
                </p>
              )}
            </>
          )}
        </section>
      </div>
    </main>
  );
}

export default function RadiologyPage() {
  return (
    <ModuleCapabilityGate module="radiology">
      <RadiologyPageContent />
    </ModuleCapabilityGate>
  );
}
