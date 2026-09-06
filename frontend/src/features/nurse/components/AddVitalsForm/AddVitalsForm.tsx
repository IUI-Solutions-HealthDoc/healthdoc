"use client";

import { useEffect } from "react";

import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";

import FormSection from "../../../../components/forms/FormSection";
import DateTimeField from "@/components/forms/DateTimeField";
import NumberField from "../../../../components/forms/NumberField";
import SelectField from "../../../../components/forms/SelectField";
import FormActions from "../../../../components/forms/FormActions";

import { AddVitalsFormProps } from "./AddVitalsForm.types";

import { DEFAULT_VALUES, nowForDateTimeLocal, PAIN_SCORE_OPTIONS } from "./constants";

import { addVitalsSchema, type AddVitalsSchema } from "./validation";

/**
 * An empty number input reports `valueAsNumber` as NaN, not undefined. Passed
 * straight to `z.number().optional()` that is a rejection — every blank
 * optional vital produced "Invalid input" — so a nurse had to fill in weight,
 * height and both blood pressures to record a pulse.
 */
const optionalNumber = {
  setValueAs: (value: string) => (value === "" || value === null ? undefined : Number(value)),
};

export default function AddVitalsForm({
  patientId,
  admissionId,
  encounterId,
  isSubmitting = false,
  onSubmit,
}: AddVitalsFormProps) {
  const {
    register,
    handleSubmit,
    reset,
    setValue,
    formState: { errors },
  } = useForm<AddVitalsSchema>({
    resolver: zodResolver(addVitalsSchema),

    defaultValues: {
      ...DEFAULT_VALUES,
      measured_at: nowForDateTimeLocal(),
      patient_id: patientId,
      admission_id: admissionId,
      encounter_id: encounterId,
    },
  });

  useEffect(() => {
    if (patientId) {
      setValue("patient_id", patientId);
    }
    setValue("admission_id", admissionId);
    setValue("encounter_id", encounterId);
  }, [patientId, admissionId, encounterId, setValue]);

  const handleReset = () => {
    reset({
      ...DEFAULT_VALUES,
      measured_at: nowForDateTimeLocal(),
      patient_id: patientId,
      admission_id: admissionId,
      encounter_id: encounterId,
    });
  };

  const submitHandler = async (data: AddVitalsSchema) => {
    const success = await onSubmit(data);

    if (success) {
      handleReset();
    }
  };

  return (
    <FormSection
      title="Add Patient Vitals"
      description="Record latest vital signs for the selected patient."
    >
      {/* noValidate: the zod schema is the single validation authority. Native
          constraint validation blocks submit without rendering anything the
          user can act on inside the app, which silently defeated every attempt
          to save a reading. */}
      <form onSubmit={handleSubmit(submitHandler)} className="space-y-6" noValidate>
        {errors.admission_id && (
          <p className="text-sm text-danger">{errors.admission_id.message}</p>
        )}

        <div className="grid gap-5 md:grid-cols-2 lg:grid-cols-3">
          {/* The schema has always required `measured_at`, and nothing rendered
              it or set it, so zodResolver rejected every submission and
              handleSubmit never ran — the Save Vitals button did nothing at
              all, silently, because an error on a field with no input has
              nowhere to appear. Exposed rather than stamped server-side for
              the same reason AdmissionForm exposes "Admitted At": vitals
              charted twenty minutes late must record when they were taken,
              not when they were typed. */}
          <DateTimeField
            label="Measured At"
            registration={register("measured_at")}
            error={errors.measured_at}
          />

          <NumberField
            label="Temperature (°C)"
            placeholder="36.8"
            registration={register("temp_c", optionalNumber)}
            error={errors.temp_c}
          />

          <NumberField
            label="Pulse (bpm)"
            placeholder="72"
            registration={register("pulse_bpm", optionalNumber)}
            error={errors.pulse_bpm}
          />

          <NumberField
            label="Respiratory Rate"
            placeholder="18"
            registration={register("resp_rate", optionalNumber)}
            error={errors.resp_rate}
          />

          <NumberField
            label="Systolic BP"
            placeholder="120"
            registration={register("bp_systolic", optionalNumber)}
            error={errors.bp_systolic}
          />

          <NumberField
            label="Diastolic BP"
            placeholder="80"
            registration={register("bp_diastolic", optionalNumber)}
            error={errors.bp_diastolic}
          />

          <NumberField
            label="SpO₂ (%)"
            placeholder="98"
            registration={register("spo2_pct", optionalNumber)}
            error={errors.spo2_pct}
          />

          <NumberField
            label="Weight (kg)"
            placeholder="65"
            registration={register("weight_kg", optionalNumber)}
            error={errors.weight_kg}
          />

          <NumberField
            label="Height (cm)"
            placeholder="170"
            registration={register("height_cm", optionalNumber)}
            error={errors.height_cm}
          />

          <SelectField
            label="Pain Score"
            options={PAIN_SCORE_OPTIONS.map((score) => ({
              label: score.toString(),
              value: score,
            }))}
            registration={register("pain_score", optionalNumber)}
            error={errors.pain_score}
          />
        </div>

        <FormActions
          isSubmitting={isSubmitting}
          submitLabel="Save Vitals"
          resetLabel="Reset"
          onReset={handleReset}
        />
      </form>
    </FormSection>
  );
}
