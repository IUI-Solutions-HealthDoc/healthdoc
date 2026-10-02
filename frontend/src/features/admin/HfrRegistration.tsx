"use client";

import { useEffect, useRef, useState } from "react";

import { ApiError, newIdempotencyKey } from "@/lib/api";
import {
  hfrDistricts,
  hfrFacilitySubtypes,
  hfrFacilityTypes,
  hfrMaster,
  hfrOwnerSubtypes,
  hfrSpecialities,
  hfrStates,
  hfrSubdistricts,
  saveHfrAdditional,
  saveHfrBasic,
  saveHfrDetailed,
  submitHfrFacility,
  type HfrBasicInformation,
  type HfrOption,
  type HfrUpload,
} from "./api/hfr";
import { readHfrUpload } from "./hfrUpload";

type Step = "basic" | "additional" | "detailed" | "submit" | "done";
interface Option { code: string; label: string }

const input = "w-full rounded-md border border-border px-3 py-2 text-sm";
const primary = "rounded-md bg-primary px-4 py-2 text-sm font-medium text-white disabled:opacity-50";
// The workbook's rules (HFR-010 to 026), checked here so Save stays disabled
// until HFR could accept the form; the server checks them again.
const RULES = {
  name: /^[A-Za-z][A-Za-z0-9 ]{2,199}$/,
  address: /^[A-Za-z0-9 .,/()_-]+$/,
  pincode: /^[1-9]\d{5}$/,
  latitude: /^[-+]?(?:90(?:\.0{1,6})?|[1-8]?\d\.\d{1,6})$/,
  longitude: /^[-+]?(?:180(?:\.0{1,6})?|(?:1[0-7]\d|[1-9]?\d)\.\d{1,6})$/,
  email: /^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$/,
  mobile: /^[6-9]\d{9}$/,
  hours: /^(?:24\*7|(?:0?[1-9]|1[0-2]):[0-5]\d ?(?:AM|PM) ?[-–] ?(?:0?[1-9]|1[0-2]):[0-5]\d ?(?:AM|PM))$/,
};
// HFR's own refusal names the only ownership subtypes it takes (C, P, NP).
const OWNER_SUBTYPES: Record<string, Option[]> = {
  G: [{ code: "", label: "State / UT government" }, { code: "C", label: "Central government" }],
  P: [{ code: "P", label: "For profit" }, { code: "NP", label: "Not for profit" }],
  PP: [{ code: "P", label: "For profit" }, { code: "NP", label: "Not for profit" }],
};
const GENERAL = [
  ["dialysis", "Dialysis centre"], ["pharmacy", "Pharmacy"], ["blood_bank", "Blood bank"],
  ["cath_lab", "Cath lab"], ["diagnostic_lab", "Diagnostic lab"], ["imaging", "Imaging centre"],
] as const;
const LINKED = [
  ["nhrr_id", "NHRR ID"], ["nin", "National Identification Number (NIN)"], ["abpmjay_id", "AB-PMJAY ID"],
  ["rohini_id", "ROHINI ID"], ["echs_id", "ECHS ID"], ["cghs_id", "CGHS ID"],
  ["cea_registration", "CEA registration number"], ["state_insurance_scheme_id", "State insurance scheme ID"],
] as const;
const BEDS = [
  ["ipd_beds_without_oxygen", "IPD beds without oxygen"], ["ipd_beds_with_oxygen", "IPD beds with oxygen"],
  ["icu_beds_with_ventilators", "ICU beds with ventilators"], ["icu_beds_without_ventilators", "ICU beds without ventilators"],
  ["hdu_beds_with_ventilators", "HDU beds with ventilators"], ["hdu_beds_without_ventilators", "HDU beds without ventilators"],
  ["daycare_beds_without_oxygen", "Day-care beds without oxygen"], ["daycare_beds_with_oxygen", "Day-care beds with oxygen"],
  ["dental_chairs", "Dental chairs"],
] as const;

function failure(reason: unknown, fallback: string): string[] {
  if (reason instanceof ApiError) {
    const messages = (reason.payload as { messages?: unknown } | undefined)?.messages;
    if (Array.isArray(messages) && messages.length) return messages.map(String);
    return [reason.message];
  }
  return [reason instanceof Error ? reason.message : fallback];
}

