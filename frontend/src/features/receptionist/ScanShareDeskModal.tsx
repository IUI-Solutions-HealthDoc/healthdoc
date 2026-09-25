"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import QRCode from "react-qr-code";
import { Modal } from "@/components/ui/Modal";
import { formatDateTime } from "@/lib/api";
import { useLocale } from "@/lib/i18n";
import { StartVisit } from "./StartVisit";
import {
  listScanShareTickets, getScanShareTicket, checkInScanShareTicket,
  type ScanShareTicketItem,
} from "./api";

export interface ScanShareDeskModalProps {
  isOpen: boolean;
  onClose: () => void;
}

/** Closing unmounts the desk, discarding identity and in-flight response handlers. */
export function ScanShareDeskModal({ isOpen, onClose }: ScanShareDeskModalProps) {
  return isOpen ? <ReceptionTicketDesk onClose={onClose} /> : null;
}

function ReceptionTicketDesk({ onClose }: { onClose: () => void }) {
  const { t } = useLocale();
  const [tickets, setTickets] = useState<ScanShareTicketItem[]>([]);
  const [selected, setSelected] = useState<ScanShareTicketItem | null>(null);
  const [filter, setFilter] = useState("active");
  const [query, setQuery] = useState("");
  const [counter, setCounter] = useState("");
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const mounted = useRef(false);
  const reads = useRef(0);
  const selection = useRef(0);
  const writing = useRef(false);

  useEffect(() => {
    mounted.current = true;
    const readSequence = reads;
    const selectionSequence = selection;
    return () => { mounted.current = false; readSequence.current++; selectionSequence.current++; };
  }, []);

  const load = useCallback(async () => {
    const request = ++reads.current;
    setLoading(true);
    setError("");
    try {
      const items = await listScanShareTickets(filter);
      if (mounted.current && reads.current === request) setTickets(items);
    } catch (err) {
      if (mounted.current && reads.current === request) {
        setTickets([]);
        setError(err instanceof Error ? err.message : t("receptionist.scanShare.errLoad"));
      }
    } finally {
      if (mounted.current && reads.current === request) setLoading(false);
    }
  }, [filter, t]);

  useEffect(() => { void load(); }, [load]);

  function choose(ticket: ScanShareTicketItem | null) {
    selection.current++;
    setSelected(ticket?.status === "active" && Date.parse(ticket.expires_at) <= Date.now()
      ? { ...ticket, status: "expired" } : ticket);
    setCounter(ticket?.counter ?? "");
    setError("");
    setNotice("");
  }

  async function lookup(event: React.FormEvent) {
    event.preventDefault();
    if (!query.trim() || writing.current) return;
    choose(null);
    const request = selection.current;
    try {
      const ticket = await getScanShareTicket(query.trim());
      if (mounted.current && request === selection.current) choose(ticket);
    } catch (err) {
      if (mounted.current && request === selection.current)
        setError(err instanceof Error ? err.message : t("receptionist.scanShare.errLookup"));
    }
  }

  async function checkIn(event: React.FormEvent) {
    event.preventDefault();
    if (!selected || !counter.trim() || writing.current) return;
    const ticketId = selected.id;
    const request = selection.current;
    const actualCounter = counter.trim();
    writing.current = true;
    setSaving(true);
    setError("");
    setNotice("");
    let accepted = false;
    try {
      const result = await checkInScanShareTicket(ticketId, actualCounter);
      if (result.ticket_id !== ticketId) throw new Error(t("receptionist.scanShare.errWrongTicket"));
      accepted = true;
      const refreshed = await getScanShareTicket(ticketId);
      if (refreshed.id !== ticketId || refreshed.status !== "checked_in")
        throw new Error(t("receptionist.scanShare.errConfirm"));
      if (!mounted.current || request !== selection.current) return;
      setSelected(refreshed);
      setTickets((rows) => rows.map((row) => row.id === ticketId ? refreshed : row));
      setNotice(t("receptionist.scanShare.noticeSaved"));
    } catch (err) {
      if (mounted.current && request === selection.current)
        setError(accepted
          ? t("receptionist.scanShare.errReadBack")
          : err instanceof Error ? err.message : t("receptionist.scanShare.errRetry"));
    } finally {
      writing.current = false;
      if (mounted.current && request === selection.current) setSaving(false);
    }
  }

  const profileText = (key: string) => {
    const value = selected?.profile_data[key];
    return typeof value === "string" && value.trim() ? value : t("receptionist.scanShare.notProvided");
  };
  const expired = selected?.status === "expired";

  function printSlip() {
    if (selected?.status !== "checked_in") return;
    document.body.classList.add("printing-scan-share");
    try { window.print(); }
    finally { document.body.classList.remove("printing-scan-share"); }
  }

  return <>
    <Modal open onClose={onClose} disableClose={saving} title={t("receptionist.scanShare.title")} size="lg">
      <p className="mb-4 text-sm text-muted-foreground">
        {t("receptionist.scanShare.intro")}
      </p>
      {error && <p role="alert" className="mb-3 text-sm text-red-700">{error}</p>}
      {notice && <p role="status" className="mb-3 text-sm text-green-700">{notice}</p>}
      <div className="grid gap-6 md:grid-cols-2">
        <section className="space-y-3" aria-label={t("receptionist.scanShare.ticketsAria")}>
          <label className="block text-sm">{t("receptionist.scanShare.ticketStatus")}
            <select value={filter} disabled={saving} onChange={(e) => {
              choose(null); reads.current++; setTickets([]); setFilter(e.target.value);
            }} className="ml-2 rounded border p-2">
              <option value="active">{t("receptionist.scanShare.statusActive")}</option>
              <option value="checked_in">{t("receptionist.scanShare.statusCheckedIn")}</option>
              <option value="expired">{t("receptionist.scanShare.statusExpired")}</option>
              <option value="all">{t("receptionist.scanShare.statusAll")}</option>
            </select>
          </label>
          <form onSubmit={lookup} className="flex gap-2">
            <label className="flex-1 text-sm">{t("receptionist.scanShare.tokenOrQr")}
              <input value={query} onChange={(e) => setQuery(e.target.value)}
                disabled={saving} className="mt-1 w-full rounded border p-2" />
            </label>
            <button disabled={saving || !query.trim()} className="self-end rounded border px-3 py-2">{t("receptionist.scanShare.lookUp")}</button>
          </form>
          <button type="button" onClick={() => void load()} disabled={saving || loading}
            className="rounded border px-3 py-2 text-sm">{t("receptionist.scanShare.refreshTickets")}</button>
          <p className="text-xs text-muted-foreground">{t("receptionist.scanShare.latestHint")}</p>
          {loading ? <p role="status">{t("receptionist.scanShare.loading")}</p> : tickets.length === 0
            ? <p>{t("receptionist.scanShare.empty")}</p>
            : <ul className="max-h-96 space-y-2 overflow-auto">
              {tickets.map((ticket) => <li key={ticket.id}>
                <button type="button" disabled={saving} onClick={() => choose(ticket)}
                  aria-pressed={selected?.id === ticket.id}
                  className="w-full rounded border border-border p-3 text-left hover:bg-muted disabled:opacity-50">
                  <strong>{ticket.token_number}</strong> · {ticket.patient_name ?? t("receptionist.scanShare.unboundProfile")}
                  <span className="block text-xs">{ticket.patient_uhid ?? t("receptionist.scanShare.noLocalBinding")} · {ticket.status}</span>
                  <span className="block text-xs text-muted-foreground">{formatDateTime(ticket.created_at)}</span>
                </button>
              </li>)}
            </ul>}
        </section>
        <section aria-label={t("receptionist.scanShare.selectedAria")} className="space-y-4">
          {selected ? <>
            <h3 className="text-lg font-semibold">{selected.patient_name ?? profileText("full_name")}</h3>
            <dl className="space-y-2 text-sm">
              <div><dt>{t("receptionist.scanShare.localUhid")}</dt><dd>{selected.patient_uhid ?? t("receptionist.scanShare.notBound")}</dd></div>
              <div><dt>{t("receptionist.scanShare.receptionToken")}</dt><dd>{selected.token_number} · {expired ? t("receptionist.scanShare.statusExpired").toLowerCase() : selected.status}</dd></div>
              <div><dt>{t("receptionist.scanShare.genderDob")}</dt><dd>{profileText("gender")} · {profileText("birth_date")}</dd></div>
              <div><dt>{t("receptionist.scanShare.abhaAddress")}</dt><dd>{selected.abha_address}</dd></div>
              <div><dt>{t("receptionist.scanShare.expires")}</dt><dd>{formatDateTime(selected.expires_at)}</dd></div>
            </dl>
            {selected.status === "active" && !expired && <form onSubmit={checkIn} className="space-y-3">
              <label className="block text-sm">{t("receptionist.scanShare.counterLabel")}
                <input required maxLength={50} value={counter} disabled={saving}
                  onChange={(e) => setCounter(e.target.value)} className="mt-1 w-full rounded border p-2" />
              </label>
              <button disabled={saving || !counter.trim()} className="rounded bg-primary px-4 py-2 text-primary-foreground disabled:opacity-50">
                {saving ? t("receptionist.scanShare.confirming") : t("receptionist.scanShare.checkIn")}
              </button>
            </form>}
            {expired && <p role="status">{t("receptionist.scanShare.expiredHint")}</p>}
            {selected.status === "checked_in" && <>
              <p>{t("receptionist.scanShare.counterLine", { counter: selected.counter ?? t("receptionist.scanShare.notRecorded") })} · {selected.checked_in_at
                ? formatDateTime(selected.checked_in_at) : t("receptionist.scanShare.historicalCheckIn")}</p>
              <button type="button" onClick={printSlip} className="rounded border px-3 py-2">{t("receptionist.scanShare.printSlip")}</button>
              {selected.patient_id && selected.patient_name && selected.patient_uhid
                ? <StartVisit key={selected.id} patient={{
                  id: selected.patient_id, full_name: selected.patient_name,
                  uhid: selected.patient_uhid, thid: null,
                }} />
                : <p>{t("receptionist.scanShare.bindingRequired")}</p>}
            </>}
          </> : <p>{t("receptionist.scanShare.selectFirst")}</p>}
        </section>
      </div>
    </Modal>
    {selected?.status === "checked_in" && typeof document !== "undefined" && createPortal(
      <div id="scan-share-slip-print-root" className="thermal-slip hidden">
        <h2>{t("receptionist.scanShare.slipTitle")}</h2>
        <p>{selected.patient_name ?? t("receptionist.scanShare.slipPatient")} · {selected.patient_uhid ?? t("receptionist.scanShare.slipUhidMissing")}</p>
        <p>{t("receptionist.scanShare.slipTokenCounter", { token: selected.token_number, counter: selected.counter ?? "" })}</p>
        <p>{selected.checked_in_at ? formatDateTime(selected.checked_in_at) : t("receptionist.scanShare.slipCheckInMissing")}</p>
        <QRCode value={selected.id} size={80} />
        <p>{t("receptionist.scanShare.slipFooter")}</p>
      </div>, document.body,
    )}
  </>;
}
