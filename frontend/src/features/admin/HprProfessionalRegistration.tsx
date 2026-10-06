"use client";

import { useEffect, useRef, useState } from "react";

import { ApiError, newIdempotencyKey } from "@/lib/api";
import { HprContactVerifier } from "./HprContactVerifier";
import {
  hprColleges,
  hprContact,
  hprCouncils,
  hprCountries,
  hprCourses,
  hprDistricts,
  hprLanguages,
  hprProfessional,
  hprProfile,
  hprRegistrationOptions,
  hprStates,
  hprSubDistricts,
  hprSystems,
  hprUniversities,
  registerHprProfessional,
  updateHprProfessional,
  type HprCouncil,
  type HprDocument,
  type HprOption,
  type HprProfessionalForm,
  type HprContact,
  type HprProfile,
  type HprRegistrationOptions,
  type HprSystem,
} from "./api/hpr";
import { HPR_DOCUMENT_ACCEPT, readHprDocument } from "./hprDocument";

const input = "w-full rounded-md border border-border px-3 py-2 text-sm";
const primary = "rounded-md bg-primary px-4 py-2 text-sm font-medium text-white disabled:opacity-50";
const secondary = "rounded-md border border-border px-3 py-2 text-sm disabled:opacity-50";
const NAME = /^[A-Za-z][A-Za-z .'-]{0,99}$/;
const FACILITY_ID = /^IN[0-9A-Z]{10}$/;
const PIN = /^[1-9]\d{5}$/;
const REG_NUMBER = /^[A-Za-z0-9/._-]{1,50}$/;
const today = () => new Date().toISOString().slice(0, 10);

function failure(reason: unknown, fallback: string): string[] {
  if (reason instanceof ApiError) {
    const payload = reason.payload as { messages?: unknown; message?: unknown } | undefined;
    if (Array.isArray(payload?.messages) && payload.messages.length) return payload.messages.map(String);
    // HealthDoc's server words these itself; the generic text says nothing.
    if (typeof payload?.message === "string" && payload.message) return [payload.message];
    return [reason.message];
  }
  return [reason instanceof Error ? reason.message : fallback];
}

type List<T = HprOption> = { rows: T[] | null; error: string | null };

/** One HPR list, keyed by what it depends on; a null key loads nothing. */
function useList<T = HprOption>(key: string | null, load: () => Promise<T[]>): List<T> {
  const [state, setState] = useState<{ key: string | null; rows: T[] | null; error: string | null }>({ key: null, rows: null, error: null });
  useEffect(() => {
    if (!key) return;
    let live = true;
    load().then((rows) => { if (live) setState({ key, rows, error: null }); },
      (reason: unknown) => { if (live) setState({ key, rows: null, error: failure(reason, "HPR did not return this list.")[0] }); });
    return () => { live = false; };
    // The loader is rebuilt each render; the key says when the list changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);
  return state.key === key ? state : { rows: null, error: null };
}

function Pick({ name, label, value, list, onChange }: {
  name: string; label: string; value: string; list: List; onChange: (value: string) => void;
}) {
  return (
    <label className="block space-y-1 text-sm"><span className="text-muted-foreground">{label}</span>
      <select name={name} value={value} onChange={(e) => onChange(e.target.value)} disabled={!list.rows} className={input}>
        <option value="">{list.rows ? "Choose" : list.error ? "Unavailable" : "Loading…"}</option>
        {(list.rows ?? []).map((row) => <option key={row.code} value={row.code}>{row.label}</option>)}
      </select>
      {list.error ? <span role="alert" className="text-danger">{list.error}</span> : null}
    </label>
  );
}

function Field({ name, label, value, onChange, valid = true, ...rest }: {
  name: string; label: string; value: string; onChange: (value: string) => void; valid?: boolean;
  type?: string; inputMode?: "numeric" | "tel" | "email"; maxLength?: number; max?: string;
}) {
  return (
    <label className="block space-y-1 text-sm"><span className="text-muted-foreground">{label}</span>
      <input name={name} value={value} onChange={(e) => onChange(e.target.value)} aria-invalid={value !== "" && !valid} className={input} {...rest} />
      {value !== "" && !valid ? <span role="alert" className="text-danger">{label} is not valid</span> : null}
    </label>
  );
}

function Attach({ name, label, value, onChange, onError }: {
  name: string; label: string; value: HprDocument | null; onChange: (value: HprDocument | null) => void; onError: (message: string) => void;
}) {
  return (
    <label className="block space-y-1 text-sm"><span className="text-muted-foreground">{label} (PDF, PNG or JPEG, up to 5 MB)</span>
      <input type="file" name={name} accept={HPR_DOCUMENT_ACCEPT} className={input}
        onChange={(e) => {
          const file = e.target.files?.[0];
          if (!file) { onChange(null); return; }
          readHprDocument(file).then(onChange, (reason: unknown) => onError(reason instanceof Error ? reason.message : "The file could not be read."));
        }} />
      {value ? <span className="text-xs text-muted-foreground">Attached ({value.file_type.toUpperCase()})</span> : null}
    </label>
  );
}

interface QualificationDraft {
  degree: string; state: string; college: string; university: string; year: string; month: string;
  certificate: HprDocument | null; name_differs: boolean; name_change_proof: HprDocument | null;
}
const emptyQualification = (): QualificationDraft => ({
  degree: "", state: "", college: "", university: "", year: "", month: "", certificate: null, name_differs: false, name_change_proof: null,
});

/**
 * Register the signed-in professional in HPR (M4 HPR-018 to 079). Their
 * Aadhaar name, photo, birth date and address are HPR's KYC, shown here and
 * never editable; HealthDoc's server reads them from HPR again on submit.
 */
export function HprProfessionalRegistration({ signedIn }: { signedIn: boolean }) {
  const [open, setOpen] = useState(false);
  return (
    <section className="surface-card space-y-3 p-5" aria-label="Register in HPR">
      <h2 className="text-lg font-semibold">Register a professional in HPR</h2>
      {!open ? (
        <>
          <p className="text-sm text-muted-foreground">Done under the professional&apos;s own HPR login: their registration with a council, qualifications and place of work.</p>
          <button type="button" className={primary} disabled={!signedIn} onClick={() => setOpen(true)}>Open the HPR registration</button>
          {!signedIn ? <p className="text-sm text-muted-foreground">Sign in to HPR as the professional above first.</p> : null}
        </>
      ) : <RegistrationForm signedIn={signedIn} />}
    </section>
  );
}

function RegistrationForm({ signedIn }: { signedIn: boolean }) {
  const [profile, setProfile] = useState<HprProfile | null>(null);
  const [registered, setRegistered] = useState<Record<string, unknown> | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [options, setOptions] = useState<HprRegistrationOptions | null>(null);
  const [kycMissing, setKycMissing] = useState(false);
  const [errors, setErrors] = useState<string[]>([]);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const key = useRef<string | null>(null);

  const [person, setPerson] = useState({ salutation: "", category: "", subcategory: "", system: "", nationality: "356",
    father_name: "", mother_name: "", spouse_name: "", languages: [] as string[] });
  const [comm, setComm] = useState({ same: true, name: "", address: "", state: "", district: "", sub_district: "", city: "", pincode: "" });
  const [contact, setContact] = useState({ official_mobile: "", official_email: "", public_mobile: "", public_email: "", landline: "", landline_code: "" });
  const [reg, setReg] = useState({ council: "", number: "", registered_on: "", certificate: null as HprDocument | null,
    renewable: false, renewal_due: "", name_differs: false, name_change_proof: null as HprDocument | null });
  const [quals, setQuals] = useState<QualificationDraft[]>([emptyQualification()]);
  const [work, setWork] = useState({ working: "", reason: "", other_reason: "", purpose: "", status: "", government_type: "",
    ministry: "", proof: null as HprDocument | null, facility_id: "", department: "", designation: "" });
  const [visibility, setVisibility] = useState({ show_photo: true, public_profile: true });
  const [verified, setVerified] = useState<HprContact | null>(null);

  useEffect(() => {
    let live = true;
    Promise.all([hprProfile(), hprRegistrationOptions()]).then(([kyc, opts]) => {
      if (!live) return;
      setProfile(kyc);
      setOptions(opts);
      hprContact().then((c) => { if (live) setVerified(c); }, () => undefined);
    }, (reason: unknown) => {
      if (!live) return;
      // A password or OTP login carries no Aadhaar KYC; HPR hands it over only
      // with an Aadhaar verification, which the panel above does.
      if (reason instanceof ApiError && (reason.payload as { code?: unknown } | undefined)?.code === "hpr_kyc_required") {
        setKycMissing(true);
        return;
      }
      setLoadError(failure(reason, "HPR did not return this professional's profile.")[0]);
    });
    // HPR-078: what HPR already holds, if anything. A failure leaves registering open.
    hprProfessional().then((found) => { if (live) setRegistered(found.practitioner); }, () => undefined);
    return () => { live = false; };
  }, []);

  const hprType = ({ "1": "doctor", "2": "nurse", "6": "pharmacist" } as const)[person.category as "1" | "2" | "6"] ?? "doctor";
  const systems = useList<HprSystem>("systems", hprSystems);
  const systemRows = (systems.rows ?? []).filter((row) => !row.hpr_type || row.hpr_type === hprType);
  // A doctor's subcategory IS their system of medicine (NHA's registration
  // codes match the system-of-medicine master); nurses and pharmacists choose
  // the course system separately, for HPR's course and college lists.
  const systemId = hprType === "doctor" ? person.subcategory : person.system;
  const systemName = (systems.rows ?? []).find((row) => row.code === systemId)?.label ?? "";
  const councils = useList<HprCouncil>(`councils:${hprType}`, () => hprCouncils(hprType === "nurse" ? "nurse" : "medical"));
  const councilRows = (councils.rows ?? []).filter((row) => hprType !== "doctor" || !systemId
    || row.system_of_medicine_id === null || String(row.system_of_medicine_id) === systemId);
  const countries = useList("countries", hprCountries);
  const languages = useList("languages", hprLanguages);
  const states = useList("states", hprStates);
  const commDistricts = useList(comm.state ? `districts:${comm.state}` : null, () => hprDistricts(comm.state));
  const commSubDistricts = useList(comm.district ? `subdistricts:${comm.district}` : null, () => hprSubDistricts(comm.district));
  const courses = useList(systemName ? `courses:${systemName}:${hprType}` : null, () => hprCourses(systemName, hprType));

  function edit(change: () => void) { key.current = null; setNotice(null); change(); }
  const setQual = (index: number, change: Partial<QualificationDraft>) =>
    edit(() => setQuals((rows) => rows.map((row, i) => (i === index ? { ...row, ...change } : row))));
  const subcategories = !options ? [] : person.category === "1" ? options.doctor_systems
    : person.category === "2" ? options.nurse_types : person.category === "6" ? [options.pharmacist_type] : [];
  const reason = work.reason === "Other" ? work.other_reason.trim() : work.reason;

  const qualsValid = quals.every((q) => q.degree && q.state && q.college && q.university && /^\d{4}$/.test(q.year)
    && Number(q.year) <= new Date().getFullYear() && q.certificate && (!q.name_differs || q.name_change_proof));
  const valid = !!person.salutation && !!person.category && !!person.subcategory && !!systemId && person.languages.length > 0
    // Where Aadhaar gave no mobile or email, HPR needs them verified by OTP (live 6 Oct 2026).
    && (!!profile?.mobile_hint || !!verified?.mobile_verified)
    && (!!profile?.email || !!verified?.email_verified)
    && [person.father_name, person.mother_name, person.spouse_name].every((n) => n === "" || NAME.test(n))
    && (comm.same || (NAME.test(comm.name) && comm.address.trim() && comm.state && comm.district && PIN.test(comm.pincode)))
    && !!reg.council && REG_NUMBER.test(reg.number) && !!reg.registered_on && reg.registered_on <= today() && !!reg.certificate
    && (!reg.renewable || !!reg.renewal_due) && (!reg.name_differs || !!reg.name_change_proof) && qualsValid
    && (work.working === "no" ? !!reason : work.working === "yes" && !!work.purpose && !!work.status && FACILITY_ID.test(work.facility_id)
      && (work.status === "PRIVATE" || (!!work.proof && !!work.government_type
        && (work.government_type !== "CENTRAL" || !!work.ministry.trim()))));

  function body(): HprProfessionalForm {
    return {
      salutation: Number(person.salutation), category: Number(person.category), subcategory: Number(person.subcategory),
      nationality: person.nationality, father_name: person.father_name.trim(), mother_name: person.mother_name.trim(),
      spouse_name: person.spouse_name.trim(), languages: person.languages.map(Number),
      communication_address: comm.same ? null : { name: comm.name.trim(), address: comm.address.trim(), country: "356",
        state: comm.state, district: comm.district, sub_district: comm.sub_district, city: comm.city.trim(), pincode: comm.pincode },
      ...contact,
      registration: {
        council: Number(reg.council), number: reg.number.trim(), registered_on: reg.registered_on, certificate: reg.certificate!,
        renewable: reg.renewable, renewal_due: reg.renewable ? reg.renewal_due : null, name_differs: reg.name_differs,
        name_change_proof: reg.name_differs ? reg.name_change_proof : null,
        qualifications: quals.map((q) => ({ degree: Number(q.degree), country: "356", state: q.state, college: Number(q.college),
          university: Number(q.university), year: Number(q.year), month: q.month || null, certificate: q.certificate!,
          name_differs: q.name_differs, name_change_proof: q.name_differs ? q.name_change_proof : null })),
      },
      work: work.working === "yes"
        ? { working: true, reason_not_working: "", purpose: work.purpose, status: work.status,
          government_type: work.status === "PRIVATE" ? null : work.government_type,
          ministry: work.status !== "PRIVATE" && work.government_type === "CENTRAL" ? work.ministry.trim() : "",
          proof: work.status === "PRIVATE" ? null : work.proof,
          facility_id: work.facility_id, department: work.department.trim(), designation: work.designation.trim() }
        : { working: false, reason_not_working: reason, purpose: null, status: null, government_type: null, ministry: "",
          proof: null, facility_id: null, department: "", designation: "" },
      ...visibility,
    };
  }

  async function submit(update: boolean) {
    setBusy(true);
    setErrors([]);
    const idempotencyKey = (key.current ??= newIdempotencyKey());
    try {
      const done = await (update ? updateHprProfessional : registerHprProfessional)(body(), idempotencyKey);
      key.current = null;
      setNotice(`${update ? "Updated" : "Submitted"} in HPR${done.reference_number ? `, reference ${done.reference_number}` : ""}${done.status ? ` (${done.status})` : ""}. HPR informs the professional by SMS and email.`);
    } catch (reason) {
      setErrors(failure(reason, "HPR did not accept this registration."));
    } finally {
      setBusy(false);
    }
  }

  if (kycMissing) {
    return (
      <p role="alert" className="rounded-md border border-border p-3 text-sm">
        This HPR login carries no Aadhaar details, which HPR registration needs: HPR hands them over only after an Aadhaar
        verification. Use <strong>Verify Aadhaar on NHA&apos;s page</strong> in the panel above with the professional; it signs
        them in with their details, whether or not they already have an HPID. Then open this form again.
      </p>
    );
  }
  if (loadError) return <p role="alert" className="text-sm text-danger">{loadError}</p>;
  if (!profile || !options) return <p role="status" className="text-sm text-muted-foreground">Loading the professional&apos;s HPR profile…</p>;
  const reportError = (message: string) => setErrors([message]);

  return (
    <div className="space-y-5">
      {registered ? (
        <p role="status" className="text-sm">HPR already holds a registration for this professional
          {typeof registered.application_status === "string" ? <> ({registered.application_status})</> : null}. Use <strong>Update in HPR</strong> to change it.</p>
      ) : null}

      <fieldset className="space-y-2"><legend className="font-medium">From Aadhaar (not editable)</legend>
        <div className="flex items-start gap-4 text-sm">
          {profile.photo ? (
            // eslint-disable-next-line @next/next/no-img-element -- the KYC photo as a one-use data URI, not an optimisable asset
            <img src={`data:image/jpeg;base64,${profile.photo}`} alt="Photograph from Aadhaar" className="h-20 w-16 rounded object-cover" />
          ) : null}
          <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1">
            <dt className="text-muted-foreground">HPR ID</dt><dd className="font-mono">{profile.hpr_id} ({profile.hpr_id_number})</dd>
            <dt className="text-muted-foreground">Name</dt><dd>{profile.name}</dd>
            {profile.gender ? <><dt className="text-muted-foreground">Gender</dt><dd>{profile.gender}</dd></> : null}
            {profile.birth_date ? <><dt className="text-muted-foreground">Date of birth</dt><dd>{profile.birth_date}</dd></> : null}
            <dt className="text-muted-foreground">Address</dt><dd>{profile.address || "—"}</dd>
            <dt className="text-muted-foreground">Mobile</dt><dd>{profile.mobile_hint ? `ending ${profile.mobile_hint}` : "—"}</dd>
            <dt className="text-muted-foreground">Email</dt><dd>{profile.email || "—"}</dd>
          </dl>
        </div>
      </fieldset>

      <fieldset className="grid gap-3 md:grid-cols-3"><legend className="mb-2 font-medium">Personal details</legend>
        <Pick name="salutation" label="Salutation" value={person.salutation} list={{ rows: options.salutations, error: null }}
          onChange={(v) => edit(() => setPerson({ ...person, salutation: v }))} />
        <Pick name="category" label="Category" value={person.category} list={{ rows: options.categories, error: null }}
          onChange={(v) => edit(() => setPerson({ ...person, category: v, subcategory: "", system: "" }))} />
        <Pick name="subcategory" label={person.category === "1" ? "System of medicine" : "Subcategory"} value={person.subcategory}
          list={{ rows: person.category ? subcategories : null, error: null }}
          onChange={(v) => { edit(() => setPerson({ ...person, subcategory: v })); if (person.category === "1") { setReg((r) => ({ ...r, council: "" })); setQuals([emptyQualification()]); } }} />
        {person.category && person.category !== "1" ? (
          <Pick name="system" label="Course system (for HPR's course and college lists)" value={person.system}
            list={{ rows: systems.rows ? systemRows : null, error: systems.error }}
            onChange={(v) => { edit(() => setPerson({ ...person, system: v })); setQuals([emptyQualification()]); }} />
        ) : null}
        <Pick name="nationality" label="Nationality" value={person.nationality} list={countries}
          onChange={(v) => edit(() => setPerson({ ...person, nationality: v }))} />
        <span />
        {(["father_name", "mother_name", "spouse_name"] as const).map((field) => (
          <Field key={field} name={field} label={`${{ father_name: "Father's", mother_name: "Mother's", spouse_name: "Spouse's" }[field]} name (optional)`}
            value={person[field]} valid={NAME.test(person[field])} maxLength={100}
            onChange={(v) => edit(() => setPerson({ ...person, [field]: v }))} />
        ))}
        <fieldset className="space-y-1 text-sm md:col-span-3"><legend className="text-muted-foreground">Languages spoken</legend>
          {languages.error ? <p role="alert" className="text-danger">{languages.error}</p> : null}
          <div className="flex flex-wrap gap-3">
            {(languages.rows ?? []).map((row) => (
              <label key={row.code} className="flex items-center gap-1">
                <input type="checkbox" name={`language:${row.code}`} checked={person.languages.includes(row.code)}
                  onChange={(e) => edit(() => setPerson({ ...person, languages: e.target.checked
                    ? [...person.languages, row.code] : person.languages.filter((code) => code !== row.code) }))} />{row.label}
              </label>
            ))}
          </div>
        </fieldset>
      </fieldset>

      <fieldset className="grid gap-3 md:grid-cols-3"><legend className="mb-2 font-medium">Communication address</legend>
        <label className="flex items-center gap-2 text-sm md:col-span-3">
          <input type="checkbox" name="comm_same" checked={comm.same} onChange={(e) => edit(() => setComm({ ...comm, same: e.target.checked }))} />
          Same as the address from Aadhaar
        </label>
        {!comm.same ? (
          <>
            <Field name="comm_name" label="Name" value={comm.name} valid={NAME.test(comm.name)} onChange={(v) => edit(() => setComm({ ...comm, name: v }))} />
            <div className="md:col-span-2"><Field name="comm_address" label="Address" value={comm.address} maxLength={300} onChange={(v) => edit(() => setComm({ ...comm, address: v }))} /></div>
            <Pick name="comm_state" label="State / UT" value={comm.state} list={states} onChange={(v) => edit(() => setComm({ ...comm, state: v, district: "", sub_district: "" }))} />
            <Pick name="comm_district" label="District" value={comm.district} list={comm.state ? commDistricts : { rows: null, error: null }}
              onChange={(v) => edit(() => setComm({ ...comm, district: v, sub_district: "" }))} />
            <Pick name="comm_sub_district" label="Sub-district (optional)" value={comm.sub_district} list={comm.district ? commSubDistricts : { rows: null, error: null }}
              onChange={(v) => edit(() => setComm({ ...comm, sub_district: v }))} />
            <Field name="comm_city" label="City / town / village (optional)" value={comm.city} maxLength={100} onChange={(v) => edit(() => setComm({ ...comm, city: v }))} />
            <Field name="comm_pincode" label="PIN code" value={comm.pincode} valid={PIN.test(comm.pincode)} inputMode="numeric" maxLength={6}
              onChange={(v) => edit(() => setComm({ ...comm, pincode: v.replace(/\D/g, "") }))} />
          </>
        ) : null}
        {!profile.mobile_hint ? <HprContactVerifier kind="mobile" contact={verified} onChange={setVerified} /> : null}
        {!profile.email ? <HprContactVerifier kind="email" contact={verified} onChange={setVerified} /> : null}
        <Field name="public_mobile" label="Public mobile (optional)" value={contact.public_mobile} valid={/^[6-9]\d{9}$/.test(contact.public_mobile)}
          inputMode="tel" maxLength={10} onChange={(v) => edit(() => setContact({ ...contact, public_mobile: v.replace(/\D/g, "") }))} />
        <Field name="public_email" label="Public email (optional)" value={contact.public_email} inputMode="email"
          valid={/^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$/.test(contact.public_email)}
          onChange={(v) => edit(() => setContact({ ...contact, public_email: v.trim() }))} />
      </fieldset>

      <fieldset className="grid gap-3 md:grid-cols-3"><legend className="mb-2 font-medium">Registration with a council</legend>
        <Pick name="council" label="Council" value={reg.council} list={{ rows: councils.rows ? councilRows : null, error: councils.error }}
          onChange={(v) => edit(() => setReg({ ...reg, council: v }))} />
        <Field name="reg_number" label="Registration number" value={reg.number} valid={REG_NUMBER.test(reg.number)} maxLength={50}
          onChange={(v) => edit(() => setReg({ ...reg, number: v.trim() }))} />
        <Field name="reg_date" label="Registration date" type="date" max={today()} value={reg.registered_on} valid={reg.registered_on <= today()}
          onChange={(v) => edit(() => setReg({ ...reg, registered_on: v }))} />
        <Attach name="reg_certificate" label="Registration certificate" value={reg.certificate} onError={reportError}
          onChange={(v) => edit(() => setReg((r) => ({ ...r, certificate: v })))} />
        <label className="flex items-center gap-2 text-sm"><input type="checkbox" name="reg_renewable" checked={reg.renewable}
          onChange={(e) => edit(() => setReg({ ...reg, renewable: e.target.checked }))} />Renewable registration</label>
        {reg.renewable ? <Field name="reg_due" label="Renewal due date" type="date" value={reg.renewal_due} onChange={(v) => edit(() => setReg({ ...reg, renewal_due: v }))} /> : <span />}
        <label className="flex items-center gap-2 text-sm"><input type="checkbox" name="reg_name_differs" checked={reg.name_differs}
          onChange={(e) => edit(() => setReg({ ...reg, name_differs: e.target.checked }))} />The name on the certificate differs</label>
        {reg.name_differs ? <Attach name="reg_name_proof" label="Proof of name change" value={reg.name_change_proof} onError={reportError}
          onChange={(v) => edit(() => setReg((r) => ({ ...r, name_change_proof: v })))} /> : null}
      </fieldset>

      {quals.map((q, index) => (
        <Qualification key={index} index={index} q={q} systemName={systemName} courses={courses} states={states}
          months={options.months} onChange={(change) => setQual(index, change)} onError={reportError}
          onRemove={quals.length > 1 ? () => edit(() => setQuals((rows) => rows.filter((_, i) => i !== index))) : null} />
      ))}
      <button type="button" className="text-sm underline" onClick={() => edit(() => setQuals((rows) => [...rows, emptyQualification()]))}>Add another qualification</button>

      <fieldset className="grid gap-3 md:grid-cols-3"><legend className="mb-2 font-medium">Current work</legend>
        <Pick name="working" label="Currently working?" value={work.working}
          list={{ rows: [{ code: "yes", label: "Yes" }, { code: "no", label: "No" }], error: null }}
          onChange={(v) => edit(() => setWork({ ...work, working: v }))} />
        {work.working === "no" ? (
          <>
            <Pick name="not_working_reason" label="Reason" value={work.reason}
              list={{ rows: [...options.not_working_reasons, "Other"].map((r) => ({ code: r, label: r })), error: null }}
              onChange={(v) => edit(() => setWork({ ...work, reason: v }))} />
            {work.reason === "Other" ? <Field name="not_working_other" label="The reason" value={work.other_reason} maxLength={100}
              onChange={(v) => edit(() => setWork({ ...work, other_reason: v }))} /> : null}
          </>
        ) : null}
        {work.working === "yes" ? (
          <>
            <Pick name="work_purpose" label="Nature of work" value={work.purpose}
              list={{ rows: options.purposes.map((p) => ({ code: p, label: p })), error: null }}
              onChange={(v) => edit(() => setWork({ ...work, purpose: v }))} />
            <Pick name="work_status" label="Government, private or both" value={work.status} list={{ rows: options.work_status, error: null }}
              onChange={(v) => edit(() => setWork({ ...work, status: v }))} />
            {work.status && work.status !== "PRIVATE" ? (
              <>
                <Pick name="government_type" label="Central or state government" value={work.government_type}
                  list={{ rows: options.government_types, error: null }} onChange={(v) => edit(() => setWork({ ...work, government_type: v }))} />
                {work.government_type === "CENTRAL" ? <Field name="ministry" label="Ministry" value={work.ministry} maxLength={150}
                  onChange={(v) => edit(() => setWork({ ...work, ministry: v }))} /> : null}
                <Attach name="work_proof" label="Payslip or recent transfer order" value={work.proof}
                  onError={reportError} onChange={(v) => edit(() => setWork((w) => ({ ...w, proof: v })))} />
              </>
            ) : null}
            <Field name="facility_id" label="Facility ID (HFR) where they work" value={work.facility_id} valid={FACILITY_ID.test(work.facility_id)}
              maxLength={12} onChange={(v) => edit(() => setWork({ ...work, facility_id: v.trim().toUpperCase() }))} />
            <Field name="department" label="Department (optional)" value={work.department} maxLength={100} onChange={(v) => edit(() => setWork({ ...work, department: v }))} />
            <Field name="designation" label="Designation (optional)" value={work.designation} maxLength={100} onChange={(v) => edit(() => setWork({ ...work, designation: v }))} />
          </>
        ) : null}
      </fieldset>

      <fieldset className="flex flex-wrap gap-4 text-sm"><legend className="mb-2 font-medium">Visibility</legend>
        <label className="flex items-center gap-2"><input type="checkbox" name="show_photo" checked={visibility.show_photo}
          onChange={(e) => edit(() => setVisibility({ ...visibility, show_photo: e.target.checked }))} />Show the profile photograph</label>
        <label className="flex items-center gap-2"><input type="checkbox" name="public_profile" checked={visibility.public_profile}
          onChange={(e) => edit(() => setVisibility({ ...visibility, public_profile: e.target.checked }))} />Profile visible to the public</label>
      </fieldset>

      <div className="flex flex-wrap gap-2">
        {!registered ? <button type="button" className={primary} disabled={busy || !signedIn || !valid} onClick={() => void submit(false)}>{busy ? "Submitting…" : "Submit to HPR"}</button> : null}
        <button type="button" className={registered ? primary : secondary} disabled={busy || !signedIn || !valid} onClick={() => void submit(true)}>Update in HPR</button>
      </div>
      {!signedIn ? <p role="alert" className="text-sm text-danger">The HPR login has ended. Sign in again above to continue.</p> : null}
      {notice ? (
        <p ref={(node) => node?.scrollIntoView({ block: "center", behavior: "smooth" })} role="status"
          className="rounded-md border border-success/30 bg-success-muted p-3 text-sm font-medium text-success">{notice}</p>
      ) : null}
      {errors.length ? <ul role="alert" className="list-disc space-y-1 pl-5 text-sm text-danger">{errors.map((m) => <li key={m}>{m}</li>)}</ul> : null}
    </div>
  );
}

function Qualification({ index, q, systemName, courses, states, months, onChange, onError, onRemove }: {
  index: number; q: QualificationDraft; systemName: string; courses: List; states: List; months: string[];
  onChange: (change: Partial<QualificationDraft>) => void; onError: (message: string) => void; onRemove: (() => void) | null;
}) {
  const colleges = useList(q.state && systemName ? `colleges:${q.state}:${systemName}` : null, () => hprColleges(q.state, systemName));
  const universities = useList(q.college ? `universities:${q.college}` : null, () => hprUniversities(q.college));
  const n = (name: string) => `q${index}_${name}`;
  return (
    <fieldset className="grid gap-3 rounded-md border border-border p-3 md:grid-cols-3">
      <legend className="px-1 font-medium">Qualification {index + 1}</legend>
      {!systemName ? <p className="text-sm text-muted-foreground md:col-span-3">Choose the system of medicine above first.</p> : null}
      <Pick name={n("degree")} label="Degree or diploma" value={q.degree} list={systemName ? courses : { rows: null, error: null }} onChange={(v) => onChange({ degree: v })} />
      <Pick name={n("state")} label="State of the college" value={q.state} list={states} onChange={(v) => onChange({ state: v, college: "", university: "" })} />
      <Pick name={n("college")} label="College" value={q.college} list={q.state && systemName ? colleges : { rows: null, error: null }}
        onChange={(v) => onChange({ college: v, university: "" })} />
      <Pick name={n("university")} label="University" value={q.university} list={q.college ? universities : { rows: null, error: null }}
        onChange={(v) => onChange({ university: v })} />
      <Field name={n("year")} label="Year awarded" value={q.year} inputMode="numeric" maxLength={4}
        valid={/^\d{4}$/.test(q.year) && Number(q.year) <= new Date().getFullYear()} onChange={(v) => onChange({ year: v.replace(/\D/g, "") })} />
      <Pick name={n("month")} label="Month awarded (optional)" value={q.month} list={{ rows: months.map((m) => ({ code: m, label: m })), error: null }}
        onChange={(v) => onChange({ month: v })} />
      <Attach name={n("certificate")} label="Degree certificate" value={q.certificate} onError={onError} onChange={(v) => onChange({ certificate: v })} />
      <label className="flex items-center gap-2 text-sm"><input type="checkbox" name={n("name_differs")} checked={q.name_differs}
        onChange={(e) => onChange({ name_differs: e.target.checked })} />The name on the certificate differs</label>
      {q.name_differs ? <Attach name={n("name_proof")} label="Proof of name change" value={q.name_change_proof} onError={onError}
        onChange={(v) => onChange({ name_change_proof: v })} /> : null}
      {onRemove ? <button type="button" className="text-sm underline md:col-span-3" onClick={onRemove}>Remove this qualification</button> : null}
    </fieldset>
  );
}
