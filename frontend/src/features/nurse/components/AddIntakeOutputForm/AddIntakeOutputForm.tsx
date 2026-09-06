"use client";

import { useEffect } from "react";

import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";

import FormSection from "../../../../components/forms/FormSection";
import NumberField from "../../../../components/forms/NumberField";
import SelectField from "../../../../components/forms/SelectField";
import DateTimeField from "../../../../components/forms/DateTimeField";
import TextAreaField from "../../../../components/forms/TextAreaField";
import FormActions from "../../../../components/forms/FormActions";

import { AddIntakeOutputFormProps } from "./AddIntakeOutputForm.types";

import { DEFAULT_VALUES, ENTRY_TYPES } from "./constants";

import {
  addIntakeOutputSchema,
  type AddIntakeOutputSchema,
} from "./validation";

export default function AddIntakeOutputForm({
  admissionId,
  isSubmitting = false,
  onSubmit,
}: AddIntakeOutputFormProps) {
  const {
    register,
    handleSubmit,
    reset,
    setValue,
    formState: { errors },
  } = useForm<AddIntakeOutputSchema>({
    resolver: zodResolver(addIntakeOutputSchema),

    defaultValues: {
      ...DEFAULT_VALUES,
      admission_id: admissionId,
    },
  });

  useEffect(() => {
    if (admissionId) {
      setValue("admission_id", admissionId);
    }
  }, [admissionId, setValue]);

  const handleReset = () => {
    reset({
      ...DEFAULT_VALUES,
      admission_id: admissionId,
    });
  };

  const submitHandler = async (data: AddIntakeOutputSchema) => {
    const success = await onSubmit(data);

    if (success) {
      handleReset();
    }
  };

  return (
    <FormSection
      title="Intake / Output Record"
      description="Record a single fluid intake or output entry. Log intake and output as separate entries."
    >
      {/* noValidate for the same reason as AddVitalsForm: zod owns validation,
          and a native bubble the app cannot see is not a usable error. */}
      <form onSubmit={handleSubmit(submitHandler)} className="space-y-6" noValidate>
        <div className="grid gap-5 md:grid-cols-2">
          <SelectField
            label="Entry Type"
            options={ENTRY_TYPES.map((type) => ({
              label: type.label,
              value: type.value,
            }))}
            registration={register("entry_type")}
            error={errors.entry_type}
          />

          <NumberField
            label="Volume (mL)"
            placeholder="500"
            // Same NaN trap as AddVitalsForm: a blank number input reads as
            // NaN, which turns "Volume must be greater than 0" into a bare
            // "Invalid input". volume_ml is required, so blank must reach zod
            // as undefined for it to say so properly.
            registration={register("volume_ml", {
              setValueAs: (value: string) =>
                value === "" || value === null ? undefined : Number(value),
            })}
            error={errors.volume_ml}
          />

          <DateTimeField
            label="Recorded At"
            registration={register("recorded_at")}
            error={errors.recorded_at}
          />
        </div>

        <TextAreaField
          label="Notes (optional)"
          placeholder="Enter additional observations..."
          rows={3}
          registration={register("notes")}
          error={errors.notes}
        />

        <FormActions
          isSubmitting={isSubmitting}
          submitLabel="Save Record"
          resetLabel="Reset"
          onReset={handleReset}
        />
      </form>
    </FormSection>
  );
}
