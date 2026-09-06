"use client";

/**
 * Stock adjustments — a two-person control, rendered as one.
 *
 * A stock adjustment moves a number without moving any goods. It is therefore
 * the instrument by which shrinkage is concealed: write off what walked out,
 * and the ledger reconciles. The database knows this and enforces separation of
 * duties with FOUR CHECK constraints:
 *
 *   created_by        <> first_approver_id
 *   created_by        <> second_approver_id
 *   first_approver_id <> second_approver_id
 *   status = 'approved' requires second_approver_id
 *
 * Three distinct people before a quantity changes. This screen's job is to make
 * that visible rather than to let someone discover it as a 422 — a control the
 * user only meets as an error is one they will work around.
 *
 * So: the submitter is never offered as first approver, the rule is stated
 * before submission rather than after, and every pending row names who has
 * already signed so the countersigner knows whose judgement they are joining.
 */
import { useCallback, useEffect, useState } from "react";

import { searchMedicines } from "@/features/pharmacy/api";
import type { BatchAvailability, MedicineSearchResult } from "@/features/pharmacy/types";
import { useCurrentUser } from "@/features/session/useCurrentUser";
import { ApiError } from "@/lib/api";

import { createAdjustment, decideAdjustment, listAdjustmentCandidates, listAdjustments } from "./api";
import type { AdjustmentListRow, ApproverCandidate } from "./types";

