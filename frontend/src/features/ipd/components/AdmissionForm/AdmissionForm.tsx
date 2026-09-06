"use client";

import { useForm, useWatch } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";

import FormSection from "@/components/forms/FormSection";
import TextField from "@/components/forms/TextField";
import SelectField from "@/components/forms/SelectField";
import DateTimeField from "@/components/forms/DateTimeField";
import TextAreaField from "@/components/forms/TextAreaField";
import FormActions from "@/components/forms/FormActions";

import BedGrid from "@/components/BedGrid";

import { AdmissionFormProps } from "./AdmissionForm.types";
import { DEFAULT_VALUES } from "./constants";
import { addAdmissionSchema, AddAdmissionSchema } from "./validation";

export default function AdmissionForm({
  wards,
  beds,
  isSubmitting = false,
  onSubmit,
}: AdmissionFormProps) {
  const {
    register,
    handleSubmit,
    reset,
    setValue,
    control,
    formState: { errors },
  } = useForm<AddAdmissionSchema>({
    resolver: zodResolver(addAdmissionSchema),
    defaultValues: DEFAULT_VALUES,
  });

  const wardId = useWatch({ control, name: "ward_id" });
  const bedId = useWatch({ control, name: "bed_id" });

  // Reusing BedGrid instead of a separate dropdown component — filtered to
  // vacant beds in the selected ward, since admission can only go to a
  // vacant bed.
  //
  // `occupant` is checked as well as `status`, and it is the one that decides.
  // The backend treats admissions as authoritative and `beds.status` as a
  // mirror it keeps in the same transaction — see reconcile_bed_status(),
  // which exists precisely because the two can drift apart. When they do, this
  // filter used to offer a bed the server knows is occupied, and the admission
  // came back 409 with nothing on screen to explain why.
  const vacantBedsInWard = beds.filter(
    (bed) => bed.ward_id === wardId && bed.status === "vacant" && bed.occupant === null,
  );

  const handleReset = () => reset(DEFAULT_VALUES);

  const submitHandler = async (data: AddAdmissionSchema) => {
    const success = await onSubmit(data);
    if (success) handleReset();
  };

  return (
    <FormSection
      title="Admit Patient"
      description="Create a new IPD admission for this patient."
    >
      <form onSubmit={handleSubmit(submitHandler)} className="space-y-6">
        <div className="grid gap-5 md:grid-cols-2">
          {/* NOTE: this should become a visit-picker (search by patient
              name/UHID) once a visit-lookup source is available; kept as a
              free-text UUID input for now — same limitation as
              AddHandoverForm's "Handed Over To" field. */}
          <TextField
            label="Visit ID"
            placeholder="Visit UUID"
            registration={register("visit_id")}
            error={errors.visit_id}
          />


          <SelectField
            label="Ward"
            options={wards.map((ward) => ({ label: ward.name, value: ward.id }))}
            registration={register("ward_id", {
              onChange: () => setValue("bed_id", ""),
            })}
            error={errors.ward_id}
          />

          <DateTimeField
            label="Admitted At"
            registration={register("admitted_at")}
            error={errors.admitted_at}
          />
        </div>

        <div>
          <p className="mb-2 text-sm font-semibold">Bed</p>

          {!wardId ? (
            <p className="text-sm text-muted-foreground">
              Select a ward first.
            </p>
          ) : (
            <BedGrid
              beds={vacantBedsInWard}
              selectedBedId={bedId}
              onBedClick={(bed) => setValue("bed_id", bed.bed_id)}
            />
          )}

          {errors.bed_id && (
            <p className="mt-2 text-sm text-danger">{errors.bed_id.message}</p>
          )}
        </div>

        <TextAreaField
          label="Reason for Admission (optional)"
          placeholder="Enter reason for admission..."
          rows={3}
          registration={register("reason")}
          error={errors.reason}
        />

        <FormActions
          isSubmitting={isSubmitting}
          submitLabel="Admit Patient"
          resetLabel="Reset"
          onReset={handleReset}
        />
      </form>
    </FormSection>
  );
}