function loadList(key: string): Promise<HfrOption[]> {
  const [kind, a = "", b = ""] = key.split(":");
  switch (kind) {
    case "master": return hfrMaster(a);
    case "states": return hfrStates();
    case "districts": return hfrDistricts(a);
    case "subdistricts": return hfrSubdistricts(a);
    case "owner2": return hfrOwnerSubtypes(a, b);
    case "types": return hfrFacilityTypes(a, b);
    case "subtypes": return hfrFacilitySubtypes(a);
    case "specialities": return hfrSpecialities(a);
    default: return Promise.reject(new Error(`Unknown HFR list ${kind}`));
  }
}

/** One HFR list, keyed by what it depends on; a null key loads nothing. */
function useList(key: string | null): { rows: Option[] | null; error: string | null } {
  const [state, setState] = useState<{ key: string | null; rows: Option[] | null; error: string | null }>(
    { key: null, rows: null, error: null });
  useEffect(() => {
    if (!key) return;
    let live = true;
    loadList(key).then(
      (rows) => {
        if (!live) return;
        // HFR pads some codes ("G         "); the code it accepts is the trimmed one.
        const options = rows.map((row) => ({ code: String(row.code).trim(), label: String(row.value ?? row.name ?? row.code).trim() }));
        setState({ key, rows: options, error: null });
      },
      (reason: unknown) => { if (live) setState({ key, rows: null, error: failure(reason, "HFR did not return this list.")[0] }); },
    );
    return () => { live = false; };
  }, [key]);
  return state.key === key ? state : { rows: null, error: null };
}

function Select({ name, label, value, list, onChange, placeholder = "Choose" }: {
  name: string; label: string; value: string; list: { rows: Option[] | null; error: string | null };
  onChange: (value: string) => void; placeholder?: string;
}) {
  return (
    <label className="block space-y-1 text-sm"><span className="text-muted-foreground">{label}</span>
      <select name={name} value={value} onChange={(e) => onChange(e.target.value)} disabled={!list.rows} className={input}>
        <option value="">{list.rows ? placeholder : list.error ? "Unavailable" : "Loading…"}</option>
        {(list.rows ?? []).map((row) => <option key={row.code} value={row.code}>{row.label}</option>)}
      </select>
      {list.error ? <span role="alert" className="text-danger">{list.error}</span> : null}
    </label>
  );
}

function Text({ name, label, value, onChange, valid = true, ...rest }: {
  name: string; label: string; value: string; onChange: (value: string) => void; valid?: boolean;
  inputMode?: "numeric" | "decimal" | "tel" | "email" | "url"; maxLength?: number;
}) {
  return (
    <label className="block space-y-1 text-sm"><span className="text-muted-foreground">{label}</span>
      <input name={name} value={value} onChange={(e) => onChange(e.target.value)} aria-invalid={value !== "" && !valid} className={input} {...rest} />
      {value !== "" && !valid ? <span role="alert" className="text-danger">{label} is not valid</span> : null}
    </label>
  );
}

function Checks({ name, legend, list, chosen, onChange }: {
  name: string; legend: string; list: { rows: Option[] | null; error: string | null };
  chosen: string[]; onChange: (codes: string[]) => void;
}) {
  return (
    <fieldset className="space-y-1 text-sm"><legend className="text-muted-foreground">{legend}</legend>
      {list.error ? <p role="alert" className="text-danger">{list.error}</p> : null}
      {!list.rows && !list.error ? <p className="text-muted-foreground">Loading…</p> : null}
      <div className="flex flex-wrap gap-3">
        {(list.rows ?? []).map((row) => (
          <label key={row.code} className="flex items-center gap-1">
            <input type="checkbox" name={`${name}:${row.code}`} checked={chosen.includes(row.code)}
              onChange={(e) => onChange(e.target.checked ? [...chosen, row.code] : chosen.filter((code) => code !== row.code))} />
            {row.label}
          </label>
        ))}
      </div>
    </fieldset>
  );
}

