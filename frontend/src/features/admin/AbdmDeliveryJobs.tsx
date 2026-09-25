"use client";

import { useEffect, useState } from "react";
import { api, getUserFacingError, newIdempotencyKey } from "@/lib/api";
import { useLocale } from "@/lib/i18n";

interface Job { id: string; kind: string; status: string; attempts: number; available_at: string; last_error: string | null }
export function AbdmDeliveryJobs() {
  const { t } = useLocale();
  const [jobs, setJobs] = useState<Job[]>([]);
  const [status, setStatus] = useState("dead");
  const [offset, setOffset] = useState(0);
  const [refresh, setRefresh] = useState(0);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let active = true;
    setLoading(true); setError(null); setJobs([]);
    api<Job[]>(`/abdm/operations/jobs?status=${status}&limit=50&offset=${offset}`)
      .then((rows) => { if (active) setJobs(rows); })
      .catch((reason) => { if (active) setError(getUserFacingError(reason, t("admin.abdm.jobs.loadFailed"))); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [status, offset, refresh, t]);
  async function retry(id: string) {
    setBusy(true); setError(null);
    try { await api<Job>(`/abdm/operations/jobs/${id}/retry`, { method: "POST", idempotencyKey: newIdempotencyKey() }); setRefresh((value) => value + 1); }
    catch (reason) { setError(getUserFacingError(reason, t("admin.abdm.jobs.requeueFailed"))); }
    finally { setBusy(false); }
  }
  return <section className="surface-card space-y-4 p-5" aria-label={t("admin.abdm.jobs.title")}>
    <h2 className="text-xl font-semibold">{t("admin.abdm.jobs.title")}</h2>
    <p className="text-sm text-muted-foreground">{t("admin.abdm.jobs.hint")}</p>
    <label className="flex items-center gap-3"><span>{t("admin.abdm.jobs.deliveryState")}</span><select className="rounded border border-border p-2" value={status} onChange={(event) => { setStatus(event.target.value); setOffset(0); }}>{["dead", "pending", "leased", "done"].map((value) => <option key={value}>{value}</option>)}</select></label>
    {error && <p role="alert" className="text-danger">{error}</p>}
    {loading && <p role="status">{t("admin.abdm.jobs.loading")}</p>}
    {!loading && !error && !jobs.length && <p>{t("admin.abdm.jobs.emptyPage")}</p>}
    <ul className="space-y-3">{jobs.map((job) => <li key={job.id} className="flex flex-wrap items-center gap-3 rounded border border-border p-3"><span>{job.kind} · {job.status} · {t("admin.abdm.jobs.attempts", { count: job.attempts })} · {job.last_error ?? t("admin.abdm.jobs.noErrorRecorded")}</span>{job.status === "dead" && <button type="button" disabled={busy} className="underline disabled:opacity-50" onClick={() => void retry(job.id)}>{t("admin.abdm.jobs.retryDelivery")}</button>}</li>)}</ul>
    <div className="flex gap-4"><button type="button" className="underline" onClick={() => { setError(null); setRefresh((value) => value + 1); }}>{t("admin.abdm.jobs.refreshJobs")}</button><button type="button" className="underline disabled:opacity-50" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - 50))}>{t("common.previous")}</button><button type="button" className="underline disabled:opacity-50" disabled={jobs.length < 50} onClick={() => setOffset(offset + 50)}>{t("common.next")}</button></div>
  </section>;
}
