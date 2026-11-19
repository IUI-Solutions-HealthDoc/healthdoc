"use client";

import { useState } from "react";

import { useLocale, translate } from "@/lib/i18n";

import { ApiError, getUserFacingError } from "@/lib/api";

import {
  copyPlatformFacilitySetup,
  createPlatformFacility,
  createPlatformFacilityAdmin,
  updatePlatformFacility,
  type PlatformFacility,
} from "./api";

const input = "w-full rounded-md border border-border px-3 py-2 text-sm";
const primary = "rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground disabled:opacity-50";
const HFR_ID = /^IN\d{10}$/;
const CODE = /^[A-Za-z0-9_]{1,20}$/;
// The server's own rules (users/schemas.StaffUsername, EmailStr): an email-style
// username was refused with a bare 422 that the panel could not explain (6 Oct 2026).
const USERNAME = /^[A-Za-z0-9._-]{3,100}$/;
const EMAIL = /^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$/;

/** A 422's field-by-field reasons, so the superadmin sees what to change. */
function said(reason: unknown, fallback: string): string {
  if (reason instanceof ApiError && reason.code === 422) {
    // api() passes the bare 422 list; older callers wrapped it as {detail}.
    const payload = reason.payload as unknown;
    const detail = Array.isArray(payload) ? payload : (payload as { detail?: unknown } | undefined)?.detail;
    if (Array.isArray(detail)) {
      const parts = detail
        .map((d: { loc?: unknown[]; msg?: unknown }) => `${(d.loc ?? []).slice(-1).join("")}: ${String(d.msg ?? "")}`)
        .filter((text) => text.length > 2);
      if (parts.length) return parts.join("; ");
    }
  }
  return getUserFacingError(reason, fallback);
}

/**
 * Bring a facility into this deployment: create it, give it its first admin,
 * copy another facility's setup (departments, rooms, wards, stores, today's
 * tariff). That admin adds the rest of the staff from the Users screen.
 * Speaking to ABDM as this facility also needs its HFR id linked to the bridge
 * and listed in ABDM_ADDITIONAL_HFR_FACILITY_IDS by operations.
 */
