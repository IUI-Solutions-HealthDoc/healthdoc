"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { AlertCircle, Droplets, Heart, Package, RefreshCw } from "lucide-react";
import { fetchBloodDonors, fetchBloodUnits } from "./api";
import { BloodCrossmatchModal } from "./components/BloodCrossmatchModal";
import { BloodDonorRegistry } from "./components/BloodDonorRegistry";
import { BloodInventoryGrid } from "./components/BloodInventoryGrid";
import { useLocale } from "@/lib/i18n";
import type { BloodDonor, BloodUnit } from "./types";

export function BloodBankPage() {
  const { t } = useLocale();
  const [activeTab, setActiveTab] = useState<"inventory" | "donors">("inventory");
  const [units, setUnits] = useState<BloodUnit[]>([]);
  const [donors, setDonors] = useState<BloodDonor[]>([]);
  const [loading, setLoading] = useState(true);
  const [loaded, setLoaded] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const loadSequence = useRef(0);

  const [selectedUnitForXm, setSelectedUnitForXm] = useState<BloodUnit | null>(null);

  // A refused or failed inventory read is not an empty blood bank. The tab
  // counts and grids only describe data that actually arrived, and a refresh
  // after a save no longer replaces the page with a spinner.
  const loadData = useCallback(async () => {
    const request = ++loadSequence.current;
    setLoadError(null);
    try {
      const [u, d] = await Promise.all([fetchBloodUnits(), fetchBloodDonors()]);
      if (request !== loadSequence.current) return;
      setUnits(u);
      setDonors(d);
      setLoaded(true);
    } catch (err: unknown) {
      if (request === loadSequence.current)
        setLoadError(err instanceof Error && err.message ? err.message : "Blood bank data could not be loaded.");
    } finally {
      if (request === loadSequence.current) setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadData();
  }, [loadData]);

  return (
    <div className="space-y-6">
      {/* Top Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-black tracking-tight text-foreground flex items-center gap-2">
            <Droplets className="h-7 w-7 text-rose-500" />
            {t("bloodBank.title")}
          </h1>
          <p className="text-xs text-muted-foreground mt-1">
            {t("bloodBank.subtitle")}
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
            {t("bloodBank.tab.inventory", { count: loaded ? units.length : "—" })}
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
            {t("bloodBank.tab.donors", { count: loaded ? donors.length : "—" })}
          </button>
        </div>
      </div>

      {loading ? (
        <div className="flex items-center justify-center p-16 text-muted-foreground">
          <RefreshCw className="h-6 w-6 animate-spin mr-2" />
          <span>{t("bloodBank.loading")}</span>
        </div>
      ) : loadError && !loaded ? (
        <div role="alert" className="rounded-2xl border border-destructive/30 bg-destructive/10 p-8 text-center text-sm text-destructive space-y-3">
          <AlertCircle className="h-8 w-8 mx-auto" />
          <p>Blood bank data could not be loaded: {loadError}</p>
          <p className="text-xs text-muted-foreground">This is not an empty inventory. Units and donors are unknown until the load succeeds.</p>
          <button
            type="button"
            onClick={() => void loadData()}
            className="rounded-xl border border-destructive/40 px-4 py-2 text-xs font-semibold hover:bg-destructive/10 transition-colors"
          >
            Retry loading blood bank data
          </button>
        </div>
      ) : (
        <>
          {loadError && (
            <p role="alert" className="flex items-center gap-2 rounded-xl border border-destructive/30 bg-destructive/10 p-3 text-xs text-destructive">
              <AlertCircle className="h-3.5 w-3.5 shrink-0" />
              The latest refresh failed: {loadError}. Units and donors shown may be out of date.
            </p>
          )}
          {activeTab === "inventory" ? (
            <BloodInventoryGrid
              units={units}
              donors={donors}
              onRefresh={loadData}
              onOpenCrossmatch={(u) => setSelectedUnitForXm(u)}
            />
          ) : (
            <BloodDonorRegistry donors={donors} onRefresh={loadData} />
          )}
        </>
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
