"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  Filter,
  Package,
  Plus,
  RotateCcw,
  Search,
  ShieldAlert,
  User,
  X,
} from "lucide-react";

import { ModuleCapabilityGate } from "@/components/common/ModuleCapabilityGate";
import { PageHeading } from "@/components/common/PageHeading";
import {
  createPharmacyReturn,
  listPharmacyReturns,
  searchMedicines,
} from "@/features/pharmacy/api";
import type {
  MedicineSearchResult,
  PharmacyReturn,
  PharmacyReturnCreateInput,
} from "@/features/pharmacy/types";
import { searchPatients } from "@/features/receptionist/api";
import type { PatientSearchResult } from "@/features/receptionist/types";
import { ApiError, formatDateTime } from "@/lib/api";
import { useLocale, type MessageKey } from "@/lib/i18n";

function DispositionBadge({ disposition }: { disposition: string }) {
  const { t } = useLocale();
  if (disposition === "resalable") {
    return (
      <span className="inline-flex items-center gap-1 rounded-full bg-success-muted px-2.5 py-0.5 text-xs font-medium text-success">
        <CheckCircle2 className="h-3 w-3" />
        {t("pharmacy.returns.badge.resalable")}
      </span>
    );
  }
  if (disposition === "quarantine") {
    return (
      <span className="inline-flex items-center gap-1 rounded-full bg-warning-muted px-2.5 py-0.5 text-xs font-medium text-warning">
        <ShieldAlert className="h-3 w-3" />
        {t("pharmacy.returns.badge.quarantine")}
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1 rounded-full bg-danger-muted px-2.5 py-0.5 text-xs font-medium text-danger">
      <AlertTriangle className="h-3 w-3" />
      {t("pharmacy.returns.badge.scrapped", {
        disposition: disposition.charAt(0).toUpperCase() + disposition.slice(1),
      })}
    </span>
  );
}

const DISPOSITION_FILTERS: { id: string; labelKey: MessageKey }[] = [
  { id: "all", labelKey: "pharmacy.returns.disposition.all" },
  { id: "resalable", labelKey: "pharmacy.returns.disposition.resalable" },
  { id: "quarantine", labelKey: "pharmacy.returns.disposition.quarantine" },
  { id: "damaged", labelKey: "pharmacy.returns.disposition.damaged" },
  { id: "expired", labelKey: "pharmacy.returns.disposition.expired" },
];

function PharmacyReturnsContent() {
  const { t } = useLocale();
  const [returns, setReturns] = useState<PharmacyReturn[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [filterDisposition, setFilterDisposition] = useState<string>("all");
  const [searchQuery, setSearchQuery] = useState("");

  // Modal State
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  // Form Fields
  const [patientSearch, setPatientSearch] = useState("");
  const [patientMatches, setPatientMatches] = useState<PatientSearchResult[]>([]);
  const [selectedPatient, setSelectedPatient] = useState<PatientSearchResult | null>(null);

  const [medicineSearch, setMedicineSearch] = useState("");
  const [medicineMatches, setMedicineMatches] = useState<MedicineSearchResult[]>([]);
  const [selectedMedicine, setSelectedMedicine] = useState<MedicineSearchResult | null>(null);

  const [selectedBatchId, setSelectedBatchId] = useState<string>("");
  const [quantity, setQuantity] = useState<string>("1");
  const [reason, setReason] = useState<string>("");
  const [disposition, setDisposition] = useState<"resalable" | "quarantine" | "damaged" | "expired">("resalable");

  const loadReturns = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await listPharmacyReturns({
        disposition: filterDisposition !== "all" ? filterDisposition : undefined,
      });
      setReturns(res.items);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : t("pharmacy.errLoadReturns"));
      setReturns([]);
    } finally {
      setLoading(false);
    }
  }, [filterDisposition]);

  useEffect(() => {
    void loadReturns();
  }, [loadReturns]);

  // Patient live search
  useEffect(() => {
    const term = patientSearch.trim();
    if (!term || selectedPatient) {
      setPatientMatches([]);
      return;
    }
    const timer = setTimeout(async () => {
      try {
        const res = await searchPatients({ full_name: term });
        setPatientMatches(res.items);
      } catch {
        setPatientMatches([]);
      }
    }, 300);
    return () => clearTimeout(timer);
  }, [patientSearch, selectedPatient]);

  // Medicine live search
  useEffect(() => {
    const term = medicineSearch.trim();
    if (!term || selectedMedicine) {
      setMedicineMatches([]);
      return;
    }
    const timer = setTimeout(async () => {
      try {
        const res = await searchMedicines(term);
        setMedicineMatches(res.items);
      } catch {
        setMedicineMatches([]);
      }
    }, 300);
    return () => clearTimeout(timer);
  }, [medicineSearch, selectedMedicine]);

  function handleSelectMedicine(med: MedicineSearchResult) {
    setSelectedMedicine(med);
    setMedicineSearch(med.name);
    setMedicineMatches([]);
    if (med.batches && med.batches.length > 0) {
      setSelectedBatchId(med.batches[0].batch_id);
    } else {
      setSelectedBatchId("");
    }
  }

  function handleSelectPatient(pat: PatientSearchResult) {
    setSelectedPatient(pat);
    setPatientSearch(`${pat.full_name} (${pat.uhid ?? "No UHID"})`);
    setPatientMatches([]);
  }

  function resetForm() {
    setSelectedPatient(null);
    setPatientSearch("");
    setPatientMatches([]);
    setSelectedMedicine(null);
    setMedicineSearch("");
    setMedicineMatches([]);
    setSelectedBatchId("");
    setQuantity("1");
    setReason("");
    setDisposition("resalable");
    setFormError(null);
  }

  async function handleCreateReturn(e: React.FormEvent) {
    e.preventDefault();
    if (!selectedPatient) {
      setFormError("Please select a patient.");
      return;
    }
    if (!selectedMedicine) {
      setFormError("Please select a medicine.");
      return;
    }
    const qtyNum = parseFloat(quantity);
    if (isNaN(qtyNum) || qtyNum <= 0) {
      setFormError("Quantity must be a positive number.");
      return;
    }
    if (!reason.trim()) {
      setFormError("Please specify a reason for return.");
      return;
    }

    setSubmitting(true);
    setFormError(null);
    try {
      const payload: PharmacyReturnCreateInput = {
        patient_id: selectedPatient.id,
        item_id: selectedMedicine.item_id,
        batch_id: selectedBatchId || null,
        quantity: qtyNum,
        return_reason: reason.trim(),
        disposition,
      };
      await createPharmacyReturn(payload);
      setIsModalOpen(false);
      resetForm();
      await loadReturns();
    } catch (err) {
      setFormError(err instanceof Error ? err.message : t("pharmacy.errRecordReturn"));
    } finally {
      setSubmitting(false);
    }
  }

  const filteredReturns = useMemo(() => {
    let list = returns;
    if (searchQuery.trim()) {
      const q = searchQuery.toLowerCase().trim();
      list = list.filter(
        (r) =>
          (r.item_name && r.item_name.toLowerCase().includes(q)) ||
          (r.batch_number && r.batch_number.toLowerCase().includes(q)) ||
          r.return_reason.toLowerCase().includes(q) ||
          r.patient_id.toLowerCase().includes(q),
      );
    }
    return list;
  }, [returns, searchQuery]);

  const metrics = useMemo(() => {
    const total = returns.length;
    const resalable = returns.filter((r) => r.disposition === "resalable").length;
    const quarantine = returns.filter((r) => r.disposition === "quarantine").length;
    const scrap = returns.filter((r) => r.disposition === "damaged" || r.disposition === "expired").length;
    return { total, resalable, quarantine, scrap };
  }, [returns]);

  return (
    <main className="space-y-6 p-6">
      {/* Header */}
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <div className="flex items-center gap-2">
            <RotateCcw className="h-6 w-6 text-primary" />
            <PageHeading titleKey="pharmacy.returnsTitle" titleClassName="text-2xl font-bold tracking-tight" />
          </div>
          <p className="mt-1 text-sm text-muted-foreground">{t("pharmacy.returns.subtitle")}</p>
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => void loadReturns()}
            className="rounded-md border border-border bg-background px-3 py-1.5 text-sm font-medium hover:bg-muted"
          >
            {t("common.refresh")}
          </button>
          <button
            type="button"
            onClick={() => {
              resetForm();
              setIsModalOpen(true);
            }}
            className="flex items-center gap-1.5 rounded-md bg-primary px-3.5 py-1.5 text-sm font-medium text-primary-foreground shadow hover:bg-primary/90"
          >
            <Plus className="h-4 w-4" />
            {t("pharmacy.returns.processReturn")}
          </button>
        </div>
      </div>

      {/* Metrics Row */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-4">
        <div className="rounded-lg border border-border bg-card p-4">
          <p className="text-xs font-medium text-muted-foreground uppercase">{t("pharmacy.returns.totalReturns")}</p>
          <p className="mt-1 text-2xl font-bold">{metrics.total}</p>
        </div>
        <div className="rounded-lg border border-border bg-card p-4">
          <div className="flex items-center justify-between">
            <p className="text-xs font-medium text-muted-foreground uppercase">{t("pharmacy.returns.restocked")}</p>
            <CheckCircle2 className="h-4 w-4 text-success" />
          </div>
          <p className="mt-1 text-2xl font-bold text-success">{metrics.resalable}</p>
        </div>
        <div className="rounded-lg border border-border bg-card p-4">
          <div className="flex items-center justify-between">
            <p className="text-xs font-medium text-muted-foreground uppercase">{t("pharmacy.returns.quarantined")}</p>
            <ShieldAlert className="h-4 w-4 text-warning" />
          </div>
          <p className="mt-1 text-2xl font-bold text-warning">{metrics.quarantine}</p>
        </div>
        <div className="rounded-lg border border-border bg-card p-4">
          <div className="flex items-center justify-between">
            <p className="text-xs font-medium text-muted-foreground uppercase">{t("pharmacy.returns.scrappedExpired")}</p>
            <AlertTriangle className="h-4 w-4 text-danger" />
          </div>
          <p className="mt-1 text-2xl font-bold text-danger">{metrics.scrap}</p>
        </div>
      </div>

      {/* Filter and Search Bar */}
      <div className="flex flex-col gap-3 rounded-lg border border-border bg-card p-4 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex items-center gap-2">
          <Filter className="h-4 w-4 text-muted-foreground" />
          <span className="text-xs font-medium text-muted-foreground">{t("pharmacy.returns.filterByDisposition")}</span>
          <div className="flex flex-wrap gap-1">
            {DISPOSITION_FILTERS.map((f) => (
              <button
                key={f.id}
                type="button"
                onClick={() => setFilterDisposition(f.id)}
                className={`rounded px-2.5 py-1 text-xs font-medium transition-colors ${
                  filterDisposition === f.id
                    ? "bg-primary text-primary-foreground"
                    : "bg-muted text-muted-foreground hover:text-foreground"
                }`}
              >
                {t(f.labelKey)}
              </button>
            ))}
          </div>
        </div>

        <div className="relative w-full sm:w-72">
          <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
          <input
            type="text"
            placeholder={t("pharmacy.returns.searchPlaceholder")}
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="w-full rounded-md border border-input bg-background pl-8 pr-3 py-1.5 text-xs placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-ring"
          />
        </div>
      </div>

      {/* Returns Table */}
      <div className="rounded-lg border border-border bg-card overflow-hidden">
        {loading ? (
          <div className="p-8 text-center text-sm text-muted-foreground">{t("pharmacy.returns.loading")}</div>
        ) : error ? (
          <div className="p-8 text-center text-sm text-danger">{error}</div>
        ) : filteredReturns.length === 0 ? (
          <div className="p-8 text-center text-sm text-muted-foreground">
            {t("pharmacy.returns.empty")}
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead className="border-b border-border bg-muted/50 text-xs font-medium text-muted-foreground">
                <tr>
                  <th className="px-4 py-3">{t("pharmacy.returns.col.dateTime")}</th>
                  <th className="px-4 py-3">{t("pharmacy.returns.col.medicine")}</th>
                  <th className="px-4 py-3">{t("pharmacy.returns.col.batch")}</th>
                  <th className="px-4 py-3">{t("pharmacy.returns.col.qty")}</th>
                  <th className="px-4 py-3">{t("pharmacy.returns.col.disposition")}</th>
                  <th className="px-4 py-3">{t("pharmacy.returns.col.reason")}</th>
                  <th className="px-4 py-3">{t("pharmacy.returns.col.status")}</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {filteredReturns.map((item) => (
                  <tr key={item.id} className="hover:bg-muted/30 transition-colors">
                    <td className="px-4 py-3 text-xs text-muted-foreground">
                      {formatDateTime(item.created_at)}
                    </td>
                    <td className="px-4 py-3">
                      <div className="font-medium text-foreground">
                        {item.item_name ?? <span className="font-mono text-xs">{item.item_id.slice(0, 8)}…</span>}
                      </div>
                      <div className="text-[11px] text-muted-foreground font-mono">
                        Pat: {item.patient_id.slice(0, 8)}…
                      </div>
                    </td>
                    <td className="px-4 py-3 font-mono text-xs">
                      {item.batch_number ?? (item.batch_id ? item.batch_id.slice(0, 8) + "…" : "—")}
                    </td>
                    <td className="px-4 py-3 font-semibold text-foreground">
                      {item.quantity}
                    </td>
                    <td className="px-4 py-3">
                      <DispositionBadge disposition={item.disposition} />
                    </td>
                    <td className="px-4 py-3 text-xs text-muted-foreground max-w-xs truncate" title={item.return_reason}>
                      {item.return_reason}
                    </td>
                    <td className="px-4 py-3">
                      <span className="rounded bg-muted px-2 py-0.5 text-xs text-muted-foreground uppercase font-mono">
                        {item.status}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Process Return Modal */}
      {isModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
          <div className="relative w-full max-w-lg rounded-xl border border-border bg-card p-6 shadow-2xl">
            <button
              type="button"
              onClick={() => setIsModalOpen(false)}
              className="absolute right-4 top-4 text-muted-foreground hover:text-foreground"
            >
              <X className="h-5 w-5" />
            </button>

            <div className="flex items-center gap-2">
              <RotateCcw className="h-5 w-5 text-primary" />
              <h2 className="text-lg font-semibold">{t("pharmacy.returns.modal.title")}</h2>
            </div>
            <p className="mt-1 text-xs text-muted-foreground">{t("pharmacy.returns.modal.hint")}</p>

            {formError && (
              <div className="mt-4 rounded-md border border-danger/20 bg-danger-muted p-2.5 text-xs text-danger">
                {formError}
              </div>
            )}

            <form onSubmit={handleCreateReturn} className="mt-4 space-y-4">
              {/* Patient Selection */}
              <div>
                <label className="block text-xs font-medium text-foreground">
                  {t("common.patient")} <span className="text-danger">*</span>
                </label>
                <div className="relative mt-1">
                  <User className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
                  <input
                    type="text"
                    placeholder={t("pharmacy.returns.modal.patientSearch")}
                    value={patientSearch}
                    onChange={(e) => {
                      setPatientSearch(e.target.value);
                      if (selectedPatient) setSelectedPatient(null);
                    }}
                    className="w-full rounded-md border border-input bg-background pl-8 pr-3 py-1.5 text-xs focus:outline-none focus:ring-1 focus:ring-ring"
                    required
                  />
                  {patientMatches.length > 0 && !selectedPatient && (
                    <div className="absolute z-10 mt-1 max-h-40 w-full overflow-auto rounded-md border border-border bg-popover p-1 shadow-lg text-xs">
                      {patientMatches.map((p) => (
                        <button
                          key={p.id}
                          type="button"
                          onClick={() => handleSelectPatient(p)}
                          className="w-full text-left px-2 py-1.5 hover:bg-muted rounded text-foreground flex justify-between"
                        >
                          <span className="font-medium">{p.full_name}</span>
                          <span className="text-muted-foreground font-mono">
                            {p.uhid ?? t("pharmacy.returns.noUhid")}
                          </span>
                        </button>
                      ))}
                    </div>
                  )}
                </div>
                {selectedPatient && (
                  <p className="mt-1 text-[11px] text-success">
                    {t("pharmacy.returns.modal.selectedPatient", {
                      name: selectedPatient.full_name,
                      uhid: selectedPatient.uhid ?? "N/A",
                    })}
                  </p>
                )}
              </div>

              {/* Medicine Selection */}
              <div>
                <label className="block text-xs font-medium text-foreground">
                  {t("pharmacy.returns.col.medicine")} <span className="text-danger">*</span>
                </label>
                <div className="relative mt-1">
                  <Package className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
                  <input
                    type="text"
                    placeholder={t("pharmacy.returns.modal.medicineSearch")}
                    value={medicineSearch}
                    onChange={(e) => {
                      setMedicineSearch(e.target.value);
                      if (selectedMedicine) setSelectedMedicine(null);
                    }}
                    className="w-full rounded-md border border-input bg-background pl-8 pr-3 py-1.5 text-xs focus:outline-none focus:ring-1 focus:ring-ring"
                    required
                  />
                  {medicineMatches.length > 0 && !selectedMedicine && (
                    <div className="absolute z-10 mt-1 max-h-40 w-full overflow-auto rounded-md border border-border bg-popover p-1 shadow-lg text-xs">
                      {medicineMatches.map((m) => (
                        <button
                          key={m.item_id}
                          type="button"
                          onClick={() => handleSelectMedicine(m)}
                          className="w-full text-left px-2 py-1.5 hover:bg-muted rounded text-foreground flex flex-col"
                        >
                          <span className="font-medium">{m.name}</span>
                          <span className="text-muted-foreground text-[10px]">
                            {m.form ?? "Item"} • Avail: {m.total_available_quantity} • Batches: {m.batches?.length ?? 0}
                          </span>
                        </button>
                      ))}
                    </div>
                  )}
                </div>
                {selectedMedicine && (
                  <p className="mt-1 text-[11px] text-success">
                    {t("pharmacy.returns.modal.selectedMedicine", {
                      name: selectedMedicine.name,
                      form: selectedMedicine.form ?? "Medicine",
                    })}
                  </p>
                )}
              </div>

              {/* Batch selection */}
              {selectedMedicine && selectedMedicine.batches && selectedMedicine.batches.length > 0 && (
                <div>
                  <label className="block text-xs font-medium text-foreground">
                    {t("pharmacy.returns.col.batch")}
                  </label>
                  <select
                    value={selectedBatchId}
                    onChange={(e) => setSelectedBatchId(e.target.value)}
                    className="mt-1 w-full rounded-md border border-input bg-background px-3 py-1.5 text-xs focus:outline-none focus:ring-1 focus:ring-ring"
                  >
                    <option value="">{t("pharmacy.returns.modal.noBatch")}</option>
                    {selectedMedicine.batches.map((b) => (
                      <option key={b.batch_id} value={b.batch_id}>
                        Batch {b.batch_number} (Exp: {b.expiry_date}, Qty: {b.quantity})
                      </option>
                    ))}
                  </select>
                </div>
              )}

              {/* Quantity */}
              <div>
                <label className="block text-xs font-medium text-foreground">
                  {t("pharmacy.returns.modal.returnedQty")} <span className="text-danger">*</span>
                </label>
                <input
                  type="number"
                  min="0.01"
                  step="any"
                  value={quantity}
                  onChange={(e) => setQuantity(e.target.value)}
                  className="mt-1 w-full rounded-md border border-input bg-background px-3 py-1.5 text-xs focus:outline-none focus:ring-1 focus:ring-ring"
                  required
                />
              </div>

              {/* Disposition */}
              <div>
                <label className="block text-xs font-medium text-foreground">
                  {t("pharmacy.returns.col.disposition")} <span className="text-danger">*</span>
                </label>
                <div className="mt-1 grid grid-cols-2 gap-2 text-xs">
                  <label
                    className={`flex cursor-pointer items-center gap-2 rounded-lg border p-2.5 transition-colors ${
                      disposition === "resalable"
                        ? "border-success bg-success-muted text-success"
                        : "border-border hover:bg-muted/40"
                    }`}
                  >
                    <input
                      type="radio"
                      name="disposition"
                      value="resalable"
                      checked={disposition === "resalable"}
                      onChange={() => setDisposition("resalable")}
                      className="hidden"
                    />
                    <CheckCircle2 className="h-4 w-4 flex-shrink-0" />
                    <div>
                      <p className="font-semibold">{t("pharmacy.returns.disposition.resalable")}</p>
                      <p className="text-[10px] opacity-80">
                        {t("pharmacy.returns.disposition.restockHint")}
                      </p>
                    </div>
                  </label>

                  <label
                    className={`flex cursor-pointer items-center gap-2 rounded-lg border p-2.5 transition-colors ${
                      disposition === "quarantine"
                        ? "border-warning bg-warning-muted text-warning"
                        : "border-border hover:bg-muted/40"
                    }`}
                  >
                    <input
                      type="radio"
                      name="disposition"
                      value="quarantine"
                      checked={disposition === "quarantine"}
                      onChange={() => setDisposition("quarantine")}
                      className="hidden"
                    />
                    <ShieldAlert className="h-4 w-4 flex-shrink-0" />
                    <div>
                      <p className="font-semibold">{t("pharmacy.returns.disposition.quarantine")}</p>
                      <p className="text-[10px] opacity-80">
                        {t("pharmacy.returns.disposition.quarantineHint")}
                      </p>
                    </div>
                  </label>

                  <label
                    className={`flex cursor-pointer items-center gap-2 rounded-lg border p-2.5 transition-colors ${
                      disposition === "damaged"
                        ? "border-danger bg-danger-muted text-danger"
                        : "border-border hover:bg-muted/40"
                    }`}
                  >
                    <input
                      type="radio"
                      name="disposition"
                      value="damaged"
                      checked={disposition === "damaged"}
                      onChange={() => setDisposition("damaged")}
                      className="hidden"
                    />
                    <AlertTriangle className="h-4 w-4 flex-shrink-0" />
                    <div>
                      <p className="font-semibold">{t("pharmacy.returns.disposition.damaged")}</p>
                      <p className="text-[10px] opacity-80">
                        {t("pharmacy.returns.disposition.damagedHint")}
                      </p>
                    </div>
                  </label>

                  <label
                    className={`flex cursor-pointer items-center gap-2 rounded-lg border p-2.5 transition-colors ${
                      disposition === "expired"
                        ? "border-danger bg-danger-muted text-danger"
                        : "border-border hover:bg-muted/40"
                    }`}
                  >
                    <input
                      type="radio"
                      name="disposition"
                      value="expired"
                      checked={disposition === "expired"}
                      onChange={() => setDisposition("expired")}
                      className="hidden"
                    />
                    <AlertTriangle className="h-4 w-4 flex-shrink-0" />
                    <div>
                      <p className="font-semibold">{t("pharmacy.returns.disposition.expired")}</p>
                      <p className="text-[10px] opacity-80">
                        {t("pharmacy.returns.disposition.expiredHint")}
                      </p>
                    </div>
                  </label>
                </div>
              </div>

              {/* Reason */}
              <div>
                <label className="block text-xs font-medium text-foreground">
                  {t("pharmacy.returns.modal.reasonLabel")} <span className="text-danger">*</span>
                </label>
                <input
                  type="text"
                  placeholder={t("pharmacy.returns.modal.reasonPlaceholder")}
                  value={reason}
                  onChange={(e) => setReason(e.target.value)}
                  className="mt-1 w-full rounded-md border border-input bg-background px-3 py-1.5 text-xs focus:outline-none focus:ring-1 focus:ring-ring"
                  required
                />
              </div>

              {/* Submit Buttons */}
              <div className="flex items-center justify-end gap-2 pt-2">
                <button
                  type="button"
                  onClick={() => setIsModalOpen(false)}
                  disabled={submitting}
                  className="rounded-md border border-border px-3 py-1.5 text-xs font-medium hover:bg-muted"
                >
                  {t("common.cancel")}
                </button>
                <button
                  type="submit"
                  disabled={submitting}
                  className="rounded-md bg-primary px-4 py-1.5 text-xs font-medium text-primary-foreground shadow hover:bg-primary/90 disabled:opacity-50"
                >
                  {submitting
                    ? t("pharmacy.returns.modal.processing")
                    : t("pharmacy.returns.modal.confirmReturn")}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </main>
  );
}

export default function PharmacyReturnsPage() {
  return (
    <ModuleCapabilityGate module="pharmacy">
      <PharmacyReturnsContent />
    </ModuleCapabilityGate>
  );
}
