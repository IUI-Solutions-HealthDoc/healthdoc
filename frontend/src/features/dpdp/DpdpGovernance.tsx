"use client";

/**
 * DPDP governance: the DPO, the grievance register, consent managers.
 *
 * All three tables have existed since migration 0022a and nothing could read or
 * write any of them. That matters more than an ordinary gap: the Act requires a
 * data fiduciary to HAVE a named, published DPO and a working grievance
 * mechanism, and a schema carrying those tables reads — to an assessor, or to
 * the next engineer — as though the hospital has them.
 *
 * The screen's job is to make the true state visible, including when the true
 * state is "nobody has been appointed".
 */
import { useCallback, useEffect, useMemo, useState } from "react";

import { listUsers } from "@/features/admin/api/users";
import type { User } from "@/features/admin/types";
import { useCurrentUser } from "@/features/session/useCurrentUser";
import { ApiError } from "@/lib/api";
import { useLocale, type MessageKey } from "@/lib/i18n";

import {
  appointDpo,
  deactivateDpo,
  getActiveDpo,
  listConsentManagers,
  listDpoHistory,
  listGrievances,
  registerConsentManager,
  transitionGrievance,
  updateConsentManager,
} from "./api";
import type { ConsentManager, Dpo, Grievance, GrievanceStatus } from "./types";

type TransitionOption = { value: GrievanceStatus; labelKey: MessageKey };

function statusTone(status: string): string {
  if (status === "resolved" || status === "closed") return "bg-green-100 text-green-800";
  if (status === "escalated_dpb") return "bg-red-100 text-red-800";
  if (status === "under_review") return "bg-blue-100 text-blue-800";
  return "bg-amber-100 text-amber-900";
}

/** Overdue is a fact about the SLA, not a styling choice. */
function isOverdue(grievance: Grievance): boolean {
  if (grievance.status === "resolved" || grievance.status === "closed") return false;
  return new Date(grievance.due_at).getTime() < Date.now();
}

