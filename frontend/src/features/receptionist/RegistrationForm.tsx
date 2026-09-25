"use client";

import { useMemo, useState } from "react";
import { Printer } from "lucide-react";

import { ApiError, newIdempotencyKey } from "@/lib/api";
import { useLocale } from "@/lib/i18n";
import { PatientAvatar } from "@/components/ui/PatientAvatar";

import { registerPatient, uploadPatientPhoto } from "./api";
import { AbhaIdentityPanel } from "./AbhaIdentityPanel";
import { StartVisit } from "./StartVisit";
import { PatientCardModal } from "./PatientCardModal";
import type { Patient, PatientCreate } from "./types";
import {
  deriveAgeFromDob,
  digitsOnly,
  isValidAbhaInput,
  isValidPatientName,
  normaliseIndianMobileInput,
} from "./patientValidation";

const SEXES = ["male", "female", "other"] as const;

type AgeMode = "dob" | "age";

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

  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [registered, setRegistered] = useState<Patient | null>(null);
  const [showCardModal, setShowCardModal] = useState(false);

  /**
   * Generated once when the form mounts, not per submit.
   *
   * That is what makes the retry safe: a double-click, or a network drop after
   * the server has committed, replays the stored response and returns the same
   * patient with the same UHID. A key generated per submit would defeat the
   * whole mechanism and hand the second click a second chart.
   */
  const idempotencyKey = useMemo(() => newIdempotencyKey(), []);

  const derivedAge = useMemo(() => (ageMode === "dob" && dob ? deriveAgeFromDob(dob) : null), [ageMode, dob]);

  const ageProvided = ageMode === "dob" ? dob !== "" : ageYears !== "";
  const fullNameValid = isValidPatientName(fullName);
  const normalisedMobile = normaliseIndianMobileInput(mobile);
  const mobileValid = !mobile.trim() || normalisedMobile !== null;
  const abhaValid = !abha.trim() || isValidAbhaInput(abha);
  const ageValid =
    ageMode === "dob"
      ? Boolean(dob && dob <= new Date().toISOString().slice(0, 10))
      : Boolean(ageYears && Number.isInteger(Number(ageYears)) && Number(ageYears) >= 0 && Number(ageYears) <= 130);
  const canSubmit = fullNameValid && sex !== "" && ageProvided && ageValid && mobileValid && abhaValid && !busy;
  const inputClass = (invalid: boolean) =>
    `w-full rounded-md border px-3 py-2 ${invalid ? "border-danger" : "border-border"}`;

  const handlePhotoChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) {
      if (file.size > 2 * 1024 * 1024) {
        setError("Patient photo must be smaller than 2MB.");
        return;
      }
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

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!canSubmit) {
      setError("Please correct the highlighted registration fields before submitting.");
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
    };

    setBusy(true);
    setError(null);
    try {
      const patient = await registerPatient(payload, idempotencyKey);
      
      // If photo was selected, upload it to the patient record
      if (photoFile) {
        try {
          const photoRes = await uploadPatientPhoto(patient.id, photoFile);
          patient.photo_file_id = photoRes.photo_file_id;
        } catch {
          // Photo failure should not fail patient creation, but let desk know
          console.warn("Patient registered, but photo upload encountered an issue.");
        }
      }

      setRegistered(patient);
      onRegistered?.(patient);
    } catch (reason) {
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
          <p className="text-sm text-muted-foreground">Registered Patient</p>
          <p className="font-mono text-3xl font-bold">{registered.uhid ?? registered.thid}</p>
          <p className="text-xl font-medium">{registered.full_name}</p>
          <p className="text-sm text-muted-foreground">
            <span className="capitalize">{registered.sex}</span>
            {registered.age_years !== null ? ` · ${registered.age_years} years` : ""}
            {registered.dob ? ` (DOB: ${registered.dob})` : ""}
          </p>
          {registered.guardian_name && (
            <p className="text-xs text-muted-foreground">
              Guardian: {registered.guardian_name} ({registered.guardian_relationship ?? "Guardian"})
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
              <Printer size={16} />
              Print Patient Card
            </button>
          </div>
        </div>

        <AbhaIdentityPanel patient={registered} />

        {/* A UHID on its own does nothing for the patient standing at the desk.
            The visit is what starts billing; the token is what gets them seen. */}
        <StartVisit patient={registered} />

        <div className="text-center">
          <button
            type="button"
            // Full reload, deliberately: the next patient needs NEW idempotency
            // keys. Resetting in place would reuse them and the server would
            // replay this registration, visit and token.
            onClick={() => window.location.reload()}
            className="text-sm underline"
          >
            Register another patient
          </button>
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
            <span className="text-xs text-danger">Enter a valid name without digits or markup characters.</span>
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
                {value}
              </option>
            ))}
          </select>
        </label>

        <div className="space-y-1 text-sm">
          <div className="flex items-center justify-between">
            <span className="text-muted-foreground">{t("field.ageDob")} *</span>
            {derivedAge && (
              <span className="rounded bg-primary/10 px-2 py-0.5 text-xs font-semibold text-primary">
                Derived: {derivedAge.displayText}
              </span>
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
                max={new Date().toISOString().slice(0, 10)}
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
            <span className="text-xs text-danger">Enter a valid Indian mobile number.</span>
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
            <span className="text-xs text-danger">ABHA number must contain 14 digits.</span>
          ) : null}
        </label>

        {/* Patient Photo Selection (HD-08) */}
        <div className="space-y-1 text-sm sm:col-span-2">
          <span className="text-muted-foreground">Patient Photograph (Optional, max 2MB)</span>
          <div className="flex items-center gap-4 pt-1">
            {photoPreview ? (
              <div className="relative">
                <img
                  src={photoPreview}
                  alt="Patient preview"
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
              accept="image/jpeg,image/png,image/webp"
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
          <span>{showAddressDetails ? "▼" : "▶"} Additional Demographics & Address (Optional)</span>
        </button>

        {showAddressDetails && (
          <div className="mt-4 grid gap-4 sm:grid-cols-2 rounded-lg border border-border/60 bg-muted/10 p-4">
            <label className="space-y-1 text-sm">
              <span className="text-muted-foreground">{t("field.guardianName")}</span>
              <input
                className={inputClass(false)}
                value={guardianName}
                onChange={(e) => setGuardianName(e.target.value)}
                placeholder={t("receptionist.phGuardianName")}
              />
            </label>

            <label className="space-y-1 text-sm">
              <span className="text-muted-foreground">{t("field.guardianRelationship")}</span>
              <select
                className={inputClass(false)}
                value={guardianRelationship}
                onChange={(e) => setGuardianRelationship(e.target.value)}
              >
                <option value="">Select relationship…</option>
                <option value="father">Father</option>
                <option value="mother">Mother</option>
                <option value="spouse">Spouse</option>
                <option value="guardian">Guardian</option>
                <option value="other">Other</option>
              </select>
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
              <input
                maxLength={4}
                className={inputClass(false)}
                value={stateCode}
                onChange={(e) => setStateCode(e.target.value.toUpperCase())}
                placeholder={t("receptionist.phState")}
              />
            </label>

            <label className="space-y-1 text-sm">
              <span className="text-muted-foreground">{t("field.pincode")}</span>
              <input
                maxLength={6}
                className={inputClass(false)}
                value={pincode}
                onChange={(e) => setPincode(e.target.value)}
                placeholder={t("receptionist.phPincode")}
                inputMode="numeric"
              />
            </label>
          </div>
        )}
      </div>

      {error && (
        <p role="alert" className="text-sm text-danger">
          {error}
        </p>
      )}

      <button
        type="submit"
        disabled={!canSubmit}
        className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
      >
        {busy ? t("forms.saving") : t("receptionist.registerPatient")}
      </button>
    </form>
  );
}

export default RegistrationForm;
