"use client";

import { useMemo, useRef, useState, useSyncExternalStore } from "react";
import { Printer } from "lucide-react";

import { ApiError, newIdempotencyKey } from "@/lib/api";
import { apiErrorCode } from "@/lib/api-error-policy.mjs";
import { useLocale } from "@/lib/i18n";
import { PatientAvatar } from "@/components/ui/PatientAvatar";

import { registerPatient, uploadPatientPhoto } from "./api";
import { AbhaIdentityPanel } from "./AbhaIdentityPanel";
import { StartVisit } from "./StartVisit";
import { PatientCardModal } from "./PatientCardModal";
import type { Patient, PatientCreate } from "./types";
import {
  INDIAN_STATES,
  PHOTO_MIME_TYPES,
  deriveAgeFromDob,
  digitsOnly,
  isValidAbhaInput,
  isValidPatientName,
  isValidPincodeInput,
  isValidStateCode,
  localToday,
  normaliseIndianMobileInput,
} from "./patientValidation";

const SEXES = ["male", "female", "other"] as const;
const SEX_LABEL_KEYS = {
  male: "common.sexMale",
  female: "common.sexFemale",
  other: "common.sexOther",
} as const;
const MAX_PHOTO_BYTES = 2 * 1024 * 1024;

type AgeMode = "dob" | "age";
const ADULT_AGE_YEARS = 18;

interface DuplicateCandidate {
  patient_id: string;
  uhid: string | null;
  full_name: string;
  age_years: number | null;
  dob: string | null;
}

function duplicateCandidates(payload: unknown): DuplicateCandidate[] {
  const detail = (payload as { detail?: { candidates?: unknown } } | undefined)?.detail;
  return Array.isArray(detail?.candidates) ? (detail.candidates as DuplicateCandidate[]) : [];
}
type PhotoStatus = "idle" | "uploading" | "failed";

const noSubscription = () => () => {};
const noServerDate = () => undefined;

