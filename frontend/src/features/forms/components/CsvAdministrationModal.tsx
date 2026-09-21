"use client";

import { useRef, useState } from "react";
import {
  AlertCircle,
  CheckCircle2,
  Download,
  FileSpreadsheet,
  ShieldAlert,
  ShieldCheck,
  Upload,
  X,
} from "lucide-react";
import { downloadCsv, importCsv, validateCsv } from "../api";
import { useClinicalWrite } from "@/lib/useClinicalWrite";
import type { CsvImportResult, CsvValidationResult } from "../types";

interface CsvAdministrationModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSuccess: () => void;
}

export function CsvAdministrationModal({
  isOpen,
  onClose,
  onSuccess,
}: CsvAdministrationModalProps) {
  const [entityType, setEntityType] = useState<string>("vaccines");
  const [csvText, setCsvText] = useState<string>("");
  const [validationResult, setValidationResult] = useState<CsvValidationResult | null>(null);
  const [importResult, setImportResult] = useState<CsvImportResult | null>(null);

  const [isValidating, setIsValidating] = useState(false);
  const [isImporting, setIsImporting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const write = useClinicalWrite();
  // While an import's outcome is unknown the draft is the retry body and must
  // not change, including through a file read that started earlier.
  const locked = isImporting || write.retryPending;
  // Bumped synchronously on every draft change so asynchronous completions can
  // tell whether the text they describe is still the text on screen, without
  // depending on a render having happened in between.
  const draftVersion = useRef(0);
  const readSequence = useRef(0);
  const validateSequence = useRef(0);

  if (!isOpen) return null;

  const touchDraft = () => {
    draftVersion.current += 1;
    setValidationResult(null);
    setImportResult(null);
  };

  const handleFileUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file || locked) return;
    const request = ++readSequence.current;
    const reader = new FileReader();
    reader.onload = (event) => {
      // A read that finishes after another file was chosen, or after the draft
      // became the body of an unconfirmed import, must not replace the draft.
      if (request !== readSequence.current || write.isPending()) return;
      const content = event.target?.result;
      setCsvText(typeof content === "string" ? content : "");
      touchDraft();
      setError(null);
    };
    reader.onerror = () => {
      if (request === readSequence.current && !write.isPending()) setError("The selected file could not be read.");
    };
    reader.readAsText(file);
  };

  const handleValidate = async () => {
    const snapshot = { csvText, entityType };
    if (!snapshot.csvText.trim()) {
      setError("Please upload a CSV file or paste raw CSV content.");
      return;
    }
    const request = ++validateSequence.current;
    const version = draftVersion.current;
    setError(null);
    setValidationResult(null);
    setImportResult(null);

    try {
      setIsValidating(true);
      const res = await validateCsv(snapshot.csvText, snapshot.entityType);
      // The verdict belongs to the content that was sent. If the draft or the
      // entity changed meanwhile, showing "Safe to Ingest" would describe text
      // the user no longer has.
      if (request !== validateSequence.current || version !== draftVersion.current) return;
      setValidationResult(res);
    } catch (err: unknown) {
      if (request === validateSequence.current) setError(err instanceof Error ? err.message : "Validation failed.");
    } finally {
      if (request === validateSequence.current) setIsValidating(false);
    }
  };

  const handleClose = () => {
    if (locked) return;
    // Discard in-flight reads/validations and stale verdicts so a reopened
    // modal cannot show a previous import as the current one.
    readSequence.current += 1;
    validateSequence.current += 1;
    setIsValidating(false);
    setValidationResult(null);
    setImportResult(null);
    setError(null);
    onClose();
  };

  const handleImport = async () => {
    if (!csvText.trim() || isImporting || !write.isCurrent()) return;
    setError(null);

    try {
      setIsImporting(true);
      const res = await write.run({ csvText, entityType }, (payload, key) => importCsv(payload.csvText, payload.entityType, key));
      if (!write.isCurrent()) return;
      setImportResult(res);
      onSuccess();
    } catch (err: unknown) {
      if (write.isCurrent()) setError(err instanceof Error ? err.message : "Import failed.");
    } finally {
      if (write.isCurrent()) setIsImporting(false);
    }
  };

  const handleDownloadExport = async () => {
    try {
      const blob = await downloadCsv(entityType);
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url; link.download = entityType + ".csv"; link.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (err) { setError(err instanceof Error ? err.message : "Export failed."); }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4">
      <div className="w-full max-w-xl rounded-2xl border border-border bg-card p-6 shadow-2xl animate-in fade-in zoom-in-95 duration-200">
        <div className="flex items-center justify-between pb-4 border-b border-border">
          <div className="flex items-center gap-2">
            <FileSpreadsheet className="h-5 w-5 text-primary" />
            <div>
              <h3 className="text-lg font-bold text-card-foreground">CSV Administration & Ingestion</h3>
              <p className="text-xs text-muted-foreground">
                Formula-injection hardened bulk upload & export
              </p>
            </div>
          </div>
          <button
            onClick={handleClose}
            disabled={locked}
            className="rounded-lg p-1.5 text-muted-foreground hover:bg-muted hover:text-foreground transition-colors"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        {error && (
          <div className="mt-4 flex items-center gap-2 rounded-xl bg-destructive/10 p-3 text-xs text-destructive border border-destructive/20">
            <AlertCircle className="h-4 w-4 shrink-0" />
            <span>{error}</span>
          </div>
        )}

        <div className="mt-4 space-y-4">
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-1">
                Target Entity
              </label>
              <select
                disabled={locked}
                value={entityType}
                onChange={(e) => {
                  setEntityType(e.target.value);
                  touchDraft();
                }}
                className="w-full rounded-xl border border-input bg-background px-3 py-2 text-xs focus:outline-none focus:ring-2 focus:ring-primary"
              >
                <option value="vaccines">Vaccine Catalogue</option>

              </select>
            </div>

            <div>
              <label className="block text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-1">
                Export Current Data
              </label>
              <button
                type="button"
                onClick={handleDownloadExport}
                className="w-full flex items-center justify-center gap-1.5 rounded-xl border border-border bg-background px-3 py-2 text-xs font-semibold text-foreground hover:bg-muted transition-colors"
              >
                <Download className="h-3.5 w-3.5" />
                Download {entityType}.csv
              </button>
            </div>
          </div>

          <div>
            <label className="block text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-1">
              Upload CSV File
            </label>
            <input
              type="file"
              disabled={locked}
              accept=".csv,text/csv"
              onChange={handleFileUpload}
              className="w-full rounded-xl border border-input bg-background px-3 py-1.5 text-xs file:mr-3 file:py-1 file:px-2.5 file:rounded-lg file:border-0 file:text-xs file:font-semibold file:bg-primary/10 file:text-primary hover:file:bg-primary/20 cursor-pointer"
            />
          </div>

          <div>
            <label className="block text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-1">
              Or Paste Raw CSV Content
            </label>
            <textarea
              disabled={locked}
              rows={4}
              placeholder="code,name,target_disease,standard_doses,min_age_days,route,site,dose_quantity"
              value={csvText}
              onChange={(e) => {
                setCsvText(e.target.value);
                touchDraft();
              }}
              className="w-full rounded-xl border border-input bg-background p-3 font-mono text-xs focus:outline-none focus:ring-2 focus:ring-primary"
            />
          </div>

          {/* Validation Feedback */}
          {validationResult && (
            <div
              className={`p-4 rounded-xl border space-y-2 text-xs ${
                validationResult.valid
                  ? "bg-emerald-500/10 border-emerald-500/30 text-emerald-800 dark:text-emerald-300"
                  : "bg-destructive/10 border-destructive/30 text-destructive"
              }`}
            >
              <div className="flex items-center gap-2 font-bold">
                {validationResult.valid ? (
                  <>
                    <ShieldCheck className="h-4 w-4 text-emerald-500" />
                    <span>CSV Validation Passed — Safe to Ingest</span>
                  </>
                ) : (
                  <>
                    <ShieldAlert className="h-4 w-4 text-destructive" />
                    <span>CSV Validation Failed</span>
                  </>
                )}
              </div>

              <div className="text-[11px] space-y-1">
                <p>
                  Rows detected: <strong>{validationResult.row_count}</strong> • Columns:{" "}
                  <strong>{validationResult.columns.join(", ")}</strong>
                </p>

                {validationResult.warnings.length > 0 && (
                  <div className="pt-1 text-amber-600 dark:text-amber-400">
                    <span className="font-semibold block">Rejected Formula-like Values:</span>
                    <ul className="list-disc list-inside">
                      {validationResult.warnings.map((w, i) => (
                        <li key={i}>{w}</li>
                      ))}
                    </ul>
                  </div>
                )}

                {validationResult.errors.length > 0 && (
                  <div className="pt-1 text-destructive">
                    <span className="font-semibold block">Validation Errors:</span>
                    <ul className="list-disc list-inside">
                      {validationResult.errors.map((e, i) => (
                        <li key={i}>{e}</li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>
            </div>
          )}

          {/* Import Result */}
          {importResult && (
            <div className="p-4 rounded-xl bg-emerald-500/10 border border-emerald-500/30 text-emerald-700 dark:text-emerald-300 flex items-center gap-2 text-xs">
              <CheckCircle2 className="h-4 w-4 text-emerald-500 shrink-0" />
              <span>
                {importResult.message} ({importResult.imported_count} records imported).
              </span>
            </div>
          )}

          <div className="pt-4 border-t border-border flex items-center justify-end gap-2">
            <button
              type="button"
              onClick={handleClose}
              disabled={locked}
              className="rounded-xl border border-border px-4 py-2 text-xs font-semibold text-muted-foreground hover:bg-muted transition-colors"
            >
              Close
            </button>

            <button
              type="button"
              disabled={isValidating || locked || !csvText.trim()}
              onClick={handleValidate}
              className="rounded-xl bg-secondary px-4 py-2 text-xs font-semibold text-secondary-foreground hover:bg-secondary/80 transition-colors disabled:opacity-50"
            >
              {isValidating ? "Validating..." : "Validate Security"}
            </button>

            {validationResult?.valid && (
              <button
                type="button"
                disabled={isImporting || !!importResult}
                onClick={handleImport}
                className="flex items-center gap-1.5 rounded-xl bg-primary px-4 py-2 text-xs font-semibold text-primary-foreground hover:bg-primary/90 transition-colors shadow-sm disabled:opacity-50"
              >
                <Upload className="h-3.5 w-3.5" />
                {isImporting ? "Importing..." : write.retryPending ? "Retry unchanged import" : "Execute Import"}
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
