"use client";

import { useEffect, useState } from "react";
import { AlertTriangle, CheckCircle, Clock, FileText, X } from "lucide-react";
import { acknowledgeCriticalAlert, listCriticalAlerts } from "@/features/lab/api";
import type { CriticalAlert } from "@/features/lab/types";
import { formatDateTime } from "@/lib/api";

interface CriticalAlertsModalProps {
  isOpen: boolean;
  onClose: () => void;
  onAlertAcknowledged?: () => void;
}

export function CriticalAlertsModal({
  isOpen,
  onClose,
  onAlertAcknowledged,
}: CriticalAlertsModalProps) {
  const [alerts, setAlerts] = useState<CriticalAlert[]>([]);
  const [loading, setLoading] = useState(false);
  const [filter, setFilter] = useState<"unacknowledged" | "all">("unacknowledged");
  const [ackNote, setAckNote] = useState<Record<string, string>>({});
  const [submittingId, setSubmittingId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const fetchAlerts = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await listCriticalAlerts(filter);
      setAlerts(res.items);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to load critical alerts");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (isOpen) {
      void fetchAlerts();
    }
  }, [isOpen, filter]);

  const handleAcknowledge = async (alertId: string) => {
    const note = ackNote[alertId] || "";
    setSubmittingId(alertId);
    setError(null);
    try {
      await acknowledgeCriticalAlert(alertId, note);
      await fetchAlerts();
      if (onAlertAcknowledged) {
        onAlertAcknowledged();
      }
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to acknowledge critical alert");
    } finally {
      setSubmittingId(null);
    }
  };

  if (!isOpen) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4 backdrop-blur-xs"
      role="dialog"
      aria-modal="true"
      aria-labelledby="critical-alerts-title"
    >
      <div className="relative flex max-h-[90vh] w-full max-w-3xl flex-col rounded-xl border border-red-200 bg-card shadow-2xl dark:border-red-900/50">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-border bg-red-50/70 px-6 py-4 dark:bg-red-950/30">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-full bg-red-600 text-white shadow-md">
              <AlertTriangle size={22} className="animate-bounce" />
            </div>
            <div>
              <h2 id="critical-alerts-title" className="text-lg font-bold text-red-950 dark:text-red-200">
                Critical Laboratory Panic Alerts
              </h2>
              <p className="text-xs text-red-800/80 dark:text-red-300/80">
                Immediate clinical review and verified clinician sign-off required
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg p-1 text-muted-foreground hover:bg-muted hover:text-foreground"
            aria-label="Close dialog"
          >
            <X size={20} />
          </button>
        </div>

        {/* Filters */}
        <div className="flex items-center justify-between border-b border-border px-6 py-3 bg-muted/20">
          <div className="flex gap-2">
            <button
              type="button"
              onClick={() => setFilter("unacknowledged")}
              className={`rounded-full px-3 py-1 text-xs font-semibold transition-colors ${
                filter === "unacknowledged"
                  ? "bg-red-600 text-white shadow-xs"
                  : "bg-muted text-muted-foreground hover:text-foreground"
              }`}
            >
              Unacknowledged ({alerts.filter((a) => a.status === "unacknowledged").length})
            </button>
            <button
              type="button"
              onClick={() => setFilter("all")}
              className={`rounded-full px-3 py-1 text-xs font-semibold transition-colors ${
                filter === "all"
                  ? "bg-primary text-white shadow-xs"
                  : "bg-muted text-muted-foreground hover:text-foreground"
              }`}
            >
              All Alerts
            </button>
          </div>
          <button
            type="button"
            onClick={() => void fetchAlerts()}
            className="text-xs font-medium text-primary hover:underline"
          >
            Refresh
          </button>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto p-6 space-y-4">
          {error && (
            <div className="rounded-lg border border-red-300 bg-red-50 p-3 text-xs text-red-700 dark:border-red-800 dark:bg-red-950/50 dark:text-red-300">
              {error}
            </div>
          )}

          {loading ? (
            <div className="py-12 text-center text-sm text-muted-foreground animate-pulse">
              Loading critical alerts...
            </div>
          ) : alerts.length === 0 ? (
            <div className="py-12 text-center">
              <CheckCircle size={40} className="mx-auto mb-3 text-emerald-500" />
              <p className="text-sm font-semibold text-foreground">No pending critical alerts</p>
              <p className="text-xs text-muted-foreground mt-1">
                All patient lab parameters are within critical safe limits.
              </p>
            </div>
          ) : (
            alerts.map((alert) => {
              const isUnack = alert.status === "unacknowledged";
              return (
                <div
                  key={alert.id}
                  className={`rounded-lg border p-4 transition-all ${
                    isUnack
                      ? "border-red-300 bg-red-50/40 shadow-xs dark:border-red-900/60 dark:bg-red-950/20"
                      : "border-border bg-card opacity-80"
                  }`}
                >
                  <div className="flex flex-wrap items-start justify-between gap-2">
                    <div className="space-y-1">
                      <div className="flex items-center gap-2">
                        <span className="rounded-full bg-red-600 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider text-white">
                          CRITICAL PANIC
                        </span>
                        <span className="font-semibold text-sm text-foreground">
                          {alert.analyte_name} ({alert.analyte_code})
                        </span>
                        <span className="text-xs text-muted-foreground">in test {alert.test_code}</span>
                      </div>
                      <div className="text-xs text-muted-foreground flex items-center gap-3">
                        <span className="flex items-center gap-1">
                          <Clock size={12} /> {formatDateTime(alert.created_at)}
                        </span>
                        <span>Patient ID: <code className="text-foreground">{alert.patient_id.slice(0, 8)}...</code></span>
                        <span>Order ID: <code className="text-foreground">{alert.order_id.slice(0, 8)}...</code></span>
                      </div>
                    </div>

                    <div className="text-right">
                      <div className="text-2xl font-black text-red-600 dark:text-red-400">
                        {alert.value} <span className="text-sm font-normal text-muted-foreground">{alert.unit || ""}</span>
                      </div>
                      <div className="text-[11px] text-muted-foreground">
                        Critical threshold:{" "}
                        {alert.critical_high != null && `High > ${alert.critical_high}`}
                        {alert.critical_low != null && `Low < ${alert.critical_low}`}
                      </div>
                    </div>
                  </div>

                  {/* Acknowledgement Action or Status */}
                  <div className="mt-4 pt-3 border-t border-border/60">
                    {isUnack ? (
                      <div className="flex flex-col sm:flex-row items-stretch sm:items-center gap-2">
                        <input
                          type="text"
                          placeholder="Enter clinical action taken or notification note (e.g. Attending notified, treatment initiated)..."
                          value={ackNote[alert.id] || ""}
                          onChange={(e) => setAckNote({ ...ackNote, [alert.id]: e.target.value })}
                          className="flex-1 rounded-lg border border-border bg-background px-3 py-1.5 text-xs text-foreground placeholder:text-muted-foreground focus:border-red-500 focus:outline-none focus:ring-1 focus:ring-red-500"
                        />
                        <button
                          type="button"
                          onClick={() => void handleAcknowledge(alert.id)}
                          disabled={submittingId === alert.id}
                          className="rounded-lg bg-red-600 px-4 py-1.5 text-xs font-semibold text-white shadow-xs hover:bg-red-700 focus:outline-none focus:ring-2 focus:ring-red-500 focus:ring-offset-1 disabled:opacity-50"
                        >
                          {submittingId === alert.id ? "Acknowledging..." : "Acknowledge Alert"}
                        </button>
                      </div>
                    ) : (
                      <div className="flex items-center gap-2 text-xs text-emerald-600 dark:text-emerald-400">
                        <CheckCircle size={14} />
                        <span className="font-semibold">
                          Acknowledged {alert.acknowledged_at ? formatDateTime(alert.acknowledged_at) : ""}
                        </span>
                        {alert.acknowledgement_note && (
                          <span className="text-muted-foreground italic">— &ldquo;{alert.acknowledgement_note}&rdquo;</span>
                        )}
                      </div>
                    )}
                  </div>
                </div>
              );
            })
          )}
        </div>

        {/* Footer */}
        <div className="border-t border-border px-6 py-3 bg-muted/10 flex justify-end">
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg border border-border px-4 py-1.5 text-xs font-medium text-foreground hover:bg-muted"
          >
            Close
          </button>
        </div>
      </div>
    </div>
  );
}
