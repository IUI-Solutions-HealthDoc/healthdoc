"use client";

import { useEffect, useState } from "react";
import {
  Activity,
  AlertOctagon,
  CheckCircle2,
  Clock,
  Eye,
  Lock,
  Radio,
  RefreshCw,
  RotateCcw,
  ShieldAlert,
  X,
} from "lucide-react";
import {
  fetchDeadLetters,
  fetchOutboxEvents,
  fetchOutboxMetrics,
  replayDeadLetter,
  type OutboxDeadLetter,
  type OutboxEvent,
  type OutboxMetrics,
} from "../api/outbox";

export function IntegrationConsole() {
  const [metrics, setMetrics] = useState<OutboxMetrics | null>(null);
  const [events, setEvents] = useState<OutboxEvent[]>([]);
  const [deadLetters, setDeadLetters] = useState<OutboxDeadLetter[]>([]);
  const [loading, setLoading] = useState(true);
  const [activeTab, setActiveTab] = useState<"dlq" | "events">("dlq");

  // Inspection modal
  const [inspectItem, setInspectItem] = useState<OutboxDeadLetter | null>(null);
  const [replayingId, setReplayingId] = useState<string | null>(null);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);

  const loadData = async () => {
    try {
      setLoading(true);
      const [m, d, e] = await Promise.all([
        fetchOutboxMetrics(),
        fetchDeadLetters(),
        fetchOutboxEvents({ limit: 40 }),
      ]);
      setMetrics(m);
      setDeadLetters(d);
      setEvents(e);
    } catch (err) {
      console.error("Failed to load integration outbox data:", err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadData();
  }, []);

  const handleReplay = async (dl: OutboxDeadLetter) => {
    try {
      setReplayingId(dl.id);
      setSuccessMsg(null);
      await replayDeadLetter(dl.id);
      setSuccessMsg(`Event ${dl.event_type} (${dl.id.slice(0, 8)}) re-enqueued for delivery.`);
      await loadData();
    } catch (err: unknown) {
      console.error("Replay failed:", err);
    } finally {
      setReplayingId(null);
    }
  };

  return (
    <div className="space-y-6">
      {/* Top Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-black tracking-tight text-foreground flex items-center gap-2">
            <Radio className="h-7 w-7 text-primary" />
            Integration Console & Safe Outbox DLQ
          </h1>
          <p className="text-xs text-muted-foreground mt-1">
            Transactional event streaming, delivery lag telemetry, PHI-redacted dead-letter queue & replay (HD-31)
          </p>
        </div>

        <button
          onClick={loadData}
          className="flex items-center gap-1.5 rounded-xl border border-border bg-card px-3.5 py-2 text-xs font-semibold text-foreground hover:bg-muted transition-colors shadow-sm self-start"
        >
          <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} />
          Refresh Metrics
        </button>
      </div>

      {/* Metrics Row */}
      <div className="grid grid-cols-2 sm:grid-cols-5 gap-3">
        <div className="rounded-2xl border border-border bg-card p-4 shadow-sm">
          <div className="flex items-center justify-between">
            <span className="text-[11px] font-semibold text-muted-foreground uppercase">Pending Queue</span>
            <Clock className="h-4 w-4 text-amber-500" />
          </div>
          <div className="mt-2 text-2xl font-black text-foreground">{metrics?.pending_count ?? 0}</div>
          <p className="text-[10px] text-muted-foreground mt-0.5">Awaiting cloud publish</p>
        </div>

        <div className="rounded-2xl border border-border bg-card p-4 shadow-sm">
          <div className="flex items-center justify-between">
            <span className="text-[11px] font-semibold text-muted-foreground uppercase">In Flight</span>
            <Activity className="h-4 w-4 text-sky-500" />
          </div>
          <div className="mt-2 text-2xl font-black text-foreground">{metrics?.in_flight_count ?? 0}</div>
          <p className="text-[10px] text-muted-foreground mt-0.5">Currently dispatching</p>
        </div>

        <div className="rounded-2xl border border-border bg-card p-4 shadow-sm">
          <div className="flex items-center justify-between">
            <span className="text-[11px] font-semibold text-muted-foreground uppercase">Delivered</span>
            <CheckCircle2 className="h-4 w-4 text-emerald-500" />
          </div>
          <div className="mt-2 text-2xl font-black text-foreground">{metrics?.sent_count ?? 0}</div>
          <p className="text-[10px] text-muted-foreground mt-0.5">Acknowledged events</p>
        </div>

        <div className="rounded-2xl border border-destructive/30 bg-destructive/5 p-4 shadow-sm">
          <div className="flex items-center justify-between">
            <span className="text-[11px] font-semibold text-destructive uppercase">Dead Letters (DLQ)</span>
            <AlertOctagon className="h-4 w-4 text-destructive" />
          </div>
          <div className="mt-2 text-2xl font-black text-destructive">{metrics?.dead_letter_count ?? 0}</div>
          <p className="text-[10px] text-muted-foreground mt-0.5">Max retries exhausted</p>
        </div>

        <div className="rounded-2xl border border-border bg-card p-4 shadow-sm col-span-2 sm:col-span-1">
          <div className="flex items-center justify-between">
            <span className="text-[11px] font-semibold text-muted-foreground uppercase">Publish Lag</span>
            <Radio className="h-4 w-4 text-primary" />
          </div>
          <div className="mt-2 text-2xl font-black text-foreground">
            {metrics ? `${metrics.delivery_lag_seconds.toFixed(1)}s` : "0.0s"}
          </div>
          <p className="text-[10px] text-muted-foreground mt-0.5">Oldest pending age</p>
        </div>
      </div>

      {successMsg && (
        <div className="flex items-center gap-2 rounded-xl bg-emerald-500/10 p-3 text-xs text-emerald-600 dark:text-emerald-400 border border-emerald-500/20">
          <CheckCircle2 className="h-4 w-4 shrink-0" />
          <span>{successMsg}</span>
        </div>
      )}

      {/* Tabs */}
      <div className="rounded-2xl border border-border bg-card overflow-hidden shadow-sm">
        <div className="flex items-center border-b border-border px-4 pt-3 bg-muted/20">
          <button
            onClick={() => setActiveTab("dlq")}
            className={`pb-3 px-3 text-xs font-semibold border-b-2 transition-colors flex items-center gap-1.5 ${
              activeTab === "dlq"
                ? "border-destructive text-destructive"
                : "border-transparent text-muted-foreground hover:text-foreground"
            }`}
          >
            <ShieldAlert className="h-4 w-4" />
            Dead-Letter Queue ({deadLetters.length})
          </button>
          <button
            onClick={() => setActiveTab("events")}
            className={`pb-3 px-3 text-xs font-semibold border-b-2 transition-colors flex items-center gap-1.5 ${
              activeTab === "events"
                ? "border-primary text-primary"
                : "border-transparent text-muted-foreground hover:text-foreground"
            }`}
          >
            <Activity className="h-4 w-4" />
            Outbox Event Stream ({events.length})
          </button>
        </div>

        {activeTab === "dlq" ? (
          <div className="p-4">
            {deadLetters.length === 0 ? (
              <div className="text-center py-12 text-muted-foreground text-xs">
                <CheckCircle2 className="h-8 w-8 mx-auto mb-2 text-emerald-500 opacity-60" />
                Dead-Letter Queue is empty. All background outbox events delivered smoothly!
              </div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-left text-xs">
                  <thead className="bg-muted/50 text-muted-foreground font-semibold">
                    <tr>
                      <th className="p-3">Event Type</th>
                      <th className="p-3">Aggregate</th>
                      <th className="p-3">Error Reason</th>
                      <th className="p-3">Failed At</th>
                      <th className="p-3">Replays</th>
                      <th className="p-3 text-right">Actions</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-border">
                    {deadLetters.map((dl) => (
                      <tr key={dl.id} className="hover:bg-muted/30">
                        <td className="p-3 font-mono font-bold text-foreground">
                          {dl.event_type}
                        </td>
                        <td className="p-3 text-muted-foreground">
                          <span className="font-semibold text-foreground uppercase">{dl.aggregate_type}</span>:{" "}
                          <span className="font-mono text-[11px]">{dl.aggregate_id.slice(0, 8)}...</span>
                        </td>
                        <td className="p-3 text-destructive max-w-xs truncate" title={dl.error_message}>
                          {dl.error_message}
                        </td>
                        <td className="p-3 font-mono text-muted-foreground">
                          {new Date(dl.failed_at).toLocaleTimeString()}
                        </td>
                        <td className="p-3 font-mono">{dl.replay_count}</td>
                        <td className="p-3 text-right space-x-2">
                          <button
                            onClick={() => setInspectItem(dl)}
                            className="inline-flex items-center gap-1 rounded-lg border border-border bg-background px-2.5 py-1 text-xs font-medium text-muted-foreground hover:bg-muted"
                          >
                            <Eye className="h-3 w-3" />
                            Payload
                          </button>
                          <button
                            disabled={replayingId === dl.id}
                            onClick={() => handleReplay(dl)}
                            className="inline-flex items-center gap-1 rounded-lg bg-primary px-2.5 py-1 text-xs font-semibold text-primary-foreground hover:bg-primary/90 disabled:opacity-50 shadow-sm"
                          >
                            <RotateCcw className={`h-3 w-3 ${replayingId === dl.id ? "animate-spin" : ""}`} />
                            Replay
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        ) : (
          /* Events Stream */
          <div className="p-4">
            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs">
                <thead className="bg-muted/50 text-muted-foreground font-semibold">
                  <tr>
                    <th className="p-3">Seq #</th>
                    <th className="p-3">Event Type</th>
                    <th className="p-3">Aggregate</th>
                    <th className="p-3">Status</th>
                    <th className="p-3">Attempts</th>
                    <th className="p-3">Created</th>
                    <th className="p-3">Sent</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border">
                  {events.map((e) => (
                    <tr key={e.id} className="hover:bg-muted/30">
                      <td className="p-3 font-mono font-bold text-muted-foreground">{e.sequence}</td>
                      <td className="p-3 font-mono font-semibold text-foreground">{e.event_type}</td>
                      <td className="p-3 text-muted-foreground">
                        {e.aggregate_type} ({e.aggregate_id.slice(0, 8)})
                      </td>
                      <td className="p-3">
                        <span
                          className={`inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-bold uppercase ${
                            e.status === "sent"
                              ? "bg-emerald-500/10 text-emerald-600 dark:text-emerald-400"
                              : e.status === "pending"
                              ? "bg-amber-500/10 text-amber-600 dark:text-amber-400"
                              : e.status === "in_flight"
                              ? "bg-sky-500/10 text-sky-600 dark:text-sky-400"
                              : "bg-destructive/10 text-destructive"
                          }`}
                        >
                          {e.status}
                        </span>
                      </td>
                      <td className="p-3 font-mono">{e.attempts}</td>
                      <td className="p-3 font-mono text-muted-foreground">
                        {new Date(e.created_at).toLocaleTimeString()}
                      </td>
                      <td className="p-3 font-mono text-muted-foreground">
                        {e.sent_at ? new Date(e.sent_at).toLocaleTimeString() : "—"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </div>

      {/* Payload Inspection Modal */}
      {inspectItem && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4">
          <div className="w-full max-w-lg rounded-2xl border border-border bg-card p-6 shadow-2xl animate-in fade-in zoom-in-95 duration-200">
            <div className="flex items-center justify-between pb-4 border-b border-border">
              <div className="flex items-center gap-2">
                <Lock className="h-5 w-5 text-emerald-500" />
                <div>
                  <h3 className="text-lg font-bold text-card-foreground">Sanitized DLQ Payload</h3>
                  <p className="text-xs text-muted-foreground">PHI-redacted clinical outbox payload</p>
                </div>
              </div>
              <button
                onClick={() => setInspectItem(null)}
                className="rounded-lg p-1.5 text-muted-foreground hover:bg-muted hover:text-foreground transition-colors"
              >
                <X className="h-5 w-5" />
              </button>
            </div>

            <div className="mt-4 space-y-3">
              <div className="p-3 rounded-xl bg-muted/40 border border-border text-xs space-y-1">
                <div>
                  <strong>Event:</strong> <span className="font-mono">{inspectItem.event_type}</span>
                </div>
                <div>
                  <strong>Aggregate:</strong> {inspectItem.aggregate_type} ({inspectItem.aggregate_id})
                </div>
                <div className="text-destructive">
                  <strong>Failure:</strong> {inspectItem.error_message}
                </div>
              </div>

              <div>
                <span className="text-[11px] font-bold uppercase tracking-wider text-muted-foreground block mb-1">
                  Redacted Payload JSON
                </span>
                <div className="p-3 rounded-xl bg-background border border-border max-h-60 overflow-y-auto font-mono text-xs">
                  <pre className="whitespace-pre-wrap">
                    {JSON.stringify(inspectItem.payload_redacted, null, 2)}
                  </pre>
                </div>
              </div>

              <div className="pt-4 border-t border-border flex justify-end">
                <button
                  type="button"
                  onClick={() => setInspectItem(null)}
                  className="rounded-xl border border-border px-4 py-2 text-xs font-semibold text-muted-foreground hover:bg-muted transition-colors"
                >
                  Close
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
