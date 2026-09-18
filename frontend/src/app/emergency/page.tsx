"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import {
  createEmergencyVisit,
  listEmergencyWorklist,
  registerEmergencyPatient,
  type EmergencyPatient,
  type EmergencyPatientInput,
  type EmergencyVisitResult,
  type EmergencyWorklistItem,
} from "@/features/emergency/api";
import { ApiError } from "@/lib/api";

const initial: EmergencyPatientInput = {
  full_name: "",
  sex: "unknown",
  age_years: 0,
  mobile: "",
};

export default function Page() {
  const [form, setForm] = useState<EmergencyPatientInput>(initial);
  const [created, setCreated] = useState<EmergencyPatient | null>(null);
  const [createdVisit, setCreatedVisit] = useState<EmergencyVisitResult | null>(null);
  const [worklist, setWorklist] = useState<EmergencyWorklistItem[]>([]);
  const [worklistLoading, setWorklistLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [visitBusy, setVisitBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function loadWorklist() {
    setWorklistLoading(true);
    try {
      const items = await listEmergencyWorklist();
      setWorklist(items);
    } catch {
      // Worklist failure is non-blocking for registration
    } finally {
      setWorklistLoading(false);
    }
  }

  useEffect(() => {
    void loadWorklist();
  }, []);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    setCreatedVisit(null);
    try {
      const patient = await registerEmergencyPatient({
        ...form,
        full_name: form.full_name?.trim() || undefined,
        mobile: form.mobile?.trim() || undefined,
      });
      setCreated(patient);
      setForm(initial);
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : "Emergency registration failed");
    } finally {
      setBusy(false);
    }
  }

  async function handleStartEmergencyVisit() {
    if (!created) return;
    setVisitBusy(true);
    setError(null);
    try {
      const v = await createEmergencyVisit(created.id);
      setCreatedVisit(v);
      void loadWorklist();
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : "Failed to create emergency visit");
    } finally {
      setVisitBusy(false);
    }
  }

  return (
    <div className="mx-auto max-w-3xl space-y-8 p-6">
      <div>
        <h1 className="text-3xl font-semibold">Emergency registration & arrivals</h1>
        <p className="mt-2 text-sm text-muted-foreground">
          Issue a temporary hospital identity (THID) immediately and start emergency clinical care.
          Unknown patients can be promoted to a UHID later through the supervisor maker–checker workflow.
        </p>
      </div>

      {error ? (
        <p role="alert" className="rounded-md bg-danger-muted p-3 text-sm text-danger">
          {error}
        </p>
      ) : null}

      {created ? (
        <section className="surface-card border border-success p-6 space-y-4" aria-live="polite">
          <div>
            <p className="text-sm text-muted-foreground">Temporary identity issued</p>
            <p className="mt-1 font-mono text-2xl font-semibold text-primary">{created.thid}</p>
            <p className="mt-1 font-medium">{created.full_name} · estimated age {created.age_years} · {created.sex}</p>
            <p className="mt-1 text-xs text-muted-foreground">
              Patient ID <span className="font-mono">{created.id}</span>
            </p>
          </div>

          {createdVisit ? (
            <div className="rounded-md border border-success/30 bg-success-muted p-4 space-y-2">
              <p className="font-semibold text-success">Emergency visit {createdVisit.visit_number} active</p>
              <p className="text-xs text-muted-foreground">
                Patient is registered and ready for clinical consultation without an OPD queue token.
              </p>
              <div className="pt-2">
                <Link
                  href={`/doctor/consultation?visit_id=${createdVisit.id}`}
                  className="inline-block rounded-md bg-primary px-4 py-2 text-sm font-medium text-white hover:bg-primary/90"
                >
                  Open Emergency Consultation
                </Link>
              </div>
            </div>
          ) : (
            <div className="flex flex-wrap items-center gap-3 pt-2">
              <button
                type="button"
                onClick={() => void handleStartEmergencyVisit()}
                disabled={visitBusy}
                className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-white hover:bg-primary/90 disabled:opacity-50"
              >
                {visitBusy ? "Starting emergency visit…" : "Start Emergency Visit & Handoff to Doctor"}
              </button>
            </div>
          )}

          <div className="pt-2">
            <button
              type="button"
              className="text-xs text-muted-foreground underline hover:text-foreground"
              onClick={() => {
                setCreated(null);
                setCreatedVisit(null);
              }}
            >
              Register another patient
            </button>
          </div>
        </section>
      ) : (
        <form onSubmit={submit} className="surface-card space-y-5 p-6">
          <label className="block space-y-1 text-sm">
            <span className="text-muted-foreground">Name (leave blank if unknown)</span>
            <input
              className="w-full rounded-md border border-border px-3 py-2"
              value={form.full_name ?? ""}
              onChange={(event) => setForm((current) => ({ ...current, full_name: event.target.value }))}
            />
          </label>
          <div className="grid gap-4 sm:grid-cols-2">
            <label className="block space-y-1 text-sm">
              <span className="text-muted-foreground">Sex</span>
              <select
                className="w-full rounded-md border border-border px-3 py-2"
                value={form.sex}
                onChange={(event) =>
                  setForm((current) => ({
                    ...current,
                    sex: event.target.value as EmergencyPatientInput["sex"],
                  }))
                }
              >
                <option value="unknown">Unknown</option>
                <option value="female">Female</option>
                <option value="male">Male</option>
                <option value="other">Other</option>
              </select>
            </label>
            <label className="block space-y-1 text-sm">
              <span className="text-muted-foreground">Estimated age (years)</span>
              <input
                type="number"
                min="0"
                max="150"
                required
                className="w-full rounded-md border border-border px-3 py-2"
                value={form.age_years}
                onChange={(event) =>
                  setForm((current) => ({ ...current, age_years: Number(event.target.value) }))
                }
              />
            </label>
          </div>
          <label className="block space-y-1 text-sm">
            <span className="text-muted-foreground">Mobile (optional)</span>
            <input
              type="tel"
              className="w-full rounded-md border border-border px-3 py-2"
              value={form.mobile ?? ""}
              onChange={(event) => setForm((current) => ({ ...current, mobile: event.target.value }))}
            />
          </label>
          <button
            type="submit"
            disabled={busy}
            className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground disabled:opacity-50"
          >
            {busy ? "Issuing THID…" : "Register and issue THID"}
          </button>
        </form>
      )}

      <section className="space-y-4 pt-4 border-t border-border">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-xl font-semibold">Active Emergency Arrivals</h2>
            <p className="text-xs text-muted-foreground">Emergency visits active for clinical consultation</p>
          </div>
          <button
            type="button"
            onClick={() => void loadWorklist()}
            disabled={worklistLoading}
            className="text-xs text-primary underline hover:text-primary/80"
          >
            {worklistLoading ? "Refreshing…" : "Refresh arrivals"}
          </button>
        </div>

        {worklist.length === 0 ? (
          <div className="surface-card p-6 text-center text-sm text-muted-foreground">
            {worklistLoading ? "Loading active arrivals…" : "No active emergency arrivals."}
          </div>
        ) : (
          <div className="surface-card overflow-hidden divide-y divide-border">
            {worklist.map((item) => (
              <div key={item.visit_id} className="p-4 flex flex-wrap items-center justify-between gap-3 hover:bg-muted/30">
                <div>
                  <div className="flex items-center gap-2">
                    <span className="font-mono text-sm font-semibold text-primary">{item.thid ?? item.uhid ?? "Unknown"}</span>
                    <span className="font-medium text-sm">{item.full_name}</span>
                    <span className="text-xs text-muted-foreground">· {item.age_years ?? "?"}y/{item.sex[0]?.toUpperCase()}</span>
                  </div>
                  <p className="text-xs text-muted-foreground mt-0.5">
                    Visit {item.visit_number} · Arrived {new Date(item.arrival_time).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
                  </p>
                </div>
                <Link
                  href={`/doctor/consultation?visit_id=${item.visit_id}`}
                  className="rounded-md bg-primary text-white px-3 py-1.5 text-xs font-medium hover:bg-primary/90"
                >
                  Consultation
                </Link>
              </div>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}
