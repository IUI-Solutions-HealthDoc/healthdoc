"use client";

import { useState, useEffect } from "react";
import { useForm, useWatch } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";

import FormSection from "@/components/forms/FormSection";
import SelectField from "@/components/forms/SelectField";
import DateTimeField from "@/components/forms/DateTimeField";
import TextAreaField from "@/components/forms/TextAreaField";
import FormActions from "@/components/forms/FormActions";

import BedGrid from "@/components/BedGrid";

import { AdmissionFormProps } from "./AdmissionForm.types";
import { DEFAULT_VALUES } from "./constants";
import { addAdmissionSchema, AddAdmissionSchema } from "./validation";
import {
  findAdmittableVisits,
  getPendingAdmissions,
  type AdmittableVisit,
  type PendingAdmissionItem,
} from "@/features/ipd/api/ipd";
import { getUserFacingError } from "@/lib/api";
import { localDateTimeNow } from "@/lib/dates";
import { formatAgeSexShort } from "@/lib/format-age";
import { useLocale } from "@/lib/i18n";

/** Who is being admitted, shown instead of a visit UUID. */
interface ChosenPatient {
  visit_id: string;
  name: string;
  identifier: string | null;
  visit_number: string | null;
  age: number | null;
  sex: string | null;
}

export default function AdmissionForm({
  wards,
  beds,
  isSubmitting = false,
  onSubmit,
  initialDispositionId,
}: AdmissionFormProps) {
  const { t, localizeField } = useLocale();
  const {
    register,
    handleSubmit,
    reset,
    setValue,
    control,
    formState: { errors },
  } = useForm<AddAdmissionSchema>({
    resolver: zodResolver(addAdmissionSchema),
    defaultValues: { ...DEFAULT_VALUES, admitted_at: localDateTimeNow() },
  });
  const [chosen, setChosen] = useState<ChosenPatient | null>(null);
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<AdmittableVisit[] | null>(null);
  const [searchError, setSearchError] = useState<string | null>(null);
  const [searching, setSearching] = useState(false);

  async function runSearch() {
    if (query.trim().length < 2) {
      setSearchError(t("ipd.searchMinChars"));
      return;
    }
    setSearching(true);
    setSearchError(null);
    try {
      setResults(await findAdmittableVisits(query));
    } catch (err) {
      setResults(null);
      setSearchError(getUserFacingError(err, t("ipd.errSearchVisits")));
    } finally {
      setSearching(false);
    }
  }

  function choose(patient: ChosenPatient) {
    setChosen(patient);
    setValue("visit_id", patient.visit_id, { shouldValidate: true });
    setResults(null);
    setQuery("");
  }

  const [pendingList, setPendingList] = useState<PendingAdmissionItem[]>([]);
  const [selectedPendingId, setSelectedPendingId] = useState<string | null>(null);
  const [_loadingPending, setLoadingPending] = useState<boolean>(false);



  const wardId = useWatch({ control, name: "ward_id" });
  const bedId = useWatch({ control, name: "bed_id" });

  const vacantBedsInWard = beds.filter(
    (bed) => bed.ward_id === wardId && bed.status === "vacant" && bed.occupant === null,
  );

  const handleReset = () => {
    reset({ ...DEFAULT_VALUES, admitted_at: localDateTimeNow() });
    setSelectedPendingId(null);
    setChosen(null);
    setResults(null);
  };

  const handleSelectPending = (item: PendingAdmissionItem) => {
    setSelectedPendingId(item.disposition_id);
    choose({
      visit_id: item.visit_id,
      name: item.patient_name,
      identifier: item.patient_uhid,
      visit_number: item.visit_number ?? null,
      age: item.patient_age ?? null,
      sex: item.patient_sex ?? null,
    });
    if (item.recommended_ward_id && wards.some((w) => w.id === item.recommended_ward_id)) {
      setValue("ward_id", item.recommended_ward_id);
    }
    if (item.reason) {
      setValue("reason", item.reason);
    }
  };

  useEffect(() => {
    let active = true;
    setLoadingPending(true);
    getPendingAdmissions()
      .then((data) => {
        if (!active) return;
        setPendingList(data || []);
        // "Admit to Bed" on the To Admit queue opens this form for that patient.
        const wanted = initialDispositionId ? (data || []).find((d) => d.disposition_id === initialDispositionId) : null;
        if (wanted) handleSelectPending(wanted);
      })
      .catch((err) => console.error("Failed to fetch pending admissions:", err))
      .finally(() => {
        if (active) setLoadingPending(false);
      });
    return () => {
      active = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- run once per mount and requested disposition
  }, [initialDispositionId]);

  const submitHandler = async (data: AddAdmissionSchema) => {
    const success = await onSubmit(data);
    if (success) {
      handleReset();
      // Refresh pending list
      getPendingAdmissions().then((data) => setPendingList(data || []));
    }
  };

  return (
    <FormSection title={t("ipd.admitFormTitle")} description={t("ipd.admitFormDescription")}>
      {/* HD-14: 1-Click Admit from Doctor Ordered Disposition Queue */}
      {pendingList.length > 0 && (
        <div className="mb-6 rounded-xl border border-blue-200 bg-blue-50/60 p-4">
          <div className="flex items-center justify-between mb-3">
            <h4 className="text-sm font-bold text-blue-950">
              {t("ipd.quickAdmitQueue", { count: pendingList.length })}
            </h4>
            <span className="text-xs text-blue-700">{t("ipd.clickAutofill")}</span>
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
                    {item.patient_uhid} · {formatAgeSexShort(item.patient_age ?? null, item.patient_sex ?? "unknown")}
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

      <form onSubmit={handleSubmit(submitHandler)} noValidate className="space-y-6">
        <input type="hidden" {...register("visit_id")} />
        <div className="space-y-2">
          <p className="text-sm font-medium">{t("ipd.patientToAdmit")}</p>
          {chosen ? (
            <div className="flex items-start justify-between gap-3 rounded-lg border border-primary/40 bg-primary/5 p-3">
              <div>
                <p className="font-semibold">{chosen.name}</p>
                <p className="text-xs text-muted-foreground">
                  {[chosen.identifier, formatAgeSexShort(chosen.age, chosen.sex ?? "unknown"), chosen.visit_number]
                    .filter(Boolean)
                    .join(" · ")}
                </p>
              </div>
              <button
                type="button"
                className="text-xs font-medium text-primary underline"
                onClick={() => {
                  setChosen(null);
                  setSelectedPendingId(null);
                  setValue("visit_id", "");
                }}
              >
                {t("common.changePatient")}
              </button>
            </div>
          ) : (
            <div className="space-y-2">
              <div className="flex gap-2">
                <input
                  type="search"
                  aria-label={t("ipd.searchVisitsLabel")}
                  aria-invalid={errors.visit_id ? true : undefined}
                  placeholder={t("ipd.searchVisitsPlaceholder")}
                  className="w-full rounded-lg border border-border bg-background px-3 py-2.5 text-sm"
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") {
                      e.preventDefault();
                      void runSearch();
                    }
                  }}
                />
                <button
                  type="button"
                  onClick={() => void runSearch()}
                  disabled={searching}
                  className="rounded-lg border border-border px-3 py-2 text-sm font-medium hover:bg-muted disabled:opacity-50"
                >
                  {searching ? t("common.loading") : t("common.search")}
                </button>
              </div>
              {searchError && <p role="alert" className="text-xs text-danger">{searchError}</p>}
              {errors.visit_id && !searchError && <p className="text-xs text-danger">{errors.visit_id.message}</p>}
              {results && results.length === 0 && (
                <p className="text-xs text-muted-foreground">{t("ipd.noAdmittableVisits")}</p>
              )}
              {results && results.length > 0 && (
                <ul className="divide-y rounded-lg border border-border">
                  {results.map((r) => (
                    <li key={r.visit_id}>
                      <button
                        type="button"
                        className="w-full px-3 py-2 text-left text-sm hover:bg-muted"
                        onClick={() =>
                          choose({
                            visit_id: r.visit_id,
                            name: r.patient_name,
                            identifier: r.patient_identifier,
                            visit_number: r.visit_number,
                            age: r.patient_age,
                            sex: r.patient_sex,
                          })
                        }
                      >
                        <span className="font-medium">{r.patient_name}</span>
                        <span className="ml-2 text-xs text-muted-foreground">
                          {[r.patient_identifier, formatAgeSexShort(r.patient_age, r.patient_sex ?? "unknown"), r.visit_number, r.visit_type.toUpperCase()]
                            .filter(Boolean)
                            .join(" · ")}
                        </span>
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          )}
        </div>

        <div className="grid gap-5 md:grid-cols-2">


          <SelectField
            label={t("ipd.ward")}
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
            label={t("ipd.admittedAt")}
            registration={register("admitted_at")}
            error={errors.admitted_at}
          />
        </div>

        <div>
          <p className="mb-2 text-sm font-semibold">{t("ipd.bed")}</p>

          {!wardId ? (
            <p className="text-sm text-muted-foreground">{t("ipd.selectWardFirst")}</p>
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
          label={t("ipd.reasonAdmissionOptional")}
          placeholder={t("ipd.reasonAdmissionPlaceholder")}
          rows={3}
          registration={register("reason")}
          error={errors.reason}
        />

        <FormActions
          isSubmitting={isSubmitting}
          submitLabel={t("ipd.admitPatient")}
          resetLabel={t("common.reset")}
          onReset={handleReset}
        />
      </form>
    </FormSection>
  );
}
