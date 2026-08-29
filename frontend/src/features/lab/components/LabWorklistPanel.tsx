"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import {
  amendLabResult,
  collectLabSample,
  enterLabResult,
  getLabResultHistory,
  listLabWork,
  verifyLabResult,
} from "@/features/lab/api";
import type { LabOrderItem, LabResult } from "@/features/lab/types";
import { ApiError, formatDateTime } from "@/lib/api";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/AsyncState";

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
  const [rows, setRows] = useState<LabOrderItem[] | null>(null);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [statusFilter, setStatusFilter] = useState("all");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [history, setHistory] = useState<LabResult[]>([]);
  const [barcode, setBarcode] = useState("");
  const [resultJson, setResultJson] = useState("{}\n");
  const [remarks, setRemarks] = useState("");
  const [amendReason, setAmendReason] = useState("");
  const [amendJson, setAmendJson] = useState("");
  const [amendRemarks, setAmendRemarks] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

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

          {selected.status === "placed" ? (
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

          {selected.status === "in_progress" ? (
            <div className="space-y-4">
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
            </div>
          ) : null}

          {selected.status === "completed" ? (
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
              {currentResult?.status === "final" || currentResult?.status === "corrected" ? (
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
    </div>
  );
}
