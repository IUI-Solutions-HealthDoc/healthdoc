"use client";

import { useForm, useWatch } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";

import FormSection from "../forms/FormSection";
import SelectField from "../forms/SelectField";
import TextAreaField from "../forms/TextAreaField";
import FormActions from "../forms/FormActions";

import { AddPatientMovementFormProps } from "./AddPatientMovementForm.types";
import { DEFAULT_VALUES } from "./constants";
import {
  addPatientMovementSchema,
  AddPatientMovementSchema,
} from "./validation";
import { useLocale } from "@/lib/i18n";

export default function AddPatientMovementForm({
  admissionId,
  wards,
  beds,
  isSubmitting = false,
  onSubmit,
}: AddPatientMovementFormProps) {
  const { localizeField } = useLocale();
  const {
    register,
    handleSubmit,
    reset,
    setValue,
    control,
    formState: { errors },
  } = useForm<AddPatientMovementSchema>({
    resolver: zodResolver(addPatientMovementSchema),

    defaultValues: {
      ...DEFAULT_VALUES,
      admission_id: admissionId,
    },
  });

  const toWardId = useWatch({ control, name: "to_ward_id" });

  // Only vacant beds in the selected destination ward are selectable.
  const destinationBeds = beds.filter(
    (bed) => bed.ward_id === toWardId && bed.status === "vacant"
  );

  const handleReset = () => {
    reset({
      ...DEFAULT_VALUES,
      admission_id: admissionId,
    });
  };

  const submitHandler = async (data: AddPatientMovementSchema) => {
    const success = await onSubmit(data);

    if (success) {
      handleReset();
    }
  };

  return (
    <FormSection
      title="In-hospital ward / bed transfer"
      description="Records a patient_movement_log inside this facility. This is not a discharge with type transferred (leaving for another facility)."
    >
      <form onSubmit={handleSubmit(submitHandler)} className="space-y-6">
        <div className="grid gap-5 md:grid-cols-2">
          <SelectField
            label="Destination Ward"
            options={wards.map((ward) => ({
              label: localizeField(ward.name, ward.name_hi),
              value: ward.id,
            }))}
            registration={register("to_ward_id", {
              onChange: () => setValue("to_bed_id", ""),
            })}
            error={errors.to_ward_id}
          />

          {destinationBeds.length === 0 ? (
            <p className="self-end text-sm text-muted-foreground">
              No vacant beds in this ward.
            </p>
          ) : (
            <SelectField
              label="Destination Bed"
              options={destinationBeds.map((bed) => ({
                label: bed.bed_number,
                value: bed.bed_id,
              }))}
              registration={register("to_bed_id")}
              error={errors.to_bed_id}
            />
          )}

        </div>

        <TextAreaField
          label="Reason for Movement"
          placeholder="Enter reason for patient transfer..."
          rows={4}
          registration={register("reason")}
          error={errors.reason}
        />

        <FormActions
          isSubmitting={isSubmitting}
          submitLabel="Record Movement"
          resetLabel="Reset"
          onReset={handleReset}
        />
      </form>
    </FormSection>
  );
}
