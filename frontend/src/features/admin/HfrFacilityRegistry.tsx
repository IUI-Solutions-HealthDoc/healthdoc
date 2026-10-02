"use client";

import { useEffect, useRef, useState } from "react";

import { ApiError, newIdempotencyKey } from "@/lib/api";
import {
  hfrDistricts,
  hfrMaster,
  hfrStates,
  hfrSubdistricts,
  linkHfrBridge,
  searchHfr,
  type HfrBridgeService,
  type HfrFacility,
  type HfrOption,
  type HfrSearch,
  type HfrSearchResult,
} from "./api/hfr";

function failure(reason: unknown, fallback: string): string {
  return reason instanceof ApiError ? reason.message : fallback;
}

const label = (option: HfrOption) => option.value ?? option.name ?? option.code;
const input = "w-full rounded-md border border-border px-3 py-2 text-sm";
/** HFR-001: twelve characters starting with IN. */
const FACILITY_ID = /^IN[0-9A-Z]{10}$/;

/**
 * ABDM M4 Health Facility Registry: search (HFR-001 to 009) and linking a
 * facility to HealthDoc's bridge (HFR-118 to 123). Every list comes from HFR;
 * a list that fails to load says so instead of showing an empty dropdown.
 */
export function HfrFacilityRegistry() {
  const [owners, setOwners] = useState<HfrOption[] | null>(null);
  const [states, setStates] = useState<HfrOption[] | null>(null);
  const [districts, setDistricts] = useState<HfrOption[] | null>(null);
  const [subdistricts, setSubdistricts] = useState<HfrOption[] | null>(null);
  const [listError, setListError] = useState<string | null>(null);
  const [criteria, setCriteria] = useState<Required<Omit<HfrSearch, "page">>>({
    facility_id: "", facility_name: "", ownership_code: "", state_lgd_code: "",
    district_lgd_code: "", subdistrict_lgd_code: "", pincode: "",
  });
  const [result, setResult] = useState<HfrSearchResult | null>(null);
  const [searchError, setSearchError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [selected, setSelected] = useState<HfrFacility | null>(null);
  // The lists load when name search is opened, not on arrival: a search by
  // facility id needs none, and the page must not fail where HFR is absent.
  const [byName, setByName] = useState(false);

  useEffect(() => {
    if (!byName) return;
    let disposed = false;
    hfrMaster("OWNER").then((rows) => { if (!disposed) setOwners(rows); },
      (reason: unknown) => { if (!disposed) setListError(failure(reason, "HFR ownership list could not be loaded.")); });
    hfrStates().then((rows) => { if (!disposed) setStates(rows); },
      (reason: unknown) => { if (!disposed) setListError(failure(reason, "HFR state list could not be loaded.")); });
    return () => { disposed = true; };
  }, [byName]);

  useEffect(() => {
    if (!criteria.state_lgd_code) return;
    let disposed = false;
    hfrDistricts(criteria.state_lgd_code).then((rows) => { if (!disposed) setDistricts(rows); },
      (reason: unknown) => { if (!disposed) setListError(failure(reason, "HFR district list could not be loaded.")); });
    return () => { disposed = true; };
  }, [criteria.state_lgd_code]);

  useEffect(() => {
    if (!criteria.district_lgd_code) return;
    let disposed = false;
    hfrSubdistricts(criteria.district_lgd_code).then((rows) => { if (!disposed) setSubdistricts(rows); },
      (reason: unknown) => { if (!disposed) setListError(failure(reason, "HFR sub-district list could not be loaded.")); });
    return () => { disposed = true; };
  }, [criteria.district_lgd_code]);

  function change(field: keyof typeof criteria, value: string) {
    setCriteria((current) => ({
      ...current,
      [field]: value,
      ...(field === "state_lgd_code" ? { district_lgd_code: "", subdistrict_lgd_code: "" } : {}),
      ...(field === "district_lgd_code" ? { subdistrict_lgd_code: "" } : {}),
    }));
    if (field === "state_lgd_code") { setDistricts(null); setSubdistricts(null); }
    if (field === "district_lgd_code") setSubdistricts(null);
  }

  const byId = criteria.facility_id.trim() !== "";
  const idValid = FACILITY_ID.test(criteria.facility_id.trim());
  const canSearch = byId ? idValid
    : criteria.facility_name.trim() !== "" && criteria.ownership_code !== "" && criteria.state_lgd_code !== ""
      && (criteria.pincode === "" || /^\d{1,6}$/.test(criteria.pincode));

  async function search(page = 1) {
    if (!canSearch) return;
    setBusy(true);
    setSearchError(null);
    setSelected(null);
    const body: HfrSearch = byId
      ? { facility_id: criteria.facility_id.trim(), page }
      : Object.fromEntries(Object.entries({ ...criteria, facility_id: "", page })
        .filter(([, value]) => value !== "")) as HfrSearch;
    try {
      setResult(await searchHfr(body));
    } catch (reason) {
      setResult(null);
      setSearchError(failure(reason, "HFR search failed."));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-5">
      <section className="surface-card space-y-3 p-5">
        <h2 className="text-lg font-semibold">Search the Health Facility Registry</h2>
        <p className="text-sm text-muted-foreground">Search by HFR facility id, or by name with ownership and state.</p>
        <label className="block space-y-1 text-sm"><span className="text-muted-foreground">HFR facility id</span>
          <input name="facility_id" value={criteria.facility_id} onChange={(e) => change("facility_id", e.target.value.toUpperCase())}
            maxLength={12} placeholder="IN0000000000" aria-invalid={byId && !idValid} className={input} />
          {byId && !idValid ? <span role="alert" className="text-danger">A facility id is 12 characters and starts with IN.</span> : null}
        </label>
        {!byName ? (
          <button type="button" onClick={() => setByName(true)} className="text-sm underline">Search by name, ownership and location instead</button>
        ) : (
        <fieldset disabled={byId} className="grid gap-3 md:grid-cols-3">
          <label className="block space-y-1 text-sm md:col-span-3"><span className="text-muted-foreground">Facility name (full or part)</span>
            <input name="facility_name" value={criteria.facility_name} onChange={(e) => change("facility_name", e.target.value)} className={input} /></label>
          <label className="block space-y-1 text-sm"><span className="text-muted-foreground">Ownership</span>
            <select name="ownership_code" value={criteria.ownership_code} onChange={(e) => change("ownership_code", e.target.value)} disabled={!owners} className={input}>
              <option value="">{owners ? "Select ownership" : "Loading…"}</option>
              {(owners ?? []).map((row) => <option key={row.code} value={row.code}>{label(row)}</option>)}
            </select></label>
          <label className="block space-y-1 text-sm"><span className="text-muted-foreground">State / UT</span>
            <select name="state_lgd_code" value={criteria.state_lgd_code} onChange={(e) => change("state_lgd_code", e.target.value)} disabled={!states} className={input}>
              <option value="">{states ? "Select State / UT" : "Loading…"}</option>
              {(states ?? []).map((row) => <option key={row.code} value={row.code}>{label(row)}</option>)}
            </select></label>
          <label className="block space-y-1 text-sm"><span className="text-muted-foreground">District</span>
            <select name="district_lgd_code" value={criteria.district_lgd_code} onChange={(e) => change("district_lgd_code", e.target.value)} disabled={!districts} className={input}>
              <option value="">Select District</option>
              {(districts ?? []).map((row) => <option key={row.code} value={row.code}>{label(row)}</option>)}
            </select></label>
          <label className="block space-y-1 text-sm"><span className="text-muted-foreground">Sub-district</span>
            <select name="subdistrict_lgd_code" value={criteria.subdistrict_lgd_code} onChange={(e) => change("subdistrict_lgd_code", e.target.value)} disabled={!subdistricts} className={input}>
              <option value="">Select Sub-District</option>
              {(subdistricts ?? []).map((row) => <option key={row.code} value={row.code}>{label(row)}</option>)}
            </select></label>
          <label className="block space-y-1 text-sm"><span className="text-muted-foreground">PIN code</span>
            <input name="pincode" value={criteria.pincode} onChange={(e) => change("pincode", e.target.value.replace(/\D/g, ""))} inputMode="numeric" maxLength={6} className={input} /></label>
        </fieldset>
        )}
        {listError ? <p role="alert" className="text-sm text-danger">{listError}</p> : null}
        <button type="button" disabled={busy || !canSearch} onClick={() => void search(1)} className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-white disabled:opacity-50">
          {busy ? "Searching…" : "Search HFR"}
        </button>
        {searchError ? <p role="alert" className="text-sm text-danger">{searchError}</p> : null}
      </section>

      {result ? (
        <section className="surface-card space-y-3 p-5" aria-label="HFR results">
          <p className="text-sm text-muted-foreground">
            {result.facilities.length === 0 ? "No HFR facility matches." : `${result.total ?? result.facilities.length} facilities found.`}
          </p>
          <ul className="divide-y divide-border">
            {result.facilities.map((facility) => (
              <li key={facility.facilityId} className="flex flex-wrap items-center justify-between gap-2 py-2 text-sm">
                <span>
                  <span className="font-mono">{facility.facilityId}</span> · {facility.facilityName}
                  <span className="block text-muted-foreground">
                    {[facility.facilityType, facility.ownership, facility.districtName, facility.stateName, facility.facilityStatus].filter(Boolean).join(" · ")}
                  </span>
                </span>
                <button type="button" onClick={() => setSelected(facility)} className="rounded-md border border-border px-3 py-1.5 text-xs">Link to HealthDoc bridge</button>
              </li>
            ))}
          </ul>
          {result.pages && result.pages > 1 ? (
            <div className="flex items-center gap-2 text-sm">
              <button type="button" disabled={busy || result.page <= 1} onClick={() => void search(result.page - 1)} className="rounded-md border border-border px-3 py-1">Previous</button>
              <span>Page {result.page} of {result.pages}</span>
              <button type="button" disabled={busy || result.page >= result.pages} onClick={() => void search(result.page + 1)} className="rounded-md border border-border px-3 py-1">Next</button>
            </div>
          ) : null}
        </section>
      ) : null}

      {selected ? <BridgeLink key={selected.facilityId} facility={selected} /> : null}
    </div>
  );
}

/** HFR-118 to 123: HIP and HIU services of this facility on HealthDoc's bridge. */
function BridgeLink({ facility }: { facility: HfrFacility }) {
  const [services, setServices] = useState<Record<"HIP" | "HIU", HfrBridgeService & { include: boolean }>>({
    HIP: { type: "HIP", hip_name: facility.facilityName, active: true, include: true },
    HIU: { type: "HIU", hip_name: `${facility.facilityName} HIU`, active: true, include: false },
  });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);
  const key = useRef<string | null>(null);

  function update(type: "HIP" | "HIU", change: Partial<HfrBridgeService & { include: boolean }>) {
    key.current = null;
    setServices((current) => ({ ...current, [type]: { ...current[type], ...change } }));
  }

  const chosen = Object.values(services).filter((service) => service.include);
  const ready = chosen.length > 0 && chosen.every((service) => service.hip_name.trim() !== "");

  async function submit() {
    if (!ready) return;
    setBusy(true);
    setError(null);
    key.current ??= newIdempotencyKey();
    try {
      const linked = await linkHfrBridge(
        facility.facilityId,
        chosen.map(({ type, hip_name, active }) => ({ type, hip_name: hip_name.trim(), active })),
        key.current,
      );
      setDone(`${linked.facility_name} is linked to bridge ${linked.bridge_id}.`);
    } catch (reason) {
      setError(failure(reason, "HFR did not link the bridge."));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="surface-card space-y-3 p-5" aria-label="Bridge linkage">
      <h2 className="text-lg font-semibold">Link {facility.facilityName} to HealthDoc</h2>
      <p className="text-sm text-muted-foreground">
        Facility <span className="font-mono">{facility.facilityId}</span>. The name below is what patients see when they search for this hospital in a PHR app.
      </p>
      {(["HIP", "HIU"] as const).map((type) => (
        <fieldset key={type} className="grid gap-2 rounded-md border border-border p-3 md:grid-cols-[auto_1fr_auto]">
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" name={`${type}-include`} checked={services[type].include} onChange={(e) => update(type, { include: e.target.checked })} />
            {type === "HIP" ? "Shares records (HIP)" : "Requests records (HIU)"}
          </label>
          <input name={`${type}-name`} value={services[type].hip_name} onChange={(e) => update(type, { hip_name: e.target.value })} disabled={!services[type].include} className={input} />
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" name={`${type}-active`} checked={services[type].active} onChange={(e) => update(type, { active: e.target.checked })} disabled={!services[type].include} />
            Active
          </label>
        </fieldset>
      ))}
      {error ? <p role="alert" className="text-sm text-danger">{error}</p> : null}
      {done ? <p role="status" className="text-sm text-success">{done}</p> : null}
      <button type="button" disabled={busy || !ready} onClick={() => void submit()} className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-white disabled:opacity-50">
        {busy ? "Linking…" : "Link bridge"}
      </button>
    </section>
  );
}
