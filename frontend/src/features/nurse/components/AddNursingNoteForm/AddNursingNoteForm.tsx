"use client";

import { useEffect } from "react";

import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";

import FormSection from "../../../../components/forms/FormSection";
import SelectField from "../../../../components/forms/SelectField";
import TextAreaField from "../../../../components/forms/TextAreaField";
import FormActions from "../../../../components/forms/FormActions";

import { AddNursingNoteFormProps } from "./AddNursingNoteForm.types";

import { DEFAULT_VALUES, NOTE_CATEGORIES, PRIORITIES } from "./constants";

import {
  addNursingNoteSchema,
  type AddNursingNoteSchema,
} from "./validation";
import { useLocale } from "@/lib/i18n";

export default function AddNursingNoteForm({
  encounterId,
  patientId,
  isSubmitting = false,
}: AddNursingNoteFormProps) {
  const { t } = useLocale();
  const {
    register,
    reset,
    setValue,
    formState: { errors },
  } = useForm<AddNursingNoteSchema>({
    resolver: zodResolver(addNursingNoteSchema),

    defaultValues: {
      ...DEFAULT_VALUES,
      encounter_id: encounterId,
      patient_id: patientId,
    },
  });

  useEffect(() => {
    setValue("encounter_id", encounterId);
    setValue("patient_id", patientId);
  }, [encounterId, patientId, setValue]);

  const handleReset = () => {
    reset({
      ...DEFAULT_VALUES,
      encounter_id: encounterId,
      patient_id: patientId,
    });
  };

  return (
    <FormSection
      title={t("nurse.ui.addNursingNote")}
      description={t("nurse.ui.nursingNotesAreNotAvailableIn")}
    >
      <p className="mb-4 rounded-md border border-border bg-muted p-3 text-sm text-muted-foreground">{t("nurse.ui.useTheApprovedPatientRecordWorkflow")}</p>
      <form onSubmit={(e) => e.preventDefault()} className="pointer-events-none space-y-6 opacity-50">
        <div className="grid gap-5 md:grid-cols-2">
          <SelectField
            label={t("billing.lineItems.col.category")}
            options={NOTE_CATEGORIES.map((category) => ({
              label: category,
              value: category,
            }))}
            registration={register("category")}
            error={errors.category}
          />

          <SelectField
            label={t("receptionist.priority")}
            options={PRIORITIES.map((priority) => ({
              label: priority,
              value: priority,
            }))}
            registration={register("priority")}
            error={errors.priority}
          />
        </div>

        <TextAreaField
          label={t("nurse.actionNursingNote")}
          placeholder={t("nurse.ui.enterNursingObservationsInterventionsOrPatient")}
          rows={6}
          registration={register("note")}
          error={errors.note}
        />

        <FormActions
          isSubmitting={isSubmitting}
          submitLabel={t("nurse.ui.saveNote")}
          resetLabel="Reset"
          onReset={handleReset}
        />
      </form>
    </FormSection>
  );
}
