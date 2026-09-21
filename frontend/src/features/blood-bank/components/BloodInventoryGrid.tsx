"use client";

import { useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  Clock,
  Droplet,
  Package,
  Plus,
  TestTube,
  X,
} from "lucide-react";
import { createBloodUnit } from "../api";
import { formatBloodGroup, type BloodDonor, type BloodUnit } from "../types";

interface BloodInventoryGridProps {
  units: BloodUnit[];
  donors: BloodDonor[];
  onRefresh: () => void;
  onOpenCrossmatch: (unit: BloodUnit) => void;
}

const BLOOD_GROUPS = ["A+", "A-", "B+", "B-", "AB+", "AB-", "O+", "O-"];



export function BloodInventoryGrid({
  units,
  donors,
  onRefresh,
  onOpenCrossmatch,
}: BloodInventoryGridProps) {
  const [selectedGroup, setSelectedGroup] = useState<string>("all");
  const [selectedStatus, setSelectedStatus] = useState<string>("all");
  const [isCollectModalOpen, setIsCollectModalOpen] = useState<boolean>(false);

  // Collect form state
  const [unitNumber, setUnitNumber] = useState<string>("");
  const [donorId, setDonorId] = useState<string>("");
  const [bloodGroup, setBloodGroup] = useState<string>("O");
  const [rhFactor, setRhFactor] = useState<string>("+");
  const [screening, setScreening] = useState<"pending" | "passed" | "failed">("pending");
  const [volumeMl, setVolumeMl] = useState<number>(350);
  const [expiryDate, setExpiryDate] = useState<string>("");

  const [isSubmitting, setIsSubmitting] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);

  const filteredUnits = units.filter((u) => {
    const fullGroup = formatBloodGroup(u.blood_group, u.rh_factor);
    if (selectedGroup !== "all" && fullGroup !== selectedGroup) return false;
    if (selectedStatus !== "all" && u.status !== selectedStatus) return false;
    return true;
  });

  // Calculate stock levels per group
  const stockByGroup: Record<string, number> = {};
  BLOOD_GROUPS.forEach((bg) => {
    stockByGroup[bg] = units.filter(
      (u) => formatBloodGroup(u.blood_group, u.rh_factor) === bg && u.status === "available" && u.screening_status === "passed" && u.expiry_date >= new Date().toISOString().slice(0, 10)
    ).length;
  });

  const handleCollect = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    try {
      setIsSubmitting(true);
      await createBloodUnit({
        bag_number: unitNumber.trim(),
        donor_id: donorId,
        blood_group: bloodGroup + rhFactor,
        volume_ml: volumeMl,
        expiry_date: expiryDate,
        screening_status: screening,
      });
      setIsCollectModalOpen(false);
      setUnitNumber(""); setDonorId(""); setExpiryDate(""); setScreening("pending");
      onRefresh();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to add blood unit to inventory.");
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="space-y-6">
      {/* 8-cell Blood Stock Dashboard */}
      <div>
        <h3 className="text-xs font-bold uppercase tracking-wider text-muted-foreground mb-3">
          Available Blood Stock (By ABO / Rh Group)
        </h3>
        <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-8 gap-3">
          {BLOOD_GROUPS.map((bg) => {
            const count = stockByGroup[bg] || 0;
            const isLow = count === 0;
            return (
              <div
                key={bg}
                onClick={() => setSelectedGroup(selectedGroup === bg ? "all" : bg)}
                className={`cursor-pointer rounded-2xl border p-3.5 transition-all text-center ${
                  selectedGroup === bg
                    ? "border-primary bg-primary/10 ring-2 ring-primary"
                    : isLow
                    ? "border-destructive/40 bg-destructive/5 hover:border-destructive"
                    : "border-border bg-card hover:border-primary/50"
                }`}
              >
                <div className="text-sm font-black tracking-tight text-foreground">{bg}</div>
                <div className="text-2xl font-black mt-1 text-foreground">{count}</div>
                <div className="text-[10px] uppercase font-bold text-muted-foreground mt-0.5">
                  {count === 1 ? "unit" : "units"}
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* Filter and Action Header */}
      <div className="flex flex-col sm:flex-row items-stretch sm:items-center justify-between gap-3 bg-card border border-border p-4 rounded-2xl shadow-sm">
        <div className="flex flex-wrap items-center gap-2">
          <div className="flex items-center gap-1 bg-muted p-1 rounded-xl border border-border">
            <span className="text-[11px] font-semibold text-muted-foreground px-2">Group:</span>
            <select
              value={selectedGroup}
              onChange={(e) => setSelectedGroup(e.target.value)}
              className="bg-background text-xs font-semibold rounded-lg px-2 py-1 border-0 focus:ring-1 focus:ring-primary"
            >
              <option value="all">All Groups</option>
              {BLOOD_GROUPS.map((bg) => (
                <option key={bg} value={bg}>
                  {bg}
                </option>
              ))}
            </select>
          </div>

          <div className="flex items-center gap-1 bg-muted p-1 rounded-xl border border-border">
            <span className="text-[11px] font-semibold text-muted-foreground px-2">Status:</span>
            <select
              value={selectedStatus}
              onChange={(e) => setSelectedStatus(e.target.value)}
              className="bg-background text-xs font-semibold rounded-lg px-2 py-1 border-0 focus:ring-1 focus:ring-primary"
            >
              <option value="all">All Statuses</option>
              <option value="available">Available</option>
              <option value="reserved">Reserved</option>
              <option value="issued">Issued</option>
              <option value="quarantined">Quarantine</option>
            </select>
          </div>
        </div>

        <button
          onClick={() => setIsCollectModalOpen(true)}
          className="inline-flex items-center justify-center gap-1.5 rounded-xl bg-rose-600 px-4 py-2 text-xs font-bold text-white shadow-sm hover:bg-rose-500 transition-colors"
        >
          <Plus className="h-4 w-4" />
          Log Blood Unit Collection
        </button>
      </div>

      {/* Units Table */}
      <div className="rounded-2xl border border-border bg-card overflow-hidden shadow-sm">
        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs">
            <thead className="bg-muted/50 text-muted-foreground font-semibold">
              <tr>
                <th className="p-3">Unit / Bag #</th>
                <th className="p-3">Blood Group</th>
                <th className="p-3">Component</th>
                <th className="p-3">Volume</th>
                <th className="p-3">Collected</th>
                <th className="p-3">Expiry</th>
                <th className="p-3">Screening</th>
                <th className="p-3">Status</th>
                <th className="p-3 text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {filteredUnits.length === 0 ? (
                <tr>
                  <td colSpan={9} className="p-8 text-center text-muted-foreground">
                    <Package className="h-8 w-8 mx-auto mb-2 opacity-30 text-rose-500" />
                    No blood units in inventory matching current criteria.
                  </td>
                </tr>
              ) : (
                filteredUnits.map((u) => {
                  const isAvailable = u.status === "available" && u.screening_status === "passed" && u.expiry_date >= new Date().toISOString().slice(0, 10);
                  return (
                    <tr key={u.id} className="hover:bg-muted/30">
                      <td className="p-3 font-mono font-bold text-foreground">
                        {u.bag_number || u.unit_number || u.id.slice(0, 8).toUpperCase()}
                      </td>
                      <td className="p-3">
                        <span className="inline-flex items-center px-2 py-0.5 rounded-full text-[11px] font-black bg-rose-500/10 text-rose-600 dark:text-rose-400">
                          {formatBloodGroup(u.blood_group, u.rh_factor)}
                        </span>
                      </td>
                      <td className="p-3 capitalize text-muted-foreground">
                        {(u.component_type || "Not recorded").replace(/_/g, " ")}
                      </td>
                      <td className="p-3 font-mono">{u.volume_ml} mL</td>
                      <td className="p-3 font-mono text-muted-foreground">
                        {u.collected_at ? u.collected_at.slice(0, 10) : u.collection_date || "—"}
                      </td>
                      <td className="p-3 font-mono text-muted-foreground">{u.expiry_date}</td>
                      <td className="p-3">
                        {u.screening_status === "passed" ? (
                          <span className="inline-flex items-center gap-1 rounded-full bg-emerald-500/10 px-2 py-0.5 text-[10px] font-semibold text-emerald-600 dark:text-emerald-400">
                            <CheckCircle2 className="h-3 w-3" /> Passed
                          </span>
                        ) : (
                          <span className="inline-flex items-center gap-1 rounded-full bg-amber-500/10 px-2 py-0.5 text-[10px] font-semibold text-amber-600 dark:text-amber-400">
                            <Clock className="h-3 w-3" /> {u.screening_status}
                          </span>
                        )}
                      </td>
                      <td className="p-3">
                        <span
                          className={`inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-bold capitalize ${
                            u.status === "available" && u.screening_status === "passed" && u.expiry_date >= new Date().toISOString().slice(0, 10)
                              ? "bg-emerald-500/10 text-emerald-600 dark:text-emerald-400"
                              : u.status === "reserved"
                              ? "bg-amber-500/10 text-amber-600 dark:text-amber-400"
                              : u.status === "issued"
                              ? "bg-blue-500/10 text-blue-600 dark:text-blue-400"
                              : "bg-muted text-muted-foreground"
                          }`}
                        >
                          {u.status}
                        </span>
                      </td>
                      <td className="p-3 text-right">
                        {isAvailable ? (
                          <button
                            onClick={() => onOpenCrossmatch(u)}
                            className="inline-flex items-center gap-1 rounded-lg bg-primary/10 px-2.5 py-1 text-xs font-semibold text-primary hover:bg-primary hover:text-primary-foreground transition-colors"
                          >
                            <TestTube className="h-3.5 w-3.5" />
                            Crossmatch
                          </button>
                        ) : (
                          <span className="text-muted-foreground text-[11px]">—</span>
                        )}
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* Collect Unit Modal */}
      {isCollectModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4">
          <div className="w-full max-w-lg rounded-2xl border border-border bg-card p-6 shadow-2xl animate-in fade-in zoom-in-95 duration-200">
            <div className="flex items-center justify-between pb-4 border-b border-border">
              <div className="flex items-center gap-2">
                <Droplet className="h-5 w-5 text-rose-500" />
                <h3 className="text-lg font-bold text-card-foreground">Log Collected Blood Unit</h3>
              </div>
              <button
                onClick={() => setIsCollectModalOpen(false)}
                className="rounded-lg p-1.5 text-muted-foreground hover:bg-muted hover:text-foreground transition-colors"
              >
                <X className="h-5 w-5" />
              </button>
            </div>

            {error && (
              <div className="mt-4 flex items-center gap-2 rounded-lg bg-destructive/10 p-3 text-sm text-destructive border border-destructive/20">
                <AlertTriangle className="h-4 w-4 shrink-0" />
                <span>{error}</span>
              </div>
            )}

            <form onSubmit={handleCollect} className="mt-4 space-y-4">
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-1">
                    Unit ID Number *
                  </label>
                  <input
                    type="text"
                    value={unitNumber}
                    onChange={(e) => setUnitNumber(e.target.value)}
                    className="w-full rounded-lg border border-input bg-background px-3 py-2 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-primary"
                    required
                  />
                </div>
                <div>
                  <label className="block text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-1">
                    Donor *
                  </label>
                  <select
                    value={donorId}
                    required
                    onChange={(e) => { setDonorId(e.target.value); const group = donors.find((d) => d.id === e.target.value)?.blood_group; if (group) { setBloodGroup(group.slice(0, -1)); setRhFactor(group.slice(-1)); } }}
                    className="w-full rounded-lg border border-input bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary"
                  >
                    <option value="">Select an eligible donor</option>
                    {donors.filter((d) => d.is_eligible).map((d) => (
                      <option key={d.id} value={d.id}>
                        {d.donor_number} — {d.full_name} ({d.blood_group}
                        {d.rh_factor})
                      </option>
                    ))}
                  </select>
                </div>
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-1">
                    ABO Blood Group *
                  </label>
                  <select
                    value={bloodGroup}
                    onChange={(e) => setBloodGroup(e.target.value)}
                    className="w-full rounded-lg border border-input bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary"
                  >
                    <option value="A">A</option>
                    <option value="B">B</option>
                    <option value="AB">AB</option>
                    <option value="O">O</option>
                  </select>
                </div>
                <div>
                  <label className="block text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-1">
                    Rh Factor *
                  </label>
                  <select
                    value={rhFactor}
                    onChange={(e) => setRhFactor(e.target.value)}
                    className="w-full rounded-lg border border-input bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary"
                  >
                    <option value="+">Positive (+)</option>
                    <option value="-">Negative (-)</option>
                  </select>
                </div>
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-1">
                    Screening Result *
                  </label>
                  <select aria-label="Screening result" value={screening} onChange={(e) => setScreening(e.target.value as "pending" | "passed" | "failed")}>
                    <option value="pending">Pending</option><option value="passed">Passed (verified)</option><option value="failed">Failed</option>
                  </select>
                </div>
                <div>
                  <label className="block text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-1">
                    Volume (mL) *
                  </label>
                  <input
                    type="number"
                    min="100"
                    max="1000"
                    value={volumeMl}
                    onChange={(e) => setVolumeMl(parseInt(e.target.value) || 350)}
                    className="w-full rounded-lg border border-input bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary"
                    required
                  />
                </div>
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-1">
                    Collection time
                  </label>
                  <p className="text-xs">Recorded as the current time. Historical collection and component-specific tracking are not supported by this form.</p>
                </div>
                <div>
                  <label className="block text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-1">
                    Expiry Date *
                  </label>
                  <input
                    type="date"
                    value={expiryDate}
                    onChange={(e) => setExpiryDate(e.target.value)}
                    className="w-full rounded-lg border border-input bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary"
                    required
                  />
                </div>
              </div>

              <div className="flex items-center justify-end gap-3 pt-4 border-t border-border">
                <button
                  type="button"
                  onClick={() => setIsCollectModalOpen(false)}
                  className="rounded-lg border border-border px-4 py-2 text-sm font-medium text-muted-foreground hover:bg-muted transition-colors"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={isSubmitting}
                  className="flex items-center gap-2 rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 transition-colors disabled:opacity-50"
                >
                  <CheckCircle2 className="h-4 w-4" />
                  {isSubmitting ? "Storing..." : "Add to Stock"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
