"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  AlertCircle,
  Clock,
  History,
  RotateCcw,
  X,
  XCircle,
} from "lucide-react";

import {
  amendLabResult,
  collectLabSample,
  enterLabResult,
  getLabResultHistory,
  getTestAnalytes,
  listLabWork,
  listSpecimenEvents,
  receiveLabSpecimen,
  recollectLabSpecimen,
  rejectLabSpecimen,
  verifyLabResult,
} from "@/features/lab/api";
import type {
  LabAnalyte,
  LabOrderItem,
  LabResult,
  LabSpecimenEvent,
} from "@/features/lab/types";
import { ApiError, formatDateTime } from "@/lib/api";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/AsyncState";
import { useAuth } from "@/providers/auth-provider";
import StructuredResultForm from "./StructuredResultForm";

const STATUS_FILTERS = [
  { value: "all", label: "All" },
  { value: "placed", label: "To collect" },
  { value: "in_progress", label: "In progress" },
  { value: "completed", label: "To verify" },
  { value: "released", label: "Released" },
] as const;

const PAGE_SIZE = 20;

function StatusChip({ status }: { status: string }) {
  const tone =
    status === "released"
      ? "bg-success-muted text-success"
      : status === "completed"
        ? "bg-warning-muted text-warning"
        : status === "in_progress"
          ? "bg-info-muted text-info"
          : "bg-muted text-muted-foreground";
  return (
    <span className={`rounded-full px-2 py-1 text-xs font-medium ${tone}`}>
      {status.replaceAll("_", " ")}
    </span>
  );
}

