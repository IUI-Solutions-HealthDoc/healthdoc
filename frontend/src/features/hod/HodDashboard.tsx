"use client";

/**
 * The head-of-department's screen.
 *
 * Eight endpoints existed for this role and there was no route, no page and no
 * sidebar entry. An HOD logged in and had nowhere to go: they could approve an
 * indent only by finding it on the storekeeper's inventory screen, and could
 * not see their department's queues, workload, escalations or outstanding lab
 * work at all.
 *
 * THE DEPARTMENT COMES FROM THE SESSION, NOT A PICKER.
 *
 * Every hod-dashboard endpoint is gated `require_roles("hod", "admin")` and
 * scoped to the caller's FACILITY — the department is a path parameter the
 * server does not check against the caller. A picker would therefore let the
 * head of Medicine read Surgery's workload and pending approvals. So the screen
 * reads `department` from /users/me and offers no choice.
 *
 * An admin has no department and legitimately oversees all of them; rather than
 * invent a picker for them here, the screen says plainly that it is a
 * departmental view. Giving admins a cross-department version is a real feature
 * with its own scoping questions, not a dropdown.
 */
import { useCallback, useEffect, useState } from "react";

import { useCurrentUser } from "@/features/session/useCurrentUser";
import { ApiError } from "@/lib/api";

import {
  getOverview,
  getWorkload,
  listEscalations,
  listPendingApprovals,
  listPendingLabOrders,
} from "./api";
import { RosterManager } from "./RosterManager";
import type {
  DepartmentWorkload,
  EmergencyEscalation,
  HodOverview,
  PendingApproval,
  PendingLabOrder,
} from "./types";

/**
 * The business date, as the FACILITY reckons it.
 *
 * `overview_date` and `workload_date` are required parameters with no server
 * default, and the day boundary that matters is the hospital's, not the
 * browser's. A device left on UTC would otherwise ask for yesterday's dashboard
 * for the first five and a half hours of every Indian working day — the same
 * business-date rule the backend applies with
 * `(now() AT TIME ZONE facilities.timezone)::date`.
 */
function facilityToday(timezone: string): string {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: timezone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(new Date());
}

function Stat({ label, value, tone }: { label: string; value: number; tone?: string }) {
  return (
    <div className="rounded border border-border p-4">
      <p className="text-sm text-muted-foreground">{label}</p>
      <p className={`mt-1 text-2xl font-semibold tabular-nums ${tone ?? ""}`}>{value}</p>
    </div>
  );
}

