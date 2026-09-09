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

export default function Page() {
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
      setError("Enter UHID, ABHA, or name with date of birth.");
      return;
    }
    if (criteria.full_name && !criteria.dob) {
      setError("Date of birth is required when searching by name.");
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
      if (response.items.length === 0) setMessage("No patient matched in your facility.");
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : "Patient search failed");
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
      setError(reason instanceof ApiError ? reason.message : "ABHA link could not be loaded");
    } finally {
      setBusy(false);
    }
  }

  async function removeLink() {
    if (!selected || !link?.abha_number) return;
    const confirmed = window.confirm(
      `Unlink ABHA ${link.abha_number} from ${selected.full_name}? This also removes the stored linking credential.`,
    );
    if (!confirmed) return;

    setBusy(true);
    setError(null);
    try {
      setLink(await unlinkAbha(selected.id));
      setMessage("ABHA link and encrypted linking credential removed.");
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : "ABHA unlink failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-8 p-6">
      <AbdmDeliveryJobs />
      <div>
        <h1 className="text-3xl font-semibold">ABDM identity links</h1>
        <p className="mt-2 max-w-3xl text-sm text-muted-foreground">
          Inspect and unlink ABHA records in your facility. Link creation stays with the
          verified receptionist/doctor workflow because it requires an ABDM linking token.
        </p>
      </div>

      <section className="rounded-md border border-warning/30 bg-warning-muted p-4 text-sm">
        <h2 className="font-medium">Delivery monitoring is not available yet</h2>
        <p className="mt-1 text-muted-foreground">
          The server records link/unlink events in its transactional outbox, but exposes no
          outbox delivery-status contract. This page does not claim that an event reached ABDM.
        </p>
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
          <span className="text-muted-foreground">Full name</span>
          <input className="w-full rounded-md border border-border px-3 py-2" value={name} onChange={(event) => setName(event.target.value)} />
        </label>
        <label className="space-y-1 text-sm">
          <span className="text-muted-foreground">Date of birth</span>
          <input type="date" className="w-full rounded-md border border-border px-3 py-2" value={dob} onChange={(event) => setDob(event.target.value)} />
        </label>
        <button type="submit" disabled={busy} className="w-fit rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground disabled:opacity-50">
          Search facility patients
        </button>
      </form>

      {results.length > 0 ? (
        <section className="surface-card overflow-hidden">
          <table className="w-full text-left text-sm">
            <thead className="border-b border-border bg-muted/50">
              <tr><th className="p-3">Patient</th><th className="p-3">Identity</th><th className="p-3">Mobile</th><th className="p-3"><span className="sr-only">Action</span></th></tr>
            </thead>
            <tbody>
              {results.map((patient) => (
                <tr key={patient.id} className="border-b border-border last:border-0">
                  <td className="p-3"><span className="font-medium">{patient.full_name}</span><span className="block text-xs text-muted-foreground">{patient.uhid ?? "No UHID"}</span></td>
                  <td className="p-3">{MATCH_LABELS[patient.matched_on] ?? patient.matched_on}</td>
                  <td className="p-3">{patient.mobile_masked ?? "—"}</td>
                  <td className="p-3 text-right"><button type="button" disabled={busy} onClick={() => void inspect(patient)} className="rounded-md border border-border px-3 py-1.5 font-medium disabled:opacity-50">Inspect link</button></td>
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
              <p className="text-xs uppercase tracking-wide text-muted-foreground">Linked ABHA</p>
              <p className="mt-1 font-medium">{link.abha_number ?? "No ABHA linked"}</p>
            </div>
            {link.abha_number ? <button type="button" disabled={busy} onClick={() => void removeLink()} className="rounded-md bg-danger px-4 py-2 text-sm font-medium text-white disabled:opacity-50">Unlink ABHA</button> : null}
          </div>
        </section>
      ) : null}
    </div>
  );
}
