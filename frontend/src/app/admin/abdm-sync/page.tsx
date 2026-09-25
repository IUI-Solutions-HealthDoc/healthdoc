"use client";

import { useState } from "react";

import { getAbhaLink, unlinkAbha, type AbhaLink } from "@/features/admin/api/abdm";
import {
  MATCH_LABELS,
  type PatientSearchRequest,
  type PatientSearchResult,
} from "@/features/receptionist/types";
import { searchPatients } from "@/features/receptionist/api";
import { ApiError } from "@/lib/api";
import { AbdmDeliveryJobs } from "@/features/admin/AbdmDeliveryJobs";
import { useLocale } from "@/lib/i18n";

export default function Page() {
  const { t } = useLocale();
  const [uhid, setUhid] = useState("");
  const [abha, setAbha] = useState("");
  const [name, setName] = useState("");
  const [dob, setDob] = useState("");
  const [results, setResults] = useState<PatientSearchResult[]>([]);
  const [selected, setSelected] = useState<PatientSearchResult | null>(null);
  const [link, setLink] = useState<AbhaLink | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  async function search(event: React.FormEvent) {
    event.preventDefault();
    const criteria: PatientSearchRequest = {};
    if (uhid.trim()) criteria.uhid = uhid.trim();
    if (abha.trim()) criteria.abha_number = abha.trim();
    if (name.trim()) criteria.full_name = name.trim();
    if (dob) criteria.dob = dob;
    if (Object.keys(criteria).length === 0) {
      setError(t("admin.abdm.searchCriteriaRequired"));
      return;
    }
    if (criteria.full_name && !criteria.dob) {
      setError(t("admin.abdm.dobRequiredForName"));
      return;
    }

    setBusy(true);
    setError(null);
    setMessage(null);
    setSelected(null);
    setLink(null);
    try {
      const response = await searchPatients(criteria);
      setResults(response.items);
      if (response.items.length === 0) setMessage(t("admin.abdm.noPatientMatch"));
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : t("admin.abdm.patientSearchFailed"));
    } finally {
      setBusy(false);
    }
  }

  async function inspect(patient: PatientSearchResult) {
    setBusy(true);
    setSelected(patient);
    setLink(null);
    setError(null);
    setMessage(null);
    try {
      setLink(await getAbhaLink(patient.id));
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : t("admin.abdm.linkLoadFailed"));
    } finally {
      setBusy(false);
    }
  }

  async function removeLink() {
    if (!selected || !link?.abha_number) return;
    const confirmed = window.confirm(
      t("admin.abdm.unlinkConfirm", {
        abha: link.abha_number,
        name: selected.full_name,
      }),
    );
    if (!confirmed) return;

    setBusy(true);
    setError(null);
    try {
      setLink(await unlinkAbha(selected.id));
      setMessage(t("admin.abdm.unlinkSuccess"));
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : t("admin.abdm.unlinkFailed"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-8 p-6">
      <AbdmDeliveryJobs />
      <div>
        <h1 className="text-3xl font-semibold">{t("admin.abdm.title")}</h1>
        <p className="mt-2 max-w-3xl text-sm text-muted-foreground">{t("admin.abdm.subtitle")}</p>
      </div>

      <section className="rounded-md border border-warning/30 bg-warning-muted p-4 text-sm">
        <h2 className="font-medium">{t("admin.abdm.monitoringTitle")}</h2>
        <p className="mt-1 text-muted-foreground">{t("admin.abdm.monitoringBody")}</p>
      </section>

      {error ? <p role="alert" className="rounded-md bg-danger-muted p-3 text-sm text-danger">{error}</p> : null}
      {message ? <p role="status" className="rounded-md bg-success-muted p-3 text-sm text-success">{message}</p> : null}

      <form onSubmit={search} className="surface-card grid gap-4 p-5 md:grid-cols-2 lg:grid-cols-4">
        <label className="space-y-1 text-sm">
          <span className="text-muted-foreground">UHID</span>
          <input className="w-full rounded-md border border-border px-3 py-2" value={uhid} onChange={(event) => setUhid(event.target.value)} />
        </label>
        <label className="space-y-1 text-sm">
          <span className="text-muted-foreground">ABHA number</span>
          <input className="w-full rounded-md border border-border px-3 py-2" value={abha} onChange={(event) => setAbha(event.target.value)} />
        </label>
        <label className="space-y-1 text-sm">
          <span className="text-muted-foreground">{t("field.fullName")}</span>
          <input className="w-full rounded-md border border-border px-3 py-2" value={name} onChange={(event) => setName(event.target.value)} />
        </label>
        <label className="space-y-1 text-sm">
          <span className="text-muted-foreground">{t("field.dob")}</span>
          <input type="date" className="w-full rounded-md border border-border px-3 py-2" value={dob} onChange={(event) => setDob(event.target.value)} />
        </label>
        <button type="submit" disabled={busy} className="w-fit rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground disabled:opacity-50">
          {t("admin.abdm.searchPatients")}
        </button>
      </form>

      {results.length > 0 ? (
        <section className="surface-card overflow-hidden">
          <table className="w-full text-left text-sm">
            <thead className="border-b border-border bg-muted/50">
              <tr><th className="p-3">{t("admin.abdm.columnPatient")}</th><th className="p-3">{t("admin.abdm.columnIdentity")}</th><th className="p-3">{t("admin.abdm.columnMobile")}</th><th className="p-3"><span className="sr-only">{t("common.actions")}</span></th></tr>
            </thead>
            <tbody>
              {results.map((patient) => (
                <tr key={patient.id} className="border-b border-border last:border-0">
                  <td className="p-3"><span className="font-medium">{patient.full_name}</span><span className="block text-xs text-muted-foreground">{patient.uhid ?? t("admin.abdm.noUhid")}</span></td>
                  <td className="p-3">{MATCH_LABELS[patient.matched_on] ?? patient.matched_on}</td>
                  <td className="p-3">{patient.mobile_masked ?? "—"}</td>
                  <td className="p-3 text-right"><button type="button" disabled={busy} onClick={() => void inspect(patient)} className="rounded-md border border-border px-3 py-1.5 font-medium disabled:opacity-50">{t("admin.abdm.inspectLink")}</button></td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      ) : null}

      {selected && link ? (
        <section className="surface-card p-5">
          <h2 className="text-lg font-medium">{selected.full_name}</h2>
          <p className="mt-1 text-sm text-muted-foreground">{selected.uhid ?? selected.id}</p>
          <div className="mt-4 flex flex-wrap items-center justify-between gap-4 rounded-md border border-border p-4">
            <div>
              <p className="text-xs uppercase tracking-wide text-muted-foreground">{t("admin.abdm.linkedAbha")}</p>
              <p className="mt-1 font-medium">{link.abha_number ?? t("admin.abdm.noAbhaLinked")}</p>
            </div>
            {link.abha_number ? <button type="button" disabled={busy} onClick={() => void removeLink()} className="rounded-md bg-danger px-4 py-2 text-sm font-medium text-white disabled:opacity-50">{t("admin.abdm.unlinkAbha")}</button> : null}
          </div>
        </section>
      ) : null}
    </div>
  );
}
