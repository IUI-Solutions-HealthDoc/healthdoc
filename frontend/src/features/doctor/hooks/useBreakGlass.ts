"use client";

import { useCallback, useEffect, useState } from "react";

import { toast } from "@/components/ui/toast";
import { ApiError } from "@/lib/api";
import { useLocale } from "@/lib/i18n";
import { hasKeycloakMfaSession, stepUpWithKeycloak } from "@/lib/auth/keycloak";
import {
  checkRecordAccess,
  requestBreakGlassGrant,
  revokeBreakGlassGrant,
} from "../api";
import type { RecordAccess } from "../types";

/** Owns the server's consent-or-emergency-access decision for one patient. */
export function useBreakGlass(patientId: string | null) {
  const { t } = useLocale();
  const [access, setAccess] = useState<RecordAccess | null>(null);
  const [loading, setLoading] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [msRemaining, setMsRemaining] = useState(0);
  const [mfaVerified, setMfaVerified] = useState(false);
  const [stepUpError, setStepUpError] = useState<string | null>(null);

  const grant = access?.grant ?? null;

  const load = useCallback(async () => {
    if (!patientId) {
      setAccess(null);
      return;
    }
    setLoading(true);
    try {
      setAccess(await checkRecordAccess(patientId));
    } catch (error) {
      toast.error(error instanceof Error ? error.message : t("doctor.toast.checkRecordAccessFailed"));
      setAccess(null);
    } finally {
      setLoading(false);
    }
  }, [patientId, t]);

  useEffect(() => {
    setMfaVerified(hasKeycloakMfaSession());
    setStepUpError(null);
    void load();
  }, [load]);

  // Tick against the server's expires_at. On expiry, ask the server again;
  // reloading or sleeping the tab can never create a fresh client-side window.
  useEffect(() => {
    if (!grant) {
      setMsRemaining(0);
      return;
    }
    const expiresAt = Date.parse(grant.expires_at);
    let cancelled = false;

    const tick = () => {
      const left = expiresAt - Date.now();
      if (cancelled) return;
      setMsRemaining(Math.max(0, left));
      if (left <= 0) {
        toast.error(t("doctor.toast.emergencyAccessExpired"));
        void load();
      }
    };

    tick();
    const id = setInterval(tick, 1000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [grant, load, t]);

  const beginStepUp = useCallback(async (): Promise<void> => {
    setStepUpError(null);
    setSubmitting(true);
    try {
      await stepUpWithKeycloak(window.location.href);
    } catch (error) {
      setStepUpError(error instanceof Error ? error.message : t("doctor.toast.keycloakVerificationFailed"));
    } finally {
      setSubmitting(false);
    }
  }, [t]);

  const requestAccess = useCallback(
    async (justification: string): Promise<string | null> => {
      if (!patientId) return t("doctor.toast.noPatientSelected");
      if (!mfaVerified) return t("doctor.toast.verifyKeycloakFirst");
      setSubmitting(true);
      try {
        const created = await requestBreakGlassGrant({
          patient_id: patientId,
          justification,
        });
        setAccess({ patient_id: patientId, allowed: true, grant: created });
        toast.success(t("doctor.toast.emergencyAccessGranted"));
        return null;
      } catch (error) {
        if (
          error instanceof ApiError &&
          error.code === 403 &&
          (error.payload as { code?: string } | undefined)?.code === "mfa_required"
        ) {
          setMfaVerified(false);
          return t("doctor.toast.mfaProofMissing");
        }
        return error instanceof Error ? error.message : t("doctor.toast.openEmergencyAccessFailed");
      } finally {
        setSubmitting(false);
      }
    },
    [mfaVerified, patientId, t],
  );

  const revoke = useCallback(async () => {
    if (!grant) return;
    setSubmitting(true);
    try {
      await revokeBreakGlassGrant(grant.id);
      toast.success(t("doctor.toast.emergencyAccessEnded"));
      await load();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : t("doctor.toast.endEmergencyAccessFailed"));
    } finally {
      setSubmitting(false);
    }
  }, [grant, load, t]);

  return {
    loading,
    submitting,
    allowed: access?.allowed ?? false,
    blockedReason: access?.blocked_reason ?? null,
    grant,
    msRemaining,
    mfaVerified,
    stepUpError,
    beginStepUp,
    requestAccess,
    revoke,
  };
}
