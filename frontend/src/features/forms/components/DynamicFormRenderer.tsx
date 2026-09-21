"use client";

import { useEffect, useRef, useState } from "react";
import { AlertCircle, CheckCircle2, FileText, Send } from "lucide-react";
import { submitForm } from "../api";
import type { FormDefinition, FormSubmission } from "../types";

interface DynamicFormRendererProps {
  formDef: FormDefinition;
  patientId: string;
  visitId?: string | null;
  onSuccess: (submission: FormSubmission) => void;
}

export function DynamicFormRenderer(props: DynamicFormRendererProps) {
  return <FormEditor key={`${props.patientId}:${props.visitId ?? ""}:${props.formDef.id}:${props.formDef.version}`} {...props} />;
}

function FormEditor({
  formDef,
  patientId,
  visitId,
  onSuccess,
}: DynamicFormRendererProps) {
  const [formData, setFormData] = useState<Record<string, unknown>>({});
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);
  const mounted = useRef(false);
  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; };
  }, []);

  const handleFieldChange = (fieldId: string, value: unknown) => {
    setFormData((prev) => ({ ...prev, [fieldId]: value }));
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setSuccessMsg(null);

    // Validate required fields
    for (const field of formDef.fields_schema) {
      if (field.required && (formData[field.id] === undefined || formData[field.id] === "")) {
        setError(`Field "${field.label}" is required.`);
        return;
      }
    }

    try {
      setIsSubmitting(true);
      const sub = await submitForm({
        patient_id: patientId,
        visit_id: visitId || null,
        form_id: formDef.id,
        form_data: formData,
      });
      if (!mounted.current) return;
      if (sub.patient_id !== patientId || sub.form_id !== formDef.id)
        throw new Error("The saved form does not match the selected patient and form.");
      setSuccessMsg("Clinical form submitted and recorded successfully!");
      setFormData({});
      onSuccess(sub);
    } catch (err: unknown) {
      if (mounted.current) setError(err instanceof Error ? err.message : "Failed to submit form responses.");
    } finally {
      if (mounted.current) setIsSubmitting(false);
    }
  };

  return (
    <div className="rounded-2xl border border-border bg-card p-6 shadow-sm space-y-6">
      <div className="border-b border-border pb-4 flex items-center justify-between">
        <div>
          <div className="flex items-center gap-2">
            <FileText className="h-5 w-5 text-primary" />
            <h3 className="text-lg font-bold text-foreground">{formDef.title}</h3>
          </div>
          <p className="text-xs text-muted-foreground mt-0.5 font-mono">
            Code: {formDef.code} • v{formDef.version}
          </p>
        </div>
        <span className="rounded-full bg-primary/10 px-2.5 py-1 text-xs font-semibold text-primary capitalize">
          {formDef.status}
        </span>
      </div>

      {error && (
        <div className="flex items-center gap-2 rounded-xl bg-destructive/10 p-3 text-xs text-destructive border border-destructive/20">
          <AlertCircle className="h-4 w-4 shrink-0" />
          <span>{error}</span>
        </div>
      )}

      {successMsg && (
        <div className="flex items-center gap-2 rounded-xl bg-emerald-500/10 p-3 text-xs text-emerald-600 dark:text-emerald-400 border border-emerald-500/20">
          <CheckCircle2 className="h-4 w-4 shrink-0" />
          <span>{successMsg}</span>
        </div>
      )}

      <form onSubmit={handleSubmit} className="space-y-4">
        {formDef.fields_schema.map((field) => {
          const rawVal = formData[field.id];
          const value = typeof rawVal === "string" || typeof rawVal === "number" ? rawVal : "";
          return (
            <div key={field.id} className="space-y-1.5">
              <label className="block text-xs font-semibold text-foreground">
                {field.label} {field.required && <span className="text-destructive">*</span>}
              </label>

              {field.type === "text" && (
                <input
                  type="text"
                  placeholder={field.placeholder || ""}
                  value={value}
                  onChange={(e) => handleFieldChange(field.id, e.target.value)}
                  className="w-full rounded-xl border border-input bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary"
                  required={field.required}
                />
              )}

              {field.type === "number" && (
                <input
                  type="number"
                  step="any"
                  placeholder={field.placeholder || ""}
                  value={value}
                  onChange={(e) => handleFieldChange(field.id, e.target.value === "" ? "" : Number(e.target.value))}
                  className="w-full rounded-xl border border-input bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary"
                  required={field.required}
                />
              )}

              {field.type === "textarea" && (
                <textarea
                  rows={3}
                  placeholder={field.placeholder || ""}
                  value={value}
                  onChange={(e) => handleFieldChange(field.id, e.target.value)}
                  className="w-full rounded-xl border border-input bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary"
                  required={field.required}
                />
              )}

              {field.type === "date" && (
                <input
                  type="date"
                  value={value}
                  onChange={(e) => handleFieldChange(field.id, e.target.value)}
                  className="w-full rounded-xl border border-input bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary"
                  required={field.required}
                />
              )}

              {field.type === "select" && (
                <select
                  value={value}
                  onChange={(e) => handleFieldChange(field.id, e.target.value)}
                  className="w-full rounded-xl border border-input bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary"
                  required={field.required}
                >
                  <option value="">Select option...</option>
                  {field.options?.map((opt) => (
                    <option key={opt.value} value={opt.value}>
                      {opt.label}
                    </option>
                  ))}
                </select>
              )}

              {field.type === "checkbox" && (
                <label className="flex items-center gap-2 pt-1 text-xs cursor-pointer">
                  <input
                    type="checkbox"
                    checked={rawVal === true}
                    onChange={(e) => handleFieldChange(field.id, e.target.checked)}
                    className="rounded border-input text-primary focus:ring-primary h-4 w-4"
                  />
                  <span className="text-muted-foreground">{field.placeholder || "Yes / Confirmed"}</span>
                </label>
              )}
            </div>
          );
        })}

        <div className="pt-4 border-t border-border flex justify-end">
          <button
            type="submit"
            disabled={isSubmitting}
            className="flex items-center gap-2 rounded-xl bg-primary px-5 py-2.5 text-xs font-semibold text-primary-foreground hover:bg-primary/90 transition-colors shadow-sm disabled:opacity-50"
          >
            <Send className="h-4 w-4" />
            {isSubmitting ? "Submitting..." : "Submit Clinical Form"}
          </button>
        </div>
      </form>
    </div>
  );
}
