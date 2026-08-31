"use client";

import { useEffect, useMemo, useState } from "react";

import { useForm, useWatch } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";

import FormSection from "@/components/forms/FormSection";
import SelectField from "@/components/forms/SelectField";
import TextField from "@/components/forms/TextField";
import TextAreaField from "@/components/forms/TextAreaField";
import FormActions from "@/components/forms/FormActions";

import { AddHandoverFormProps } from "./AddHandoverForm.types";
import { DEFAULT_VALUES, SHIFTS } from "./constants";
import { addHandoverSchema, AddHandoverSchema } from "./validation";

export default function AddHandoverForm({
  admissionId,
  isSubmitting = false,
  recipientOptions = [],
}: AddHandoverFormProps) {
  const [useManualUuid, setUseManualUuid] = useState(recipientOptions.length === 0);

  const {
    register,
    reset,
    setValue,
    control,
    formState: { errors },
  } = useForm<AddHandoverSchema>({
    resolver: zodResolver(addHandoverSchema),
    defaultValues: {
      ...DEFAULT_VALUES,
      admission_id: admissionId,
    },
  });

  useEffect(() => {
    setValue("admission_id", admissionId);
  }, [admissionId, setValue]);

  useEffect(() => {
    if (recipientOptions.length === 0) setUseManualUuid(true);
  }, [recipientOptions.length]);

  const selectedRecipient = useWatch({ control, name: "handed_over_to" });

  const pickerOptions = useMemo(
    () => [
      { value: "", label: "Select receiving nurse…" },
      ...recipientOptions,
      { value: "__manual__", label: "Enter user UUID manually…" },
    ],
    [recipientOptions],
  );

  const handleReset = () => {
    reset({
      ...DEFAULT_VALUES,
      admission_id: admissionId,
    });
    setUseManualUuid(recipientOptions.length === 0);
  };

  return (
    <FormSection
      title="Patient Handover"
      description="Shift handover entry is not available in this release."
    >
      <p className="mb-4 rounded-md border border-border bg-muted p-3 text-sm text-muted-foreground">
        Continue using the approved ward handover process for this release.
      </p>
      <form
        onSubmit={(e) => e.preventDefault()}
        className="pointer-events-none space-y-6 opacity-50"
      >
        <div className="grid gap-5 md:grid-cols-2">
          <SelectField
            label="Shift"
            options={SHIFTS.map((shift) => ({
              label: shift.charAt(0).toUpperCase() + shift.slice(1),
              value: shift,
            }))}
            registration={register("shift")}
            error={errors.shift}
          />

          {recipientOptions.length > 0 && !useManualUuid ? (
            <div className="space-y-2">
              <SelectField
                label="Handed over to"
                options={pickerOptions}
                registration={register("handed_over_to", {
                  onChange: (event) => {
                    const value = (event.target as HTMLSelectElement).value;
                    if (value === "__manual__") {
                      setUseManualUuid(true);
                      setValue("handed_over_to", "");
                    }
                  },
                })}
                error={errors.handed_over_to}
              />
              {selectedRecipient && selectedRecipient !== "__manual__" ? (
                <p className="text-xs text-muted-foreground font-mono">{selectedRecipient}</p>
              ) : null}
            </div>
          ) : (
            <div className="space-y-2">
              <TextField
                label="Handed over to (user UUID)"
                placeholder="Receiving nurse users.id"
                registration={register("handed_over_to")}
                error={errors.handed_over_to}
              />
            </div>
          )}
        </div>

        <TextAreaField
          label="Situation"
          placeholder="Current situation / reason for handover..."
          rows={3}
          registration={register("situation")}
          error={errors.situation}
        />

        <TextAreaField
          label="Background"
          placeholder="Relevant patient background / history..."
          rows={3}
          registration={register("background")}
          error={errors.background}
        />

        <TextAreaField
          label="Assessment"
          placeholder="Current clinical assessment..."
          rows={3}
          registration={register("assessment")}
          error={errors.assessment}
        />

        <TextAreaField
          label="Recommendation"
          placeholder="Recommended next steps / things to watch..."
          rows={3}
          registration={register("recommendation")}
          error={errors.recommendation}
        />

        <FormActions
          isSubmitting={isSubmitting}
          submitLabel="Complete Handover"
          resetLabel="Reset"
          onReset={handleReset}
        />
      </form>
    </FormSection>
  );
}
