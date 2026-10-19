"use client";

import { useEffect, useMemo, useState } from "react";

import { ApiError, api, newIdempotencyKey } from "@/lib/api";
import { useLocale } from "@/lib/i18n";
import { createConsentRecord, listConsentPurposes } from "../api";
import { consentChannelFormLabel } from "../i18nLabels";
import type {
  ConsentChannel,
  ConsentPurpose,
  ConsentRecord,
  GrantedByType,
} from "../types";

type Props = {
  patientId: string;
  onCreated: (record: ConsentRecord) => void;
};

const GRANT_FORM_CHANNELS: ConsentChannel[] = ["written", "verbal", "digital_otp"];

const GRANTERS: Array<{ value: GrantedByType; label: string }> = [
  { value: "patient", label: "Patient" },
  { value: "guardian", label: "Guardian" },
  { value: "nominee", label: "Nominee" },
];

function humanise(code: string) {
  return code.replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function defaultExpiry(days: number | null): string {
  if (days === null) return "";
  const value = new Date();
  value.setDate(value.getDate() + days);
  return localDate(value);
}

function localDate(value = new Date()): string {
  const year = value.getFullYear();
  const month = String(value.getMonth() + 1).padStart(2, "0");
  const day = String(value.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

export function ConsentGrantForm({ patientId, onCreated }: Props) {
  const { t } = useLocale();
  const [purposes, setPurposes] = useState<ConsentPurpose[] | null>(null);
  const [purposeId, setPurposeId] = useState("");
  const [channel, setChannel] = useState<ConsentChannel>("written");
  const [grantedBy, setGrantedBy] = useState<GrantedByType>("patient");
  const [representativeName, setRepresentativeName] = useState("");
  const [relationship, setRelationship] = useState("");
  const [expiresOn, setExpiresOn] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [created, setCreated] = useState<ConsentRecord | null>(null);
  const [idempotencyKey, setIdempotencyKey] = useState(() => newIdempotencyKey());
  // A minor's consent is a guardian's decision. "Patient" was offered and
  // saved for a 4-year-old (QA 16 Oct 2026); the server now refuses it, and
  // the form starts on Guardian with the guardian from registration.
  const [minorAge, setMinorAge] = useState<number | null>(null);

  useEffect(() => {
    let cancelled = false;
    api<{ age_years?: number | null; guardian_name?: string | null; guardian_relationship?: string | null }>(
      `/patients/${patientId}`,
    )
      .then((p) => {
        if (cancelled || p.age_years === null || p.age_years === undefined || p.age_years >= 18) return;
        setMinorAge(p.age_years);
        setGrantedBy("guardian");
        if (p.guardian_name) setRepresentativeName(p.guardian_name);
        if (p.guardian_relationship) setRelationship(p.guardian_relationship);
      })
      .catch(() => {
        // The server still refuses a minor's own consent; the form only loses the head start.
      });
    return () => {
      cancelled = true;
    };
  }, [patientId]);

  useEffect(() => {
    let cancelled = false;
    listConsentPurposes()
      .then((rows) => {
        if (cancelled) return;
        const active = rows.filter((row) => row.is_active);
        setPurposes(active);
        const preferred = active.find((row) => row.purpose_code === "clinical_review") ?? active[0];
        if (preferred) {
          setPurposeId(preferred.id);
          setExpiresOn(defaultExpiry(preferred.default_expiry_days));
        }
      })
      .catch((reason: unknown) => {
        if (!cancelled) {
          setPurposes([]);
          setError(reason instanceof ApiError ? reason.message : "Could not load consent purposes.");
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const needsRepresentative = grantedBy !== "patient";
  const canSubmit = useMemo(
    () =>
      Boolean(purposeId) &&
      (!needsRepresentative || Boolean(representativeName.trim() && relationship.trim())) &&
      !busy,
    [busy, needsRepresentative, purposeId, relationship, representativeName],
  );

  function changePurpose(nextId: string) {
    setPurposeId(nextId);
    const purpose = purposes?.find((row) => row.id === nextId);
    setExpiresOn(defaultExpiry(purpose?.default_expiry_days ?? null));
  }

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!canSubmit) {
      setError("Complete the required consent fields before recording the decision.");
      return;
    }

    setBusy(true);
    setError(null);
    try {
      const record = await createConsentRecord(
        patientId,
        {
          purpose_id: purposeId,
          granted_by_type: grantedBy,
          guardian_name: needsRepresentative ? representativeName.trim() : null,
          guardian_relationship: needsRepresentative ? relationship.trim() : null,
          expires_at: expiresOn ? new Date(`${expiresOn}T23:59:59`).toISOString() : null,
          channel,
          status: "granted",
        },
        idempotencyKey,
      );
      setCreated(record);
      onCreated(record);
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : "Could not record consent.");
    } finally {
      setBusy(false);
    }
  }

  if (created) {
    return (
      <section className="surface-card space-y-2 border border-success/30 bg-success-muted p-5">
        <h2 className="text-base font-semibold text-success">{t("consent.ui.consentRecorded")}</h2>
        <p className="text-sm text-muted-foreground">{t("consent.ui.theDecisionIsNowInThe")}</p>
        <button
          type="button"
          className="text-sm font-medium underline"
          onClick={() => {
            setCreated(null);
            setError(null);
            setIdempotencyKey(newIdempotencyKey());
          }}
        >{t("consent.ui.recordAnotherConsent")}</button>
      </section>
    );
  }

  return (
    <form onSubmit={submit} className="surface-card space-y-4 p-5">
      <div>
        <h2 className="text-base font-semibold">{t("consent.recordConsent")}</h2>
        <p className="mt-1 text-sm text-muted-foreground">{t("consent.ui.recordTheDecisionCommunicatedByThe")}</p>
      </div>

      {purposes === null ? (
        <p className="text-sm text-muted-foreground">{t("consent.loadingPurposes")}</p>
      ) : purposes.length === 0 ? (
        <p role="alert" className="text-sm text-danger">{t("consent.ui.noActiveConsentPurposeIsConfigured")}</p>
      ) : (
        <div className="grid gap-4 md:grid-cols-2">
          <label className="space-y-1 text-sm">
            <span className="text-muted-foreground">{t("field.purpose")} *</span>
            <select
              required
              value={purposeId}
              onChange={(event) => changePurpose(event.target.value)}
              className="w-full rounded-md border border-border bg-background px-3 py-2"
            >
              {purposes.map((purpose) => (
                <option key={purpose.id} value={purpose.id}>
                  {humanise(purpose.purpose_code)}
                </option>
              ))}
            </select>
          </label>

          <label className="space-y-1 text-sm">
            <span className="text-muted-foreground">{t("field.channel")} *</span>
            <select
              required
              value={channel}
              onChange={(event) => setChannel(event.target.value as ConsentChannel)}
              className="w-full rounded-md border border-border bg-background px-3 py-2"
            >
              {GRANT_FORM_CHANNELS.map((value) => (
                <option key={value} value={value}>
                  {consentChannelFormLabel(t, value)}
                </option>
              ))}
            </select>
          </label>

          <label className="space-y-1 text-sm">
            <span className="text-muted-foreground">{t("consent.ui.decisionGivenBy")}</span>
            <select
              required
              value={grantedBy}
              onChange={(event) => setGrantedBy(event.target.value as GrantedByType)}
              className="w-full rounded-md border border-border bg-background px-3 py-2"
            >
              {GRANTERS.map((option) => (
                <option key={option.value} value={option.value} disabled={option.value === "patient" && minorAge !== null}>
                  {option.label}
                </option>
              ))}
            </select>
            {minorAge !== null && (
              <span className="block text-xs text-muted-foreground">
                {t("consent.minorNeedsGuardian", { age: minorAge })}
              </span>
            )}
          </label>

          <label className="space-y-1 text-sm">
            <span className="text-muted-foreground">{t("field.validUntil")}</span>
            <input
              type="date"
              min={localDate()}
              value={expiresOn}
              onChange={(event) => setExpiresOn(event.target.value)}
              className="w-full rounded-md border border-border px-3 py-2"
            />
            <span className="block text-xs text-muted-foreground">{t("consent.ui.leaveBlankOnlyWhenThePurpose")}</span>
          </label>

          {needsRepresentative ? (
            <>
              <label className="space-y-1 text-sm">
                <span className="text-muted-foreground">{t("consent.ui.representativeName")}</span>
                <input
                  required
                  minLength={2}
                  maxLength={120}
                  value={representativeName}
                  onChange={(event) => setRepresentativeName(event.target.value)}
                  className="w-full rounded-md border border-border px-3 py-2"
                />
              </label>
              <label className="space-y-1 text-sm">
                <span className="text-muted-foreground">{t("consent.ui.relationship")}</span>
                <input
                  required
                  minLength={2}
                  maxLength={80}
                  value={relationship}
                  onChange={(event) => setRelationship(event.target.value)}
                  className="w-full rounded-md border border-border px-3 py-2"
                />
              </label>
            </>
          ) : null}
        </div>
      )}

      {error ? <p role="alert" className="text-sm text-danger">{error}</p> : null}

      <button
        type="submit"
        disabled={!canSubmit || purposes?.length === 0}
        className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
      >
        {busy ? t("consent.recording") : t("consent.recordConsent")}
      </button>
    </form>
  );
}