export function DpdpGovernance() {
  const { t } = useLocale();
  const { user, loading: sessionLoading } = useCurrentUser();
  const isAdmin = (user?.roles ?? []).includes("admin");

  const nextStatus = useMemo(
    (): Record<GrievanceStatus, readonly TransitionOption[]> => ({
      pending: [
        { value: "under_review", labelKey: "dpdp.grievance.action.under_review" },
        { value: "escalated_dpb", labelKey: "dpdp.grievance.action.escalated_dpb" },
      ],
      under_review: [
        { value: "resolved", labelKey: "dpdp.grievance.action.resolved" },
        { value: "escalated_dpb", labelKey: "dpdp.grievance.action.escalated_dpb" },
      ],
      escalated_dpb: [{ value: "resolved", labelKey: "dpdp.grievance.action.resolved" }],
      resolved: [{ value: "closed", labelKey: "dpdp.grievance.action.closed" }],
      closed: [],
    }),
    [],
  );

  const [dpo, setDpo] = useState<Dpo | null>(null);
  const [dpoMissing, setDpoMissing] = useState(false);
  const [history, setHistory] = useState<Dpo[]>([]);
  const [grievances, setGrievances] = useState<Grievance[]>([]);
  const [managers, setManagers] = useState<ConsentManager[]>([]);
  const [staff, setStaff] = useState<User[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const [appointee, setAppointee] = useState("");
  const [publishContact, setPublishContact] = useState(false);
  const [contact, setContact] = useState("");

  const [cmRegistrationId, setCmRegistrationId] = useState("");
  const [cmName, setCmName] = useState("");
  const [cmEndpoint, setCmEndpoint] = useState("");

  const load = useCallback(async () => {
    if (sessionLoading) return;
    try {
      // The DPO read 404s when none has ever been appointed. That is an ANSWER,
      // not an error — handled separately so it does not poison the rest of the
      // screen, and surfaced as a warning rather than swallowed.
      const dpoResult = await getActiveDpo().catch((reason) => {
        // ApiError carries `code`, not `status` — see lib/api.ts.
        if (reason instanceof ApiError && reason.code === 404) {
          setDpoMissing(true);
          return null;
        }
        throw reason;
      });

      const [historyResult, grievanceResult, managerResult, staffPage] = await Promise.all([
        listDpoHistory(),
        listGrievances(),
        listConsentManagers(),
        // GET /users is admin-only. Auditors can read this governance screen,
        // but granting them the facility staff directory just to turn a UUID
        // into a label would widen their access for a cosmetic convenience.
        isAdmin ? listUsers({ page_size: 100 }) : Promise.resolve(null),
      ]);

      setDpo(dpoResult);
      if (dpoResult) setDpoMissing(false);
      setHistory(historyResult);
      setGrievances(grievanceResult);
      setManagers(managerResult);
      setStaff(staffPage?.items ?? []);
      setError(null);
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : t("dpdp.loadFailed"));
    }
  }, [isAdmin, sessionLoading, t]);

  useEffect(() => {
    void load();
  }, [load]);

  const act = async (fn: () => Promise<unknown>, failure: string) => {
    setBusy(true);
    try {
      await fn();
      await load();
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : failure);
    } finally {
      setBusy(false);
    }
  };

  const submitAppointment = () =>
    act(
      () =>
        appointDpo({
          user_id: appointee,
          // Recorded when there is a sitting DPO, so succession is a handover
          // rather than the previous appointment quietly disappearing.
          replaces_dpo_id: dpo?.id ?? null,
          contact_published: publishContact,
          published_contact: publishContact ? contact.trim() : null,
        }).then(() => {
          setAppointee("");
          setContact("");
          setPublishContact(false);
        }),
      t("dpdp.dpoAppointFailed"),
    );

  const nameOf = (userId: string) =>
    staff.find((candidate) => candidate.id === userId)?.full_name ?? userId;

  const submitTransition = (
    grievance: Grievance,
    target: GrievanceStatus,
  ): void => {
    let resolution: string | null = null;
    let escalationReason: string | null = null;

    if (target === "resolved") {
      const entered = window.prompt(t("dpdp.grievance.promptResolution"));
      if (entered === null) return;
      resolution = entered.trim();
      if (!resolution) {
        setError(t("dpdp.grievance.resolutionRequired"));
        return;
      }
    }

    if (target === "escalated_dpb") {
      const entered = window.prompt(t("dpdp.grievance.promptEscalation"));
      if (entered === null) return;
      escalationReason = entered.trim();
      if (!escalationReason) {
        setError(t("dpdp.grievance.escalationRequired"));
        return;
      }
    }

    void act(
      () =>
        transitionGrievance(grievance.id, {
          status: target,
          resolution,
          escalation_reason: escalationReason,
          assigned_to: null,
        }),
      t("dpdp.grievanceUpdateFailed"),
    );
  };

  return (
    <div className="space-y-8 p-6">
      <div>
        <h1 className="text-3xl font-semibold">{t("dpdp.title")}</h1>
        <p className="mt-2 max-w-prose text-sm text-muted-foreground">{t("dpdp.subtitle")}</p>
      </div>

      {error ? (
        <p role="alert" className="rounded-md bg-danger-muted p-3 text-sm text-danger">
          {error}
        </p>
      ) : null}

      {/* ------------------------------------------------------------ DPO */}
      <section className="space-y-3">
        <h2 className="text-xl font-semibold">{t("dpdp.dpoSection")}</h2>

        {dpoMissing ? (
          <p className="rounded border border-warning p-3 text-sm">{t("dpdp.dpoMissingWarning")}</p>
        ) : null}

        {dpo ? (
          <div className="rounded border border-border p-4 text-sm">
            <p className="font-medium">{nameOf(dpo.user_id)}</p>
            <p className="mt-1 text-muted-foreground">
              {t("dpdp.dpoAppointed", { date: new Date(dpo.appointed_at).toLocaleDateString() })}
            </p>
            {dpo.contact_published ? (
              <p className="mt-1">{t("dpdp.dpoPublishedContact", { contact: dpo.published_contact ?? "" })}</p>
            ) : (
              <p className="mt-1 text-warning">{t("dpdp.dpoContactNotPublished")}</p>
            )}
            {isAdmin ? (
              <button
                type="button"
                disabled={busy}
                onClick={() => void act(() => deactivateDpo(dpo.id), t("dpdp.dpoStandDownFailed"))}
                className="mt-3 rounded border border-gray-300 px-3 py-1 text-xs disabled:opacity-50"
              >
                {t("dpdp.dpoStandDown")}
              </button>
            ) : null}
          </div>
        ) : null}

        {isAdmin ? (
          <div className="rounded border border-border p-4">
            <h3 className="text-base font-semibold">
              {dpo ? t("dpdp.dpoAppointSuccessor") : t("dpdp.dpoAppoint")}
            </h3>
            <div className="mt-3 grid gap-3 sm:grid-cols-2">
              <label className="text-sm">
                <span className="block text-muted-foreground">{t("dpdp.dpoOfficer")}</span>
                <select
                  className="mt-1 w-full rounded border border-gray-300 p-2"
                  value={appointee}
                  onChange={(e) => setAppointee(e.target.value)}
                >
                  <option value="">{t("dpdp.dpoSelectStaff")}</option>
                  {staff.map((candidate) => (
                    <option key={candidate.id} value={candidate.id}>
                      {candidate.full_name}
                    </option>
                  ))}
                </select>
              </label>
              <label className="text-sm">
                <span className="block text-muted-foreground">{t("dpdp.dpoPublishedContactLabel")}</span>
                <input
                  className="mt-1 w-full rounded border border-gray-300 p-2"
                  placeholder={t("dpdp.dpoContactPlaceholder")}
                  value={contact}
                  onChange={(e) => setContact(e.target.value)}
                  disabled={!publishContact}
                />
              </label>
            </div>
            <label className="mt-3 flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={publishContact}
                onChange={(e) => {
                  setPublishContact(e.target.checked);
                  if (!e.target.checked) setContact("");
                }}
              />
              {/* The server refuses both halves of the mismatch, so the form
                  keeps them in step rather than letting a 422 explain it. */}
              {t("dpdp.dpoPublishContact")}
            </label>
            <button
              type="button"
              disabled={busy || !appointee || (publishContact && !contact.trim())}
              onClick={() => void submitAppointment()}
              className="mt-4 rounded bg-blue-700 px-4 py-2 text-sm text-white disabled:bg-gray-300"
            >
              {dpo ? t("dpdp.dpoAppointSuccessorButton") : t("dpdp.dpoAppointButton")}
            </button>
          </div>
        ) : null}

        {history.length > 1 ? (
          <details className="text-sm">
            <summary className="cursor-pointer text-muted-foreground">
              {t("dpdp.dpoHistory", { count: history.length })}
            </summary>
            <ul className="mt-2 space-y-1">
              {history.map((entry) => (
                <li key={entry.id} className="text-muted-foreground">
                  {t("dpdp.dpoHistoryEntry", {
                    name: nameOf(entry.user_id),
                    date: new Date(entry.appointed_at).toLocaleDateString(),
                    current: entry.is_active ? t("dpdp.dpoCurrentSuffix") : "",
                  })}
                </li>
              ))}
            </ul>
          </details>
        ) : null}
      </section>

      {/* ----------------------------------------------------- grievances */}
      <section className="space-y-3">
        <h2 className="text-xl font-semibold">{t("dpdp.grievancesSection", { count: grievances.length })}</h2>
        {grievances.length === 0 ? (
          <p className="text-sm text-muted-foreground">{t("dpdp.grievancesEmpty")}</p>
        ) : (
          <ul className="space-y-2">
            {grievances.map((grievance) => (
              <li
                key={grievance.id}
                className={`rounded border p-3 text-sm ${
                  isOverdue(grievance) ? "border-danger" : "border-border"
                }`}
              >
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div>
                    <span className="font-medium">{grievance.grievance_number}</span>
                    <span className="text-muted-foreground">
                      {" "}
                      · {grievance.grievance_type.replace("_", " ")}
                    </span>
                  </div>
                  <span className={`rounded px-2 py-0.5 text-xs ${statusTone(grievance.status)}`}>
                    {grievance.status.replace("_", " ")}
                  </span>
                </div>

                <p className="mt-1">{grievance.description}</p>

                <p className={`mt-1 text-xs ${isOverdue(grievance) ? "text-danger" : "text-muted-foreground"}`}>
                  {t("dpdp.grievanceDue", { date: new Date(grievance.due_at).toLocaleString() })}
                  {isOverdue(grievance) ? t("dpdp.grievanceOverdue") : ""}
                </p>

                {grievance.resolution ? (
                  <p className="mt-1 text-muted-foreground">
                    {t("dpdp.grievanceResolution", { text: grievance.resolution })}
                  </p>
                ) : null}

                {nextStatus[grievance.status].length > 0 ? (
                  <div className="mt-2 flex flex-wrap gap-2">
                    {nextStatus[grievance.status].map((option) => (
                        <button
                          key={option.value}
                          type="button"
                          disabled={busy}
                          onClick={() => submitTransition(grievance, option.value)}
                          className="rounded border border-gray-300 px-3 py-1 text-xs disabled:opacity-50"
                        >
                          {t(option.labelKey)}
                        </button>
                      ))}
                  </div>
                ) : null}
              </li>
            ))}
          </ul>
        )}
      </section>

      {/* ----------------------------------------------- consent managers */}
      <section className="space-y-3">
        <h2 className="text-xl font-semibold">{t("dpdp.consentManagersSection", { count: managers.length })}</h2>
        <p className="text-sm text-muted-foreground">{t("dpdp.consentManagersHint")}</p>

        {managers.length === 0 ? (
          <p className="text-sm text-muted-foreground">{t("dpdp.consentManagersEmpty")}</p>
        ) : (
          <ul className="space-y-2">
            {managers.map((manager) => (
              <li key={manager.id} className="rounded border border-border p-3 text-sm">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div>
                    <span className="font-medium">{manager.name}</span>
                    <span className="text-muted-foreground"> · {manager.cm_registration_id}</span>
                  </div>
                  <span
                    className={`rounded px-2 py-0.5 text-xs ${
                      manager.is_active
                        ? "bg-green-100 text-green-800"
                        : "bg-gray-100 text-gray-700"
                    }`}
                  >
                    {manager.is_active ? t("dpdp.consentManagerActive") : t("dpdp.consentManagerInactive")}
                  </span>
                </div>
                {manager.endpoint_url ? (
                  <p className="mt-1 font-mono text-xs text-muted-foreground">
                    {manager.endpoint_url}
                  </p>
                ) : null}
                {isAdmin ? (
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() =>
                      void act(
                        () =>
                          updateConsentManager(manager.id, { is_active: !manager.is_active }),
                        t("dpdp.consentManagerUpdateFailed"),
                      )
                    }
                    className="mt-2 rounded border border-gray-300 px-3 py-1 text-xs disabled:opacity-50"
                  >
                    {manager.is_active ? t("dpdp.consentManagerDeactivate") : t("dpdp.consentManagerReactivate")}
                  </button>
                ) : null}
              </li>
            ))}
          </ul>
        )}

        {isAdmin ? (
          <div className="rounded border border-border p-4">
            <h3 className="text-base font-semibold">{t("dpdp.registerConsentManager")}</h3>
            <div className="mt-3 grid gap-3 sm:grid-cols-3">
              <label className="text-sm">
                <span className="block text-muted-foreground">{t("dpdp.registrationId")}</span>
                <input
                  className="mt-1 w-full rounded border border-gray-300 p-2"
                  value={cmRegistrationId}
                  onChange={(e) => setCmRegistrationId(e.target.value)}
                />
              </label>
              <label className="text-sm">
                <span className="block text-muted-foreground">{t("dpdp.managerName")}</span>
                <input
                  className="mt-1 w-full rounded border border-gray-300 p-2"
                  value={cmName}
                  onChange={(e) => setCmName(e.target.value)}
                />
              </label>
              <label className="text-sm">
                <span className="block text-muted-foreground">{t("dpdp.endpointUrl")}</span>
                <input
                  className="mt-1 w-full rounded border border-gray-300 p-2"
                  placeholder="https://…"
                  value={cmEndpoint}
                  onChange={(e) => setCmEndpoint(e.target.value)}
                />
              </label>
            </div>
            <button
              type="button"
              disabled={busy || !cmRegistrationId.trim() || !cmName.trim()}
              onClick={() =>
                void act(
                  () =>
                    registerConsentManager({
                      cm_registration_id: cmRegistrationId.trim(),
                      name: cmName.trim(),
                      endpoint_url: cmEndpoint.trim() || null,
                    }).then(() => {
                      setCmRegistrationId("");
                      setCmName("");
                      setCmEndpoint("");
                    }),
                  t("dpdp.registerConsentManagerFailed"),
                )
              }
              className="mt-4 rounded bg-blue-700 px-4 py-2 text-sm text-white disabled:bg-gray-300"
            >
              {t("dpdp.register")}
            </button>
          </div>
        ) : null}
      </section>
    </div>
  );
}
