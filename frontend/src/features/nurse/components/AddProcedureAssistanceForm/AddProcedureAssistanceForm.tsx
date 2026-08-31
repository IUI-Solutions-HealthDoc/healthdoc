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

export default function AddProcedureAssistanceForm({
  encounterId,
  patientId,
  assistedBy,
  isSubmitting = false,
}: AddProcedureAssistanceFormProps) {
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
      title="Procedure Assistance"
      description="Procedure-assistance entry is not available in this release."
    >
      <p className="mb-4 rounded-md border border-border bg-muted p-3 text-sm text-muted-foreground">
        Use the doctor&apos;s procedure order for bedside documentation.
      </p>
      <form onSubmit={(e) => e.preventDefault()} className="pointer-events-none space-y-6 opacity-50">
        <div className="grid gap-5 md:grid-cols-2">
          <TextField
            label="Procedure Name"
            placeholder="Wound dressing, catheterization, etc."
            registration={register("procedure_name")}
            error={errors.procedure_name}
          />

          <SelectField
            label="Setting"
            options={SETTINGS.map((s) => ({ label: s.label, value: s.value }))}
            registration={register("setting")}
            error={errors.setting}
          />

          <TextField
            label="Performed By (Doctor ID)"
            placeholder="Doctor's user UUID"
            registration={register("performed_by")}
            error={errors.performed_by}
          />

          {setting === "ot" && (
            <TextField
              label="OT Schedule ID"
              placeholder="Only applicable for Operation Theatre setting"
              registration={register("ot_schedule_id")}
              error={errors.ot_schedule_id}
            />
          )}

          <DateTimeField
            label="Started At"
            registration={register("started_at")}
            error={errors.started_at}
          />

          <DateTimeField
            label="Ended At (optional)"
            registration={register("ended_at")}
            error={errors.ended_at}
          />

          <TextField
            label="Procedure Code (optional)"
            placeholder="ICD-11 / SNOMED code"
            registration={register("procedure_code")}
            error={errors.procedure_code}
          />

      
          <TextField
            label="Code System (optional)"
            placeholder="ICD-11, SNOMED-CT, etc."
            registration={register("code_system")}
            error={errors.code_system}
          />
        </div>

        <TextAreaField
          label="Outcome (optional)"
          placeholder="Procedure outcome..."
          rows={2}
          registration={register("outcome")}
          error={errors.outcome}
        />

        <TextAreaField
          label="Complications (optional)"
          placeholder="Any complications during the procedure..."
          rows={2}
          registration={register("complications")}
          error={errors.complications}
        />

        <FormActions
          isSubmitting={isSubmitting}
          submitLabel="Save Procedure Record"
          resetLabel="Reset"
          onReset={handleReset}
        />
      </form>
    </FormSection>
  );
}
