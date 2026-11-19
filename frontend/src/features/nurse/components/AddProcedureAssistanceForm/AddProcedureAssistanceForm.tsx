"use client";

import { useEffect } from "react";

import { useForm, useWatch } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";

import FormSection from "../../../../components/forms/FormSection";
import TextField from "../../../../components/forms/TextField";
import SelectField from "../../../../components/forms/SelectField";
import DateTimeField from "../../../../components/forms/DateTimeField";
import TextAreaField from "../../../../components/forms/TextAreaField";
import FormActions from "../../../../components/forms/FormActions";

import { AddProcedureAssistanceFormProps } from "./AddProcedureAssistance.types";
import { DEFAULT_VALUES, SETTINGS } from "./constants";
import {
  addProcedureAssistanceSchema,
  AddProcedureAssistanceSchema,
} from "./validation";
import { useLocale } from "@/lib/i18n";

export default function AddProcedureAssistanceForm({
  encounterId,
  patientId,
  assistedBy,
  isSubmitting = false,
}: AddProcedureAssistanceFormProps) {
  const { t } = useLocale();
  const {
    register,
    reset,
    setValue,
    control,
    formState: { errors },
  } = useForm<AddProcedureAssistanceSchema>({
    resolver: zodResolver(addProcedureAssistanceSchema),

    defaultValues: {
      ...DEFAULT_VALUES,
      encounter_id: encounterId,
      patient_id: patientId,
      assisted_by: assistedBy,
    },
  });

  useEffect(() => {
    setValue("encounter_id", encounterId);
    setValue("patient_id", patientId);
    setValue("assisted_by", assistedBy);
  }, [encounterId, patientId, assistedBy, setValue]);

  const setting = useWatch({ control, name: "setting" });

  const handleReset = () => {
    reset({
      ...DEFAULT_VALUES,
      encounter_id: encounterId,
      patient_id: patientId,
      assisted_by: assistedBy,
    });
  };

  return (
    <FormSection
      title={t("nurse.ui.procedureAssistance")}
      description={t("nurse.ui.procedureAssistanceEntryIsNotAvailable")}
    >
      <p className="mb-4 rounded-md border border-border bg-muted p-3 text-sm text-muted-foreground">{t("nurse.ui.useTheDoctorSProcedureOrder")}</p>
      <form onSubmit={(e) => e.preventDefault()} className="pointer-events-none space-y-6 opacity-50">
        <div className="grid gap-5 md:grid-cols-2">
          <TextField
            label={t("nurse.ui.procedureName")}
            placeholder={t("nurse.ui.woundDressingCatheterizationEtc")}
            registration={register("procedure_name")}
            error={errors.procedure_name}
          />

          <SelectField
            label={t("nurse.ui.setting")}
            options={SETTINGS.map((s) => ({ label: s.label, value: s.value }))}
            registration={register("setting")}
            error={errors.setting}
          />

          <TextField
            label={t("nurse.ui.performedByDoctorId")}
            placeholder={t("nurse.ui.doctorSUserUuid")}
            registration={register("performed_by")}
            error={errors.performed_by}
          />

          {setting === "ot" && (
            <TextField
              label={t("nurse.ui.otScheduleId")}
              placeholder={t("nurse.ui.onlyApplicableForOperationTheatreSetting")}
              registration={register("ot_schedule_id")}
              error={errors.ot_schedule_id}
            />
          )}

          <DateTimeField
            label={t("nurse.ui.startedAt")}
            registration={register("started_at")}
            error={errors.started_at}
          />

          <DateTimeField
            label={t("nurse.ui.endedAtOptional")}
            registration={register("ended_at")}
            error={errors.ended_at}
          />

          <TextField
            label={t("nurse.ui.procedureCodeOptional")}
            placeholder={t("nurse.ui.icd11SnomedCode")}
            registration={register("procedure_code")}
            error={errors.procedure_code}
          />

      
          <TextField
            label={t("nurse.ui.codeSystemOptional")}
            placeholder={t("nurse.ui.icd11SnomedCtEtc")}
            registration={register("code_system")}
            error={errors.code_system}
          />
        </div>

        <TextAreaField
          label={t("nurse.ui.outcomeOptional")}
          placeholder={t("nurse.ui.procedureOutcome")}
          rows={2}
          registration={register("outcome")}
          error={errors.outcome}
        />

        <TextAreaField
          label={t("nurse.ui.complicationsOptional")}
          placeholder={t("nurse.ui.anyComplicationsDuringTheProcedure")}
          rows={2}
          registration={register("complications")}
          error={errors.complications}
        />

        <FormActions
          isSubmitting={isSubmitting}
          submitLabel={t("nurse.ui.saveProcedureRecord")}
          resetLabel="Reset"
          onReset={handleReset}
        />
      </form>
    </FormSection>
  );
}
