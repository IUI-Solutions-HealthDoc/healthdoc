"use client";

/**
 * Control-room officers: state or district health officials who watch
 * hospitals on /monitor. Each has a Keycloak account with only the monitor
 * role and no hospital, and sees only the areas granted here: a whole state,
 * or named districts in it. Removing an officer's last area closes their
 * board (it is refused, never shown empty).
 */
import { useCallback, useEffect, useMemo, useState } from "react";

import { ApiError, getUserFacingError } from "@/lib/api";

import {
  addMonitorScope,
  createMonitor,
  listMonitorScopes,
  removeMonitorScope,
  type MonitorScope,
  type PlatformFacility,
} from "./api";

const input = "w-full rounded-md border border-border px-3 py-2 text-sm";
const primary = "rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground disabled:opacity-50";
// Same rules the server applies (users/schemas.StaffUsername, EmailStr).
const USERNAME = /^[A-Za-z0-9._-]{3,100}$/;
const EMAIL = /^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$/;
const STATE = /^[A-Z]{2,5}$/;

function said(reason: unknown, fallback: string): string {
  if (reason instanceof ApiError && reason.code === 422) {
    const detail = (reason.payload as { detail?: unknown } | undefined)?.detail;
    if (Array.isArray(detail)) {
      const parts = detail
        .map((d: { loc?: unknown[]; msg?: unknown }) => `${(d.loc ?? []).slice(-1).join("")}: ${String(d.msg ?? "")}`)
        .filter((text) => text.length > 2);
      if (parts.length) return parts.join("; ");
    }
  }
  return getUserFacingError(reason, fallback);
}

function area(scope: Pick<MonitorScope, "state_code" | "district">): string {
  return scope.district ? `${scope.district}, ${scope.state_code}` : `${scope.state_code} (whole state)`;
}

