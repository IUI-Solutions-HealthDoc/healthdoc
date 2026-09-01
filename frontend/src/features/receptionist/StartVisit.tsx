"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

import { ApiError, newIdempotencyKey } from "@/lib/api";

import { createVisit, issueToken, listQueues } from "./api";
import {
  BED_OCCUPYING_VISIT_TYPES,
  VISIT_TYPE_LABELS,
  type Patient,
  type QueueSummary,
  type QueueToken,
  type Visit,
  type VisitType,
} from "./types";

type VisitPatient = Pick<Patient, "id" | "full_name" | "uhid" | "thid">;

const RECEPTION_PRIORITIES = [
  { value: "normal", label: "Normal" },
  { value: "senior_citizen", label: "Senior citizen" },
  { value: "pregnant", label: "Pregnant patient" },
  { value: "follow_up_recall", label: "Follow-up recall" },
] as const;

/**
 * Register → visit → token, the rest of the OPD entry point.
 *
 * Registration alone was a dead end: a UHID and nothing else. A visit is what
 * puts the patient into the billing chain (its registration invoice is raised
 * in the same server transaction) and a token is what puts them in front of a
 * doctor.
 */
export function StartVisit({ patient }: { patient: VisitPatient }) {
  const [queues, setQueues] = useState<QueueSummary[] | null>(null);
  const [queueId, setQueueId] = useState<string>("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [token, setToken] = useState<QueueToken | null>(null);
  const [visit, setVisit] = useState<Visit | null>(null);
  const [priority, setPriority] = useState("normal");
  // Was hardcoded to "opd", so a hospital with wards could not admit anyone
  // from the desk (REC-03). OPD stays the default because it is the common
  // case, not because it was the only one.
  const [visitType, setVisitType] = useState<VisitType>("opd");

  // One key per patient, for the same reason the registration form holds one:
  // a retried click must replay the visit, not open a second one and bill a
  // second registration fee.
  const visitKey = useMemo(() => newIdempotencyKey(), []);
  const tokenKey = useMemo(() => newIdempotencyKey(), []);

  useEffect(() => {
    let cancelled = false;
    listQueues()
      .then((rows) => {
        if (cancelled) return;
        setQueues(rows);
        // Shortest queue first from the server, so the first row is the
        // sensible default — but it stays changeable.
        if (rows.length > 0) setQueueId(rows[0].id);
      })
      .catch((reason: unknown) => {
        if (!cancelled) {
          setError(reason instanceof ApiError ? reason.message : "Could not load queues");
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  async function start() {
    if (!queueId) return;
    let visitReady = Boolean(visit);
    setBusy(true);
    setError(null);
    try {
      let activeVisit = visit;
      if (!activeVisit) {
        activeVisit = await createVisit(
          {
            patient_id: patient.id,
            visit_type: visitType,
            visit_date: new Date().toISOString(),
          },
          visitKey,
        );
        setVisit(activeVisit);
        visitReady = true;
      }

      const issued = await issueToken(
        { queue_id: queueId, visit_id: activeVisit.id, priority },
        tokenKey,
      );
      setToken(issued);
    } catch (reason) {
      setError(
        reason instanceof ApiError
          ? reason.message
          : visitReady
            ? "The visit exists, but the token could not be issued. Retry the token; do not create another visit."
            : "Could not start the visit. Retry from this screen so the same request is safely replayed.",
      );
    } finally {
      setBusy(false);
    }
  }

  if (token) {
    return (
      <div className="surface-card space-y-3 p-8 text-center">
        <p className="text-sm text-muted-foreground">Token issued</p>
        <p className="font-mono text-5xl font-bold">{token.token_display}</p>
        <p className="text-sm text-muted-foreground">
          {patient.full_name} · {patient.uhid ?? patient.thid}
        </p>
        {visit && (
          <p className="text-xs text-muted-foreground">Visit {visit.visit_number}</p>
        )}
        <div className="flex flex-wrap justify-center gap-4 pt-2 text-sm">
          <Link href="/receptionist/queue" className="font-medium underline">View queue</Link>
          <Link href="/consent" className="font-medium underline">Record consent</Link>
          <Link href="/billing" className="font-medium underline">Open billing</Link>
        </div>
      </div>
    );
  }

  return (
    <div className="surface-card space-y-4 p-6">
      <h3 className="text-base font-medium">Start visit</h3>

      <label className="block space-y-1 text-sm">
        <span className="text-muted-foreground">Visit type</span>
        <select
          className="w-full rounded-md border border-border px-3 py-2"
          value={visitType}
          onChange={(e) => setVisitType(e.target.value as VisitType)}
          disabled={busy || Boolean(visit)}  /* locked once the visit exists */
        >
          {(Object.keys(VISIT_TYPE_LABELS) as VisitType[]).map((t) => (
            <option key={t} value={t}>{VISIT_TYPE_LABELS[t]}</option>
          ))}
        </select>
        {BED_OCCUPYING_VISIT_TYPES.includes(visitType) && (
          <span className="block text-xs text-muted-foreground">
            Takes a ward bed. The visit is created here; admitting the patient to a
            specific bed is done by the ward from IPD.
          </span>
        )}
      </label>
      <p className="text-sm text-muted-foreground">
        This counter flow creates an OPD visit. Use the IPD workspace for admission after clinical review.
      </p>

      {visit ? (
        <p className="rounded-md border border-warning/30 bg-warning-muted p-3 text-sm">
          Visit {visit.visit_number} was created. Only token issue will be retried.
        </p>
      ) : null}

      {queues === null && !error && (
        <p className="text-sm text-muted-foreground">Loading today&apos;s queues…</p>
      )}

      {queues !== null && queues.length === 0 && (
        <div className="space-y-2">
          <p className="text-sm text-muted-foreground">
            No open queues today. A queue has to be opened for a doctor before
            tokens can be issued.
          </p>
          <Link href="/receptionist/queue" className="inline-block text-sm font-medium underline">
            Open today&apos;s queue
          </Link>
        </div>
      )}

      {queues !== null && queues.length > 0 && (
        <>
          <label className="block space-y-1 text-sm">
            <span className="text-muted-foreground">Doctor</span>
            <select
              className="w-full rounded-md border border-border px-3 py-2"
              value={queueId}
              onChange={(e) => setQueueId(e.target.value)}
              disabled={Boolean(visit)}
            >
              {queues.map((q) => (
                <option key={q.id} value={q.id}>
                  {q.doctor_name ?? "Doctor"}
                  {q.room_number ? ` · Room ${q.room_number}` : ""}
                  {` · ${q.waiting_count} waiting`}
                </option>
              ))}
            </select>
          </label>

          <label className="block space-y-1 text-sm">
            <span className="text-muted-foreground">Queue priority</span>
            <select
              className="w-full rounded-md border border-border px-3 py-2"
              value={priority}
              onChange={(event) => setPriority(event.target.value)}
              disabled={Boolean(visit)}
            >
              {RECEPTION_PRIORITIES.map((option) => (
                <option key={option.value} value={option.value}>{option.label}</option>
              ))}
            </select>
          </label>

          <button
            type="button"
            onClick={() => void start()}
            disabled={busy || !queueId}
            className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
          >
            {busy ? "Starting…" : visit ? "Retry token issue" : "Create visit and issue token"}
          </button>
        </>
      )}

      {error && (
        <p role="alert" className="text-sm text-danger">
          {error}
        </p>
      )}
    </div>
  );
}

export default StartVisit;
