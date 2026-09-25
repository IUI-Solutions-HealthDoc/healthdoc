"use client";

import { useState, useEffect } from "react";
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
import { getPendingAdmissions, type PendingAdmissionItem } from "@/features/ipd/api/ipd";
import { useLocale } from "@/lib/i18n";

export default function AdmissionForm({
  wards,
  beds,
  isSubmitting = false,
  onSubmit,
}: AdmissionFormProps) {
  const { localizeField } = useLocale();
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

  const [pendingList, setPendingList] = useState<PendingAdmissionItem[]>([]);
  const [selectedPendingId, setSelectedPendingId] = useState<string | null>(null);
  const [_loadingPending, setLoadingPending] = useState<boolean>(false);

  useEffect(() => {
    let active = true;
    setLoadingPending(true);
    getPendingAdmissions()
      .then((data) => {
        if (active) setPendingList(data || []);
      })
      .catch((err) => console.error("Failed to fetch pending admissions:", err))
      .finally(() => {
        if (active) setLoadingPending(false);
      });
    return () => {
      active = false;
    };
  }, []);

  const wardId = useWatch({ control, name: "ward_id" });
  const bedId = useWatch({ control, name: "bed_id" });

  const vacantBedsInWard = beds.filter(
    (bed) => bed.ward_id === wardId && bed.status === "vacant" && bed.occupant === null,
  );

  const handleReset = () => {
    reset(DEFAULT_VALUES);
    setSelectedPendingId(null);
  };

  const handleSelectPending = (item: PendingAdmissionItem) => {
    setSelectedPendingId(item.disposition_id);
    setValue("visit_id", item.visit_id);
    if (item.recommended_ward_id && wards.some((w) => w.id === item.recommended_ward_id)) {
      setValue("ward_id", item.recommended_ward_id);
    }
    if (item.reason) {
      setValue("reason", item.reason);
    }
  };

  const submitHandler = async (data: AddAdmissionSchema) => {
    const success = await onSubmit(data);
    if (success) {
      handleReset();
      // Refresh pending list
      getPendingAdmissions().then((data) => setPendingList(data || []));
    }
  };

  return (
    <FormSection
      title="Admit Patient"
      description="Create a new IPD admission for this patient."
    >
      {/* HD-14: 1-Click Admit from Doctor Ordered Disposition Queue */}
      {pendingList.length > 0 && (
        <div className="mb-6 rounded-xl border border-blue-200 bg-blue-50/60 p-4">
          <div className="flex items-center justify-between mb-3">
            <h4 className="text-sm font-bold text-blue-950">
              Quick Admit from &ldquo;To Admit&rdquo; Queue ({pendingList.length} waiting)
            </h4>
            <span className="text-xs text-blue-700">Click to auto-fill details</span>
          </div>
          <div className="grid gap-2.5 sm:grid-cols-2 lg:grid-cols-3">
            {pendingList.map((item) => {
              const isSelected = selectedPendingId === item.disposition_id;
              const isEmergency = item.priority === "emergency";
              const isUrgent = item.priority === "urgent";

              return (
                <button
                  key={item.disposition_id}
                  type="button"
                  onClick={() => handleSelectPending(item)}
                  className={`rounded-lg border p-3 text-left transition-all ${
                    isSelected
                      ? "border-blue-600 bg-white shadow-md ring-2 ring-blue-500"
                      : "border-blue-200/80 bg-white/90 hover:border-blue-400 hover:bg-white"
                  }`}
                >
                  <div className="flex items-start justify-between gap-2">
                    <span className="font-semibold text-sm text-slate-900 line-clamp-1">
                      {item.patient_name}
                    </span>
                    <span
                      className={`inline-block rounded px-1.5 py-0.5 text-[10px] font-bold uppercase ${
                        isEmergency
                          ? "bg-red-100 text-red-700 animate-pulse"
                          : isUrgent
                          ? "bg-amber-100 text-amber-800"
                          : "bg-blue-100 text-blue-800"
                      }`}
                    >
                      {item.priority}
                    </span>
                  </div>
                  <div className="mt-1 text-xs text-slate-600">
                    UHID: {item.patient_uhid} · {item.patient_sex || ""}
                  </div>
                  {item.recommended_ward_name && (
                    <div className="mt-1 text-xs font-medium text-blue-700">
                      Rec: {item.recommended_ward_name}
                    </div>
                  )}
                  {item.reason && (
                    <div className="mt-1 text-[11px] text-slate-500 line-clamp-1">
                      {item.reason}
                    </div>
                  )}
                </button>
              );
            })}
          </div>
        </div>
      )}

      <form onSubmit={handleSubmit(submitHandler)} className="space-y-6">
        <div className="grid gap-5 md:grid-cols-2">
          <TextField
            label="Visit ID"
            placeholder="Select from queue above or paste Visit UUID"
            registration={register("visit_id")}
            error={errors.visit_id}
          />


          <SelectField
            label="Ward"
            options={wards.map((ward) => ({
              label: localizeField(ward.name, ward.name_hi),
              value: ward.id,
            }))}
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