export function RegistrationForm({ onRegistered }: { onRegistered?: (p: Patient) => void }) {
  const { t } = useLocale();
  const [fullName, setFullName] = useState("");
  const [sex, setSex] = useState<PatientCreate["sex"] | "">("");
  const [ageMode, setAgeMode] = useState<AgeMode>("dob");
  const [dob, setDob] = useState("");
  const [ageYears, setAgeYears] = useState("");
  const [mobile, setMobile] = useState("");
  const [abha, setAbha] = useState("");

  // Demographics & Address (HD-06, HD-07)
  const [showAddressDetails, setShowAddressDetails] = useState(false);
  const [guardianName, setGuardianName] = useState("");
  const [guardianRelationship, setGuardianRelationship] = useState("");
  const [addressLine, setAddressLine] = useState("");
  const [villageTown, setVillageTown] = useState("");
  const [district, setDistrict] = useState("");
  const [stateCode, setStateCode] = useState("");
  const [pincode, setPincode] = useState("");

  // Patient Photo (HD-08)
  const [photoFile, setPhotoFile] = useState<File | null>(null);
  const [photoPreview, setPhotoPreview] = useState<string | null>(null);
  const [photoStatus, setPhotoStatus] = useState<PhotoStatus>("idle");
  // One key per patient and file, kept across Retry so a resend after a lost
  // response replays the stored photo instead of uploading a second copy.
  const photoAttempt = useRef<{ patientId: string; file: File; key: string } | null>(null);
  // Read on the client only: the server renders in UTC and would disagree
  // with the browser's date for five and a half hours every night.
  const today = useSyncExternalStore(noSubscription, localToday, noServerDate);

  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [registered, setRegistered] = useState<Patient | null>(null);
  const [showCardModal, setShowCardModal] = useState(false);
  // The server's possible-duplicate answer: the records that look like this
  // person. Registering anyway needs an explicit "different person".
  const [duplicates, setDuplicates] = useState<DuplicateCandidate[]>([]);

  /**
   * Generated once when the form mounts, not per submit.
   *
   * That is what makes the retry safe: a double-click, or a network drop after
   * the server has committed, replays the stored response and returns the same
   * patient with the same UHID. A key generated per submit would defeat the
   * whole mechanism and hand the second click a second chart.
   */
  const idempotencyKey = useRef<string>("");
  if (!idempotencyKey.current) idempotencyKey.current = newIdempotencyKey();

  const derivedAge = useMemo(() => (ageMode === "dob" && dob ? deriveAgeFromDob(dob) : null), [ageMode, dob]);

  const ageProvided = ageMode === "dob" ? dob !== "" : ageYears !== "";
  const fullNameValid = isValidPatientName(fullName);
  const normalisedMobile = normaliseIndianMobileInput(mobile);
  const mobileValid = !mobile.trim() || normalisedMobile !== null;
  const abhaValid = !abha.trim() || isValidAbhaInput(abha);
  const ageValid =
    ageMode === "dob"
      ? Boolean(dob && (!today || dob <= today))
      : Boolean(ageYears && Number.isInteger(Number(ageYears)) && Number(ageYears) >= 0 && Number(ageYears) <= 130);
  const pincodeValid = !pincode.trim() || isValidPincodeInput(pincode);
  const stateValid = !stateCode || isValidStateCode(stateCode);
  const ageError = !ageProvided || ageValid
    ? null
    : ageMode === "dob"
      ? "Date of birth cannot be in the future."
      : "Enter an age in whole years between 0 and 130.";
  const ageInYears = ageMode === "dob" ? derivedAge?.years ?? null : ageValid ? Number(ageYears) : null;
  const isMinor = ageInYears !== null && ageInYears < ADULT_AGE_YEARS;
  const guardianNameValid = !guardianName.trim() || isValidPatientName(guardianName);
  const guardianMissing = isMinor && !guardianName.trim();
  const relationshipMissing = Boolean(guardianName.trim()) && !guardianRelationship;
  // What still stops Register, in words: a greyed-out button alone left the
  // desk guessing (QA 10 Oct 2026).
  const blockers = [
    !fullNameValid && "full name",
    sex === "" && "sex",
    (!ageProvided || !ageValid) && (ageMode === "dob" ? "date of birth" : "age"),
    !mobileValid && "mobile number",
    !abhaValid && "ABHA number",
    !guardianNameValid && "guardian name",
    guardianMissing && "guardian (required under 18)",
    relationshipMissing && "guardian relationship",
    !pincodeValid && "PIN code",
    !stateValid && "state",
  ].filter((item): item is string => Boolean(item));
  const canSubmit = blockers.length === 0 && !busy;
  const inputClass = (invalid: boolean) =>
    `w-full rounded-md border px-3 py-2 ${invalid ? "border-danger" : "border-border"}`;

  const handlePhotoChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) {
      if (!PHOTO_MIME_TYPES.includes(file.type)) {
        setError(t("receptionist.photoTypeInvalid"));
        e.target.value = "";
        return;
      }
      if (file.size > MAX_PHOTO_BYTES) {
        setError(t("receptionist.photoTooLarge"));
        e.target.value = "";
        return;
      }
      setError(null);
      if (photoPreview) URL.revokeObjectURL(photoPreview);
      setPhotoFile(file);
      const previewUrl = URL.createObjectURL(file);
      setPhotoPreview(previewUrl);
    }
  };

  const handleClearPhoto = () => {
    setPhotoFile(null);
    if (photoPreview) {
      URL.revokeObjectURL(photoPreview);
      setPhotoPreview(null);
    }
  };

  async function uploadPhoto(patient: Patient, file: File): Promise<Patient> {
    const attempt = photoAttempt.current;
    if (!attempt || attempt.patientId !== patient.id || attempt.file !== file) {
      photoAttempt.current = { patientId: patient.id, file, key: newIdempotencyKey() };
    }
    setPhotoStatus("uploading");
    try {
      const saved = await uploadPatientPhoto(patient.id, file, photoAttempt.current!.key);
      setPhotoStatus("idle");
      return { ...patient, photo_file_id: saved.photo_file_id };
    } catch {
      // The registration stands; the desk is told and offered a retry.
      setPhotoStatus("failed");
      return patient;
    }
  }

  async function retryPhoto() {
    if (!registered || !photoFile || photoStatus === "uploading") return;
    setRegistered(await uploadPhoto(registered, photoFile));
  }

  async function submit(event: React.FormEvent, confirmNotDuplicate = false) {
    event.preventDefault();
    if (!canSubmit || sex === "") {
      setError(`Complete: ${blockers.join(", ")}.`);
      return;
    }

    const payload: PatientCreate = {
      full_name: fullName.trim(),
      sex,
      // Exactly one, matching the server's `_dob_or_age_required`. Sending both
      // would let a typed age silently disagree with a date of birth.
      ...(ageMode === "dob"
        ? { dob, age_years: null }
        : { dob: null, age_years: Number(ageYears) }),
      mobile: normalisedMobile,
      abha_number: abha.trim() ? digitsOnly(abha) : null,
      guardian_name: guardianName.trim() || null,
      guardian_relationship: guardianRelationship.trim() || null,
      address_line: addressLine.trim() || null,
      village_town: villageTown.trim() || null,
      district: district.trim() || null,
      state_code: stateCode.trim() || null,
      pincode: pincode.trim() || null,
      ...(confirmNotDuplicate ? { confirm_not_duplicate: true } : {}),
    };

    setBusy(true);
    setError(null);
    setDuplicates([]);
    try {
      const patient = await registerPatient(payload, idempotencyKey.current);
      const saved = photoFile ? await uploadPhoto(patient, photoFile) : patient;
      setRegistered(saved);
      onRegistered?.(saved);
    } catch (reason) {
      const code = reason instanceof ApiError ? apiErrorCode(reason.payload) : undefined;
      if (code === "possible_duplicate" || code === "duplicate_abha") {
        // A refusal before anything was written: the next attempt is a new
        // request and gets its own key.
        idempotencyKey.current = newIdempotencyKey();
      }
      if (code === "possible_duplicate") {
        setDuplicates(duplicateCandidates((reason as ApiError).payload));
        return;
      }
      setError(
        reason instanceof ApiError
          ? reason.message
          : "Registration failed. Do not retry from a new form — reload this page first.",
      );
    } finally {
      setBusy(false);
    }
  }

  if (registered) {
    return (
      <div className="space-y-6">
        <div className="surface-card flex flex-col items-center space-y-3 p-8 text-center">
          <PatientAvatar
            patientId={registered.id}
            photoFileId={registered.photo_file_id}
            photoUrl={photoPreview}
            name={registered.full_name}
            size="xl"
          />
          <p className="text-sm text-muted-foreground">{t("receptionist.ui.registeredPatient")}</p>
          <p className="font-mono text-3xl font-bold">{registered.uhid ?? registered.thid}</p>
          <p className="text-xl font-medium">{registered.full_name}</p>
          {photoStatus === "uploading" ? (
            <p role="status" className="text-xs text-muted-foreground">{t("receptionist.photoUploading")}</p>
          ) : null}
          {photoStatus === "failed" ? (
            <div role="alert" className="flex flex-wrap items-center justify-center gap-3 rounded-md border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-900">
              <span>{t("receptionist.photoUploadFailed")}</span>
              <button
                type="button"
                onClick={() => void retryPhoto()}
                className="rounded-md border border-amber-400 bg-white px-3 py-1 text-xs font-semibold hover:bg-amber-100"
              >
                {t("receptionist.retryPhotoUpload")}
              </button>
            </div>
          ) : null}
          <p className="text-sm text-muted-foreground">
            <span>
              {registered.sex in SEX_LABEL_KEYS
                ? t(SEX_LABEL_KEYS[registered.sex as keyof typeof SEX_LABEL_KEYS])
                : registered.sex}
            </span>
            {registered.age_years !== null ? ` · ${registered.age_years} years` : ""}
            {registered.dob ? ` (DOB: ${registered.dob})` : ""}
          </p>
          {registered.guardian_name && (
            <p className="text-xs text-muted-foreground">{t("nurse.ui.guardian")}{" "}{registered.guardian_name} ({registered.guardian_relationship ?? t("receptionist.ui.guardian")})
            </p>
          )}
          {registered.address_line && (
            <p className="text-xs text-muted-foreground">
              {[registered.address_line, registered.village_town, registered.district, registered.state_code, registered.pincode]
                .filter(Boolean)
                .join(", ")}
            </p>
          )}

          <div className="pt-2">
            <button
              type="button"
              onClick={() => setShowCardModal(true)}
              className="inline-flex items-center gap-2 rounded-md border border-border bg-card px-4 py-2 text-sm font-semibold hover:bg-muted shadow-sm"
            >
              <Printer size={16} />{t("receptionist.ui.printPatientCard")}</button>
          </div>
        </div>

        <AbhaIdentityPanel key={`abha-${registered.id}`} patient={registered} />

        {/* A UHID on its own does nothing for the patient standing at the desk.
            The visit is what starts billing; the token is what gets them seen. */}
        <StartVisit key={`visit-${registered.id}`} patient={registered} />

        <div className="text-center">
          <button
            type="button"
            // Full reload, deliberately: the next patient needs NEW idempotency
            // keys. Resetting in place would reuse them and the server would
            // replay this registration, visit and token.
            onClick={() => window.location.reload()}
            className="text-sm underline"
          >{t("emergency.registerAnother")}</button>
        </div>

        {showCardModal && (
          <PatientCardModal
            open={showCardModal}
            onClose={() => setShowCardModal(false)}
            patient={registered}
          />
        )}
      </div>
    );
  }

  return (
    <form onSubmit={submit} className="surface-card space-y-5 p-6">
      <div className="grid gap-4 sm:grid-cols-2">
        <label className="space-y-1 text-sm sm:col-span-2">
          <span className="text-muted-foreground">{t("field.fullName")} *</span>
          <input
            required
            className={inputClass(Boolean(fullName) && !fullNameValid)}
            aria-invalid={Boolean(fullName) && !fullNameValid}
            value={fullName}
            onChange={(e) => setFullName(e.target.value)}
            minLength={2}
          />
          {fullName && !fullNameValid ? (
            <span className="text-xs text-danger">{t("receptionist.ui.enterAValidNameWithoutDigits")}</span>
          ) : null}
        </label>

        <label className="space-y-1 text-sm">
          <span className="text-muted-foreground">{t("field.sex")} *</span>
          <select
            required
            className={inputClass(false)}
            value={sex}
            onChange={(e) => setSex(e.target.value as PatientCreate["sex"] | "")}
          >
            <option value="">{t("common.select")}…</option>
            {SEXES.map((value) => (
              <option key={value} value={value}>
                {t(SEX_LABEL_KEYS[value])}
              </option>
            ))}
          </select>
        </label>

        <div className="space-y-1 text-sm">
          <div className="flex items-center justify-between">
            <span className="text-muted-foreground">{t("field.ageDob")} *</span>
            {derivedAge && (
              <span className="rounded bg-primary/10 px-2 py-0.5 text-xs font-semibold text-primary">{t("receptionist.ui.derivedDisplaytext", { displayText: derivedAge.displayText })}</span>
            )}
          </div>
          <div className="flex gap-2">
            <select
              className="rounded-md border border-border px-2 py-2"
              value={ageMode}
              onChange={(e) => setAgeMode(e.target.value as AgeMode)}
            >
              <option value="dob">{t("field.dob")}</option>
              <option value="age">{t("field.age")}</option>
            </select>

            {/* Either, never both. Many patients at a district hospital do not
                know a date of birth, which is why the server accepts an age —
                but a recorded DOB and a recorded age that disagree are worse
                than one honest value. */}
            {ageMode === "dob" ? (
              <input
                type="date"
                className={`flex-1 rounded-md border px-3 py-2 ${dob && !ageValid ? "border-danger" : "border-border"}`}
                aria-invalid={Boolean(dob) && !ageValid}
                value={dob}
                onChange={(e) => setDob(e.target.value)}
                max={today}
                required
              />
            ) : (
              <input
                type="number"
                min={0}
                max={130}
                className={`flex-1 rounded-md border px-3 py-2 ${ageYears && !ageValid ? "border-danger" : "border-border"}`}
                aria-invalid={Boolean(ageYears) && !ageValid}
                value={ageYears}
                onChange={(e) => setAgeYears(e.target.value)}
                required
              />
            )}
          </div>
          {ageError ? <span className="text-xs text-danger">{ageError}</span> : null}
          {isMinor ? (
            <span className="text-xs text-muted-foreground">{t("receptionist.ui.under18EnterTheGuardianUnder")}</span>
          ) : null}
        </div>

        <label className="space-y-1 text-sm">
          <span className="text-muted-foreground">{t("field.mobile")}</span>
          <input
            className={inputClass(!mobileValid)}
            aria-invalid={!mobileValid}
            value={mobile}
            onChange={(e) => setMobile(e.target.value)}
            inputMode="tel"
            maxLength={18}
            placeholder={t("patient.mobilePlaceholder")}
          />
          {!mobileValid ? (
            <span className="text-xs text-danger">{t("receptionist.ui.enterAValidIndianMobileNumber")}</span>
          ) : null}
        </label>

        <label className="space-y-1 text-sm">
          <span className="text-muted-foreground">{t("field.abha")}</span>
          <input
            className={inputClass(!abhaValid)}
            aria-invalid={!abhaValid}
            value={abha}
            onChange={(e) => setAbha(e.target.value)}
            inputMode="numeric"
            maxLength={20}
          />
          {!abhaValid ? (
            <span className="text-xs text-danger">{t("receptionist.ui.abhaNumberMustContain14Digits")}</span>
          ) : null}
        </label>

        {/* Patient Photo Selection (HD-08) */}
        <div className="space-y-1 text-sm sm:col-span-2">
          <span className="text-muted-foreground">{t("receptionist.ui.patientPhotographOptionalMax2mb")}</span>
          <div className="flex items-center gap-4 pt-1">
            {photoPreview ? (
              <div className="relative">
                {/* A local blob: preview of a file not yet uploaded; the Next image
                    optimizer cannot fetch blob URLs, so next/image adds nothing here. */}
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img
                  src={photoPreview}
                  alt={t("receptionist.ui.patientPreview")}
                  className="h-16 w-16 rounded-full border border-border object-cover shadow-sm"
                />
                <button
                  type="button"
                  onClick={handleClearPhoto}
                  className="absolute -right-1 -top-1 rounded-full bg-danger px-1.5 py-0.5 text-[10px] font-bold text-white shadow"
                >
                  ✕
                </button>
              </div>
            ) : null}
            <input
              type="file"
              accept={PHOTO_MIME_TYPES.join(",")}
              onChange={handlePhotoChange}
              className="text-xs text-muted-foreground file:mr-3 file:rounded-md file:border-0 file:bg-muted file:px-3 file:py-1.5 file:text-xs file:font-semibold file:text-foreground hover:file:bg-muted/80"
            />
          </div>
        </div>
      </div>

      {/* Additional Demographics & Structured Address Accordion (HD-06, HD-07) */}
      <div className="border-t border-border/80 pt-3">
        <button
          type="button"
          onClick={() => setShowAddressDetails((shown) => !shown)}
          className="flex items-center justify-between text-xs font-semibold uppercase tracking-wider text-muted-foreground hover:text-foreground transition-colors"
        >
          <span>{t("receptionist.ui.valueAdditionalDemographicsAddressValue2", { value: showAddressDetails || isMinor ? "▼" : "▶", value2: isMinor ? " (guardian required)" : " (Optional)" })}</span>
        </button>

        {(showAddressDetails || isMinor) && (
          <div className="mt-4 grid gap-4 sm:grid-cols-2 rounded-lg border border-border/60 bg-muted/10 p-4">
            <label className="space-y-1 text-sm">
              <span className="text-muted-foreground">{t("field.guardianName")}</span>
              <input
                className={inputClass(!guardianNameValid || guardianMissing)}
                aria-invalid={!guardianNameValid || guardianMissing}
                value={guardianName}
                onChange={(e) => setGuardianName(e.target.value)}
                placeholder={t("receptionist.phGuardianName")}
              />
              {!guardianNameValid ? (
                <span className="text-xs text-danger">{t("receptionist.ui.enterAValidNameWithoutDigits")}</span>
              ) : guardianMissing ? (
                <span className="text-xs text-danger">{t("receptionist.ui.aPatientUnder18NeedsA")}</span>
              ) : null}
            </label>

            <label className="space-y-1 text-sm">
              <span className="text-muted-foreground">{t("field.guardianRelationship")}</span>
              <select
                className={inputClass(relationshipMissing)}
                aria-invalid={relationshipMissing}
                value={guardianRelationship}
                onChange={(e) => setGuardianRelationship(e.target.value)}
              >
                <option value="">{t("receptionist.ui.selectRelationship")}</option>
                <option value="father">{t("receptionist.ui.father")}</option>
                <option value="mother">{t("receptionist.ui.mother")}</option>
                <option value="spouse">{t("receptionist.ui.spouse")}</option>
                <option value="guardian">{t("receptionist.ui.guardian")}</option>
                <option value="other">{t("equipment.category.other")}</option>
              </select>
              {relationshipMissing ? (
                <span className="text-xs text-danger">{t("receptionist.ui.chooseHowTheGuardianIsRelated")}</span>
              ) : null}
            </label>

            <label className="space-y-1 text-sm sm:col-span-2">
              <span className="text-muted-foreground">{t("field.address")}</span>
              <input
                className={inputClass(false)}
                value={addressLine}
                onChange={(e) => setAddressLine(e.target.value)}
                placeholder={t("receptionist.phAddressLine")}
              />
            </label>

            <label className="space-y-1 text-sm">
              <span className="text-muted-foreground">{t("field.villageTown")}</span>
              <input
                className={inputClass(false)}
                value={villageTown}
                onChange={(e) => setVillageTown(e.target.value)}
                placeholder={t("receptionist.phVillage")}
              />
            </label>

            <label className="space-y-1 text-sm">
              <span className="text-muted-foreground">{t("field.district")}</span>
              <input
                className={inputClass(false)}
                value={district}
                onChange={(e) => setDistrict(e.target.value)}
                placeholder={t("receptionist.phDistrict")}
              />
            </label>

            <label className="space-y-1 text-sm">
              <span className="text-muted-foreground">{t("field.state")}</span>
              <select
                className={inputClass(!stateValid)}
                aria-invalid={!stateValid}
                value={stateCode}
                onChange={(e) => setStateCode(e.target.value)}
              >
                <option value="">{t("receptionist.selectState")}</option>
                {INDIAN_STATES.map((state) => (
                  <option key={state.code} value={state.code}>
                    {state.code} — {state.name}
                  </option>
                ))}
              </select>
              {!stateValid ? <span className="text-xs text-danger">{t("receptionist.errState")}</span> : null}
            </label>

            <label className="space-y-1 text-sm">
              <span className="text-muted-foreground">{t("field.pincode")}</span>
              <input
                maxLength={6}
                className={inputClass(!pincodeValid)}
                aria-invalid={!pincodeValid}
                value={pincode}
                onChange={(e) => setPincode(digitsOnly(e.target.value))}
                placeholder={t("receptionist.phPincode")}
                inputMode="numeric"
              />
              {!pincodeValid ? <span className="text-xs text-danger">{t("receptionist.errPincode")}</span> : null}
            </label>
          </div>
        )}
      </div>

      {error && (
        <p role="alert" className="text-sm text-danger">
          {error}
        </p>
      )}

      {duplicates.length > 0 && (
        <div role="alert" className="space-y-2 rounded-md border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900">
          <p className="font-semibold">{t("receptionist.ui.thisPatientMayAlreadyBeRegistered")}</p>
          <p>{t("receptionist.ui.sameNameAgeAndMobileAs")}</p>
          <ul className="list-disc pl-5">
            {duplicates.map((candidate) => (
              <li key={candidate.patient_id}>
                {candidate.full_name}{" "}{t("receptionist.ui.uhid")}{" "}{candidate.uhid ?? "not issued"}
                {candidate.dob ? ` · DOB ${candidate.dob}` : candidate.age_years !== null ? ` · ${candidate.age_years} years` : ""}
              </li>
            ))}
          </ul>
          <p>{t("receptionist.ui.searchByUhidToOpenThat")}</p>
          <button
            type="button"
            disabled={busy}
            onClick={(event) => void submit(event, true)}
            className="rounded-md border border-amber-400 bg-white px-3 py-1 text-xs font-semibold hover:bg-amber-100 disabled:opacity-50"
          >{t("receptionist.ui.differentPersonRegisterAnyway")}</button>
        </div>
      )}

      <button
        type="submit"
        disabled={!canSubmit}
        className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
      >
        {busy ? t("forms.saving") : t("receptionist.registerPatient")}
      </button>
      {!busy && blockers.length > 0 ? (
        <p className="text-xs text-muted-foreground">{t("receptionist.ui.stillNeededValue", { value: blockers.join(", ") })}</p>
      ) : null}
    </form>
  );
}

export default RegistrationForm;
