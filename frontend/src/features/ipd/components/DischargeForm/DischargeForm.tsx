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
import { localDateTimeNow } from "@/lib/dates";
import { useLocale } from "@/lib/i18n";

export default function DischargeForm({
  admissionId,
  notificationPreview,
  isSubmitting = false,
  onSubmit,
}: DischargeFormProps) {
  const { t } = useLocale();
  const [showPreview, setShowPreview] = useState(false);
  // The server's refusal, shown in the form. Discharge used to fail with no
  // message at all (QA 16 Oct 2026).
  const [serverError, setServerError] = useState<{ code?: string; message: string } | null>(null);
  const [acknowledged, setAcknowledged] = useState(false);

  const {
    register,
    handleSubmit,
    reset,
    control,
    formState: { errors },
  } = useForm<AddDischargeSchema>({
    resolver: zodResolver(addDischargeSchema),
    defaultValues: { ...DEFAULT_VALUES, admission_id: admissionId, discharged_at: localDateTimeNow() },
  });
  const dischargedAt = useWatch({ control, name: "discharged_at" });

  const dischargeType = useWatch({ control, name: "discharge_type" }) as DischargeType;
  // Per ADR 0002: billing settlement is a warning, never a hard block —
  // emergency/DAMA/deceased discharges must not be blocked by settlement checks.
  const isEmergencyType =
    dischargeType === "dama" || dischargeType === "deceased";

  const handleReset = () => {
    reset({ ...DEFAULT_VALUES, admission_id: admissionId, discharged_at: localDateTimeNow() });
    setShowPreview(false);
    setServerError(null);
    setAcknowledged(false);
  };

  const submitHandler = async (data: AddDischargeSchema) => {
    if (!showPreview) {
      setShowPreview(true);
      return;
    }

    const outcome = await onSubmit({
      ...data,
      acknowledge_incomplete_checklist: serverError?.code === "checklist_incomplete" ? acknowledged : undefined,
    });
    if (outcome.ok) {
      handleReset();
      return;
    }
    setServerError({ code: outcome.code, message: outcome.message });
    setAcknowledged(false);
  };

  return (
    <FormSection title={t("ipd.dischargeFormTitle")} description={t("ipd.dischargeFormDescription")}>
      <form onSubmit={handleSubmit(submitHandler)} noValidate className="space-y-6">
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

        <div className="space-y-2">
          <label htmlFor="field-follow_up_date" className="text-sm font-medium">
            {t("ipd.followUpDateOptional")}
          </label>
          <input
            id="field-follow_up_date"
            type="date"
            min={dischargedAt ? dischargedAt.slice(0, 10) : undefined}
            aria-invalid={errors.follow_up_date ? true : undefined}
            className="w-full rounded-lg border border-border bg-background px-3 py-2.5 text-sm"
            {...register("follow_up_date")}
          />
          {errors.follow_up_date && <p className="text-xs text-danger">{errors.follow_up_date.message}</p>}
        </div>

        {serverError && (
          <div role="alert" className="space-y-2 rounded-lg border border-danger/40 bg-danger/5 px-4 py-3 text-sm text-danger">
            <p>{serverError.message}</p>
            {serverError.code === "checklist_incomplete" && (
              <label className="flex items-start gap-2 text-foreground">
                <input type="checkbox" className="mt-0.5" checked={acknowledged} onChange={(e) => setAcknowledged(e.target.checked)} />
                <span>{t("ipd.dischargeWithOpenChecklist")}</span>
              </label>
            )}
          </div>
        )}

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
