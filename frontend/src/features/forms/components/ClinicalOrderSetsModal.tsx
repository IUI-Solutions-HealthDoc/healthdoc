"use client";

import { useState } from "react";
import {
  AlertCircle,
  CheckCircle2,
  ChevronRight,
  ClipboardList,
  FlaskConical,
  Layers,
  Pill,
  Radio,
  X,
} from "lucide-react";
import { applyOrderSet } from "../api";
import type { ApplyOrderSetResult, ClinicalOrderSet } from "../types";

interface ClinicalOrderSetsModalProps {
  isOpen: boolean;
  onClose: () => void;
  orderSets: ClinicalOrderSet[];
  patientId: string;
  visitId: string;
  onSuccess: (result: ApplyOrderSetResult) => void;
}

export function ClinicalOrderSetsModal({
  isOpen,
  onClose,
  orderSets,
  patientId,
  visitId,
  onSuccess,
}: ClinicalOrderSetsModalProps) {
  const [selectedSet, setSelectedSet] = useState<ClinicalOrderSet | null>(
    orderSets[0] || null
  );
  const [isApplying, setIsApplying] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [appliedResult, setAppliedResult] = useState<ApplyOrderSetResult | null>(null);

  if (!isOpen) return null;

  const handleApply = async () => {
    if (!selectedSet) return;
    setError(null);
    try {
      setIsApplying(true);
      const res = await applyOrderSet(selectedSet.code, {
        patient_id: patientId,
        visit_id: visitId,
      });
      setAppliedResult(res);
      onSuccess(res);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to apply clinical order set.");
    } finally {
      setIsApplying(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4">
      <div className="w-full max-w-2xl rounded-2xl border border-border bg-card p-6 shadow-2xl animate-in fade-in zoom-in-95 duration-200">
        <div className="flex items-center justify-between pb-4 border-b border-border">
          <div className="flex items-center gap-2">
            <Layers className="h-5 w-5 text-primary" />
            <div>
              <h3 className="text-lg font-bold text-card-foreground">Clinical Order Sets</h3>
              <p className="text-xs text-muted-foreground">Standardized multi-speciality clinical pathways & bundles</p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="rounded-lg p-1.5 text-muted-foreground hover:bg-muted hover:text-foreground transition-colors"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        {appliedResult ? (
          <div className="mt-6 text-center space-y-4 p-6 rounded-2xl bg-emerald-500/10 border border-emerald-500/20">
            <CheckCircle2 className="h-12 w-12 mx-auto text-emerald-500" />
            <div>
              <h4 className="font-bold text-base text-foreground">Order Set Applied Successfully</h4>
              <p className="text-xs text-muted-foreground mt-1">{appliedResult.message}</p>
            </div>

            <div className="rounded-xl bg-background p-4 text-left border border-border space-y-2">
              <span className="text-xs font-bold uppercase tracking-wider text-muted-foreground block mb-2">
                Orders Dispatched ({appliedResult.orders_applied.length})
              </span>
              <div className="space-y-1.5 text-xs">
                {appliedResult.orders_applied.map((o, idx) => (
                  <div key={idx} className="flex items-center justify-between py-1 border-b border-border/50">
                    <span className="font-medium text-foreground">{o.name}</span>
                    <span className="font-mono text-[10px] text-primary uppercase rounded bg-primary/10 px-1.5 py-0.5">
                      {o.type}
                    </span>
                  </div>
                ))}
              </div>
            </div>

            <button
              onClick={onClose}
              className="w-full rounded-xl bg-primary px-4 py-2.5 text-xs font-semibold text-primary-foreground hover:bg-primary/90 transition-colors"
            >
              Done
            </button>
          </div>
        ) : (
          <div className="mt-4 grid grid-cols-1 md:grid-cols-5 gap-4">
            {/* List of sets */}
            <div className="md:col-span-2 space-y-2 border-r border-border pr-2">
              <span className="text-[11px] font-bold uppercase tracking-wider text-muted-foreground block mb-1">
                Select Protocol
              </span>
              {orderSets.map((os) => (
                <button
                  key={os.id}
                  onClick={() => setSelectedSet(os)}
                  className={`w-full text-left p-3 rounded-xl border transition-all text-xs flex items-center justify-between ${
                    selectedSet?.id === os.id
                      ? "border-primary bg-primary/10 text-foreground font-semibold"
                      : "border-border bg-card text-muted-foreground hover:bg-muted"
                  }`}
                >
                  <div>
                    <div className="font-bold text-foreground">{os.title}</div>
                    <div className="text-[10px] text-muted-foreground uppercase font-mono mt-0.5">
                      {os.category} • {os.orders.length} items
                    </div>
                  </div>
                  <ChevronRight className="h-4 w-4 shrink-0 text-muted-foreground" />
                </button>
              ))}
            </div>

            {/* Details and Preview */}
            <div className="md:col-span-3 space-y-4">
              {selectedSet ? (
                <>
                  <div>
                    <span className="text-[11px] font-bold uppercase tracking-wider text-muted-foreground block">
                      Bundle Preview: {selectedSet.title}
                    </span>
                    <p className="text-xs text-muted-foreground mt-0.5">
                      Code: <span className="font-mono text-primary font-bold">{selectedSet.code}</span>
                    </p>
                  </div>

                  {error && (
                    <div className="flex items-center gap-2 rounded-xl bg-destructive/10 p-2.5 text-xs text-destructive border border-destructive/20">
                      <AlertCircle className="h-4 w-4 shrink-0" />
                      <span>{error}</span>
                    </div>
                  )}

                  <div className="max-h-60 overflow-y-auto space-y-2 pr-1">
                    {selectedSet.orders.map((item, idx) => (
                      <div
                        key={idx}
                        className="p-2.5 rounded-xl border border-border bg-background flex items-start justify-between gap-2 text-xs"
                      >
                        <div className="flex items-start gap-2">
                          {item.type === "lab" ? (
                            <FlaskConical className="h-4 w-4 text-emerald-500 shrink-0 mt-0.5" />
                          ) : item.type === "pharmacy" ? (
                            <Pill className="h-4 w-4 text-sky-500 shrink-0 mt-0.5" />
                          ) : (
                            <Radio className="h-4 w-4 text-purple-500 shrink-0 mt-0.5" />
                          )}
                          <div>
                            <span className="font-semibold text-foreground block">{item.name}</span>
                            <span className="text-[10px] text-muted-foreground">
                              {item.dosage ? `${item.dosage} • ${item.frequency}` : item.instructions || item.code}
                            </span>
                          </div>
                        </div>
                        <span className="rounded bg-muted px-1.5 py-0.5 text-[9px] uppercase font-mono text-muted-foreground shrink-0">
                          {item.type}
                        </span>
                      </div>
                    ))}
                  </div>

                  <div className="pt-4 border-t border-border flex items-center justify-end gap-2">
                    <button
                      type="button"
                      onClick={onClose}
                      className="rounded-xl border border-border px-3.5 py-2 text-xs font-semibold text-muted-foreground hover:bg-muted transition-colors"
                    >
                      Cancel
                    </button>
                    <button
                      type="button"
                      disabled={isApplying}
                      onClick={handleApply}
                      className="flex items-center gap-1.5 rounded-xl bg-primary px-4 py-2 text-xs font-semibold text-primary-foreground hover:bg-primary/90 transition-colors disabled:opacity-50"
                    >
                      <ClipboardList className="h-4 w-4" />
                      {isApplying ? "Placing Orders..." : `Place All ${selectedSet.orders.length} Orders`}
                    </button>
                  </div>
                </>
              ) : (
                <div className="text-center py-12 text-muted-foreground text-xs">
                  Select an order set on the left to preview bundled items.
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
