"use client";

import { useState } from "react";

import { getUserFacingError } from "@/lib/api";

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
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [form, setForm] = useState({ code: "", name: "", state_code: "", ownership: "", hfr_facility_id: "" });
  const [selected, setSelected] = useState("");
  const [hfr, setHfr] = useState("");
  const [admin, setAdmin] = useState({ username: "", full_name: "", email: "", temporary_password: "" });
  const [source, setSource] = useState("");
  const target = facilities.find((f) => f.id === selected);

  async function run(action: () => Promise<string>, fallback: string) {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      setNotice(await action());
      onChanged();
    } catch (reason) {
      setError(getUserFacingError(reason, fallback));
    } finally {
      setBusy(false);
    }
  }

  const canCreate = CODE.test(form.code) && form.name.trim() && /^[A-Z]{2,5}$/.test(form.state_code)
    && (!form.hfr_facility_id || HFR_ID.test(form.hfr_facility_id));
  const canAdmin = admin.username.length >= 3 && admin.full_name.trim() && admin.temporary_password.length >= 8;

  return (
    <section className="surface-card space-y-5 p-5" aria-label="Onboard a facility">
      <div>
        <h2 className="text-lg font-medium">Onboard a facility</h2>
        <p className="mt-1 text-sm text-muted-foreground">
          Create it, give it its first admin, then copy another facility&apos;s setup. Each step runs once.
        </p>
      </div>

      <div className="grid gap-3 sm:grid-cols-5">
        <input aria-label="Code" placeholder="Code (e.g. DEV002)" className={input} value={form.code}
          onChange={(e) => setForm((f) => ({ ...f, code: e.target.value }))} />
        <input aria-label="Name" placeholder="Facility name" className={`${input} sm:col-span-2`} value={form.name}
          onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))} />
        <input aria-label="State code" placeholder="State (e.g. BR)" className={input} value={form.state_code}
          onChange={(e) => setForm((f) => ({ ...f, state_code: e.target.value.toUpperCase() }))} />
        <select aria-label="Ownership" className={input} value={form.ownership}
          onChange={(e) => setForm((f) => ({ ...f, ownership: e.target.value }))}>
          <option value="">Ownership</option>
          <option value="private">Private</option>
          <option value="government">Government</option>
        </select>
        <input aria-label="HFR facility id" placeholder="HFR id (optional, IN0910034387)" className={`${input} sm:col-span-2`}
          value={form.hfr_facility_id} onChange={(e) => setForm((f) => ({ ...f, hfr_facility_id: e.target.value.trim() }))} />
        <button type="button" className={primary} disabled={busy || !canCreate}
          onClick={() => void run(async () => {
            const created = await createPlatformFacility({
              code: form.code, name: form.name.trim(), state_code: form.state_code,
              ownership: (form.ownership || null) as "government" | "private" | null,
              hfr_facility_id: form.hfr_facility_id || null,
            });
            setSelected(created.id);
            setForm({ code: "", name: "", state_code: "", ownership: "", hfr_facility_id: "" });
            return `${created.name} created. Now give it its first admin.`;
          }, "The facility could not be created.")}>Create facility</button>
      </div>

      <label className="block space-y-1 text-sm">
        <span className="text-muted-foreground">Facility to set up</span>
        <select aria-label="Facility to set up" className={input} value={selected}
          onChange={(e) => { setSelected(e.target.value); setHfr(facilities.find((f) => f.id === e.target.value)?.hfr_facility_id ?? ""); }}>
          <option value="">Choose</option>
          {facilities.map((f) => <option key={f.id} value={f.id}>{f.name} ({f.code})</option>)}
        </select>
      </label>

      {target ? (
        <div className="space-y-4">
          <div className="flex flex-wrap items-end gap-3">
            <label className="flex-1 space-y-1 text-sm">
              <span className="text-muted-foreground">HFR facility id</span>
              <input aria-label="Set HFR facility id" className={input} value={hfr} placeholder="IN0910034387"
                onChange={(e) => setHfr(e.target.value.trim())} />
            </label>
            <button type="button" className={primary} disabled={busy || (hfr !== "" && !HFR_ID.test(hfr))}
              onClick={() => void run(async () => {
                await updatePlatformFacility(target.id, { hfr_facility_id: hfr || null });
                return hfr ? `HFR id ${hfr} saved for ${target.name}.` : `HFR id cleared for ${target.name}.`;
              }, "The HFR id could not be saved.")}>Save HFR id</button>
          </div>

          <div className="grid gap-3 sm:grid-cols-4">
            <input aria-label="Admin username" placeholder="Admin username" className={input} value={admin.username}
              onChange={(e) => setAdmin((a) => ({ ...a, username: e.target.value.trim() }))} />
            <input aria-label="Admin full name" placeholder="Full name" className={input} value={admin.full_name}
              onChange={(e) => setAdmin((a) => ({ ...a, full_name: e.target.value }))} />
            <input aria-label="Admin email" placeholder="Email (optional)" className={input} value={admin.email}
              onChange={(e) => setAdmin((a) => ({ ...a, email: e.target.value.trim() }))} />
            <input aria-label="Temporary password" type="password" placeholder="Temporary password" className={input}
              value={admin.temporary_password} onChange={(e) => setAdmin((a) => ({ ...a, temporary_password: e.target.value }))} />
            <button type="button" className={primary} disabled={busy || !canAdmin}
              onClick={() => void run(async () => {
                const created = await createPlatformFacilityAdmin(target.id, {
                  username: admin.username, full_name: admin.full_name.trim(),
                  email: admin.email || null, temporary_password: admin.temporary_password,
                });
                setAdmin({ username: "", full_name: "", email: "", temporary_password: "" });
                return `Admin ${created.username} created at ${target.name}. They change the password at first sign-in.`;
              }, "The admin could not be created.")}>Create first admin</button>
          </div>

          <div className="flex flex-wrap items-end gap-3">
            <label className="flex-1 space-y-1 text-sm">
              <span className="text-muted-foreground">Copy setup from</span>
              <select aria-label="Copy setup from" className={input} value={source} onChange={(e) => setSource(e.target.value)}>
                <option value="">Choose</option>
                {facilities.filter((f) => f.id !== target.id).map((f) => <option key={f.id} value={f.id}>{f.name} ({f.code})</option>)}
              </select>
            </label>
            <button type="button" className={primary} disabled={busy || !source}
              onClick={() => void run(async () => {
                const copied = await copyPlatformFacilitySetup(target.id, source);
                return `Copied ${copied.departments} departments, ${copied.rooms} rooms, ${copied.wards} wards, `
                  + `${copied.stock_locations} stores and ${copied.tariff_rows} tariff rows.`;
              }, "The setup could not be copied.")}>Copy setup</button>
          </div>
        </div>
      ) : null}

      {notice ? <p role="status" className="rounded-md bg-success-muted p-3 text-sm text-success">{notice}</p> : null}
      {error ? <p role="alert" className="rounded-md bg-danger-muted p-3 text-sm text-danger">{error}</p> : null}
    </section>
  );
}
