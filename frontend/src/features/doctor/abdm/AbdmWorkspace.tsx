"use client";

import { useEffect, useRef, useState } from "react";
import { searchPatients } from "@/features/receptionist/api";
import type { PatientSearchResult } from "@/features/receptionist/types";
import { getUserFacingError, newIdempotencyKey } from "@/lib/api";
import { useLocale } from "@/lib/i18n";
import { askConsent, askRecords, HI_TYPES, loadWorkspace, type HiType, type Workspace } from "./api";
import { PageHeading } from "@/components/common/PageHeading";
import { ExternalRecordViewer } from "./ExternalRecordViewer";
import { DocumentSharing } from "./DocumentSharing";

const inputClass = "w-full rounded-md border border-border bg-background px-3 py-2";
const buttonClass = "rounded-md bg-primary px-4 py-2 text-sm font-medium text-white disabled:opacity-50";

export function AbdmWorkspace() {
  const { t } = useLocale();
  const [query, setQuery] = useState("");
  const [dob, setDob] = useState("");
  const [matches, setMatches] = useState<PatientSearchResult[]>([]);
  const [selected, setSelected] = useState<PatientSearchResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  async function search() {
    if (query.trim().length < 2 || !dob) {
      setError(t("doctor.abdm.errSearchIncomplete"));
      return;
    }
    setBusy(true);
    setError(null);
    setMatches([]);
    setSelected(null);
    try {
      setMatches((await searchPatients({ full_name: query.trim(), dob })).items);
    } catch (reason) {
      setError(getUserFacingError(reason, t("doctor.abdm.errSearchFailed")));
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="space-y-6 p-5">
      <PageHeading titleKey="doctor.abdmTitle" />
      <form
        className="surface-card space-y-3 p-5"
        onSubmit={(event) => {
          event.preventDefault();
          void search();
        }}
      >
        <label className="block space-y-1">
          <span>{t("doctor.abdm.findPatientByName")}</span>
          <input
            className={inputClass}
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            required
            minLength={2}
            maxLength={120}
            autoComplete="off"
          />
        </label>
        <label className="block space-y-1">
          <span>{t("doctor.abdm.dateOfBirth")}</span>
          <input
            type="date"
            className={inputClass}
            value={dob}
            onChange={(event) => setDob(event.target.value)}
            required
          />
        </label>
        <button className={buttonClass} disabled={busy}>
          {busy ? t("common.searching") : t("doctor.abdm.searchPatients")}
        </button>
        {error && <p role="alert" className="text-danger">{error}</p>}
        <ul className="space-y-2">
          {matches.map((patient) => (
            <li key={patient.id}>
              <button type="button" className="text-left underline" onClick={() => setSelected(patient)}>
                {patient.full_name} · {patient.uhid ?? t("doctor.abdm.noUhid")} · {patient.sex} ·{" "}
                {patient.age_years ?? t("doctor.abdm.unknownAge")}
              </button>
            </li>
          ))}
        </ul>
        {matches.length === 20 && (
          <p className="text-sm text-muted-foreground">{t("doctor.abdm.refineSearch")}</p>
        )}
      </form>
      {selected && <PatientWorkspace key={selected.id} patientId={selected.id} />}
    </div>
  );
}

function PatientWorkspace({ patientId }: { patientId: string }) {
  const { t } = useLocale();
  const [workspace, setWorkspace] = useState<Workspace | null>(null);
  const [offset, setOffset] = useState(0);
  const [refresh, setRefresh] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [expiry, setExpiry] = useState("");
  const [types, setTypes] = useState<HiType[]>([]);
  const [viewId, setViewId] = useState<string | null>(null);
  const retry = useRef<{ signature: string; key: string } | null>(null);
  const transferKeys = useRef(new Map<string, string>());
  const active = useRef(true);
  useEffect(() => {
    active.current = true;
    return () => {
      active.current = false;
    };
  }, []);
  useEffect(() => {
    let controller: AbortController | null = null;
    let disposed = false;
    async function load() {
      controller?.abort();
      controller = new AbortController();
      const attempt = controller;
      if (document.hidden) {
        setViewId(null);
        return;
      }
      try {
        const result = await loadWorkspace(patientId, offset, attempt.signal);
        if (!disposed && !attempt.signal.aborted) {
          setWorkspace(result);
          setError(null);
        }
      } catch (reason) {
        if (!disposed && !attempt.signal.aborted) {
          setWorkspace(null);
          setViewId(null);
          setError(getUserFacingError(reason, t("doctor.abdm.errLoadWorkspace")));
        }
      }
    }
    void load();
    const onVisibility = () => {
      void load();
    };
    const timer = window.setInterval(onVisibility, 10000);
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      disposed = true;
      controller?.abort();
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, [patientId, offset, refresh, t]);
  async function requestConsent() {
    const start = new Date(from);
    const end = new Date(to);
    const until = new Date(expiry);
    if (!workspace?.identity_verified || !workspace.abha_address) {
      setError(t("doctor.abdm.errVerifyBeforeConsent"));
      return;
    }
    if (!workspace.requester_ready) {
      setError(t("doctor.abdm.errRequesterNotReady"));
      return;
    }
    if (
      !types.length ||
      [start, end, until].some((date) => !Number.isFinite(date.getTime())) ||
      start > end ||
      until.getTime() <= Date.now()
    ) {
      setError(t("doctor.abdm.errConsentFields"));
      return;
    }
    const body = {
      patient_id: patientId,
      abha_address: workspace.abha_address,
      purpose_code: "CAREMGT" as const,
      hi_types: types,
      date_range_from: start.toISOString(),
      date_range_to: end.toISOString(),
      requested_expiry: until.toISOString(),
    };
    const signature = JSON.stringify(body);
    if (retry.current?.signature !== signature) retry.current = { signature, key: newIdempotencyKey() };
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      await askConsent(body, retry.current.key);
      if (active.current) {
        setNotice(t("doctor.abdm.noticeConsentQueued"));
        setRefresh((value) => value + 1);
      }
    } catch (reason) {
      if (active.current) setError(getUserFacingError(reason, t("doctor.abdm.errConsentQueue")));
    } finally {
      if (active.current) setBusy(false);
    }
  }
  async function requestData(artefactId: string) {
    const key = transferKeys.current.get(artefactId) ?? newIdempotencyKey();
    transferKeys.current.set(artefactId, key);
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      await askRecords(artefactId, key);
      if (active.current) {
        setNotice(t("doctor.abdm.noticeDataQueued"));
        setRefresh((value) => value + 1);
      }
    } catch (reason) {
      if (active.current) setError(getUserFacingError(reason, t("doctor.abdm.errDataQueue")));
    } finally {
      if (active.current) setBusy(false);
    }
  }
  const availableRecords =
    workspace?.requests.flatMap((request) =>
      request.transfers.flatMap((transfer) => transfer.records),
    ) ?? [];
  const dateFields: [string, string, (value: string) => void][] = [
    [t("doctor.abdm.recordsFrom"), from, setFrom],
    [t("doctor.abdm.recordsTo"), to, setTo],
    [t("doctor.abdm.consentExpires"), expiry, setExpiry],
  ];
  return (
    <div className="space-y-5">
      {error && <p role="alert" className="text-danger">{error}</p>}
      {notice && <p role="status" className="text-sm">{notice}</p>}
      {!workspace && !error && <p role="status">{t("doctor.abdm.loadingWorkspace")}</p>}
      {workspace && (
        <>
          <DocumentSharing patientId={patientId} verified={workspace.identity_verified} />
          <section className="surface-card space-y-3 p-5">
            <h2 className="text-xl font-semibold">{workspace.patient_name}</h2>
            <p>
              {workspace.identity_verified
                ? t("doctor.abdm.verifiedAbha", { address: workspace.abha_address ?? "" })
                : t("doctor.abdm.verifyAtReception")}
            </p>
            <p className="text-sm text-muted-foreground">{t("doctor.abdm.scopeNotice")}</p>
            {!workspace.requester_ready && (
              <p role="alert" className="text-danger">
                {t("doctor.abdm.requesterIncomplete")}
              </p>
            )}
            <form
              className="space-y-4"
              onSubmit={(event) => {
                event.preventDefault();
                void requestConsent();
              }}
            >
              <fieldset
                disabled={busy || !workspace.identity_verified || !workspace.requester_ready}
                className="space-y-4"
              >
                <legend className="font-medium">{t("doctor.abdm.requestConsent")}</legend>
                <div className="grid gap-3 md:grid-cols-3">
                  {dateFields.map(([label, value, setter]) => (
                    <label key={label} className="space-y-1">
                      <span className="text-sm">{label}</span>
                      <input
                        type="datetime-local"
                        required
                        className={inputClass}
                        value={value}
                        onChange={(event) => setter(event.target.value)}
                      />
                    </label>
                  ))}
                </div>
                <fieldset>
                  <legend className="mb-2 text-sm">{t("doctor.abdm.requiredRecordTypes")}</legend>
                  <div className="flex flex-wrap gap-4">
                    {HI_TYPES.map((type) => (
                      <label className="flex items-center gap-2 text-sm" key={type}>
                        <input
                          type="checkbox"
                          checked={types.includes(type)}
                          onChange={(event) =>
                            setTypes((current) =>
                              event.target.checked
                                ? [...current, type]
                                : current.filter((entry) => entry !== type),
                            )
                          }
                        />
                        {type}
                      </label>
                    ))}
                  </div>
                </fieldset>
                <button className={buttonClass} disabled={busy || !types.length}>
                  {t("doctor.abdm.queueConsentRequest")}
                </button>
              </fieldset>
            </form>
          </section>
          <section className="surface-card space-y-4 p-5" aria-label="Consent and transfer status">
            <div className="flex justify-between gap-3">
              <h2 className="text-xl font-semibold">{t("doctor.abdm.consentAndDelivery")}</h2>
              <button
                type="button"
                className="underline"
                onClick={() => {
                  setViewId(null);
                  setRefresh((value) => value + 1);
                }}
              >
                {t("doctor.abdm.refreshStatus")}
              </button>
            </div>
            {!workspace.requests.length && <p>{t("doctor.abdm.noConsentRequests")}</p>}
            {workspace.requests.map((request) => (
              <article key={request.id} className="space-y-3 rounded border border-border p-4">
                <h3 className="font-medium">{request.hi_types.join(", ")}</h3>
                <p className="text-sm">
                  {new Date(request.date_range_from).toLocaleString()} —{" "}
                  {new Date(request.date_range_to).toLocaleString()}
                </p>
                <p>
                  {t("doctor.abdm.consentLabel", {
                    status: request.status,
                    delivery: request.delivery_status ?? t("doctor.abdm.deliveryNotQueued"),
                  })}
                </p>
                {request.delivery_status === "dead" && (
                  <p role="alert" className="text-danger">
                    {t("doctor.abdm.deliveryDead")}
                  </p>
                )}
                {request.artefacts.map((artefact) => (
                  <div key={artefact.id} className="flex flex-wrap items-center gap-3">
                    <span>
                      {t("doctor.abdm.grantStatus", {
                        status: artefact.status,
                        expiry: artefact.expires_at
                          ? new Date(artefact.expires_at).toLocaleString()
                          : t("doctor.abdm.expiryUnknown"),
                      })}
                    </span>
                    <button
                      type="button"
                      className={buttonClass}
                      disabled={busy || artefact.status !== "granted"}
                      onClick={() => void requestData(artefact.id)}
                    >
                      {t("doctor.abdm.requestConsentedRecords")}
                    </button>
                  </div>
                ))}
                {request.transfers.map((transfer) => (
                  <div key={transfer.id} className="space-y-2 border-t pt-2">
                    <p className="text-sm">
                      {t("doctor.abdm.transferStatus", {
                        status: transfer.status,
                        delivery: transfer.delivery_status ?? t("doctor.abdm.deliveryNotQueued"),
                        received: transfer.received_pages,
                        expected: transfer.expected_pages ?? t("doctor.abdm.expiryUnknown"),
                      })}
                    </p>
                    {transfer.records.map((record) => (
                      <div key={record.id} className="flex flex-wrap items-center gap-3">
                        <span>
                          {record.hi_type ?? t("doctor.abdm.rejectedRecord")} ·{" "}
                          {record.source_hip_id ?? t("doctor.abdm.unverifiedSource")} ·{" "}
                          {record.document_at
                            ? new Date(record.document_at).toLocaleString()
                            : t("doctor.abdm.unknownDate")}{" "}
                          · {record.status}
                        </span>
                        <button
                          type="button"
                          disabled={!record.available}
                          className="underline disabled:opacity-50"
                          onClick={() => setViewId(record.id)}
                        >
                          {t("doctor.abdm.viewRecord")}
                        </button>
                      </div>
                    ))}
                  </div>
                ))}
              </article>
            ))}
            <div className="flex gap-4">
              <button
                type="button"
                className="underline disabled:opacity-50"
                disabled={offset === 0}
                onClick={() => {
                  setViewId(null);
                  setOffset(Math.max(0, offset - 20));
                }}
              >
                {t("common.previous")}
              </button>
              <button
                type="button"
                className="underline disabled:opacity-50"
                disabled={workspace.next_offset === null}
                onClick={() => {
                  setViewId(null);
                  setOffset(workspace.next_offset ?? offset);
                }}
              >
                {t("common.next")}
              </button>
            </div>
          </section>
        </>
      )}
      {viewId && availableRecords.some((record) => record.id === viewId && record.available) && (
        <ExternalRecordViewer key={viewId} id={viewId} close={() => setViewId(null)} />
      )}
    </div>
  );
}
