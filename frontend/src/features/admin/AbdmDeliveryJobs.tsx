"use client";

import { useEffect, useState } from "react";
import { api, getUserFacingError, newIdempotencyKey } from "@/lib/api";

interface Job { id: string; kind: string; status: string; attempts: number; available_at: string; last_error: string | null }
export function AbdmDeliveryJobs() {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [status, setStatus] = useState("dead");
  const [offset, setOffset] = useState(0);
  const [refresh, setRefresh] = useState(0);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    // This bounded metadata GET can finish during cleanup. Ignore its result
    // after a filter change/unmount; Strict Mode's setup-cleanup-setup must
    // not cancel a valid read or let an older response replace the new page.
    let active = true;
    setLoading(true); setError(null); setJobs([]);
    api<Job[]>(`/abdm/operations/jobs?status=${status}&limit=50&offset=${offset}`)
      .then((rows) => { if (active) setJobs(rows); })
      .catch((reason) => { if (active) setError(getUserFacingError(reason, "ABDM jobs could not be loaded.")); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [status, offset, refresh]);
  async function retry(id: string) {
    setBusy(true); setError(null);
    try { await api<Job>(`/abdm/operations/jobs/${id}/retry`, { method: "POST", idempotencyKey: newIdempotencyKey() }); setRefresh((value) => value + 1); }
    catch (reason) { setError(getUserFacingError(reason, "Delivery could not be requeued.")); }
    finally { setBusy(false); }
  }
  return <section className="surface-card space-y-4 p-5" aria-label="ABDM delivery jobs">
    <h2 className="text-xl font-semibold">ABDM delivery jobs</h2>
    <p className="text-sm text-muted-foreground">Fix the reported configuration or connection problem before retrying. The dedicated worker must be running. Requeueing does not renew expired consent, keys or link tokens; those require a new clinical request.</p>
    <label className="flex items-center gap-3"><span>Delivery state</span><select className="rounded border border-border p-2" value={status} onChange={(event) => { setStatus(event.target.value); setOffset(0); }}>{["dead", "pending", "leased", "done"].map((value) => <option key={value}>{value}</option>)}</select></label>
    {error && <p role="alert" className="text-danger">{error}</p>}
    {loading && <p role="status">Loading delivery jobs…</p>}
    {!loading && !error && !jobs.length && <p>No jobs in this page.</p>}
    <ul className="space-y-3">{jobs.map((job) => <li key={job.id} className="flex flex-wrap items-center gap-3 rounded border border-border p-3"><span>{job.kind} · {job.status} · {job.attempts} attempt(s) · {job.last_error ?? "No error recorded"}</span>{job.status === "dead" && <button type="button" disabled={busy} className="underline disabled:opacity-50" onClick={() => void retry(job.id)}>Retry delivery</button>}</li>)}</ul>
    <div className="flex gap-4"><button type="button" className="underline" onClick={() => { setError(null); setRefresh((value) => value + 1); }}>Refresh jobs</button><button type="button" className="underline disabled:opacity-50" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - 50))}>Previous</button><button type="button" className="underline disabled:opacity-50" disabled={jobs.length < 50} onClick={() => setOffset(offset + 50)}>Next</button></div>
  </section>;
}
