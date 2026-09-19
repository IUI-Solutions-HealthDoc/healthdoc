"use client";

import { useState, useMemo } from "react";
import type { LabAnalyte } from "../types";

export interface StructuredResultFormProps {
  analytes: LabAnalyte[];
  testName: string;
  initialValues?: Record<string, unknown>;
  initialRemarks?: string;
  onSubmit: (resultData: Record<string, unknown>, remarks: string) => Promise<void>;
  busy?: boolean;
}

type ClinicalFlag = "normal" | "abnormal_low" | "abnormal_high" | "critical_low" | "critical_high";

const FLAG_CONFIG: Record<ClinicalFlag, { label: string; badge: string }> = {
  critical_low: {
    label: "CRITICAL LOW",
    badge: "bg-red-600 text-white font-bold",
  },
  critical_high: {
    label: "CRITICAL HIGH",
    badge: "bg-red-600 text-white font-bold",
  },
  abnormal_low: {
    label: "LOW",
    badge: "bg-amber-500 text-white font-semibold",
  },
  abnormal_high: {
    label: "HIGH",
    badge: "bg-amber-500 text-white font-semibold",
  },
  normal: {
    label: "NORMAL",
    badge: "bg-emerald-600 text-white font-medium",
  },
};

function computeFlag(analyte: LabAnalyte, valStr: string): ClinicalFlag | null {
  if (!valStr.trim()) return null;
  const num = parseFloat(valStr);
  if (isNaN(num)) return null;

  if (analyte.critical_low !== null && num < analyte.critical_low) {
    return "critical_low";
  }
  if (analyte.critical_high !== null && num > analyte.critical_high) {
    return "critical_high";
  }
  if (analyte.reference_low !== null && num < analyte.reference_low) {
    return "abnormal_low";
  }
  if (analyte.reference_high !== null && num > analyte.reference_high) {
    return "abnormal_high";
  }
  if (analyte.reference_low !== null || analyte.reference_high !== null) {
    return "normal";
  }
  return null;
}