export function AdjustmentWorkspace() {
  const { user } = useCurrentUser();
  const [rows, setRows] = useState<AdjustmentListRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const [term, setTerm] = useState("");
  const [matches, setMatches] = useState<MedicineSearchResult[]>([]);
  const [item, setItem] = useState<MedicineSearchResult | null>(null);
  const [batch, setBatch] = useState<BatchAvailability | null>(null);
  const [change, setChange] = useState("");
  const [reason, setReason] = useState("");

  const [approverTerm, setApproverTerm] = useState("");
  const [approvers, setApprovers] = useState<ApproverCandidate[]>([]);
  const [approverError, setApproverError] = useState<string | null>(null);
  const [firstApprover, setFirstApprover] = useState<ApproverCandidate | null>(null);

  const reload = useCallback(async () => {
    try {
      setRows(await listAdjustments());
      setError(null);
    } catch (reason_) {
      setError(reason_ instanceof ApiError ? reason_.message : "Could not load adjustments");
    }
  }, []);

  useEffect(() => {
    void reload();
  }, [reload]);

  useEffect(() => {
    const q = term.trim();
    if (q.length < 2) {
      setMatches([]);
      return;
    }
    let cancelled = false;
    const timer = setTimeout(() => {
      searchMedicines(q)
        .then((r) => !cancelled && setMatches(r.items))
        .catch(() => !cancelled && setMatches([]));
    }, 250);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [term]);

  useEffect(() => {
    const q = approverTerm.trim();
    if (q.length < 2) {
      setApprovers([]);
      return;
    }
    let cancelled = false;
    const timer = setTimeout(() => {
      listAdjustmentCandidates(q)
        .then((candidates) => {
          if (cancelled) return;
          setApproverError(null);
          // The submitter cannot be their own first approver — the server
          // refuses it 422 and the database refuses it again. The endpoint
          // already excludes the caller; this is belt and braces against a
          // stale token identity.
          setApprovers(candidates.filter((candidate) => candidate.id !== user?.id));
        })
        .catch((reason: unknown) => {
          if (cancelled) return;
          // Never swallow this. The previous version returned an empty list on
          // failure, so a lookup that was actually being refused looked exactly
          // like a colleague who does not work here.
          setApprovers([]);
          setApproverError(
            reason instanceof ApiError ? reason.message : "Could not search staff",
          );
        });
    }, 250);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [approverTerm, user?.id]);

  const resultingQuantity =
    batch && change !== "" && !Number.isNaN(Number(change))
      ? Number(batch.quantity) + Number(change)
      : null;

  const wouldGoNegative = resultingQuantity !== null && resultingQuantity < 0;

  const canSubmit =
    Boolean(item && batch && firstApprover) &&
    change !== "" &&
    Number(change) !== 0 &&
    reason.trim().length > 0 &&
    !wouldGoNegative &&
    !busy;

  const submit = async () => {
    if (!item || !batch || !firstApprover) return;
    setBusy(true);
    try {
      await createAdjustment({
        item_id: item.item_id,
        batch_id: batch.batch_id,
        quantity_change: change,
        reason: reason.trim(),
        first_approver_id: firstApprover.id,
      });
      setItem(null);
      setBatch(null);
      setChange("");
      setReason("");
      setFirstApprover(null);
      setApproverTerm("");
      setTerm("");
      await reload();
    } catch (reason_) {
      setError(
        reason_ instanceof ApiError ? reason_.message : "Could not propose the adjustment",
      );
    } finally {
      setBusy(false);
    }
  };

  const decide = async (id: string, approve: boolean) => {
    setBusy(true);
    try {
      await decideAdjustment(id, { approve, reason: null });
      await reload();
    } catch (reason_) {
      setError(reason_ instanceof ApiError ? reason_.message : "Could not record the decision");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-8">
      {error ? (
        <p
          role="alert"
          className="rounded border border-red-300 bg-red-50 p-3 text-sm text-red-800"
        >
          {error}
        </p>
      ) : null}

      <section className="rounded border border-gray-200 p-4">
        <h3 className="text-base font-semibold">Propose an adjustment</h3>
        <p className="mt-1 text-sm text-gray-600">
          Nothing changes when you submit. The adjustment is recorded as pending and
          takes effect only once a second person, different from you and from the
          approver you nominate, countersigns it.
        </p>

        <div className="mt-4 space-y-3">
          <div>
            <span className="block text-sm text-gray-700">Item</span>
            {item ? (
              <div className="mt-1 flex items-center justify-between rounded bg-gray-50 p-2 text-sm">
                <span>{item.name}</span>
                <button
                  type="button"
                  className="text-xs text-blue-700 underline"
                  onClick={() => {
                    setItem(null);
                    setBatch(null);
                  }}
                >
                  change
                </button>
              </div>
            ) : (
              <>
                <input
                  className="mt-1 w-full rounded border border-gray-300 p-2"
                  placeholder="Search medicines…"
                  value={term}
                  onChange={(event) => setTerm(event.target.value)}
                />
                {matches.length > 0 ? (
                  <ul className="mt-1 max-h-40 overflow-auto rounded border border-gray-200 text-sm">
                    {matches.map((match) => (
                      <li key={match.item_id}>
                        <button
                          type="button"
                          className="w-full px-2 py-1 text-left hover:bg-gray-100"
                          onClick={() => {
                            setItem(match);
                            setMatches([]);
                            setTerm("");
                          }}
                        >
                          {match.name}
                          <span className="text-gray-500">
                            {" "}
                            · {match.batches.length} batch
                            {match.batches.length === 1 ? "" : "es"} in stock
                          </span>
                        </button>
                      </li>
                    ))}
                  </ul>
                ) : null}
              </>
            )}
          </div>

          {item ? (
            <div>
              <span className="block text-sm text-gray-700">Batch</span>
              {item.batches.length === 0 ? (
                <p className="mt-1 text-sm text-amber-800">
                  No batches with stock on hand. Search only returns batches holding a
                  positive quantity, so a batch that has already reached zero cannot be
                  adjusted from this screen.
                </p>
              ) : (
                <select
                  className="mt-1 w-full rounded border border-gray-300 p-2 text-sm"
                  value={batch?.batch_id ?? ""}
                  onChange={(event) =>
                    setBatch(
                      item.batches.find((b) => b.batch_id === event.target.value) ?? null,
                    )
                  }
                >
                  <option value="">Select a batch…</option>
                  {item.batches.map((b) => (
                    <option key={b.batch_id} value={b.batch_id}>
                      {b.batch_number} · expires {b.expiry_date} · {b.quantity} on hand
                    </option>
                  ))}
                </select>
              )}
            </div>
          ) : null}

          <div className="grid gap-3 sm:grid-cols-2">
            <label className="text-sm">
              <span className="block text-gray-700">
                Change (negative to write down)
              </span>
              <input
                type="number"
                step="0.01"
                className="mt-1 w-full rounded border border-gray-300 p-2"
                value={change}
                onChange={(event) => setChange(event.target.value)}
              />
            </label>
            <label className="text-sm">
              <span className="block text-gray-700">Reason</span>
              <input
                className="mt-1 w-full rounded border border-gray-300 p-2"
                placeholder="Damaged in transit, count correction…"
                value={reason}
                onChange={(event) => setReason(event.target.value)}
              />
            </label>
          </div>

          {batch && resultingQuantity !== null ? (
            <p
              className={`text-sm ${wouldGoNegative ? "text-red-700" : "text-gray-700"}`}
            >
              {batch.quantity} on hand → <strong>{resultingQuantity}</strong> after this
              adjustment.
              {wouldGoNegative ? (
                <>
                  {" "}
                  A batch cannot hold less than nothing — the database refuses it
                  (quantity &gt;= 0), so this would be rejected on approval rather than
                  now.
                </>
              ) : null}
            </p>
          ) : null}

          <div>
            <span className="block text-sm text-gray-700">First approver</span>
            <p className="text-xs text-gray-600">
              Someone other than you. You cannot approve your own adjustment.
            </p>
            {firstApprover ? (
              <div className="mt-1 flex items-center justify-between rounded bg-gray-50 p-2 text-sm">
                <span>{firstApprover.full_name}</span>
                <button
                  type="button"
                  className="text-xs text-blue-700 underline"
                  onClick={() => setFirstApprover(null)}
                >
                  change
                </button>
              </div>
            ) : (
              <>
                <input
                  className="mt-1 w-full rounded border border-gray-300 p-2"
                  placeholder="Search staff…"
                  value={approverTerm}
                  onChange={(event) => setApproverTerm(event.target.value)}
                />
                {approvers.length > 0 ? (
                  <ul className="mt-1 max-h-40 overflow-auto rounded border border-gray-200 text-sm">
                    {approvers.map((candidate) => (
                      <li key={candidate.id}>
                        <button
                          type="button"
                          className="w-full px-2 py-1 text-left hover:bg-gray-100"
                          onClick={() => {
                            setFirstApprover(candidate);
                            setApprovers([]);
                            setApproverTerm("");
                          }}
                        >
                          {candidate.full_name}
                        </button>
                      </li>
                    ))}
                  </ul>
                ) : null}
                {approverError ? (
                  <p role="alert" className="mt-1 text-xs text-danger">
                    {approverError}
                  </p>
                ) : null}
              </>
            )}
          </div>
        </div>

        <button
          type="button"
          disabled={!canSubmit}
          onClick={() => void submit()}
          className="mt-5 rounded bg-blue-700 px-4 py-2 text-sm text-white disabled:bg-gray-300"
        >
          Propose adjustment
        </button>
      </section>

      <section>
        <h3 className="text-base font-semibold">Adjustments</h3>
        {rows === null ? (
          <p className="mt-2 text-sm text-gray-600">Loading…</p>
        ) : rows.length === 0 ? (
          <p className="mt-2 text-sm text-gray-600">No adjustments recorded.</p>
        ) : (
          <ul className="mt-3 space-y-2">
            {rows.map((row) => {
              const isWriteDown = Number(row.quantity_change) < 0;
              // A countersigner must be neither the proposer nor the first
              // approver. Both are named on the row so the rule is checkable by
              // the person it applies to.
              const currentUserAlreadyInChain =
                user?.id === row.created_by || user?.id === row.first_approver_id;
              return (
                <li key={row.id} className="rounded border border-gray-200 p-3 text-sm">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div>
                      <span className="font-medium">{row.item_name}</span>
                      <span className="text-gray-600">
                        {" "}
                        · batch {row.batch_number} · expires {row.expiry_date}
                      </span>
                    </div>
                    <span
                      className={`rounded px-2 py-0.5 text-xs ${
                        row.status === "approved"
                          ? "bg-green-100 text-green-800"
                          : row.status === "rejected"
                            ? "bg-red-100 text-red-800"
                            : "bg-amber-100 text-amber-900"
                      }`}
                    >
                      {row.status}
                    </span>
                  </div>

                  <p className="mt-1">
                    <strong className={isWriteDown ? "text-red-700" : "text-gray-900"}>
                      {isWriteDown ? "" : "+"}
                      {row.quantity_change}
                    </strong>{" "}
                    against {row.quantity_on_hand} on hand — {row.reason}
                  </p>

                  <p className="mt-1 text-xs text-gray-600">
                    Proposed by {row.created_by_name} · first approver{" "}
                    {row.first_approver_name}
                    {row.second_approver_name
                      ? ` · countersigned by ${row.second_approver_name}`
                      : " · awaiting a countersignature"}
                  </p>

                  {row.status === "pending" ? (
                    currentUserAlreadyInChain ? (
                      <p className="mt-2 text-xs text-gray-600">
                        You are already named on this adjustment, so you cannot be its
                        second approver.
                      </p>
                    ) : (
                      <div className="mt-2 flex gap-2">
                        <button
                          type="button"
                          disabled={busy}
                          onClick={() => void decide(row.id, true)}
                          className="rounded bg-blue-700 px-3 py-1 text-xs text-white disabled:bg-gray-300"
                        >
                          Countersign
                        </button>
                        <button
                          type="button"
                          disabled={busy}
                          onClick={() => void decide(row.id, false)}
                          className="rounded border border-gray-300 px-3 py-1 text-xs disabled:opacity-50"
                        >
                          Reject
                        </button>
                      </div>
                    )
                  ) : null}
                </li>
              );
            })}
          </ul>
        )}
      </section>
    </div>
  );
}