export function HodDashboard() {
  const { user, loading: sessionLoading } = useCurrentUser();
  const department = user?.department ?? null;

  const [overview, setOverview] = useState<HodOverview | null>(null);
  const [workload, setWorkload] = useState<DepartmentWorkload | null>(null);
  const [escalations, setEscalations] = useState<EmergencyEscalation[]>([]);
  const [labOrders, setLabOrders] = useState<PendingLabOrder[]>([]);
  const [approvals, setApprovals] = useState<PendingApproval[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    if (!department || !user) return;
    setLoading(true);
    const today = facilityToday(user.facility.timezone);
    try {
      // Loaded together: a head looking at "waiting" alongside "escalations"
      // needs both to describe the same moment. Staggered fetches would show a
      // count that no single instant produced.
      const [ov, wl, esc, labs, appr] = await Promise.all([
        getOverview(department.id, today),
        getWorkload(department.id, today),
        listEscalations(department.id),
        listPendingLabOrders(department.id),
        listPendingApprovals(department.id),
      ]);
      setOverview(ov);
      setWorkload(wl);
      setEscalations(esc);
      setLabOrders(labs);
      setApprovals(appr);
      setError(null);
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : "Could not load the dashboard");
    } finally {
      setLoading(false);
    }
  }, [department, user]);

  useEffect(() => {
    void load();
  }, [load]);

  if (sessionLoading) {
    return <p className="p-6 text-sm text-muted-foreground">Loading…</p>;
  }

  // No department, no dashboard — and say why rather than rendering empty
  // panels that look like a quiet day.
  if (!department) {
    return (
      <div className="space-y-3 p-6">
        <h1 className="text-3xl font-semibold">Department dashboard</h1>
        <p className="max-w-prose text-sm text-muted-foreground">
          This is a departmental view and your account is not attached to a
          department. Facility-wide roles such as admin and auditor have no home
          department, so there is nothing to scope this screen to.
        </p>
        <p className="max-w-prose text-sm text-muted-foreground">
          If you head a department and are seeing this, your user record needs a
          department set — an administrator can do that from Administration →
          Users.
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-8 p-6">
      <div className="flex flex-wrap items-baseline justify-between gap-4">
        <div>
          <h1 className="text-3xl font-semibold">{department.name}</h1>
          <p className="mt-2 text-sm text-muted-foreground">
            Queues, workload and approvals for {facilityToday(user!.facility.timezone)} at{" "}
            {user!.facility.name}.
          </p>
        </div>
        <button type="button" className="text-sm underline" onClick={() => void load()}>
          Refresh
        </button>
      </div>

      {error ? (
        <p role="alert" className="rounded-md bg-danger-muted p-3 text-sm text-danger">
          {error}
        </p>
      ) : null}

      {loading && !workload ? (
        <p className="text-sm text-muted-foreground">Loading…</p>
      ) : null}

      {workload ? (
        <section className="grid gap-4 sm:grid-cols-4">
          <Stat label="Waiting now" value={workload.total_waiting} />
          <Stat label="Queues open" value={workload.queues_open} />
          <Stat label="Queues closed" value={workload.queues_closed} />
          <Stat label="Completed today" value={workload.completed_today} />
        </section>
      ) : null}

      {escalations.length > 0 ? (
        <section className="space-y-3">
          <h2 className="text-xl font-semibold text-danger">
            Emergency escalations ({escalations.length})
          </h2>
          <p className="text-sm text-muted-foreground">
            Tokens raised to emergency priority and not yet seen. Listed first
            because these are the ones where waiting has a clinical cost.
          </p>
          <ul className="space-y-2">
            {escalations.map((e) => (
              <li
                key={e.token_id}
                className="rounded border border-danger p-3 text-sm"
              >
                <span className="font-medium">{e.token_display}</span>
                <span className="text-muted-foreground">
                  {" "}
                  · {e.status}
                  {e.doctor_name ? ` · ${e.doctor_name}` : " · no doctor assigned"}
                </span>
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      <section className="space-y-3">
        <h2 className="text-xl font-semibold">Queues</h2>
        {overview && overview.queues.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            No queues opened in this department today.
          </p>
        ) : null}
        <ul className="space-y-2">
          {overview?.queues.map((q) => (
            <li key={q.queue_id} className="rounded border border-border p-3 text-sm">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <span className="font-medium">
                  {q.doctor_name ?? "Unassigned"}
                </span>
                <span
                  className={`rounded px-2 py-0.5 text-xs ${
                    q.is_open
                      ? "bg-green-100 text-green-800"
                      : "bg-gray-100 text-gray-700"
                  }`}
                >
                  {q.is_open ? "open" : "closed"}
                </span>
              </div>
              <p className="mt-1 text-muted-foreground">
                {q.waiting_count} waiting
                {q.now_serving ? ` · now serving ${q.now_serving}` : " · none called yet"}
              </p>
            </li>
          ))}
        </ul>
      </section>

      <section className="space-y-3">
        <h2 className="text-xl font-semibold">
          Indents awaiting your approval ({approvals.length})
        </h2>
        <p className="text-sm text-muted-foreground">
          Approval is a departmental budget decision, so these are yours rather
          than the storekeeper&apos;s. Approve or reject them from Inventory →
          Indents.
        </p>
        {approvals.length === 0 ? (
          <p className="text-sm text-muted-foreground">Nothing waiting.</p>
        ) : (
          <ul className="space-y-2">
            {approvals.map((a) => (
              <li key={a.indent_id} className="rounded border border-border p-3 text-sm">
                <p className="font-medium">
                  {a.items.length} item{a.items.length === 1 ? "" : "s"}
                </p>
                <ul className="mt-1 text-muted-foreground">
                  {a.items.map((item) => (
                    <li key={item.item_id}>
                      {item.item_name ?? "Unnamed item"} — {item.quantity_requested}
                    </li>
                  ))}
                </ul>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="space-y-3">
        <h2 className="text-xl font-semibold">
          Outstanding lab work ({labOrders.length})
        </h2>
        {labOrders.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            Nothing outstanding for this department.
          </p>
        ) : (
          <div className="surface-card overflow-hidden">
            <table className="min-w-full border-collapse text-sm">
              <thead className="bg-muted">
                <tr>
                  <th className="px-4 py-3 text-left">Accession</th>
                  <th className="px-4 py-3 text-left">Test</th>
                  <th className="px-4 py-3 text-left">Status</th>
                  <th className="px-4 py-3 text-right">Est. minutes</th>
                </tr>
              </thead>
              <tbody>
                {labOrders.map((o) => (
                  <tr
                    key={o.lab_order_item_id}
                    className="border-b border-border last:border-none"
                  >
                    <td className="px-4 py-3 font-mono text-xs">{o.accession_number}</td>
                    <td className="px-4 py-3">{o.test_name}</td>
                    <td className="px-4 py-3">{o.status}</td>
                    <td className="px-4 py-3 text-right tabular-nums">
                      {/* Null means no published turnaround, which is not the
                          same as zero. */}
                      {o.estimated_minutes ?? "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <RosterManager
        departmentId={department.id}
        today={facilityToday(user!.facility.timezone)}
      />
    </div>
  );
}
