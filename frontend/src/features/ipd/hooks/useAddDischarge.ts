"use client";

import { useState } from "react";

import { toast } from "@/components/ui/toast";
import { ApiError, apiErrorCode, getUserFacingError } from "@/lib/api";
import { useLocale } from "@/lib/i18n";
import { dischargePatient } from "../api/ipd";
import type { AddDischargeSchema } from "@/features/ipd/components/DischargeForm/validation";

export type DischargeOutcome =
  | { ok: true }
  | { ok: false; code?: string; message: string };

/**
 * The server's reason (discharge before admission, follow-up in the past,
 * open checklist items) reaches the form instead of the console.
 */
export function useAddDischarge() {
  const { t } = useLocale();
  const [isSubmitting, setIsSubmitting] = useState(false);

  const submitDischarge = async (data: AddDischargeSchema): Promise<DischargeOutcome> => {
    setIsSubmitting(true);
    try {
      await dischargePatient(data);
      toast.success(t("ipd.toastDischarged"));
      return { ok: true };
    } catch (err) {
      const message = getUserFacingError(err, t("ipd.errDischarge"));
      return { ok: false, code: err instanceof ApiError ? apiErrorCode(err.payload) : undefined, message };
    } finally {
      setIsSubmitting(false);
    }
  };

  return { submitDischarge, isSubmitting };
}