function emptyBasic(): HfrBasicInformation {
  return {
    tracking_id: "", name: "",
    address: { state_code: "", district_code: "", sub_district_code: "", region: "", address_line1: "", address_line2: "", pincode: "", latitude: "", longitude: "" },
    contact: { email: "", mobile: "", website: "", landline: "", std_code: "" },
    ownership_code: "", ownership_subtype_code: "", ownership_subtype_code2: "",
    systems_of_medicine: [], types_of_service: [], facility_type_code: "", facility_subtype_code: "",
    speciality_type: "", operational_status: "", timings: [{ days: [], hours: "" }],
    board_photo: null, building_photo: null, address_proofs: [],
  };
}

/**
 * HFR facility registration (M4 HFR-010 to 117) under the facility manager's
 * HPR login. Four HFR steps keep one tracking id; submit returns the facility
 * id. Every list is HFR's own; HFR's field messages are shown as it sends them.
 */
export function HfrRegistration({ signedIn }: { signedIn: boolean }) {
  const [open, setOpen] = useState(false);
  return (
    <section className="surface-card space-y-3 p-5" aria-label="Register a facility in HFR">
      <h2 className="font-medium">Register a facility in HFR</h2>
      {!open ? (
        <>
          <p className="text-sm text-muted-foreground">Registration is done under the facility manager&apos;s HPR login. HFR verifies the facility after it is submitted.</p>
          <button type="button" className={primary} disabled={!signedIn} onClick={() => setOpen(true)}>Start registration</button>
          {!signedIn ? <p className="text-sm text-muted-foreground">Sign in to HPR above first.</p> : null}
        </>
      ) : <RegistrationSteps signedIn={signedIn} />}
    </section>
  );
}

