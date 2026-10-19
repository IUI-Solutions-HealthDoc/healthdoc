"use client";

/**
 * Wards and beds. Nothing created beds before (QA 10 Oct 2026): a fresh
 * facility had wards with no beds and nobody could be admitted. Beds are
 * added and taken out of service with a reason, never deleted, because
 * admissions keep pointing at them.
 */
import { useCallback, useEffect, useState } from "react";

import { ApiError, api, newIdempotencyKey } from "@/lib/api";
import { useLocale, translate } from "@/lib/i18n";

interface Ward {
  id: string;
  name: string;
}

interface BedItem {
  bed_id: string;
  bed_number: string;
  status: string;
  occupant: unknown | null;
}

export default function Page() {
  const { t } = useLocale();
  const [wards, setWards] = useState<Ward[] | null>(null);
  const [wardId, setWardId] = useState("");
  const [beds, setBeds] = useState<BedItem[] | null>(null);
  const [number, setNumber] = useState("");
  const [reasons, setReasons] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => {
    api<Ward[]>("/wards")
      .then((rows) => {
        setWards(rows);
        if (rows.length) setWardId((current) => current || rows[0].id);
      })
      .catch((reason) => setError(reason instanceof ApiError ? reason.message : translate("admin.msg.wardsCouldNotBeLoaded")));
  }, []);

  const loadBeds = useCallback(async (id: string) => {
    if (!id) return;
    setBeds(null);
    try {
      const grid = await api<{ items: BedItem[] }>(`/wards/${id}/beds`);
      setBeds(grid.items);
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : translate("admin.msg.bedsCouldNotBeLoaded"));
    }
  }, []);

  useEffect(() => {
    void loadBeds(wardId);
  }, [wardId, loadBeds]);

  async function run(action: () => Promise<unknown>, done: string) {
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      await action();
      setMessage(done);
      await loadBeds(wardId);
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : translate("admin.msg.theChangeWasNotSaved"));
    } finally {
      setBusy(false);
    }
  }

  const addBed = () => run(
    () => api(`/wards/${wardId}/beds`, {
      method: "POST",
      body: JSON.stringify({ bed_number: number.trim() }),
      idempotencyKey: newIdempotencyKey(),
    }).then(() => setNumber("")),
    translate("admin.msg.bedValueAdded", undefined, { value: number.trim().toUpperCase() }),
  );

  const setStatus = (bed: BedItem, status: "vacant" | "maintenance") => run(
    () => api(`/wards/beds/${bed.bed_id}`, {
      method: "PATCH",
      body: JSON.stringify({ status, reason: (reasons[bed.bed_id] ?? "").trim() }),
    }),
    status === "maintenance" ? translate("admin.msg.bedBedNumberTakenOutOf", undefined, { bed_number: bed.bed_number }) : translate("admin.msg.bedBedNumberBackInService", undefined, { bed_number: bed.bed_number }),
  );

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">{t("sidebar.wardsBeds")}</h1>
        <p className="text-sm text-muted-foreground">{t("admin.ui.addBedsToAWardOr")}</p>
      </div>

      {error ? <p role="alert" className="text-sm text-danger">{error}</p> : null}
      {message ? <p role="status" className="text-sm text-success">{message}</p> : null}

      {wards && wards.length === 0 ? (
        <p className="text-sm text-muted-foreground">{t("admin.ui.noWardsYetWardsAreCreated")}</p>
      ) : null}

      {wards && wards.length > 0 ? (
        <section className="surface-card space-y-4 p-5">
          <div className="flex flex-wrap items-end gap-3">
            <label className="text-sm">
              <span className="block text-muted-foreground">{t("monitor.ward")}</span>
              <select value={wardId} onChange={(e) => setWardId(e.target.value)}
                className="mt-1 rounded-md border border-border px-2 py-2">
                {wards.map((w) => <option key={w.id} value={w.id}>{w.name}</option>)}
              </select>
            </label>
            <label className="text-sm">
              <span className="block text-muted-foreground">{t("admin.ui.newBedNumber")}</span>
              <input value={number} maxLength={20} onChange={(e) => setNumber(e.target.value)}
                placeholder={t("admin.ui.eG7OrA12")} className="mt-1 rounded-md border border-border px-2 py-2" />
            </label>
            <button type="button" disabled={busy || !wardId || !/^[A-Za-z0-9][A-Za-z0-9 ./-]*$/.test(number.trim())}
              onClick={() => void addBed()}
              className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-white disabled:opacity-50">{t("admin.ui.addBed")}</button>
          </div>

          {beds === null ? <p className="text-sm text-muted-foreground">{t("admin.ui.loadingBeds")}</p> : beds.length === 0 ? (
            <p className="text-sm text-amber-800">{t("admin.ui.thisWardHasNoBedsYet")}</p>
          ) : (
            <table className="min-w-full border-collapse text-sm">
              <thead className="bg-muted">
                <tr>
                  <th className="px-3 py-2 text-left">{t("ipd.bed")}</th>
                  <th className="px-3 py-2 text-left">{t("common.status")}</th>
                  <th className="px-3 py-2 text-left">{t("admin.ui.reasonForTheChange")}</th>
                  <th className="px-3 py-2 text-left">{t("receptionist.action")}</th>
                </tr>
              </thead>
              <tbody>
                {beds.map((bed) => {
                  const occupied = Boolean(bed.occupant);
                  const reason = (reasons[bed.bed_id] ?? "").trim();
                  return (
                    <tr key={bed.bed_id} className="border-b border-border">
                      <td className="px-3 py-2 font-mono">{bed.bed_number}</td>
                      <td className="px-3 py-2 capitalize">{occupied ? "occupied" : bed.status}</td>
                      <td className="px-3 py-2">
                        {occupied ? <span className="text-muted-foreground">{t("admin.ui.patientAdmitted")}</span> : (
                          <input value={reasons[bed.bed_id] ?? ""} maxLength={300}
                            onChange={(e) => setReasons((r) => ({ ...r, [bed.bed_id]: e.target.value }))}
                            placeholder={t("forms.required")} aria-label={translate("admin.msg.reasonForChangingBedBedNumber", undefined, { bed_number: bed.bed_number })} className="w-full rounded-md border border-border px-2 py-1" />
                        )}
                      </td>
                      <td className="px-3 py-2">
                        {occupied ? null : bed.status === "maintenance" ? (
                          <button type="button" disabled={busy || reason.length < 3} onClick={() => void setStatus(bed, "vacant")}
                            className="text-xs underline disabled:opacity-50">{t("admin.ui.backInService")}</button>
                        ) : bed.status === "vacant" ? (
                          <button type="button" disabled={busy || reason.length < 3} onClick={() => void setStatus(bed, "maintenance")}
                            className="text-xs underline disabled:opacity-50">{t("admin.ui.outOfService")}</button>
                        ) : null}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </section>
      ) : null}
    </div>
  );
}
