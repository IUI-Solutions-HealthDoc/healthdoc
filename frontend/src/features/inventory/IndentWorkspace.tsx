"use client";

/**
 * Department indents: request → HOD approval → pharmacy issue.
 *
 * Three roles, three steps, and the endpoints gate them differently:
 *   create  — pharmacist, admin, hod, nurse, doctor (a ward raises the request)
 *   approve — HOD ONLY (the department head owns the budget)
 *   issue   — pharmacist, admin (the store hands the goods over)
 *
 * The buttons follow those gates rather than showing everything and letting the
 * server refuse. A user who is shown an action they cannot take learns to
 * distrust the screen.
 */
import { useCallback, useEffect, useMemo, useState } from "react";

import { listDepartments } from "@/features/admin/api/departments";
import type { Department } from "@/features/admin/api/departments";
import { searchMedicines } from "@/features/pharmacy/api";
import type { MedicineSearchResult } from "@/features/pharmacy/types";
import { useCurrentUser } from "@/features/session/useCurrentUser";
import { ApiError } from "@/lib/api";

import { createIndent, decideIndent, issueIndent, listIndents } from "./api";
import type { IndentListRow } from "./types";

interface DraftLine {
  item_id: string;
  item_name: string;
  quantity_requested: string;
}

export function IndentWorkspace() {
  const { user } = useCurrentUser();
  const roles = user?.roles ?? [];
  const isHod = roles.includes("hod");
  const canIssue = roles.includes("pharmacist") || roles.includes("admin");

  const [rows, setRows] = useState<IndentListRow[] | null>(null);
  const [departments, setDepartments] = useState<Department[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const [departmentId, setDepartmentId] = useState("");
  const [lines, setLines] = useState<DraftLine[]>([]);
  const [term, setTerm] = useState("");
  const [matches, setMatches] = useState<MedicineSearchResult[]>([]);

  const reload = useCallback(async () => {
    try {
      const [indents, depts] = await Promise.all([listIndents(), listDepartments()]);
      setRows(indents);
      setDepartments(depts.items);
      setError(null);
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : "Could not load indents");
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

  const submit = async () => {
    const ready = lines.filter((l) => l.item_id && Number(l.quantity_requested) > 0);
    if (!departmentId || ready.length === 0) return;
    setBusy(true);
    try {
      await createIndent({
        department_id: departmentId,
        items: ready.map((l) => ({
          item_id: l.item_id,
          quantity_requested: l.quantity_requested,
        })),
      });
      setDepartmentId("");
      setLines([]);
      await reload();
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : "Could not raise the indent");
    } finally {
      setBusy(false);
    }
  };

  const act = async (fn: () => Promise<unknown>, failure: string) => {
    setBusy(true);
    try {
      await fn();
      await reload();
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : failure);
    } finally {
      setBusy(false);
    }
  };

  const canRaise =
    !isHod &&
    (roles.includes("pharmacist") ||
      roles.includes("admin") ||
      roles.includes("nurse") ||
      roles.includes("doctor"));

  const visibleRows = useMemo(() => {
    if (!rows) return null;
    if (isHod) return rows.filter((row) => row.status === "requested");
    return rows;
  }, [isHod, rows]);

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

      {canRaise ? (
      <section className="rounded border border-gray-200 p-4">
        <h3 className="text-base font-semibold">Raise an indent</h3>
        <p className="mt-1 text-sm text-gray-600">
          A request from a department to the store. It needs the department head&apos;s
          approval before pharmacy can issue against it.
        </p>

        <label className="mt-4 block text-sm">
          <span className="block text-gray-700">Requesting department</span>
          <select
            className="mt-1 w-full rounded border border-gray-300 p-2 sm:max-w-sm"
            value={departmentId}
            onChange={(event) => setDepartmentId(event.target.value)}
          >
            <option value="">Select…</option>
            {departments.map((dept) => (
              <option key={dept.id} value={dept.id}>
                {dept.name}
              </option>
            ))}
          </select>
        </label>

        <div className="mt-4">
          <input
            className="w-full rounded border border-gray-300 p-2 text-sm sm:max-w-sm"
            placeholder="Search medicines to add…"
            value={term}
            onChange={(event) => setTerm(event.target.value)}
          />
          {matches.length > 0 ? (
            <ul className="mt-1 max-h-40 max-w-sm overflow-auto rounded border border-gray-200 text-sm">
              {matches.map((match) => (
                <li key={match.item_id}>
                  <button
                    type="button"
                    className="w-full px-2 py-1 text-left hover:bg-gray-100"
                    onClick={() => {
                      setLines((current) =>
                        current.some((l) => l.item_id === match.item_id)
                          ? current
                          : [
                              ...current,
                              {
                                item_id: match.item_id,
                                item_name: match.name,
                                quantity_requested: "",
                              },
                            ],
                      );
                      setTerm("");
                      setMatches([]);
                    }}
                  >
                    {match.name}
                  </button>
                </li>
              ))}
            </ul>
          ) : null}
        </div>

        {lines.length > 0 ? (
          <ul className="mt-4 space-y-2">
            {lines.map((line, index) => (
              <li key={line.item_id} className="flex items-center gap-3 text-sm">
                <span className="flex-1">{line.item_name}</span>
                <input
                  type="number"
                  min="0"
                  step="0.01"
                  placeholder="Qty"
                  className="w-28 rounded border border-gray-300 p-1"
                  value={line.quantity_requested}
                  onChange={(event) =>
                    setLines((current) =>
                      current.map((l, i) =>
                        i === index ? { ...l, quantity_requested: event.target.value } : l,
                      ),
                    )
                  }
                />
                <button
                  type="button"
                  className="text-xs text-blue-700 underline"
                  onClick={() =>
                    setLines((current) => current.filter((_, i) => i !== index))
                  }
                >
                  remove
                </button>
              </li>
            ))}
          </ul>
        ) : null}

        <button
          type="button"
          disabled={busy || !departmentId || lines.length === 0}
          onClick={() => void submit()}
          className="mt-5 rounded bg-blue-700 px-4 py-2 text-sm text-white disabled:bg-gray-300"
        >
          Raise indent
        </button>
      </section>
      ) : null}

      <section>
        <h3 className="text-base font-semibold">{isHod ? "Pending approvals" : "Indents"}</h3>
        {visibleRows === null ? (
          <p className="mt-2 text-sm text-gray-600">Loading…</p>
        ) : visibleRows.length === 0 ? (
          <p className="mt-2 text-sm text-gray-600">
            {isHod ? "No indents awaiting your approval." : "No indents raised."}
          </p>
        ) : (
          <ul className="mt-3 space-y-2">
            {visibleRows.map((row) => (
              <li key={row.id} className="rounded border border-gray-200 p-3 text-sm">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div>
                    <span className="font-medium">{row.department_name}</span>
                    <span className="text-gray-600">
                      {" "}
                      · {row.line_count} line{row.line_count === 1 ? "" : "s"}
                    </span>
                    {row.approved_by_name ? (
                      <span className="text-gray-600"> · approved by {row.approved_by_name}</span>
                    ) : null}
                  </div>
                  <span
                    className={`rounded px-2 py-0.5 text-xs ${
                      row.status === "issued"
                        ? "bg-green-100 text-green-800"
                        : row.status === "rejected"
                          ? "bg-red-100 text-red-800"
                          : row.status === "approved"
                            ? "bg-blue-100 text-blue-800"
                            : "bg-amber-100 text-amber-900"
                    }`}
                  >
                    {row.status}
                  </span>
                </div>

                {row.status === "requested" ? (
                  isHod ? (
                    <div className="mt-2 flex gap-2">
                      <button
                        type="button"
                        disabled={busy}
                        onClick={() =>
                          void act(
                            () => decideIndent(row.id, { approve: true, reason: null }),
                            "Could not approve the indent",
                          )
                        }
                        className="rounded bg-blue-700 px-3 py-1 text-xs text-white disabled:bg-gray-300"
                      >
                        Approve
                      </button>
                      <button
                        type="button"
                        disabled={busy}
                        onClick={() =>
                          void act(
                            () => decideIndent(row.id, { approve: false, reason: null }),
                            "Could not reject the indent",
                          )
                        }
                        className="rounded border border-gray-300 px-3 py-1 text-xs disabled:opacity-50"
                      >
                        Reject
                      </button>
                    </div>
                  ) : (
                    <p className="mt-2 text-xs text-gray-600">
                      Waiting on the department head. Only an HOD can approve an indent.
                    </p>
                  )
                ) : null}

                {row.status === "approved" && canIssue ? (
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() =>
                      void act(() => issueIndent(row.id), "Could not issue the indent")
                    }
                    className="mt-2 rounded bg-blue-700 px-3 py-1 text-xs text-white disabled:bg-gray-300"
                  >
                    Issue stock
                  </button>
                ) : null}
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