function RegistrationSteps({ signedIn }: { signedIn: boolean }) {
  const [step, setStep] = useState<Step>("basic");
  const [basic, setBasic] = useState<HfrBasicInformation>(emptyBasic);
  const [additional, setAdditional] = useState({
    links: Object.fromEntries(LINKED.map(([key]) => [key, ""])) as Record<string, string>,
    general: Object.fromEntries(GENERAL.map(([key]) => [key, "N"])) as Record<string, string>,
    imaging: {} as Record<string, string>,
  });
  const [detailed, setDetailed] = useState({
    specialities: {} as Record<string, { available: "Y" | "N"; codes: string[] }>,
    beds: Object.fromEntries(BEDS.map(([key]) => [key, ""])) as Record<string, string>,
    imaging: {} as Record<string, string>,
    diagnostics: [] as string[],
  });
  const [facilityId, setFacilityId] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [errors, setErrors] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const keys = useRef<Record<string, string | null>>({});

  const a = basic.address;
  const lists = {
    owner: useList("master:OWNER"), medicine: useList("master:MEDICINE"), service: useList("master:TYPE-SERVICE"),
    region: useList("master:FACILITY-REGION"), speciality: useList("master:SPECIALITY-TYPE"),
    status: useList("master:FAC-STATUS"), days: useList("master:DAYS-OF-OPERATION"), proof: useList("master:ADDRESS-PROOF"),
    general: useList("master:GENERAL-INFO-OPTIONS"), imaging: useList("master:IMAGING"), diagnostic: useList("master:DIAGNOSTIC"),
    states: useList("states"),
    districts: useList(a.state_code ? `districts:${a.state_code}` : null),
    subdistricts: useList(a.district_code ? `subdistricts:${a.district_code}` : null),
    owner2: useList(basic.ownership_subtype_code ? `owner2:${basic.ownership_code}:${basic.ownership_subtype_code}` : null),
    types: useList(basic.ownership_code && basic.systems_of_medicine[0] ? `types:${basic.ownership_code}:${basic.systems_of_medicine[0]}` : null),
    subtypes: useList(basic.facility_type_code ? `subtypes:${basic.facility_type_code}` : null),
  };

  function edit(stage: string, change: () => void) {
    keys.current[stage] = null; // A changed form is a new request.
    change();
  }
  function setB<K extends keyof HfrBasicInformation>(field: K, value: HfrBasicInformation[K]) {
    edit("basic", () => setBasic((current) => {
      const next = { ...current, [field]: value };
      if (field === "ownership_code") Object.assign(next, { ownership_subtype_code: OWNER_SUBTYPES[value as string]?.[0]?.code ?? "", ownership_subtype_code2: "", facility_type_code: "", facility_subtype_code: "" });
      if (field === "ownership_subtype_code") next.ownership_subtype_code2 = "";
      if (field === "systems_of_medicine") Object.assign(next, { facility_type_code: "", facility_subtype_code: "" });
      if (field === "facility_type_code") next.facility_subtype_code = "";
      return next;
    }));
  }
  function setAddress(field: keyof HfrBasicInformation["address"], value: string) {
    edit("basic", () => setBasic((current) => ({
      ...current,
      address: {
        ...current.address, [field]: value,
        ...(field === "state_code" ? { district_code: "", sub_district_code: "" } : {}),
        ...(field === "district_code" ? { sub_district_code: "" } : {}),
      },
    })));
  }
  function setContact(field: keyof HfrBasicInformation["contact"], value: string) {
    edit("basic", () => setBasic((current) => ({ ...current, contact: { ...current.contact, [field]: value } })));
  }
  async function choose(file: File | undefined, apply: (upload: HfrUpload | null) => void) {
    if (!file) { apply(null); return; }
    try {
      apply(await readHfrUpload(file));
    } catch (reason) {
      setErrors(failure(reason, "The image could not be read."));
    }
  }
  function locate() {
    navigator.geolocation?.getCurrentPosition(
      (position) => edit("basic", () => setBasic((current) => ({
        ...current,
        address: { ...current.address, latitude: position.coords.latitude.toFixed(6), longitude: position.coords.longitude.toFixed(6) },
      }))),
      () => setErrors(["This device did not share its location. Enter the latitude and longitude."]),
    );
  }

  const subtypeOptions = OWNER_SUBTYPES[basic.ownership_code] ?? [];
  const basicValid = RULES.name.test(basic.name) && a.state_code !== "" && a.district_code !== "" && a.sub_district_code !== ""
    && a.region !== "" && RULES.address.test(a.address_line1) && (a.address_line2 === "" || RULES.address.test(a.address_line2))
    && RULES.pincode.test(a.pincode) && RULES.latitude.test(a.latitude) && RULES.longitude.test(a.longitude)
    && RULES.email.test(basic.contact.email) && RULES.mobile.test(basic.contact.mobile)
    && basic.ownership_code !== "" && (basic.ownership_subtype_code === "" || basic.ownership_subtype_code2 !== "")
    && basic.systems_of_medicine.length > 0 && basic.facility_type_code !== "" && basic.speciality_type !== ""
    && basic.operational_status !== "" && basic.timings.every((timing) => timing.days.length > 0 && RULES.hours.test(timing.hours))
    && basic.board_photo !== null && basic.building_photo !== null;

  async function run(stage: string, call: (key: string) => Promise<void>) {
    setBusy(true);
    setErrors([]);
    const key = (keys.current[stage] ??= newIdempotencyKey());
    try {
      await call(key);
      keys.current[stage] = null;
    } catch (reason) {
      setErrors(failure(reason, "HFR did not accept this step."));
    } finally {
      setBusy(false);
    }
  }
  const saveBasic = () => run("basic", async (key) => {
    const saved = await saveHfrBasic(basic, key);
    setBasic((current) => ({ ...current, tracking_id: saved.tracking_id }));
    setNotice(`Saved in HFR. Tracking ID ${saved.tracking_id}.`);
    setStep("additional");
  });
  const saveAdditional = () => run("additional", async (key) => {
    const imaging = Object.entries(additional.imaging).filter(([, count]) => Number(count) > 0)
      .map(([service, count]) => ({ service, count: Number(count) }));
    await saveHfrAdditional({
      tracking_id: basic.tracking_id, ...(additional.links as Record<(typeof LINKED)[number][0], string>),
      general: additional.general as Record<(typeof GENERAL)[number][0], string>,
      imaging_services: additional.general.imaging === "N" ? [] : imaging,
    }, key);
    setNotice("Additional information saved in HFR.");
    setStep("detailed");
  });
  const saveDetailed = () => run("detailed", async (key) => {
    await saveHfrDetailed({
      tracking_id: basic.tracking_id,
      specialities: basic.systems_of_medicine.map((system) => ({
        system_of_medicine: system,
        available: detailed.specialities[system]?.available ?? "N",
        codes: detailed.specialities[system]?.available === "Y" ? detailed.specialities[system].codes : [],
      })),
      infrastructure: Object.fromEntries(BEDS.map(([field]) => [field, Number(detailed.beds[field] || 0)])),
      imaging_services: Object.entries(detailed.imaging).filter(([, count]) => Number(count) > 0)
        .map(([service, count]) => ({ service, count: Number(count) })),
      diagnostic_services: detailed.diagnostics,
    }, key);
    setNotice("Detailed information saved in HFR.");
    setStep("submit");
  });
  const submit = () => run("submit", async (key) => {
    const created = await submitHfrFacility(basic.tracking_id, key);
    setFacilityId(created.facility_id);
    setNotice(created.message);
    setStep("done");
  });

  const bed = (field: string) => Number(detailed.beds[field] || 0);
  // HFR-111/114, as HFR checks them: ventilators are ICU and HDU beds with one;
  // total beds are the IPD and HDU beds.
  const totalVentilators = bed("icu_beds_with_ventilators") + bed("hdu_beds_with_ventilators");
  const totalBeds = bed("ipd_beds_without_oxygen") + bed("ipd_beds_with_oxygen") + bed("hdu_beds_with_ventilators") + bed("hdu_beds_without_ventilators");
  const twoDigits = (value: string) => /^\d{0,2}$/.test(value);

  if (step === "done" && facilityId) {
    return (
      <div role="status" className="space-y-1 text-sm">
        <p className="font-medium">HFR facility ID: <span className="font-mono">{facilityId}</span></p>
        <p>{notice}</p>
        <p className="text-muted-foreground">HFR now verifies the facility; its status reads &ldquo;Submitted&rdquo; until then. Search for it above to follow it.</p>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <ol className="flex flex-wrap gap-3 text-xs text-muted-foreground" aria-label="Registration steps">
        {(["basic", "additional", "detailed", "submit"] as const).map((name, index) => (
          <li key={name} aria-current={step === name ? "step" : undefined} className={step === name ? "font-semibold text-foreground" : ""}>
            {index + 1}. {{ basic: "Basic information", additional: "Additional information", detailed: "Detailed information", submit: "Submit" }[name]}
          </li>
        ))}
      </ol>
      {basic.tracking_id ? <p className="text-xs text-muted-foreground">Tracking ID {basic.tracking_id}</p> : null}
      {notice ? <p role="status" className="text-sm">{notice}</p> : null}
      {!signedIn ? <p role="alert" className="text-sm text-danger">The HPR login has ended. Sign in again above to continue.</p> : null}

      {step === "basic" ? (
        <div className="grid gap-3 md:grid-cols-2">
          <div className="md:col-span-2"><Text name="facility_name" label="Facility name" value={basic.name} valid={RULES.name.test(basic.name)} onChange={(v) => setB("name", v)} maxLength={200} /></div>
          <label className="block space-y-1 text-sm"><span className="text-muted-foreground">Country</span><input value="India" disabled className={input} readOnly /></label>
          <Select name="state" label="State / UT" value={a.state_code} list={lists.states} onChange={(v) => setAddress("state_code", v)} />
          <Select name="district" label="District" value={a.district_code} list={a.state_code ? lists.districts : { rows: null, error: null }} onChange={(v) => setAddress("district_code", v)} placeholder="Choose" />
          <Select name="subdistrict" label="Sub-district" value={a.sub_district_code} list={a.district_code ? lists.subdistricts : { rows: null, error: null }} onChange={(v) => setAddress("sub_district_code", v)} />
          <Select name="region" label="Region" value={a.region} list={lists.region} onChange={(v) => setAddress("region", v)} />
          <Text name="address_line1" label="Address line 1" value={a.address_line1} valid={RULES.address.test(a.address_line1)} onChange={(v) => setAddress("address_line1", v)} maxLength={200} />
          <Text name="address_line2" label="Address line 2" value={a.address_line2} valid={RULES.address.test(a.address_line2)} onChange={(v) => setAddress("address_line2", v)} maxLength={200} />
          <Text name="pincode" label="PIN code" value={a.pincode} valid={RULES.pincode.test(a.pincode)} onChange={(v) => setAddress("pincode", v.replace(/\D/g, ""))} inputMode="numeric" maxLength={6} />
          <Text name="latitude" label="Latitude" value={a.latitude} valid={RULES.latitude.test(a.latitude)} onChange={(v) => setAddress("latitude", v)} inputMode="decimal" />
          <Text name="longitude" label="Longitude" value={a.longitude} valid={RULES.longitude.test(a.longitude)} onChange={(v) => setAddress("longitude", v)} inputMode="decimal" />
          <div className="flex items-end"><button type="button" onClick={locate} className="rounded-md border border-border px-3 py-2 text-sm">Use this device&apos;s location</button></div>
          <Text name="email" label="Email (for public display)" value={basic.contact.email} valid={RULES.email.test(basic.contact.email)} onChange={(v) => setContact("email", v.trim())} inputMode="email" />
          <Text name="mobile" label="Mobile (for public display)" value={basic.contact.mobile} valid={RULES.mobile.test(basic.contact.mobile)} onChange={(v) => setContact("mobile", v.replace(/\D/g, ""))} inputMode="tel" maxLength={10} />
          <Text name="website" label="Website (optional)" value={basic.contact.website} onChange={(v) => setContact("website", v.trim())} inputMode="url" />
          <Text name="std_code" label="STD code (optional)" value={basic.contact.std_code} valid={/^0\d{1,4}$/.test(basic.contact.std_code)} onChange={(v) => setContact("std_code", v.replace(/\D/g, ""))} inputMode="numeric" maxLength={5} />
          <Text name="landline" label="Landline (optional)" value={basic.contact.landline} valid={/^\d{6,8}$/.test(basic.contact.landline)} onChange={(v) => setContact("landline", v.replace(/\D/g, ""))} inputMode="numeric" maxLength={8} />
          <Select name="ownership" label="Ownership" value={basic.ownership_code} list={lists.owner} onChange={(v) => setB("ownership_code", v)} />
          {basic.ownership_code ? (
            <label className="block space-y-1 text-sm"><span className="text-muted-foreground">Ownership subtype</span>
              <select name="ownership_subtype" value={basic.ownership_subtype_code} onChange={(e) => setB("ownership_subtype_code", e.target.value)} className={input}>
                {subtypeOptions.map((option) => <option key={option.code} value={option.code}>{option.label}</option>)}
              </select></label>
          ) : null}
          {basic.ownership_subtype_code ? <Select name="ownership_subtype2" label="Ownership subtype 2" value={basic.ownership_subtype_code2} list={lists.owner2} onChange={(v) => setB("ownership_subtype_code2", v)} /> : null}
          <div className="md:col-span-2"><Checks name="medicine" legend="System of medicine" list={lists.medicine} chosen={basic.systems_of_medicine} onChange={(v) => setB("systems_of_medicine", v)} /></div>
          <Select name="facility_type" label="Facility type" value={basic.facility_type_code} list={basic.systems_of_medicine[0] && basic.ownership_code ? lists.types : { rows: null, error: null }} onChange={(v) => setB("facility_type_code", v)} />
          <Select name="facility_subtype" label="Facility subtype" value={basic.facility_subtype_code} list={basic.facility_type_code ? lists.subtypes : { rows: null, error: null }} onChange={(v) => setB("facility_subtype_code", v)} />
          <div className="md:col-span-2"><Checks name="service" legend="Type of service (not needed for a pharmacy, lab, imaging centre, blood bank, cath lab or dialysis centre)" list={lists.service} chosen={basic.types_of_service} onChange={(v) => setB("types_of_service", v)} /></div>
          <Select name="speciality_type" label="Speciality type" value={basic.speciality_type} list={lists.speciality} onChange={(v) => setB("speciality_type", v)} />
          <Select name="operational_status" label="Operational status" value={basic.operational_status} list={lists.status} onChange={(v) => setB("operational_status", v)} />
          {basic.timings.map((timing, index) => (
            <div key={index} className="space-y-2 rounded-md border border-border p-3 md:col-span-2">
              <Checks name={`days${index}`} legend="Working days" list={lists.days} chosen={timing.days}
                onChange={(days) => setB("timings", basic.timings.map((row, i) => (i === index ? { ...row, days } : row)))} />
              <Text name={`hours${index}`} label="Opening hours (e.g. 9:00 AM - 6:00 PM, or 24*7)" value={timing.hours} valid={RULES.hours.test(timing.hours)}
                onChange={(hours) => setB("timings", basic.timings.map((row, i) => (i === index ? { ...row, hours } : row)))} />
              {basic.timings.length > 1 ? <button type="button" className="text-sm underline" onClick={() => setB("timings", basic.timings.filter((_, i) => i !== index))}>Remove these hours</button> : null}
            </div>
          ))}
          <div className="md:col-span-2"><button type="button" className="text-sm underline" onClick={() => setB("timings", [...basic.timings, { days: [], hours: "" }])}>Add different hours for other days</button></div>
          {(["board_photo", "building_photo"] as const).map((field) => (
            <label key={field} className="block space-y-1 text-sm"><span className="text-muted-foreground">{field === "board_photo" ? "Facility board photograph" : "Facility building photograph"} (PNG or JPEG, up to 5 MB)</span>
              <input type="file" name={field} accept="image/png,image/jpeg" onChange={(e) => void choose(e.target.files?.[0], (upload) => setB(field, upload))} className={input} />
              {basic[field] ? <span className="text-xs text-muted-foreground">{basic[field]?.name}</span> : null}
            </label>
          ))}
          <div className="space-y-2 md:col-span-2">
            <p className="text-sm text-muted-foreground">Address proofs (optional)</p>
            {basic.address_proofs.map((proof, index) => (
              <p key={index} className="text-sm">{lists.proof.rows?.find((row) => row.code === proof.type)?.label ?? proof.type}: {proof.attachment.name}
                <button type="button" className="ml-2 underline" onClick={() => setB("address_proofs", basic.address_proofs.filter((_, i) => i !== index))}>Remove</button></p>
            ))}
            <AddressProofPicker list={lists.proof} onAdd={(proof) => setB("address_proofs", [...basic.address_proofs, proof])} choose={choose} />
          </div>
          <div className="md:col-span-2"><button type="button" className={primary} disabled={busy || !signedIn || !basicValid} onClick={() => void saveBasic()}>{busy ? "Saving in HFR…" : "Save basic information"}</button></div>
        </div>
      ) : null}

      {step === "additional" ? (
        <div className="grid gap-3 md:grid-cols-2">
          {LINKED.map(([field, label]) => (
            <Text key={field} name={field} label={`${label} (optional)`} value={additional.links[field]}
              onChange={(v) => edit("additional", () => setAdditional((current) => ({ ...current, links: { ...current.links, [field]: v.trim() } })))} maxLength={50} />
          ))}
          {GENERAL.map(([field, label]) => (
            <Select key={field} name={field} label={label} value={additional.general[field]} list={lists.general}
              onChange={(v) => edit("additional", () => setAdditional((current) => ({ ...current, general: { ...current.general, [field]: v || "N" } })))} />
          ))}
          {additional.general.imaging !== "N" ? (lists.imaging.rows ?? []).map((row) => (
            <Text key={row.code} name={`imaging:${row.code}`} label={`${row.label}: number of machines`} value={additional.imaging[row.code] ?? ""} valid={twoDigits(additional.imaging[row.code] ?? "")}
              onChange={(v) => edit("additional", () => setAdditional((current) => ({ ...current, imaging: { ...current.imaging, [row.code]: v.replace(/\D/g, "") } })))} inputMode="numeric" maxLength={2} />
          )) : null}
          <div className="md:col-span-2"><button type="button" className={primary} disabled={busy || !signedIn} onClick={() => void saveAdditional()}>{busy ? "Saving in HFR…" : "Save additional information"}</button></div>
        </div>
      ) : null}

      {step === "detailed" ? (
        <div className="grid gap-3 md:grid-cols-2">
          {basic.systems_of_medicine.map((system) => (
            <SpecialityPicker key={system} system={system}
              label={lists.medicine.rows?.find((row) => row.code === system)?.label ?? system}
              value={detailed.specialities[system] ?? { available: "N", codes: [] }}
              onChange={(value) => edit("detailed", () => setDetailed((current) => ({ ...current, specialities: { ...current.specialities, [system]: value } })))} />
          ))}
          {BEDS.map(([field, label]) => (
            <Text key={field} name={field} label={label} value={detailed.beds[field]} valid={twoDigits(detailed.beds[field])}
              onChange={(v) => edit("detailed", () => setDetailed((current) => ({ ...current, beds: { ...current.beds, [field]: v.replace(/\D/g, "") } })))} inputMode="numeric" maxLength={2} />
          ))}
          <p className="text-sm md:col-span-2" aria-live="polite">Total beds (IPD and HDU): <strong>{totalBeds}</strong>. Total ventilators: <strong>{totalVentilators}</strong>.</p>
          <div className="space-y-2 md:col-span-2">
            <p className="text-sm text-muted-foreground">Only for an imaging centre or diagnostic laboratory; HFR refuses these for other facility types.</p>
            <div className="grid gap-3 md:grid-cols-3">
              {(lists.imaging.rows ?? []).map((row) => (
                <Text key={row.code} name={`detailed-imaging:${row.code}`} label={`${row.label}: number`} value={detailed.imaging[row.code] ?? ""} valid={twoDigits(detailed.imaging[row.code] ?? "")}
                  onChange={(v) => edit("detailed", () => setDetailed((current) => ({ ...current, imaging: { ...current.imaging, [row.code]: v.replace(/\D/g, "") } })))} inputMode="numeric" maxLength={2} />
              ))}
            </div>
            <Checks name="diagnostic" legend="Diagnostic services" list={lists.diagnostic} chosen={detailed.diagnostics}
              onChange={(codes) => edit("detailed", () => setDetailed((current) => ({ ...current, diagnostics: codes })))} />
          </div>
          <div className="md:col-span-2"><button type="button" className={primary} disabled={busy || !signedIn || !BEDS.every(([field]) => twoDigits(detailed.beds[field]))} onClick={() => void saveDetailed()}>{busy ? "Saving in HFR…" : "Save detailed information"}</button></div>
        </div>
      ) : null}

      {step === "submit" ? (
        <div className="space-y-2 text-sm">
          <p>Submit <strong>{basic.name}</strong> (tracking ID {basic.tracking_id}) to HFR. HFR returns the facility ID and verifies the facility afterwards.</p>
          <button type="button" className={primary} disabled={busy || !signedIn} onClick={() => void submit()}>{busy ? "Submitting…" : "Submit to HFR"}</button>
        </div>
      ) : null}

      {errors.length ? (
        <ul role="alert" className="list-disc space-y-1 pl-5 text-sm text-danger">
          {errors.map((message) => <li key={message}>{message}</li>)}
        </ul>
      ) : null}
    </div>
  );
}

function AddressProofPicker({ list, onAdd, choose }: {
  list: { rows: Option[] | null; error: string | null };
  onAdd: (proof: { type: string; attachment: HfrUpload }) => void;
  choose: (file: File | undefined, apply: (upload: HfrUpload | null) => void) => Promise<void>;
}) {
  const [type, setType] = useState("");
  return (
    <div className="grid gap-2 md:grid-cols-2">
      <Select name="address_proof_type" label="Address proof type" value={type} list={list} onChange={setType} />
      <label className="block space-y-1 text-sm"><span className="text-muted-foreground">Address proof (PNG or JPEG, up to 5 MB)</span>
        <input type="file" name="address_proof" accept="image/png,image/jpeg" disabled={!type} className={input}
          onChange={(e) => void choose(e.target.files?.[0], (upload) => { if (upload) { onAdd({ type, attachment: upload }); setType(""); } })} /></label>
    </div>
  );
}

function SpecialityPicker({ system, label, value, onChange }: {
  system: string; label: string; value: { available: "Y" | "N"; codes: string[] };
  onChange: (value: { available: "Y" | "N"; codes: string[] }) => void;
}) {
  const list = useList(value.available === "Y" ? `specialities:${system}` : null);
  return (
    <fieldset className="space-y-2 rounded-md border border-border p-3 text-sm md:col-span-2">
      <legend className="px-1 font-medium">{label}: specialities</legend>
      <label className="flex items-center gap-2">
        <input type="checkbox" name={`specialisation:${system}`} checked={value.available === "Y"}
          onChange={(e) => onChange({ available: e.target.checked ? "Y" : "N", codes: [] })} />
        Specialisation is available
      </label>
      {value.available === "Y" ? (
        <Checks name={`speciality:${system}`} legend="Specialities" list={list} chosen={value.codes} onChange={(codes) => onChange({ ...value, codes })} />
      ) : null}
    </fieldset>
  );
}
