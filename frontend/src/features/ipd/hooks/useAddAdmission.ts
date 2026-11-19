"use client";

import { useState } from "react";

import { toast } from "@/components/ui/toast";
import { getUserFacingError } from "@/lib/api";
import { useLocale } from "@/lib/i18n";
import { admitPatient } from "../api/ipd";
import type { AddAdmissionSchema } from "@/features/ipd/components/AdmissionForm/validation";

/**
 * A refusal used to go to console.error only, so "Bed is already occupied"
 * or "already admitted" left the form sitting there silently, and a success
 * cleared it without a word (QA 16 Oct 2026).
 */
export function useAddAdmission() {
  const { t } = useLocale();
  const [isSubmitting, setIsSubmitting] = useState(false);

  const submitAdmission = async (data: AddAdmissionSchema) => {
    setIsSubmitting(true);
    try {
      const admission = await admitPatient(data);
      toast.success(
        t("ipd.toastAdmitted", {
          name: admission.patient_name ?? "",
          ward: admission.ward_name ?? "",
          bed: admission.bed_number ?? "",
        }),
      );
      return true;
    } catch (err) {
      toast.error(getUserFacingError(err, t("ipd.errAdmit")));
      return false;
    } finally {
      setIsSubmitting(false);
    }
  };

  return { submitAdmission, isSubmitting };
}