function SpecimenStatusChip({ status }: { status?: string | null }) {
  const s = status || "pending_collection";
  const tone =
    s === "received"
      ? "bg-emerald-100 text-emerald-800 dark:bg-emerald-950/50 dark:text-emerald-300"
      : s === "collected"
        ? "bg-blue-100 text-blue-800 dark:bg-blue-950/50 dark:text-blue-300"
        : s === "rejected"
          ? "bg-red-100 text-red-800 dark:bg-red-950/50 dark:text-red-300 font-bold"
          : s === "recollected"
            ? "bg-purple-100 text-purple-800 dark:bg-purple-950/50 dark:text-purple-300"
            : "bg-amber-100 text-amber-800 dark:bg-amber-950/50 dark:text-amber-300";
  return (
    <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${tone}`}>
      {s.replaceAll("_", " ")}
    </span>
  );
}

function ResultHistory({ items }: { items: LabResult[] }) {
  if (items.length === 0) return null;
  return (
    <section className="space-y-3">
      <h3 className="font-medium">Result history</h3>
      {items.map((result) => (
        <article key={result.id} className="rounded-md border border-border p-4 text-sm">
          <div className="flex flex-wrap justify-between gap-3">
            <strong>
              Version {result.version} · {result.status}
              {result.is_current ? " · current" : ""}
            </strong>
            <span className="text-muted-foreground">{formatDateTime(result.created_at)}</span>
          </div>
          {result.amendment_reason ? (
            <p className="mt-2 text-warning">Amendment: {result.amendment_reason}</p>
          ) : null}
          <pre className="mt-3 overflow-x-auto rounded-md bg-muted p-3 text-xs">
            {JSON.stringify(result.result_data, null, 2)}
          </pre>
          {result.remarks ? <p className="mt-2">Remarks: {result.remarks}</p> : null}
          {result.tat_minutes != null ? (
            <p className="mt-1 text-muted-foreground">TAT: {result.tat_minutes} minutes</p>
          ) : null}
        </article>
      ))}
    </section>
  );
}

export function LabWorklistPanel() {
  const { user } = useAuth();
  const canManageResults = user?.role === "lab_tech";
  const [rows, setRows] = useState<LabOrderItem[] | null>(null);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [statusFilter, setStatusFilter] = useState("all");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [history, setHistory] = useState<LabResult[]>([]);
  const [barcode, setBarcode] = useState("");
  const [resultJson, setResultJson] = useState("{}\n");
  const [remarks, setRemarks] = useState("");
  const [analytes, setAnalytes] = useState<LabAnalyte[]>([]);
  const [useStructured, setUseStructured] = useState(true);
  const [amendReason, setAmendReason] = useState("");
  const [amendJson, setAmendJson] = useState("");
  const [amendRemarks, setAmendRemarks] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  const [rejectModalOpen, setRejectModalOpen] = useState(false);
  const [rejectionReason, setRejectionReason] = useState("hemolyzed");
  const [rejectionNotes, setRejectionNotes] = useState("");
  const [timelineModalOpen, setTimelineModalOpen] = useState(false);
  const [specimenEvents, setSpecimenEvents] = useState<LabSpecimenEvent[]>([]);
  const [loadingEvents, setLoadingEvents] = useState(false);

  const selected = useMemo(
    () => rows?.find((row) => row.id === selectedId) ?? null,
    [rows, selectedId],
  );

  const currentResult = useMemo(
    () => history.find((result) => result.is_current) ?? history.at(-1) ?? null,
    [history],
  );

  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  const load = useCallback(async () => {
    try {
      const response = await listLabWork({
        page,
        page_size: PAGE_SIZE,
        status: statusFilter,
      });
      setRows(response.items);
      setTotal(response.total);
      setError(null);
      if (selectedId && !response.items.some((row) => row.id === selectedId)) {
        setSelectedId(null);
        setHistory([]);
      }
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : "Failed to load lab worklist");
    }
  }, [page, selectedId, statusFilter]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    setPage(1);
  }, [statusFilter]);

  async function loadHistory(item: LabOrderItem) {
    if (item.status === "placed" || item.status === "in_progress") {
      setHistory([]);
      return;
    }
    try {
      const response = await getLabResultHistory(item.id);
      setHistory(response.items);
      const current = response.items.find((result) => result.is_current);
      if (current) {
        setAmendJson(JSON.stringify(current.result_data, null, 2));
        setAmendRemarks(current.remarks ?? "");
      }
    } catch (reason) {
      if (reason instanceof ApiError && reason.code === 404) {
        setHistory([]);
      } else {
        setError(reason instanceof Error ? reason.message : "Could not load result history");
      }
    }
  }

  function selectRow(item: LabOrderItem) {
    setSelectedId(item.id);
    setBarcode(item.barcode ?? "");
    setResultJson(
      item.test_name.toLowerCase().includes("hemoglobin")
        ? '{\n  "hemoglobin_g_dl": null\n}\n'
        : "{}\n",
    );
    setRemarks("");
    setAmendReason("");
    setMessage(null);
    setError(null);
    setAnalytes([]);
    setUseStructured(true);
    const code =
      item.test_code ||
      (item.test_name.toLowerCase().includes("hemoglobin")
        ? "HEMOGLOBIN"
        : item.test_name.toUpperCase());
    if (code) {
      getTestAnalytes(code)
        .then((res) => {
          if (res && res.items && res.items.length > 0) {
            setAnalytes(res.items);
          }
        })
        .catch(() => setAnalytes([]));
    }
    void loadHistory(item);
  }

  function updateRow(updated: LabOrderItem) {
    setRows((current) => current?.map((row) => (row.id === updated.id ? updated : row)) ?? []);
  }

  async function collectSample() {
    if (!selected || !barcode.trim()) {
      setError("Scan or enter a barcode before collecting the sample.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const updated = await collectLabSample(selected.id, barcode.trim());
      updateRow(updated);
      setMessage("Sample collected. Result entry is now available.");
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : "Sample collection failed");
    } finally {
      setBusy(false);
    }
  }

  async function handleReceiveSpecimen() {
    if (!selected) return;
    setBusy(true);
    setError(null);
    try {
      const updated = await receiveLabSpecimen(selected.id);
      updateRow(updated);
      setMessage("Specimen successfully received at laboratory bench.");
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : "Failed to receive specimen");
    } finally {
      setBusy(false);
    }
  }

  async function handleRejectSpecimen() {
    if (!selected) return;
    setBusy(true);
    setError(null);
    try {
      const updated = await rejectLabSpecimen(selected.id, rejectionReason, rejectionNotes);
      updateRow(updated);
      setRejectModalOpen(false);
      setRejectionNotes("");
      setMessage(
        `Specimen rejected (${rejectionReason.replaceAll("_", " ")}). Recollection can now be ordered.`,
      );
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : "Failed to reject specimen");
    } finally {
      setBusy(false);
    }
  }

  async function handleRecollectSpecimen() {
    if (!selected) return;
    setBusy(true);
    setError(null);
    try {
      const newLinkedItem = await recollectLabSpecimen(selected.id);
      setMessage(`Recollection ordered! New linked accession: ${newLinkedItem.accession_number}`);
      void load();
      selectRow(newLinkedItem);
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : "Failed to order specimen recollection");
    } finally {
      setBusy(false);
    }
  }

  async function handleOpenTimeline() {
    if (!selected) return;
    setTimelineModalOpen(true);
    setLoadingEvents(true);
    try {
      const events = await listSpecimenEvents(selected.id);
      setSpecimenEvents(events);
    } catch {
      setSpecimenEvents([]);
    } finally {
      setLoadingEvents(false);
    }
  }

  async function enterResult() {
    if (!selected) return;
    let parsed: unknown;
    try {
      parsed = JSON.parse(resultJson);
    } catch {
      setError("Result data must be valid JSON.");
      return;
    }
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
      setError("Result data must be a JSON object.");
      return;
    }
    if (Object.keys(parsed).length === 0) {
      setError("Enter at least one result field.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const result = await enterLabResult(
        selected.id,
        parsed as Record<string, unknown>,
        remarks,
      );
      updateRow({ ...selected, status: "completed" });
      setHistory([result]);
      setMessage(
        "Preliminary result saved. A different lab professional must verify and release it.",
      );
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : "Result entry failed");
    } finally {
      setBusy(false);
    }
  }

  async function verifyResult() {
    if (!selected) return;
    setBusy(true);
    setError(null);
    try {
      const verified = await verifyLabResult(selected.id);
      updateRow({ ...selected, status: "released" });
      setHistory((current) =>
        current.map((result) => (result.id === verified.id ? verified : result)),
      );
      setMessage("Result verified and released.");
    } catch (reason) {
      if (reason instanceof ApiError && reason.code === 403) {
        setError("Maker–checker blocked this action. Sign in as a different lab professional.");
      } else {
        setError(reason instanceof ApiError ? reason.message : "Verification failed");
      }
    } finally {
      setBusy(false);
    }
  }

  async function submitAmendment() {
    if (!selected || !amendReason.trim()) {
      setError("An amendment reason is required.");
      return;
    }
    let parsed: Record<string, unknown> | null = null;
    if (amendJson.trim()) {
      try {
        const value = JSON.parse(amendJson);
        if (!value || typeof value !== "object" || Array.isArray(value)) {
          setError("Amended result data must be a JSON object.");
          return;
        }
        parsed = value as Record<string, unknown>;
      } catch {
        setError("Amended result data must be valid JSON.");
        return;
      }
    }
    setBusy(true);
    setError(null);
    try {
      await amendLabResult(
        selected.id,
        amendReason,
        parsed,
        amendRemarks.trim() || null,
      );
      setMessage("Result amended. A new corrected version is now current.");
      setAmendReason("");
      await loadHistory({ ...selected, status: "released" });
      void load();
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : "Amendment failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <p className="text-sm text-muted-foreground">
          {rows === null ? "Loading live orders…" : `${total} order${total === 1 ? "" : "s"}`}
        </p>
        <button type="button" className="text-sm underline" onClick={() => void load()}>
          Refresh
        </button>
      </div>

      <div className="flex flex-wrap gap-2">
        {STATUS_FILTERS.map((filter) => (
          <button
            key={filter.value}
            type="button"
            onClick={() => setStatusFilter(filter.value)}
            className={`rounded-md border px-3 py-1 text-sm ${
              statusFilter === filter.value ? "border-primary text-primary" : "border-border"
            }`}
          >
            {filter.label}
          </button>
        ))}
      </div>

      {rows === null && !error ? <LoadingState label="Loading live lab orders" /> : null}
      {error ? <ErrorState message={error} onRetry={() => void load()} /> : null}
      {message ? (
        <p role="status" className="rounded-md bg-success-muted p-3 text-sm text-success">
          {message}
        </p>
      ) : null}

      {rows?.length === 0 ? (
        <EmptyState title="Worklist clear" description="No lab orders match this filter." />
      ) : null}

      {rows && rows.length > 0 ? (
        <>
          <div className="surface-card overflow-hidden">
            <div className="overflow-x-auto">
              <table className="min-w-full border-collapse text-sm">
                <caption className="sr-only">Live laboratory worklist</caption>
                <thead className="bg-muted">
                  <tr>
                    {[
                      "Accession",
                      "Test",
                      "Sample",
                      "Barcode",
                      "Specimen",
                      "Status",
                      "Ordered",
                      "Actions",
                    ].map((label) => (
                      <th key={label} scope="col" className="px-4 py-3 text-left">
                        {label}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {rows.map((row) => (
                    <tr key={row.id} className="border-b border-border last:border-none">
                      <td className="px-4 py-3 font-mono">{row.accession_number}</td>
                      <td className="px-4 py-3 font-medium">{row.test_name}</td>
                      <td className="px-4 py-3">{row.sample_type}</td>
                      <td className="px-4 py-3">{row.barcode ?? "Not collected"}</td>
                      <td className="px-4 py-3">
                        <SpecimenStatusChip status={row.specimen_status} />
                      </td>
                      <td className="px-4 py-3">
                        <StatusChip status={row.status} />
                      </td>
                      <td className="px-4 py-3">{formatDateTime(row.created_at)}</td>
                      <td className="px-4 py-3 text-right">
                        <button type="button" className="underline" onClick={() => selectRow(row)}>
                          Open
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          {totalPages > 1 ? (
            <div className="flex items-center justify-between text-sm">
              <button
                type="button"
                disabled={page <= 1}
                className="rounded-md border border-border px-3 py-1 disabled:opacity-40"
                onClick={() => setPage((current) => Math.max(1, current - 1))}
              >
                Previous
              </button>
              <span className="text-muted-foreground">
                Page {page} of {totalPages}
              </span>
              <button
                type="button"
                disabled={page >= totalPages}
                className="rounded-md border border-border px-3 py-1 disabled:opacity-40"
                onClick={() => setPage((current) => Math.min(totalPages, current + 1))}
              >
                Next
              </button>
            </div>
          ) : null}
        </>
      ) : null}

      {selected ? (
        <section className="surface-card space-y-5 p-6">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <h2 className="text-lg font-medium">{selected.test_name}</h2>
              <p className="text-sm text-muted-foreground">
                {selected.accession_number} · {selected.sample_type}
              </p>
            </div>
            <StatusChip status={selected.status} />
          </div>

          {!canManageResults && (
            <p className="text-sm text-muted-foreground">
              Read-only result view. Sample collection, result entry and verification are handled by lab professionals.
            </p>
          )}

          {/* Specimen Quality Control & Lifecycle */}
          <div className="rounded-lg border border-border bg-muted/20 p-4 space-y-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="flex items-center gap-2">
                <span className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                  Specimen Status:
                </span>
                <SpecimenStatusChip status={selected.specimen_status} />
                {selected.recollected_from_id && (
                  <span className="rounded-full bg-purple-500/10 px-2 py-0.5 text-[10px] font-medium text-purple-600 dark:text-purple-300">
                    Linked Recollection
                  </span>
                )}
              </div>
              <button
                type="button"
                onClick={() => void handleOpenTimeline()}
                className="inline-flex items-center gap-1 text-xs font-medium text-primary hover:underline"
              >
                <History size={13} /> Specimen Timeline
              </button>
            </div>

            {selected.specimen_status === "rejected" && (
              <div className="rounded-md border border-red-300 bg-red-50 p-3 text-xs text-red-800 dark:border-red-900/60 dark:bg-red-950/40 dark:text-red-200">
                <div className="font-semibold flex items-center gap-1.5 text-red-700 dark:text-red-300">
                  <XCircle size={15} /> Specimen Rejected: {selected.rejection_reason?.replaceAll("_", " ")}
                </div>
                <p className="mt-1 text-muted-foreground">
                  The collected sample did not meet lab quality standards. Order a linked recollection to notify phlebotomy.
                </p>
                {canManageResults && (
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => void handleRecollectSpecimen()}
                    className="mt-3 inline-flex items-center gap-1.5 rounded-md bg-red-600 px-3 py-1.5 text-xs font-semibold text-white shadow-xs hover:bg-red-700 disabled:opacity-50"
                  >
                    <RotateCcw size={13} /> Order Recollection (Spawn Linked Specimen)
                  </button>
                )}
              </div>
            )}

            {canManageResults && selected.specimen_status === "collected" && (
              <div className="flex flex-wrap items-center gap-2 pt-1">
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => void handleReceiveSpecimen()}
                  className="rounded-md bg-emerald-600 px-3 py-1.5 text-xs font-semibold text-white shadow-xs hover:bg-emerald-700 disabled:opacity-50"
                >
                  Receive at Bench
                </button>
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => setRejectModalOpen(true)}
                  className="rounded-md border border-red-300 bg-red-50 px-3 py-1.5 text-xs font-semibold text-red-700 shadow-xs hover:bg-red-100 dark:border-red-900 dark:bg-red-950/40 dark:text-red-300 disabled:opacity-50"
                >
                  Reject Specimen
                </button>
              </div>
            )}

            {canManageResults && selected.specimen_status === "received" && (
              <div className="flex flex-wrap items-center gap-2 pt-1">
                <span className="text-xs text-emerald-600 dark:text-emerald-400 font-medium">
                  ✓ Sample verified & ready for bench testing
                </span>
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => setRejectModalOpen(true)}
                  className="rounded-md border border-red-200 px-2.5 py-1 text-xs text-red-600 hover:bg-red-50 dark:border-red-900 dark:hover:bg-red-950/30"
                >
                  Reject on Bench Defect
                </button>
              </div>
            )}
          </div>

          {canManageResults && selected.status === "placed" ? (
            <div className="space-y-3">
              <label className="block max-w-md space-y-1 text-sm">
                <span className="text-muted-foreground">Sample barcode</span>
                <input
                  className="w-full rounded-md border border-border px-3 py-2"
                  value={barcode}
                  onChange={(event) => setBarcode(event.target.value)}
                  placeholder="Scan or enter barcode"
                />
              </label>
              <button
                type="button"
                disabled={busy}
                onClick={() => void collectSample()}
                className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground disabled:opacity-50"
              >
                {busy ? "Saving…" : "Confirm sample collection"}
              </button>
            </div>
          ) : null}

          {canManageResults && selected.status === "in_progress" ? (
            <div className="space-y-4">
              {analytes.length > 0 && (
                <div className="flex items-center justify-between border-b border-border pb-2">
                  <span className="text-xs text-muted-foreground">
                    {useStructured
                      ? "Structured analyte entry mode"
                      : "Raw JSON object mode"}
                  </span>
                  <button
                    type="button"
                    onClick={() => setUseStructured(!useStructured)}
                    className="text-xs text-primary underline hover:text-primary/80"
                  >
                    {useStructured
                      ? "Switch to Raw JSON"
                      : "Switch to Structured Form"}
                  </button>
                </div>
              )}

              {analytes.length > 0 && useStructured ? (
                <StructuredResultForm
                  analytes={analytes}
                  testName={selected.test_name}
                  initialRemarks={remarks}
                  busy={busy}
                  onSubmit={async (resultData, formRemarks) => {
                    setBusy(true);
                    setError(null);
                    try {
                      const result = await enterLabResult(
                        selected.id,
                        resultData,
                        formRemarks,
                      );
                      updateRow({ ...selected, status: "completed" });
                      setHistory([result]);
                      setMessage(
                        "Preliminary result saved with structured clinical flags. A different lab professional must verify and release it.",
                      );
                    } catch (reason) {
                      setError(
                        reason instanceof ApiError
                          ? reason.message
                          : "Result entry failed",
                      );
                    } finally {
                      setBusy(false);
                    }
                  }}
                />
              ) : (
                <>
                  <label className="block space-y-1 text-sm">
                    <span className="text-muted-foreground">Result data (JSON object)</span>
                    <textarea
                      className="min-h-48 w-full rounded-md border border-border px-3 py-2 font-mono text-sm"
                      value={resultJson}
                      onChange={(event) => setResultJson(event.target.value)}
                      spellCheck={false}
                    />
                  </label>
                  {selected.test_name.toLowerCase().includes("hemoglobin") ? (
                    <p className="text-xs text-muted-foreground">
                      Use numeric field <code>hemoglobin_g_dl</code>; configured critical limits are
                      below 7.0 or above 20.0 g/dL.
                    </p>
                  ) : (
                    <p className="text-xs text-muted-foreground">
                      Enter fields authorized by the lab SOP; the server preserves the JSON exactly.
                    </p>
                  )}
                  <label className="block space-y-1 text-sm">
                    <span className="text-muted-foreground">Remarks</span>
                    <textarea
                      className="min-h-20 w-full rounded-md border border-border px-3 py-2"
                      value={remarks}
                      onChange={(event) => setRemarks(event.target.value)}
                    />
                  </label>
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => void enterResult()}
                    className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground disabled:opacity-50"
                  >
                    {busy ? "Saving…" : "Save preliminary result"}
                  </button>
                </>
              )}
            </div>
          ) : null}


          {canManageResults && selected.status === "completed" ? (
            <div className="space-y-3 rounded-md border border-warning bg-warning-muted p-4 text-sm">
              <p>
                This preliminary result needs independent verification. The user who entered it is
                blocked by the server from verifying it.
              </p>
              <button
                type="button"
                disabled={busy}
                onClick={() => void verifyResult()}
                className="rounded-md bg-primary px-4 py-2 font-medium text-primary-foreground disabled:opacity-50"
              >
                {busy ? "Verifying…" : "Verify and release"}
              </button>
            </div>
          ) : null}

          {selected.status === "released" ? (
            <div className="space-y-4">
              <p className="rounded-md bg-success-muted p-3 text-sm text-success">
                Result verified and released.
              </p>
              {canManageResults && (currentResult?.status === "final" || currentResult?.status === "corrected") ? (
                <div className="space-y-3 rounded-md border border-border p-4">
                  <h3 className="font-medium">Amend released result</h3>
                  <p className="text-xs text-muted-foreground">
                    Creates a new corrected version. The original final result stays in history.
                  </p>
                  <label className="block space-y-1 text-sm">
                    <span className="text-muted-foreground">Amendment reason</span>
                    <input
                      className="w-full rounded-md border border-border px-3 py-2"
                      value={amendReason}
                      onChange={(event) => setAmendReason(event.target.value)}
                      placeholder="Why is this result being corrected?"
                    />
                  </label>
                  <label className="block space-y-1 text-sm">
                    <span className="text-muted-foreground">Updated result data (optional JSON)</span>
                    <textarea
                      className="min-h-32 w-full rounded-md border border-border px-3 py-2 font-mono text-sm"
                      value={amendJson}
                      onChange={(event) => setAmendJson(event.target.value)}
                      spellCheck={false}
                    />
                  </label>
                  <label className="block space-y-1 text-sm">
                    <span className="text-muted-foreground">Updated remarks</span>
                    <textarea
                      className="min-h-16 w-full rounded-md border border-border px-3 py-2"
                      value={amendRemarks}
                      onChange={(event) => setAmendRemarks(event.target.value)}
                    />
                  </label>
                  <button
                    type="button"
                    disabled={busy || !amendReason.trim()}
                    onClick={() => void submitAmendment()}
                    className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground disabled:opacity-50"
                  >
                    {busy ? "Saving…" : "Submit amendment"}
                  </button>
                </div>
              ) : null}
            </div>
          ) : null}

          <ResultHistory items={history} />
        </section>
      ) : null}

      {/* Specimen Rejection Modal */}
      {rejectModalOpen && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4 backdrop-blur-xs"
          role="dialog"
          aria-modal="true"
        >
          <div className="w-full max-w-md rounded-xl border border-border bg-card p-6 shadow-xl">
            <div className="flex items-center justify-between border-b border-border pb-3">
              <h3 className="font-semibold text-base text-foreground flex items-center gap-2 text-red-600 dark:text-red-400">
                <AlertCircle size={18} /> Reject Laboratory Specimen
              </h3>
              <button
                type="button"
                onClick={() => setRejectModalOpen(false)}
                className="rounded-lg p-1 text-muted-foreground hover:bg-muted hover:text-foreground"
              >
                <X size={18} />
              </button>
            </div>

            <div className="mt-4 space-y-4">
              <label className="block space-y-1 text-xs">
                <span className="font-semibold text-foreground">Rejection Reason *</span>
                <select
                  value={rejectionReason}
                  onChange={(e) => setRejectionReason(e.target.value)}
                  className="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm text-foreground focus:outline-none focus:ring-1 focus:ring-primary"
                >
                  <option value="hemolyzed">Hemolyzed sample</option>
                  <option value="clotted">Clotted sample</option>
                  <option value="insufficient_quantity">Insufficient specimen volume (QNS)</option>
                  <option value="wrong_container">Wrong specimen container / additive</option>
                  <option value="unlabeled">Unlabeled or mislabeled specimen</option>
                  <option value="broken_tube">Broken container or leak in transit</option>
                  <option value="other">Other reason</option>
                </select>
              </label>

              <label className="block space-y-1 text-xs">
                <span className="font-semibold text-foreground">Notes / Observations</span>
                <textarea
                  value={rejectionNotes}
                  onChange={(e) => setRejectionNotes(e.target.value)}
                  placeholder="Describe specimen defect or reason for rejection..."
                  rows={3}
                  className="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-primary"
                />
              </label>
            </div>

            <div className="mt-6 flex justify-end gap-2 border-t border-border pt-4">
              <button
                type="button"
                onClick={() => setRejectModalOpen(false)}
                className="rounded-lg border border-border px-4 py-2 text-xs font-medium text-foreground hover:bg-muted"
              >
                Cancel
              </button>
              <button
                type="button"
                disabled={busy}
                onClick={() => void handleRejectSpecimen()}
                className="rounded-lg bg-red-600 px-4 py-2 text-xs font-semibold text-white shadow-xs hover:bg-red-700 disabled:opacity-50"
              >
                {busy ? "Rejecting..." : "Confirm Rejection"}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Specimen Timeline Modal */}
      {timelineModalOpen && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4 backdrop-blur-xs"
          role="dialog"
          aria-modal="true"
        >
          <div className="w-full max-w-lg rounded-xl border border-border bg-card p-6 shadow-xl">
            <div className="flex items-center justify-between border-b border-border pb-3">
              <h3 className="font-semibold text-base text-foreground flex items-center gap-2">
                <History size={18} /> Specimen Audit Timeline
              </h3>
              <button
                type="button"
                onClick={() => setTimelineModalOpen(false)}
                className="rounded-lg p-1 text-muted-foreground hover:bg-muted hover:text-foreground"
              >
                <X size={18} />
              </button>
            </div>

            <div className="mt-4 max-h-80 overflow-y-auto space-y-3">
              {loadingEvents ? (
                <div className="py-8 text-center text-xs text-muted-foreground animate-pulse">
                  Loading specimen events...
                </div>
              ) : specimenEvents.length === 0 ? (
                <div className="py-8 text-center text-xs text-muted-foreground">
                  No lifecycle events recorded for this specimen yet.
                </div>
              ) : (
                <div className="relative pl-6 space-y-4 border-l-2 border-primary/30 ml-2">
                  {specimenEvents.map((evt) => (
                    <div key={evt.id} className="relative text-xs">
                      <div className="absolute -left-[31px] top-0.5 h-3 w-3 rounded-full bg-primary ring-4 ring-background" />
                      <div className="font-semibold uppercase tracking-wider text-foreground">
                        {evt.event_type.replaceAll("_", " ")}
                      </div>
                      <div className="text-[11px] text-muted-foreground flex items-center gap-2 mt-0.5">
                        <Clock size={11} /> {formatDateTime(evt.created_at)}
                      </div>
                      {evt.rejection_reason && (
                        <div className="mt-1 text-red-600 dark:text-red-400 font-medium">
                          Reason: {evt.rejection_reason.replaceAll("_", " ")}
                        </div>
                      )}
                      {evt.notes && (
                        <div className="mt-1 text-muted-foreground italic">&ldquo;{evt.notes}&rdquo;</div>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </div>

            <div className="mt-6 flex justify-end border-t border-border pt-3">
              <button
                type="button"
                onClick={() => setTimelineModalOpen(false)}
                className="rounded-lg border border-border px-4 py-1.5 text-xs font-medium text-foreground hover:bg-muted"
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