export function ControlRoomOfficers({ facilities }: { facilities: PlatformFacility[] }) {
  const [scopes, setScopes] = useState<MonitorScope[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [form, setForm] = useState({
    username: "", full_name: "", email: "", temporary_password: "", state_code: "", district: "",
  });
  const [extra, setExtra] = useState<Record<string, { state_code: string; district: string }>>({});

  const load = useCallback(async () => {
    try {
      setScopes(await listMonitorScopes());
      setLoadError(null);
    } catch (reason) {
      // Shown as a failure, never as "no officers yet".
      setLoadError(getUserFacingError(reason, "Control-room officers could not be loaded."));
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  // Districts the deployment actually has, per state, so a grant matches the
  // facilities' own spelling (the board compares case-blind, not by fuzzy match).
  const districts = useMemo(() => {
    const byState = new Map<string, Set<string>>();
    for (const facility of facilities) {
      if (!facility.district) continue;
      const set = byState.get(facility.state_code) ?? new Set<string>();
      set.add(facility.district.trim());
      byState.set(facility.state_code, set);
    }
    return byState;
  }, [facilities]);

  const officers = useMemo(() => {
    const grouped = new Map<string, { username: string; scopes: MonitorScope[] }>();
    for (const scope of scopes ?? []) {
      const entry = grouped.get(scope.keycloak_sub) ?? { username: scope.username, scopes: [] };
      entry.scopes.push(scope);
      grouped.set(scope.keycloak_sub, entry);
    }
    return [...grouped.entries()].sort((a, b) => a[1].username.localeCompare(b[1].username));
  }, [scopes]);

  async function run(action: () => Promise<string>, fallback: string) {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      setNotice(await action());
      await load();
    } catch (reason) {
      setError(said(reason, fallback));
    } finally {
      setBusy(false);
    }
  }

  const canCreate = USERNAME.test(form.username) && form.full_name.trim() && form.temporary_password.length >= 8
    && (form.email === "" || EMAIL.test(form.email)) && STATE.test(form.state_code);

  function districtList(id: string, state: string) {
    return (
      <datalist id={id}>
        {[...(districts.get(state) ?? [])].sort().map((name) => <option key={name} value={name} />)}
      </datalist>
    );
  }

  return (
    <section className="surface-card space-y-5 p-5" aria-label="Control-room officers">
      <div>
        <h2 className="text-lg font-medium">Control-room officers</h2>
        <p className="mt-1 text-sm text-muted-foreground">
          State and district officials who watch hospitals on the control room. They see counts for the
          facilities in their area and, on request, a day&apos;s activity with patients shown as codes, never names.
          They belong to no hospital.
        </p>
      </div>

      <div className="grid gap-3 sm:grid-cols-6">
        <input aria-label="Officer username" placeholder="Username (e.g. patna.cmo)" className={input}
          value={form.username} onChange={(e) => setForm((f) => ({ ...f, username: e.target.value.trim() }))} />
        <input aria-label="Officer full name" placeholder="Full name" className={`${input} sm:col-span-2`}
          value={form.full_name} onChange={(e) => setForm((f) => ({ ...f, full_name: e.target.value }))} />
        <input aria-label="Officer email" placeholder="Email (optional)" className={input}
          value={form.email} onChange={(e) => setForm((f) => ({ ...f, email: e.target.value.trim() }))} />
        <input aria-label="Officer temporary password" type="password" placeholder="Temporary password (8+)" className={`${input} sm:col-span-2`}
          value={form.temporary_password} onChange={(e) => setForm((f) => ({ ...f, temporary_password: e.target.value }))} />
        <input aria-label="Officer state" placeholder="State (e.g. BR)" className={input}
          value={form.state_code} onChange={(e) => setForm((f) => ({ ...f, state_code: e.target.value.toUpperCase().trim() }))} />
        <input aria-label="Officer district" placeholder="District (blank = whole state)" list="new-officer-districts"
          className={`${input} sm:col-span-2`} value={form.district}
          onChange={(e) => setForm((f) => ({ ...f, district: e.target.value }))} />
        {districtList("new-officer-districts", form.state_code)}
        <button type="button" className={`${primary} sm:col-span-3`} disabled={busy || !canCreate}
          onClick={() => void run(async () => {
            const created = await createMonitor({
              username: form.username, full_name: form.full_name.trim(), email: form.email || null,
              temporary_password: form.temporary_password, state_code: form.state_code,
              district: form.district.trim() || null,
            });
            setForm({ username: "", full_name: "", email: "", temporary_password: "", state_code: "", district: "" });
            return `${created.username} can sign in and see ${area(created)}. They change the temporary password at first sign-in.`;
          }, "The officer could not be created.")}>Create officer</button>
      </div>

      {error ? <p className="text-sm text-danger" role="alert">{error}</p> : null}
      {notice ? <p className="text-sm text-success" role="status">{notice}</p> : null}
      {loadError ? <p className="text-sm text-danger" role="alert">{loadError}</p> : null}
      {scopes === null && !loadError ? <p className="text-sm text-muted-foreground">Loading officers…</p> : null}
      {scopes !== null && officers.length === 0 ? (
        <p className="text-sm text-muted-foreground">No control-room officers yet.</p>
      ) : null}

      <ul className="space-y-3">
        {officers.map(([sub, officer]) => {
          const draft = extra[sub] ?? { state_code: "", district: "" };
          const listId = `districts-${sub}`;
          return (
            <li key={sub} className="rounded border border-border p-3 text-sm">
              <p className="font-medium">{officer.username}</p>
              <ul className="mt-2 flex flex-wrap gap-2">
                {officer.scopes.map((scope) => (
                  <li key={scope.id} className="flex items-center gap-2 rounded border border-border px-2 py-1 text-xs">
                    {area(scope)}
                    <button type="button" className="underline disabled:opacity-50" disabled={busy}
                      aria-label={`Remove ${area(scope)} from ${officer.username}`}
                      onClick={() => void run(async () => {
                        await removeMonitorScope(scope.id);
                        return officer.scopes.length === 1
                          ? `${officer.username} has no area left; their control room is closed until one is granted.`
                          : `${area(scope)} removed from ${officer.username}.`;
                      }, "The area could not be removed.")}>Remove</button>
                  </li>
                ))}
              </ul>
              <div className="mt-2 flex flex-wrap items-center gap-2">
                <input aria-label={`State to add for ${officer.username}`} placeholder="State" className="w-24 rounded-md border border-border px-2 py-1 text-xs"
                  value={draft.state_code}
                  onChange={(e) => setExtra((all) => ({ ...all, [sub]: { ...draft, state_code: e.target.value.toUpperCase().trim() } }))} />
                <input aria-label={`District to add for ${officer.username}`} placeholder="District (blank = whole state)" list={listId}
                  className="min-w-48 rounded-md border border-border px-2 py-1 text-xs" value={draft.district}
                  onChange={(e) => setExtra((all) => ({ ...all, [sub]: { ...draft, district: e.target.value } }))} />
                {districtList(listId, draft.state_code)}
                <button type="button" className="rounded-md border border-border px-3 py-1 text-xs font-medium disabled:opacity-50"
                  disabled={busy || !STATE.test(draft.state_code)}
                  onClick={() => void run(async () => {
                    const added = await addMonitorScope(sub, { state_code: draft.state_code, district: draft.district.trim() || null });
                    setExtra((all) => ({ ...all, [sub]: { state_code: "", district: "" } }));
                    return `${officer.username} can now also see ${area(added)}.`;
                  }, "The area could not be added.")}>Add area</button>
              </div>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
