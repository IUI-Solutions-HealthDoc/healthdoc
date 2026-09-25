"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

import { ApiError, newIdempotencyKey } from "@/lib/api";
import { canRoleAccessPath } from "@/lib/auth/routes";
import { useLocale, type MessageKey } from "@/lib/i18n";
import { useAuth } from "@/providers/auth-provider";
import { useDeskCounter } from "./useDeskCounter";

import { createVisit, issueToken, listQueues } from "./api";
import {
  BED_OCCUPYING_VISIT_TYPES,
  TOKEN_ISSUING_VISIT_TYPES,
  VISIT_TYPE_LABELS,
  type Patient,
  type QueueSummary,
  type QueueToken,
  type Visit,
  type VisitType,
} from "./types";

type VisitPatient = Pick<Patient, "id" | "full_name" | "uhid" | "thid">;

const RECEPTION_PRIORITIES = ["normal", "senior_citizen", "pregnant", "follow_up_recall"] as const;

/**
 * Register → visit → token, the rest of the OPD entry point.
 *
 * Registration alone was a dead end: a UHID and nothing else. A visit is what
 * puts the patient into the billing chain (its registration invoice is raised
 * in the same server transaction) and a token is what puts them in front of a
 * doctor.
 */
export function StartVisit({ patient }: { patient: VisitPatient }) {
  const { t } = useLocale();
  const { user } = useAuth();
  const { counter } = useDeskCounter();
  const canAccessBilling = canRoleAccessPath(user?.role ?? null, "/billing");
  const canAccessEmergency = canRoleAccessPath(user?.role ?? null, "/emergency");
  const canAccessIpd = canRoleAccessPath(user?.role ?? null, "/ipd");
  const [queues, setQueues] = useState<QueueSummary[] | null>(null);
  const [queueId, setQueueId] = useState<string>("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [token, setToken] = useState<QueueToken | null>(null);
  const [visit, setVisit] = useState<Visit | null>(null);
  const [priority, setPriority] = useState("normal");
  // Optional desk observations (HD-10) — off by default
  const [enableDeskObs, setEnableDeskObs] = useState(false);
  const [deskPulse, setDeskPulse] = useState("");
  const [deskBpSys, setDeskBpSys] = useState("");
  const [deskBpDia, setDeskBpDia] = useState("");
  const [deskTemp, setDeskTemp] = useState("");
  // Was hardcoded to "opd", so a hospital with wards could not admit anyone
  // from the desk (REC-03). OPD stays the default because it is the common
  // case, not because it was the only one.
  const [visitType, setVisitType] = useState<VisitType>("opd");

  // One key per patient, for the same reason the registration form holds one:
  // a retried click must replay the visit, not open a second one and bill a
  // second registration fee.
  const visitKey = useMemo(() => newIdempotencyKey(), []);
  const tokenKey = useMemo(() => newIdempotencyKey(), []);

  // Only an outpatient waits for a number to be called. This screen used to
  // run the OPD pipeline for every visit type: it issued a corridor token to
  // admissions and teleconsults, and — because the whole control was rendered
  // only when a queue was open — it refused to create an IPD, day-care,
  // EMERGENCY or teleconsult visit at all on a day nobody had opened one.
  const needsToken = TOKEN_ISSUING_VISIT_TYPES.includes(visitType);

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
          setError(reason instanceof ApiError ? reason.message : t("receptionist.errLoadQueuesStartVisit"));
        }
      });
    return () => {
      cancelled = true;
    };
  }, [t]);

  async function start() {
    if (needsToken && !queueId) return;
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

      if (!needsToken) return;
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
            ? t("receptionist.errTokenAfterVisit")
            : t("receptionist.errStartVisitRetry"),
      );
    } finally {
      setBusy(false);
    }
  }

  // A visit type that takes no token is finished the moment the visit exists.
  // Keyed on `token || visit`, because waiting for a token that is never
  // coming left the desk staring at the form it had just submitted.
  if (token || (visit && !needsToken)) {
    return (
      <div className="surface-card space-y-3 p-8 text-center">
        <p className="text-sm text-muted-foreground">
          {token ? t("startVisit.tokenIssued") : t("startVisit.visitCreated")}
        </p>
        {token ? (
          <p className="font-mono text-5xl font-bold">{token.token_display}</p>
        ) : (
          <p className="text-2xl font-semibold">{t(`visitType.${visitType}` as "visitType.opd")}</p>
        )}
        <p className="text-sm text-muted-foreground">
          {patient.full_name} · {patient.uhid ?? patient.thid}
        </p>
        {visit && (
          <p className="text-xs text-muted-foreground">
            {t("startVisit.visitNumberShort", { visitNumber: visit.visit_number })}
          </p>
        )}
        <div className="flex flex-wrap justify-center gap-4 pt-2 text-sm">
          {needsToken && (
            <Link href="/receptionist/queue" className="font-medium underline">
              {t("startVisit.viewQueue")}
            </Link>
          )}
          {visitType === "emergency" && canAccessEmergency && (
            <Link href="/emergency" className="font-medium underline">
              {t("startVisit.emergencyDept")}
            </Link>
          )}
          {visitType === "ipd" && canAccessIpd && (
            <Link href="/ipd" className="font-medium underline">
              {t("startVisit.inpatientAdmission")}
            </Link>
          )}
          <Link href="/consent" className="font-medium underline">
            {t("consent.recordConsent")}
          </Link>
          {canAccessBilling && (
            <Link href="/billing" className="font-medium underline">
              {t("startVisit.openBilling")}
            </Link>
          )}
        </div>
        {!canAccessBilling && (
          <p className="text-xs text-muted-foreground pt-1">{t("startVisit.regInvoiceHint")}</p>
        )}
        {visitType === "emergency" && (
          <p className="text-xs text-muted-foreground">{t("startVisit.directEmergency")}</p>
        )}
        {visitType === "ipd" && (
          <p className="text-xs text-muted-foreground">{t("startVisit.directIpd")}</p>
        )}
        {visitType === "day_care" && (
          <p className="text-xs text-muted-foreground">{t("startVisit.directDayCare")}</p>
        )}
        {visitType === "teleconsult" && (
          <p className="text-xs text-muted-foreground">{t("startVisit.directTeleconsult")}</p>
        )}
      </div>
    );
  }

  return (
    <div className="surface-card space-y-4 p-6">
      <h3 className="text-base font-medium">{t("common.startVisit")}</h3>

      <label className="block space-y-1 text-sm">
        <span className="text-muted-foreground">{t("field.visitType")}</span>
        <select
          className="w-full rounded-md border border-border px-3 py-2"
          value={visitType}
          onChange={(e) => setVisitType(e.target.value as VisitType)}
          disabled={busy || Boolean(visit)}  /* locked once the visit exists */
        >
          {(Object.keys(VISIT_TYPE_LABELS) as VisitType[]).map((type) => (
            <option key={type} value={type}>
              {t(`visitType.${type}` as "visitType.opd")}
            </option>
          ))}
        </select>
        {BED_OCCUPYING_VISIT_TYPES.includes(visitType) && (
          <span className="block text-xs text-muted-foreground">{t("startVisit.bedOccupyingHint")}</span>
        )}
      </label>
      <p className="text-sm text-muted-foreground">{t("startVisit.counterFlowHint")}</p>

      {visit ? (
        <p className="rounded-md border border-warning/30 bg-warning-muted p-3 text-sm">
          {t("startVisit.visitRetryTokenOnly", { visitNumber: visit.visit_number })}
        </p>
      ) : null}

      {needsToken && queues === null && !error && (
        <p className="text-sm text-muted-foreground">{t("startVisit.loadingQueues")}</p>
      )}

      {!needsToken && (
        <button
          type="button"
          onClick={() => void start()}
          disabled={busy}
          className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
        >
          {busy ? t("common.loading") : t("receptionist.createVisit")}
        </button>
      )}

      {needsToken && queues !== null && queues.length === 0 && (
        <div className="space-y-2">
          <p className="text-sm text-muted-foreground">
            {t("receptionist.noOpenQueues")} A queue has to be opened for a doctor before
            tokens can be issued.
          </p>
          <Link href="/receptionist/queue" className="inline-block text-sm font-medium underline">
            {t("receptionist.openTodaysQueue")}
          </Link>
        </div>
      )}

      {needsToken && queues !== null && queues.length > 0 && (
        <>
          <label className="block space-y-1 text-sm">
            <span className="text-muted-foreground">{t("common.doctor")}</span>
            <select
              className="w-full rounded-md border border-border px-3 py-2"
              value={queueId}
              onChange={(e) => setQueueId(e.target.value)}
              disabled={Boolean(visit)}
            >
              {queues.map((q) => (
                <option key={q.id} value={q.id}>
                  {q.doctor_name ?? t("common.doctor")}
                  {q.room_number ? ` · ${t("receptionist.room", { number: q.room_number })}` : ""}
                  {` · ${q.waiting_count} waiting`}
                </option>
              ))}
            </select>
          </label>

          <label className="block space-y-1 text-sm">
            <span className="text-muted-foreground">{t("field.queuePriority")}</span>
            <select
              className="w-full rounded-md border border-border px-3 py-2"
              value={priority}
              onChange={(event) => setPriority(event.target.value)}
              disabled={Boolean(visit)}
            >
              {RECEPTION_PRIORITIES.map((value) => (
                <option key={value} value={value}>
                  {t(`priority.${value}` as MessageKey)}
                </option>
              ))}
            </select>
          </label>

          <button
            type="button"
            onClick={() => void start()}
            disabled={busy || !queueId}
            className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
          >
            {busy
              ? t("common.loading")
              : visit
                ? t("startVisit.retryToken")
                : t("receptionist.createVisitAndToken")}
          </button>
        </>
      )}

      {/* Desk Observations (HD-10) — Off by default */}
      <div className="border-t border-border/80 pt-3.5">
        <button
          type="button"
          onClick={() => setEnableDeskObs((prev) => !prev)}
          className="text-xs text-muted-foreground hover:text-foreground font-medium underline"
        >
          {enableDeskObs ? "− Hide Desk Observations" : "+ Optional Desk Observations (Trained Staff Only)"}
        </button>
        {enableDeskObs && (
          <div className="mt-2.5 rounded-lg border border-border bg-muted/20 p-3.5 space-y-2.5">
            <p className="text-[11px] text-muted-foreground">
              Counter vitals entry requires authorized clinical training. Units: Pulse (bpm), BP (mmHg), Temp (°F).
            </p>
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
              <label className="text-xs space-y-1">
                <span className="text-muted-foreground">Pulse (bpm)</span>
                <input
                  type="number"
                  placeholder="72"
                  value={deskPulse}
                  onChange={(e) => setDeskPulse(e.target.value)}
                  className="w-full rounded border border-border bg-card px-2 py-1 text-xs"
                />
              </label>
              <label className="text-xs space-y-1">
                <span className="text-muted-foreground">BP Systolic</span>
                <input
                  type="number"
                  placeholder="120"
                  value={deskBpSys}
                  onChange={(e) => setDeskBpSys(e.target.value)}
                  className="w-full rounded border border-border bg-card px-2 py-1 text-xs"
                />
              </label>
              <label className="text-xs space-y-1">
                <span className="text-muted-foreground">BP Diastolic</span>
                <input
                  type="number"
                  placeholder="80"
                  value={deskBpDia}
                  onChange={(e) => setDeskBpDia(e.target.value)}
                  className="w-full rounded border border-border bg-card px-2 py-1 text-xs"
                />
              </label>
              <label className="text-xs space-y-1">
                <span className="text-muted-foreground">Temp (°F)</span>
                <input
                  type="number"
                  step="0.1"
                  placeholder="98.6"
                  value={deskTemp}
                  onChange={(e) => setDeskTemp(e.target.value)}
                  className="w-full rounded border border-border bg-card px-2 py-1 text-xs"
                />
              </label>
            </div>
            <p className="text-[10px] text-muted-foreground">
              {t("startVisit.recordedBy")}{" "}
              <span className="font-medium text-foreground">
                {user?.name || t("startVisit.receptionStaff")}
              </span>{" "}
              ({counter})
            </p>
          </div>
        )}
      </div>

      {error && (
        <p role="alert" className="text-sm text-danger">
          {error}
        </p>
      )}
    </div>
  );
}

export default StartVisit;
