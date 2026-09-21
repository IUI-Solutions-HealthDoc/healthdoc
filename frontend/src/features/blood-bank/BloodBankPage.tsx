"use client";

import { useEffect, useState } from "react";
import { Droplets, Heart, Package, RefreshCw } from "lucide-react";
import { fetchBloodDonors, fetchBloodUnits } from "./api";
import { BloodCrossmatchModal } from "./components/BloodCrossmatchModal";
import { BloodDonorRegistry } from "./components/BloodDonorRegistry";
import { BloodInventoryGrid } from "./components/BloodInventoryGrid";
import type { BloodDonor, BloodUnit } from "./types";

export function BloodBankPage() {
  const [activeTab, setActiveTab] = useState<"inventory" | "donors">("inventory");
  const [units, setUnits] = useState<BloodUnit[]>([]);
  const [donors, setDonors] = useState<BloodDonor[]>([]);
  const [loading, setLoading] = useState(true);

  const [selectedUnitForXm, setSelectedUnitForXm] = useState<BloodUnit | null>(null);

  const loadData = async () => {
    try {
      setLoading(true);
      const [u, d] = await Promise.all([fetchBloodUnits(), fetchBloodDonors()]);
      setUnits(u);
      setDonors(d);
    } catch (err) {
      console.error("Failed to load blood bank data:", err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadData();
  }, []);

  return (
    <div className="space-y-6">
      {/* Top Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-black tracking-tight text-foreground flex items-center gap-2">
            <Droplets className="h-7 w-7 text-rose-500" />
            Blood Bank & Transfusion Services
          </h1>
          <p className="text-xs text-muted-foreground mt-1">
            Donor screening, component inventory, crossmatching & controlled release slips (HD-29)
          </p>
        </div>

        {/* Navigation Tabs */}
        <div className="inline-flex rounded-xl bg-muted p-1 border border-border">
          <button
            onClick={() => setActiveTab("inventory")}
            className={`flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-semibold transition-all ${
              activeTab === "inventory"
                ? "bg-background text-foreground shadow-sm"
                : "text-muted-foreground hover:text-foreground"
            }`}
          >
            <Package className="h-3.5 w-3.5 text-rose-500" />
            Unit Inventory ({units.length})
          </button>
          <button
            onClick={() => setActiveTab("donors")}
            className={`flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-semibold transition-all ${
              activeTab === "donors"
                ? "bg-background text-foreground shadow-sm"
                : "text-muted-foreground hover:text-foreground"
            }`}
          >
            <Heart className="h-3.5 w-3.5 text-rose-500" />
            Donor Registry ({donors.length})
          </button>
        </div>
      </div>

      {loading ? (
        <div className="flex items-center justify-center p-16 text-muted-foreground">
          <RefreshCw className="h-6 w-6 animate-spin mr-2" />
          <span>Loading blood bank data...</span>
        </div>
      ) : activeTab === "inventory" ? (
        <BloodInventoryGrid
          units={units}
          donors={donors}
          onRefresh={loadData}
          onOpenCrossmatch={(u) => setSelectedUnitForXm(u)}
        />
      ) : (
        <BloodDonorRegistry donors={donors} onRefresh={loadData} />
      )}

      {/* Crossmatch Modal */}
      <BloodCrossmatchModal key={selectedUnitForXm?.id || "closed"}
        isOpen={!!selectedUnitForXm}
        onClose={() => setSelectedUnitForXm(null)}
        unit={selectedUnitForXm}
        onSuccess={loadData}
      />
    </div>
  );
}
