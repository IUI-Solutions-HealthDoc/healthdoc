"use client";

import { useCallback, useEffect, useState } from "react";
import { toast } from "@/components/ui/toast";
import { formatDateTime } from "@/lib/api";
import {
  listScanShareTickets,
  getScanShareTicket,
  checkInScanShareTicket,
  type ScanShareTicketItem,
} from "./api";

export interface ScanShareDeskModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSelectForRegistration?: (ticket: ScanShareTicketItem) => void;
}

export function ScanShareDeskModal({
  isOpen,
  onClose,
  onSelectForRegistration,
}: ScanShareDeskModalProps) {
  const [tickets, setTickets] = useState<ScanShareTicketItem[]>([]);
  const [selectedTicket, setSelectedTicket] = useState<ScanShareTicketItem | null>(null);
  const [loading, setLoading] = useState(false);
  const [checkingIn, setCheckingIn] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState<"active" | "checked_in" | "all">("active");
  const [counterId, setCounterId] = useState("COUNTER-1");

  const loadTickets = useCallback(async () => {
    setLoading(true);
    try {
      const res = await listScanShareTickets(statusFilter === "all" ? "" : statusFilter);
      setTickets(res.items);
      if (res.items.length > 0 && !selectedTicket) {
        setSelectedTicket(res.items[0]);
      }
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to load Scan & Share tickets");
    } finally {
      setLoading(false);
    }
  }, [statusFilter, selectedTicket]);

  useEffect(() => {
    if (isOpen) {
      void loadTickets();
    }
  }, [isOpen, loadTickets]);

  // Keyboard shortcut to close
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape" && isOpen) {
        onClose();
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [isOpen, onClose]);

  const handleLookup = async (token: string) => {
    const trimmed = token.trim();
    if (!trimmed) return;
    try {
      const ticket = await getScanShareTicket(trimmed);
      setSelectedTicket(ticket);
      // Also add to tickets list if not present
      setTickets((prev) => {
        if (prev.some((t) => t.token_number === ticket.token_number)) return prev;
        return [ticket, ...prev];
      });
      toast.success(`Found ticket ${ticket.token_number}`);
    } catch {
      toast.error(`Token ${trimmed} not found or expired`);
    }
  };

  const handleCheckIn = async (ticket: ScanShareTicketItem) => {
    setCheckingIn(true);
    try {
      const updated = await checkInScanShareTicket(ticket.token_number, counterId);
      setSelectedTicket(updated);
      setTickets((prev) =>
        prev.map((t) => (t.token_number === updated.token_number ? updated : t)),
      );
      toast.success(`Patient checked in at ${counterId}`);
      if (onSelectForRegistration) {
        onSelectForRegistration(updated);
        onClose();
      }
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Check-in failed");
    } finally {
      setCheckingIn(false);
    }
  };

  const handlePrintSlip = () => {
    document.body.classList.add("printing-scan-share");
    window.print();
    setTimeout(() => {
      document.body.classList.remove("printing-scan-share");
    }, 1000);
  };

  if (!isOpen) return null;

  const filteredTickets = tickets.filter((t) => {
    if (!searchQuery) return true;
    const q = searchQuery.toLowerCase();
    return (
      t.token_number.toLowerCase().includes(q) ||
      t.name.toLowerCase().includes(q) ||
      (t.mobile && t.mobile.includes(q)) ||
      (t.abha_number && t.abha_number.includes(q)) ||
      (t.abha_address && t.abha_address.toLowerCase().includes(q))
    );
  });

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="scan-share-modal-title"
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4 backdrop-blur-sm"
    >
      <div className="surface-card flex h-[90vh] max-h-[820px] w-full max-w-5xl flex-col overflow-hidden rounded-xl border border-border shadow-2xl">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-border bg-muted/40 px-6 py-4">
          <div>
            <div className="flex items-center gap-2">
              <span className="rounded bg-primary px-2 py-0.5 text-xs font-bold uppercase tracking-wider text-primary-foreground">
                ABDM M1
              </span>
              <h2 id="scan-share-modal-title" className="text-xl font-bold">
                Scan & Share Reception Desk
              </h2>
            </div>
            <p className="mt-1 text-xs text-muted-foreground">
              Express check-in queue for patients scanning the hospital QR code via ABHA/PHR apps.
            </p>
          </div>
          <div className="flex items-center gap-3">
            <div className="flex items-center gap-1.5 text-xs">
              <label htmlFor="desk-counter-select" className="font-medium text-muted-foreground">
                Active Counter:
              </label>
              <select
                id="desk-counter-select"
                value={counterId}
                onChange={(e) => setCounterId(e.target.value)}
                className="rounded border border-border bg-card px-2.5 py-1 text-xs font-semibold"
              >
                <option value="COUNTER-1">Counter 1 (General)</option>
                <option value="COUNTER-2">Counter 2 (Express/ABDM)</option>
                <option value="COUNTER-3">Counter 3 (Senior / Priority)</option>
              </select>
            </div>
            <button
              type="button"
              onClick={onClose}
              className="rounded-md border border-border p-1.5 text-muted-foreground hover:bg-muted"
              aria-label="Close modal"
            >
              ✕
            </button>
          </div>
        </div>

        {/* Content Body (2 Columns) */}
        <div className="flex flex-1 overflow-hidden">
          {/* Left Column: Ticket List */}
          <div className="flex w-2/5 flex-col border-r border-border bg-muted/10">
            {/* Search and Filters */}
            <div className="border-b border-border p-3 space-y-2">
              <div className="flex gap-2">
                <input
                  type="search"
                  placeholder="Search token or patient…"
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") void handleLookup(searchQuery);
                  }}
                  className="flex-1 rounded-md border border-border bg-card px-3 py-1.5 text-xs"
                />
                <button
                  type="button"
                  onClick={() => void loadTickets()}
                  className="rounded-md border border-border bg-card px-2.5 py-1.5 text-xs font-medium hover:bg-muted"
                  title="Refresh tickets"
                >
                  ↻
                </button>
              </div>

              <div className="flex gap-1">
                {(
                  [
                    { id: "active", label: "Active Queue" },
                    { id: "checked_in", label: "Checked In" },
                    { id: "all", label: "All" },
                  ] as const
                ).map((f) => (
                  <button
                    key={f.id}
                    type="button"
                    onClick={() => setStatusFilter(f.id)}
                    className={`flex-1 rounded py-1 text-xs font-medium transition-colors ${
                      statusFilter === f.id
                        ? "bg-primary text-primary-foreground"
                        : "border border-border bg-card text-muted-foreground hover:bg-muted"
                    }`}
                  >
                    {f.label}
                  </button>
                ))}
              </div>
            </div>

            {/* List */}
            <div className="flex-1 overflow-y-auto p-2 space-y-2">
              {loading && tickets.length === 0 ? (
                <p className="p-4 text-center text-xs text-muted-foreground">Loading queue…</p>
              ) : filteredTickets.length === 0 ? (
                <div className="p-6 text-center text-xs text-muted-foreground">
                  <p className="font-semibold">No tickets in this view</p>
                  <p className="mt-1">Patients will appear here automatically when they scan the desk QR code.</p>
                </div>
              ) : (
                filteredTickets.map((t) => {
                  const isSelected = selectedTicket?.token_number === t.token_number;
                  return (
                    <div
                      key={t.token_number}
                      onClick={() => setSelectedTicket(t)}
                      className={`cursor-pointer rounded-lg border p-3 transition-all ${
                        isSelected
                          ? "border-primary bg-primary/5 shadow-sm"
                          : "border-border bg-card hover:border-primary/50"
                      }`}
                    >
                      <div className="flex items-center justify-between">
                        <span className="font-mono text-sm font-black text-primary">
                          {t.token_number}
                        </span>
                        <span
                          className={`rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase ${
                            t.status === "active"
                              ? "bg-emerald-500/10 text-emerald-600"
                              : "bg-muted text-muted-foreground"
                          }`}
                        >
                          {t.status}
                        </span>
                      </div>
                      <p className="mt-1 text-xs font-semibold text-foreground">{t.name}</p>
                      <div className="mt-1 flex items-center justify-between text-[11px] text-muted-foreground">
                        <span>{t.abha_address ?? t.abha_number ?? "ABHA verified"}</span>
                        <span>{formatDateTime(t.shared_at)}</span>
                      </div>
                    </div>
                  );
                })
              )}
            </div>
          </div>

          {/* Right Column: Selected Ticket Details & Check-In */}
          <div className="flex flex-1 flex-col overflow-y-auto p-6">
            {selectedTicket ? (
              <div className="space-y-6">
                {/* Token Hero Banner */}
                <div className="flex items-center justify-between rounded-xl border border-primary/20 bg-primary/5 p-5">
                  <div>
                    <p className="text-xs font-semibold uppercase tracking-wider text-primary">
                      Counter Token
                    </p>
                    <p className="font-mono text-4xl font-black text-primary">
                      {selectedTicket.token_number}
                    </p>
                    <p className="mt-1 text-xs text-muted-foreground">
                      Shared via ABDM Profile Share · Expires {formatDateTime(selectedTicket.expires_at)}
                    </p>
                  </div>
                  <div className="text-right">
                    <span
                      className={`rounded-full px-3 py-1 text-xs font-bold uppercase tracking-wide ${
                        selectedTicket.status === "active"
                          ? "bg-emerald-500/15 text-emerald-700"
                          : "bg-muted text-muted-foreground"
                      }`}
                    >
                      {selectedTicket.status.replace("_", " ")}
                    </span>
                    {selectedTicket.checked_in_at && (
                      <p className="mt-2 text-xs text-muted-foreground">
                        Checked in at {selectedTicket.counter_id} · {formatDateTime(selectedTicket.checked_in_at)}
                      </p>
                    )}
                  </div>
                </div>

                {/* Patient Profile Facts */}
                <div className="space-y-3">
                  <h3 className="text-sm font-semibold uppercase tracking-wider text-muted-foreground">
                    Verified Demographic Data
                  </h3>
                  <div className="grid grid-cols-2 gap-3 text-xs">
                    <div className="surface-card rounded-lg border border-border p-3">
                      <span className="text-muted-foreground">Full Name</span>
                      <p className="mt-1 text-sm font-semibold">{selectedTicket.name}</p>
                    </div>
                    <div className="surface-card rounded-lg border border-border p-3">
                      <span className="text-muted-foreground">Gender / DOB</span>
                      <p className="mt-1 text-sm font-semibold">
                        {selectedTicket.gender.toUpperCase()} ·{" "}
                        {selectedTicket.year_of_birth
                          ? `${selectedTicket.day_of_birth ?? "01"}/${selectedTicket.month_of_birth ?? "01"}/${selectedTicket.year_of_birth}`
                          : "Age recorded"}
                      </p>
                    </div>
                    <div className="surface-card rounded-lg border border-border p-3">
                      <span className="text-muted-foreground">ABHA Number</span>
                      <p className="mt-1 font-mono text-sm font-semibold">
                        {selectedTicket.abha_number ?? "Not linked"}
                      </p>
                    </div>
                    <div className="surface-card rounded-lg border border-border p-3">
                      <span className="text-muted-foreground">ABHA Address</span>
                      <p className="mt-1 text-sm font-semibold text-primary">
                        {selectedTicket.abha_address ?? "—"}
                      </p>
                    </div>
                    <div className="surface-card rounded-lg border border-border p-3">
                      <span className="text-muted-foreground">Mobile</span>
                      <p className="mt-1 font-mono text-sm font-semibold">
                        {selectedTicket.mobile ?? "—"}
                      </p>
                    </div>
                    <div className="surface-card rounded-lg border border-border p-3">
                      <span className="text-muted-foreground">Address / State</span>
                      <p className="mt-1 text-sm font-semibold">
                        {selectedTicket.address && typeof selectedTicket.address === "object"
                          ? `${(selectedTicket.address as Record<string, string>).district ?? ""}, ${(selectedTicket.address as Record<string, string>).state ?? "India"}`
                          : "India"}
                      </p>
                    </div>
                  </div>
                </div>

                {/* Actions */}
                <div className="flex flex-wrap items-center gap-3 border-t border-border pt-4">
                  {selectedTicket.status === "active" ? (
                    <button
                      type="button"
                      disabled={checkingIn}
                      onClick={() => void handleCheckIn(selectedTicket)}
                      className="flex-1 rounded-md bg-primary px-4 py-2.5 text-sm font-semibold text-primary-foreground shadow hover:bg-primary/90 disabled:opacity-50"
                    >
                      {checkingIn ? "Checking in…" : `Check-In Patient to ${counterId}`}
                    </button>
                  ) : (
                    <button
                      type="button"
                      onClick={() => {
                        if (onSelectForRegistration) {
                          onSelectForRegistration(selectedTicket);
                          onClose();
                        }
                      }}
                      className="flex-1 rounded-md border border-primary px-4 py-2.5 text-sm font-semibold text-primary hover:bg-primary/5"
                    >
                      Fill Registration Form with Verified Data
                    </button>
                  )}

                  <button
                    type="button"
                    onClick={handlePrintSlip}
                    className="rounded-md border border-border bg-card px-4 py-2.5 text-sm font-semibold text-foreground hover:bg-muted"
                  >
                    Print 80mm Reception Slip
                  </button>
                </div>
              </div>
            ) : (
              <div className="flex h-full flex-col items-center justify-center text-center text-muted-foreground">
                <p className="text-base font-semibold">Select a ticket from the queue</p>
                <p className="mt-1 text-xs">Or search by token number to check in the patient.</p>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Hidden Thermal Slip Print Container (HD-35 / HD-36) */}
      {selectedTicket && (
        <div id="scan-share-slip-print-root" className="thermal-slip hidden">
          <div className="text-center">
            <p className="text-xs font-bold uppercase tracking-wider">HealthDoc Hospital</p>
            <p className="text-[9px]">NABH Accredited · ABDM Integrated</p>
            <div className="thermal-divider" />
            <p className="text-[10px] font-bold uppercase">OPD Reception Token</p>
            <div className="token-number">{selectedTicket.token_number}</div>
            <p className="text-[10px] font-semibold">{counterId}</p>
            <div className="thermal-divider" />
          </div>
          <div className="text-[9px] space-y-1">
            <p><strong>Patient:</strong> {selectedTicket.name}</p>
            <p><strong>Gender/Age:</strong> {selectedTicket.gender.toUpperCase()} · {selectedTicket.year_of_birth ? `${new Date().getFullYear() - selectedTicket.year_of_birth}y` : ""}</p>
            <p><strong>ABHA:</strong> {selectedTicket.abha_address ?? selectedTicket.abha_number ?? "Verified"}</p>
            <p><strong>Time:</strong> {new Date().toLocaleString()}</p>
          </div>
          <div className="thermal-divider" />
          <div className="barcode-block font-mono text-center text-[10px] tracking-widest">
            ||||| | ||| |||| | |||||| || |
            <p className="text-[8px] mt-0.5">{selectedTicket.token_number}</p>
          </div>
          <p className="text-center text-[8px] text-muted-foreground mt-1">
            Please proceed to {counterId} when your token is called.
          </p>
        </div>
      )}
    </div>
  );
}