export default function StructuredResultForm({
  analytes,
  testName,
  initialValues = {},
  initialRemarks = "",
  onSubmit,
  busy = false,
}: StructuredResultFormProps) {
  const [values, setValues] = useState<Record<string, string>>(() => {
    const init: Record<string, string> = {};
    for (const a of analytes) {
      const val = initialValues[a.analyte_code];
      init[a.analyte_code] = val !== undefined && val !== null ? String(val) : "";
    }
    return init;
  });

  const [remarks, setRemarks] = useState(initialRemarks);
  const [error, setError] = useState<string | null>(null);

  // Calculate flags for all current values
  const flagMap = useMemo(() => {
    const map: Record<string, ClinicalFlag | null> = {};
    for (const a of analytes) {
      map[a.analyte_code] = computeFlag(a, values[a.analyte_code] ?? "");
    }
    return map;
  }, [analytes, values]);

  // Check if any flag is critical
  const hasCritical = useMemo(() => {
    return Object.values(flagMap).some(
      (flag) => flag === "critical_low" || flag === "critical_high"
    );
  }, [flagMap]);

  function handleValueChange(code: string, val: string) {
    setValues((prev) => ({ ...prev, [code]: val }));
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);

    // Validate required analytes
    for (const a of analytes) {
      const val = values[a.analyte_code]?.trim();
      if (a.is_required && !val) {
        setError(`Analyte '${a.analyte_name}' is required.`);
        return;
      }
      if (val && a.value_type === "numeric") {
        const num = parseFloat(val);
        if (isNaN(num)) {
          setError(`Analyte '${a.analyte_name}' must be a valid number.`);
          return;
        }
      }
    }

    const payload: Record<string, unknown> = {};
    for (const a of analytes) {
      const val = values[a.analyte_code]?.trim();
      if (!val) {
        payload[a.analyte_code] = null;
      } else if (a.value_type === "numeric") {
        payload[a.analyte_code] = parseFloat(val);
      } else {
        payload[a.analyte_code] = val;
      }
    }

    try {
      await onSubmit(payload, remarks);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to record lab results");
    }
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-5 text-sm">
      <div className="border-b border-border pb-2">
        <h3 className="font-semibold text-foreground text-base">
          Structured Analyte Entry — {testName}
        </h3>
        <p className="text-xs text-muted-foreground">
          Versioned clinical rules validate bounds and automatically compute diagnostic flags.
        </p>
      </div>

      {error && (
        <div role="alert" className="rounded-md bg-danger/10 border border-danger/30 p-3 text-xs text-danger">
          {error}
        </div>
      )}

      {hasCritical && (
        <div className="rounded-md border border-red-500/40 bg-red-500/10 p-3 text-xs text-red-700 dark:text-red-300">
          <div className="flex items-center gap-1.5 font-bold">
            <span>⚠️ CRITICAL THRESHOLD ALERT</span>
          </div>
          <p className="mt-1">
            One or more recorded analyte values breach emergency panic limits. Saving this result
            will automatically dispatch high-priority notifications to the treating clinical team.
          </p>
        </div>
      )}

      <div className="divide-y divide-border rounded-lg border border-border bg-card">
        {analytes.map((analyte) => {
          const flag = flagMap[analyte.analyte_code];
          const flagConfig = flag ? FLAG_CONFIG[flag] : null;

          return (
            <div
              key={analyte.id}
              className={`p-4 flex flex-col sm:flex-row sm:items-center justify-between gap-4 ${
                flag === "critical_low" || flag === "critical_high"
                  ? "bg-red-500/5"
                  : ""
              }`}
            >
              <div className="space-y-1 flex-1">
                <div className="flex items-center gap-2">
                  <span className="font-medium text-foreground">
                    {analyte.analyte_name}
                  </span>
                  {analyte.is_required && (
                    <span className="text-[10px] text-danger font-semibold">*Required</span>
                  )}
                  {analyte.unit && (
                    <span className="text-xs text-muted-foreground">
                      ({analyte.unit})
                    </span>
                  )}
                </div>

                <div className="flex items-center gap-3 text-xs text-muted-foreground flex-wrap">
                  {analyte.reference_low !== null && analyte.reference_high !== null && (
                    <span>
                      Ref: {analyte.reference_low} – {analyte.reference_high} {analyte.unit ?? ""}
                    </span>
                  )}
                  {(analyte.critical_low !== null || analyte.critical_high !== null) && (
                    <span className="text-red-600 dark:text-red-400">
                      Panic: {analyte.critical_low !== null ? `< ${analyte.critical_low}` : ""}{" "}
                      {analyte.critical_high !== null ? `> ${analyte.critical_high}` : ""}
                    </span>
                  )}
                </div>
              </div>

              <div className="flex items-center gap-3">
                <div className="w-36">
                  <input
                    type={analyte.value_type === "numeric" ? "number" : "text"}
                    step="any"
                    required={analyte.is_required}
                    placeholder="Enter value"
                    className="w-full rounded-md border border-border bg-background px-3 py-1.5 text-sm text-foreground focus:border-primary"
                    value={values[analyte.analyte_code] ?? ""}
                    onChange={(e) => handleValueChange(analyte.analyte_code, e.target.value)}
                  />
                </div>

                <div className="w-28 text-center">
                  {flagConfig ? (
                    <span className={`inline-block rounded px-2 py-0.5 text-[10px] ${flagConfig.badge}`}>
                      {flagConfig.label}
                    </span>
                  ) : (
                    <span className="text-xs text-muted-foreground italic">—</span>
                  )}
                </div>
              </div>
            </div>
          );
        })}
      </div>

      <label className="block space-y-1">
        <span className="font-medium text-foreground">Pathologist / Tech Remarks</span>
        <textarea
          rows={2}
          className="w-full rounded-md border border-border bg-background px-3 py-2 text-foreground"
          placeholder="Clinical comments, specimen quality, delta check notes..."
          value={remarks}
          onChange={(e) => setRemarks(e.target.value)}
        />
      </label>

      <div className="flex items-center justify-end gap-3 pt-2">
        <button
          type="submit"
          disabled={busy}
          className={`rounded-md px-4 py-2 font-medium text-white shadow-sm disabled:opacity-50 ${
            hasCritical ? "bg-red-600 hover:bg-red-700" : "bg-primary hover:bg-primary/90"
          }`}
        >
          {busy
            ? "Saving Results…"
            : hasCritical
            ? "Save Result & Dispatch Alert"
            : "Save Preliminary Result"}
        </button>
      </div>
    </form>
  );
}
