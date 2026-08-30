"use client";

import { useCallback, useEffect, useState } from "react";

import { toast } from "@/components/ui/toast";
import { ApiError } from "@/lib/api";
import { hasKeycloakMfaSession, stepUpWithKeycloak } from "@/lib/auth/keycloak";
import {
  checkRecordAccess,
  requestBreakGlassGrant,
  revokeBreakGlassGrant,
} from "../api";
import type { RecordAccess } from "../types";

/** Owns the server's consent-or-emergency-access decision for one patient. */
export function useBreakGlass(patientId: string | null) {
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
      toast.error(error instanceof Error ? error.message : "Failed to check record access");
      setAccess(null);
    } finally {
      setLoading(false);
    }
  }, [patientId]);

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
        toast.error("Emergency access expired.");
        void load();
      }
    };

    tick();
    const id = setInterval(tick, 1000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [grant, load]);

  const beginStepUp = useCallback(async (): Promise<void> => {
    setStepUpError(null);
    setSubmitting(true);
    try {
      await stepUpWithKeycloak(window.location.href);
    } catch (error) {
      setStepUpError(error instanceof Error ? error.message : "Keycloak verification failed.");
    } finally {
      setSubmitting(false);
    }
  }, []);

  const requestAccess = useCallback(
    async (justification: string): Promise<string | null> => {
      if (!patientId) return "No patient selected.";
      if (!mfaVerified) return "Verify your identity with Keycloak first.";
      setSubmitting(true);
      try {
        const created = await requestBreakGlassGrant({
          patient_id: patientId,
          justification,
        });
        setAccess({ patient_id: patientId, allowed: true, grant: created });
        toast.success("Emergency access granted — this session is being recorded.");
        return null;
      } catch (error) {
        if (
          error instanceof ApiError &&
          error.code === 403 &&
          (error.payload as { code?: string } | undefined)?.code === "mfa_required"
        ) {
          setMfaVerified(false);
          return "Keycloak did not return OTP/MFA proof. Verify again or ask an administrator to enroll your authenticator.";
        }
        return error instanceof Error ? error.message : "Could not open emergency access.";
      } finally {
        setSubmitting(false);
      }
    },
    [mfaVerified, patientId],
  );

  const revoke = useCallback(async () => {
    if (!grant) return;
    setSubmitting(true);
    try {
      await revokeBreakGlassGrant(grant.id);
      toast.success("Emergency access ended.");
      await load();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Failed to end emergency access");
    } finally {
      setSubmitting(false);
    }
  }, [grant, load]);

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