export function FacilityOnboarding({ facilities, onChanged }: {
  facilities: PlatformFacility[];
  onChanged: () => void;
}) {
  const { t } = useLocale();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [form, setForm] = useState({ code: "", name: "", state_code: "", ownership: "", hfr_facility_id: "" });
  const [selected, setSelected] = useState("");
  const [hfr, setHfr] = useState("");
  const [admin, setAdmin] = useState({ username: "", full_name: "", email: "", temporary_password: "" });
  const [source, setSource] = useState("");
  const target = facilities.find((f) => f.id === selected);
  // The Create buttons stayed disabled until every rule held, so a click said
  // nothing about what was wrong (QA 17 Oct 2026). They now always answer.
  const [triedCreate, setTriedCreate] = useState(false);
  const [triedAdmin, setTriedAdmin] = useState(false);

  async function run(action: () => Promise<string>, fallback: string) {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      setNotice(await action());
      onChanged();
    } catch (reason) {
      setError(said(reason, fallback));
    } finally {
      setBusy(false);
    }
  }

  const createProblems = {
    code: !CODE.test(form.code),
    name: !form.name.trim(),
    state_code: !/^[A-Z]{2,5}$/.test(form.state_code),
    hfr: Boolean(form.hfr_facility_id) && !HFR_ID.test(form.hfr_facility_id),
  };
  const canCreate = !Object.values(createProblems).some(Boolean);
  const adminProblems = {
    username: !USERNAME.test(admin.username),
    full_name: !admin.full_name.trim(),
    email: admin.email !== "" && !EMAIL.test(admin.email),
    password: admin.temporary_password.length < 8,
  };
  const canAdmin = !Object.values(adminProblems).some(Boolean);
  const mark = (tried: boolean, bad: boolean) => (tried && bad ? true : undefined);

  return (
    <section className="surface-card space-y-5 p-5" aria-label={t("platform.onboardTitle")}>
      <div>
        <h2 className="text-lg font-medium">{t("platform.onboardTitle")}</h2>
        <p className="mt-1 text-sm text-muted-foreground">{t("platform.onboardIntro")}</p>
      </div>

      <div className="grid gap-3 sm:grid-cols-5">
        <input aria-label={t("platform.code")} placeholder={t("platform.codePlaceholder")} className={input} value={form.code}
          aria-invalid={mark(triedCreate, createProblems.code)}
          onChange={(e) => setForm((f) => ({ ...f, code: e.target.value }))} />
        <input aria-label={t("platform.name")} placeholder={t("platform.facilityName")} className={`${input} sm:col-span-2`} value={form.name}
          aria-invalid={mark(triedCreate, createProblems.name)}
          onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))} />
        <input aria-label={t("platform.stateCode")} placeholder={t("platform.statePlaceholder")} className={input} value={form.state_code}
          aria-invalid={mark(triedCreate, createProblems.state_code)}
          onChange={(e) => setForm((f) => ({ ...f, state_code: e.target.value.toUpperCase() }))} />
        <select aria-label={t("platform.ownership")} className={input} value={form.ownership}
          onChange={(e) => setForm((f) => ({ ...f, ownership: e.target.value }))}>
          <option value="">{t("platform.ownership")}</option>
          <option value="private">{t("platform.private")}</option>
          <option value="government">{t("platform.government")}</option>
        </select>
        <input aria-label={t("platform.hfrId")} placeholder={t("platform.hfrOptional")} className={`${input} sm:col-span-2`}
          aria-invalid={mark(triedCreate, createProblems.hfr)}
          value={form.hfr_facility_id} onChange={(e) => setForm((f) => ({ ...f, hfr_facility_id: e.target.value.trim() }))} />
        <button type="button" className={primary} disabled={busy}
          onClick={() => {
            if (!canCreate) {
              setTriedCreate(true);
              setNotice(null);
              setError(t("platform.createFacilityFields"));
              return;
            }
            setTriedCreate(false);
            void run(async () => {
            const created = await createPlatformFacility({
              code: form.code, name: form.name.trim(), state_code: form.state_code,
              ownership: (form.ownership || null) as "government" | "private" | null,
              hfr_facility_id: form.hfr_facility_id || null,
            });
            setSelected(created.id);
            setForm({ code: "", name: "", state_code: "", ownership: "", hfr_facility_id: "" });
            return translate("platform.msg.nameCreatedNowGiveItIts", undefined, { name: created.name });
          }, t("platform.errFacility"));
          }}>{t("platform.createFacility")}</button>
      </div>

      <label className="block space-y-1 text-sm">
        <span className="text-muted-foreground">{t("platform.facilityToSetUp")}</span>
        <select aria-label={t("platform.facilityToSetUp")} className={input} value={selected}
          onChange={(e) => { setSelected(e.target.value); setHfr(facilities.find((f) => f.id === e.target.value)?.hfr_facility_id ?? ""); }}>
          <option value="">{t("platform.choose")}</option>
          {facilities.map((f) => <option key={f.id} value={f.id}>{f.name} ({f.code})</option>)}
        </select>
      </label>

      {target ? (
        <div className="space-y-4">
          <div className="flex flex-wrap items-end gap-3">
            <label className="flex-1 space-y-1 text-sm">
              <span className="text-muted-foreground">{t("platform.hfrId")}</span>
              <input aria-label={t("platform.setHfr")} className={input} value={hfr} placeholder={t("platform.ui.in0910034387")}
                onChange={(e) => setHfr(e.target.value.trim())} />
            </label>
            <button type="button" className={primary} disabled={busy || (hfr !== "" && !HFR_ID.test(hfr))}
              onClick={() => void run(async () => {
                await updatePlatformFacility(target.id, { hfr_facility_id: hfr || null });
                return hfr ? translate("platform.msg.hfrIdHfrSavedForName", undefined, { hfr, name: target.name }) : translate("platform.msg.hfrIdClearedForName", undefined, { name: target.name });
              }, t("platform.errHfr"))}>{t("platform.saveHfr")}</button>
          </div>

          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={Boolean(target.publish_availability)} disabled={busy}
              onChange={(e) => {
                const publish = e.target.checked;
                void run(async () => {
                  await updatePlatformFacility(target.id, { publish_availability: publish });
                  return publish
                    ? translate("platform.msg.nameSFreeBedsAndBlood", undefined, { name: target.name })
                    : translate("platform.msg.nameIsNoLongerOnThe", undefined, { name: target.name });
                }, t("platform.errPublish"));
              }} />{t("platform.publishAvailability")}</label>

          <div className="grid gap-3 sm:grid-cols-4">
            <div className="space-y-1">
              <input aria-label={t("platform.adminUsername")} placeholder={t("platform.adminUsername")} className={input} value={admin.username}
                aria-invalid={(admin.username !== "" || triedAdmin) && !USERNAME.test(admin.username)}
                onChange={(e) => setAdmin((a) => ({ ...a, username: e.target.value.trim() }))} />
              {admin.username !== "" && !USERNAME.test(admin.username) ? (
                <p role="alert" className="text-xs text-danger">{t("platform.usernameRule")}</p>
              ) : null}
            </div>
            <input aria-label={t("platform.adminFullName")} placeholder={t("platform.fullName")} className={input} value={admin.full_name}
              aria-invalid={mark(triedAdmin, adminProblems.full_name)}
              onChange={(e) => setAdmin((a) => ({ ...a, full_name: e.target.value }))} />
            <input aria-label={t("platform.adminEmail")} placeholder={t("platform.emailOptional")} className={input} value={admin.email}
              aria-invalid={mark(triedAdmin, adminProblems.email)}
              onChange={(e) => setAdmin((a) => ({ ...a, email: e.target.value.trim() }))} />
            <input aria-label={t("platform.tempPassword")} type="password" placeholder={t("platform.tempPassword8")} className={input}
              aria-invalid={mark(triedAdmin, adminProblems.password)}
              value={admin.temporary_password} onChange={(e) => setAdmin((a) => ({ ...a, temporary_password: e.target.value }))} />
            <button type="button" className={primary} disabled={busy}
              onClick={() => {
                if (!canAdmin) {
                  setTriedAdmin(true);
                  setNotice(null);
                  setError(t("platform.createAdminFields"));
                  return;
                }
                setTriedAdmin(false);
                void run(async () => {
                const created = await createPlatformFacilityAdmin(target.id, {
                  username: admin.username, full_name: admin.full_name.trim(),
                  email: admin.email || null, temporary_password: admin.temporary_password,
                });
                setAdmin({ username: "", full_name: "", email: "", temporary_password: "" });
                return translate("platform.msg.adminUsernameCreatedAtNameThey", undefined, { username: created.username, name: target.name });
              }, t("platform.errAdmin"));
              }}>{t("platform.createFirstAdmin")}</button>
          </div>

          <div className="flex flex-wrap items-end gap-3">
            <label className="flex-1 space-y-1 text-sm">
              <span className="text-muted-foreground">{t("platform.copySetupFrom")}</span>
              <select aria-label={t("platform.copySetupFrom")} className={input} value={source} onChange={(e) => setSource(e.target.value)}>
                <option value="">{t("platform.choose")}</option>
                {facilities.filter((f) => f.id !== target.id).map((f) => <option key={f.id} value={f.id}>{f.name} ({f.code})</option>)}
              </select>
            </label>
            <button type="button" className={primary} disabled={busy || !source}
              onClick={() => void run(async () => {
                const copied = await copyPlatformFacilitySetup(target.id, source);
                return translate("platform.msg.copiedDepartmentsDepartmentsRoomsRoomsWards", undefined, { departments: copied.departments, rooms: copied.rooms, wards: copied.wards })
                  + translate("platform.msg.stockLocationsStoresAndTariffRows", undefined, { stock_locations: copied.stock_locations, tariff_rows: copied.tariff_rows });
              }, t("platform.errCopy"))}>{t("platform.copySetup")}</button>
          </div>
        </div>
      ) : null}

      {notice ? <p role="status" className="rounded-md bg-success-muted p-3 text-sm text-success">{notice}</p> : null}
      {error ? <p role="alert" className="rounded-md bg-danger-muted p-3 text-sm text-danger">{error}</p> : null}
    </section>
  );
}
