"use client";

import { useState } from "react";

import { useForm, useWatch } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";

import FormSection from "@/components/forms/FormSection";
import SelectField from "@/components/forms/SelectField";
import DateTimeField from "@/components/forms/DateTimeField";
import TextAreaField from "@/components/forms/TextAreaField";
import FormActions from "@/components/forms/FormActions";
import TextField from "@/components/forms/TextField";

import { DischargeFormProps } from "./DischargeForm.types";
import { DEFAULT_VALUES, DISCHARGE_TYPE_LABELS, MODULE_LABELS } from "./constants";
import {
  addDischargeSchema,
  AddDischargeSchema,
  DISCHARGE_TYPES,
  DischargeType,
} from "./validation";
import { useLocale } from "@/lib/i18n";

export default function DischargeForm({
  admissionId,
  notificationPreview,
  isSubmitting = false,
  onSubmit,
}: DischargeFormProps) {
  const { t } = useLocale();
  const [showPreview, setShowPreview] = useState(false);

  const {
    register,
    handleSubmit,
    reset,
    control,
    formState: { errors },
  } = useForm<AddDischargeSchema>({
    resolver: zodResolver(addDischargeSchema),
    defaultValues: { ...DEFAULT_VALUES, admission_id: admissionId },
  });

  const dischargeType = useWatch({ control, name: "discharge_type" }) as DischargeType;
  // Per ADR 0002: billing settlement is a warning, never a hard block —
  // emergency/DAMA/deceased discharges must not be blocked by settlement checks.
  const isEmergencyType =
    dischargeType === "dama" || dischargeType === "deceased";

  const handleReset = () => {
    reset({ ...DEFAULT_VALUES, admission_id: admissionId });
    setShowPreview(false);
  };

  const submitHandler = async (data: AddDischargeSchema) => {
    if (!showPreview) {
      setShowPreview(true);
      return;
    }

    const success = await onSubmit(data);
    if (success) handleReset();
  };

  return (
    <FormSection title={t("ipd.dischargeFormTitle")} description={t("ipd.dischargeFormDescription")}>
      <form onSubmit={handleSubmit(submitHandler)} className="space-y-6">
        <SelectField
          label={t("ipd.dischargeType")}
          options={DISCHARGE_TYPES.map((type) => ({
            label: DISCHARGE_TYPE_LABELS[type],
            value: type,
          }))}
          registration={register("discharge_type")}
          error={errors.discharge_type}
        />

        {isEmergencyType && (
          <div className="rounded-lg border border-warning bg-warning-muted px-4 py-3 text-sm text-warning">
            {t("ipd.dischargeEmergencyWarning")}
          </div>
        )}

     {dischargeType === "transferred" && (
  <>
    <div className="rounded-lg border border-border bg-muted px-4 py-3 text-sm text-muted-foreground">
      {t("ipd.dischargeTransferHint")}
    </div>

    <TextField
      label={t("ipd.destinationFacilityName")}
      placeholder={t("ipd.destinationFacilityPlaceholder")}
      registration={register("destination_facility_name")}
      error={errors.destination_facility_name}
    />
  </>
)}

        <DateTimeField
          label={t("ipd.dischargedAt")}
          registration={register("discharged_at")}
          error={errors.discharged_at}
        />

        <TextAreaField
          label={t("ipd.dischargeSummary")}
          placeholder={t("ipd.dischargeSummaryPlaceholder")}
          rows={4}
          registration={register("discharge_summary")}
          error={errors.discharge_summary}
        />

        <DateTimeField
          label={t("ipd.followUpDateOptional")}
          registration={register("follow_up_date")}
          error={errors.follow_up_date}
        />

        {showPreview && (
          <div className="surface-muted space-y-2 p-4">
            <h3 className="text-sm font-semibold">
              {t("ipd.dischargePreviewHeading")}
            </h3>

            <ul className="space-y-1 text-sm">
              {notificationPreview.map((n) => (
                <li
                  key={n.target_module}
                  className="flex items-center justify-between"
                >
                  <span>{MODULE_LABELS[n.target_module] ?? n.target_module}</span>
                  <span className="text-xs capitalize text-muted-foreground">
                    {n.status}
                  </span>
                </li>
              ))}
            </ul>
          </div>
        )}

        <FormActions
          isSubmitting={isSubmitting}
          submitLabel={showPreview ? t("ipd.confirmDischarge") : t("ipd.previewDischarge")}
          resetLabel={t("common.reset")}
          onReset={handleReset}
        />
      </form>
    </FormSection>
  );
}
