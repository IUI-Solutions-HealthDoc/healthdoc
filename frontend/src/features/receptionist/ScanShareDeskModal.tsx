"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import QRCode from "react-qr-code";
import { Modal } from "@/components/ui/Modal";
import { formatDateTime } from "@/lib/api";
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
        setError(err instanceof Error ? err.message : "Cannot load reception tickets");
      }
    } finally {
      if (mounted.current && reads.current === request) setLoading(false);
    }
  }, [filter]);

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
        setError(err instanceof Error ? err.message : "Cannot look up reception ticket");
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
      if (result.ticket_id !== ticketId) throw new Error("Check-in returned another ticket");
      accepted = true;
      const refreshed = await getScanShareTicket(ticketId);
      if (refreshed.id !== ticketId || refreshed.status !== "checked_in")
        throw new Error("Check-in could not be confirmed from the server");
      if (!mounted.current || request !== selection.current) return;
      setSelected(refreshed);
      setTickets((rows) => rows.map((row) => row.id === ticketId ? refreshed : row));
      setNotice("Reception check-in saved. Start the visit separately below.");
    } catch (err) {
      if (mounted.current && request === selection.current)
        setError(accepted
          ? "Check-in was saved but read-back failed. Retry with the same counter to confirm; do not create another ticket."
          : err instanceof Error ? err.message : "Check-in could not be confirmed. Retry with the same counter.");
    } finally {
      writing.current = false;
      if (mounted.current && request === selection.current) setSaving(false);
    }
  }

  const profileText = (key: string) => {
    const value = selected?.profile_data[key];
    return typeof value === "string" && value.trim() ? value : "Not provided";
  };
  const expired = selected?.status === "expired";

  function printSlip() {
    if (selected?.status !== "checked_in") return;
    document.body.classList.add("printing-scan-share");
    try { window.print(); }
    finally { document.body.classList.remove("printing-scan-share"); }
  }

  return <>
    <Modal open onClose={onClose} disableClose={saving} title="Scan & Share Reception Desk" size="lg">
      <p className="mb-4 text-sm text-muted-foreground">
        Profile sharing creates a reception ticket, not an OPD visit, appointment or clinical consent.
      </p>
      {error && <p role="alert" className="mb-3 text-sm text-red-700">{error}</p>}
      {notice && <p role="status" className="mb-3 text-sm text-green-700">{notice}</p>}
      <div className="grid gap-6 md:grid-cols-2">
        <section className="space-y-3" aria-label="Reception tickets">
          <label className="block text-sm">Ticket status
            <select value={filter} disabled={saving} onChange={(e) => {
              choose(null); reads.current++; setTickets([]); setFilter(e.target.value);
            }} className="ml-2 rounded border p-2">
              <option value="active">Active</option>
              <option value="checked_in">Checked in</option>
              <option value="expired">Expired</option>
              <option value="all">All</option>
            </select>
          </label>
          <form onSubmit={lookup} className="flex gap-2">
            <label className="flex-1 text-sm">Token number or ticket QR reference
              <input value={query} onChange={(e) => setQuery(e.target.value)}
                disabled={saving} className="mt-1 w-full rounded border p-2" />
            </label>
            <button disabled={saving || !query.trim()} className="self-end rounded border px-3 py-2">Look up</button>
          </form>
          <button type="button" onClick={() => void load()} disabled={saving || loading}
            className="rounded border px-3 py-2 text-sm">Refresh tickets</button>
          <p className="text-xs text-muted-foreground">Latest 100 tickets. Use lookup for an older ticket.</p>
          {loading ? <p role="status">Loading tickets…</p> : tickets.length === 0
            ? <p>No tickets in this view.</p>
            : <ul className="max-h-96 space-y-2 overflow-auto">
              {tickets.map((ticket) => <li key={ticket.id}>
                <button type="button" disabled={saving} onClick={() => choose(ticket)}
                  aria-pressed={selected?.id === ticket.id}
                  className="w-full rounded border border-border p-3 text-left hover:bg-muted disabled:opacity-50">
                  <strong>{ticket.token_number}</strong> · {ticket.patient_name ?? "Unbound profile"}
                  <span className="block text-xs">{ticket.patient_uhid ?? "No local patient binding"} · {ticket.status}</span>
                  <span className="block text-xs text-muted-foreground">{formatDateTime(ticket.created_at)}</span>
                </button>
              </li>)}
            </ul>}
        </section>
        <section aria-label="Selected reception ticket" className="space-y-4">
          {selected ? <>
            <h3 className="text-lg font-semibold">{selected.patient_name ?? profileText("full_name")}</h3>
            <dl className="space-y-2 text-sm">
              <div><dt>Local UHID</dt><dd>{selected.patient_uhid ?? "Not bound"}</dd></div>
              <div><dt>Reception token</dt><dd>{selected.token_number} · {expired ? "expired" : selected.status}</dd></div>
              <div><dt>Gender / birth date</dt><dd>{profileText("gender")} · {profileText("birth_date")}</dd></div>
              <div><dt>ABHA address</dt><dd>{selected.abha_address}</dd></div>
              <div><dt>Expires</dt><dd>{formatDateTime(selected.expires_at)}</dd></div>
            </dl>
            {selected.status === "active" && !expired && <form onSubmit={checkIn} className="space-y-3">
              <label className="block text-sm">Actual reception counter
                <input required maxLength={50} value={counter} disabled={saving}
                  onChange={(e) => setCounter(e.target.value)} className="mt-1 w-full rounded border p-2" />
              </label>
              <button disabled={saving || !counter.trim()} className="rounded bg-primary px-4 py-2 text-primary-foreground disabled:opacity-50">
                {saving ? "Confirming check-in…" : "Check in"}
              </button>
            </form>}
            {expired && <p role="status">This ticket has expired. Ask the patient to share a fresh profile.</p>}
            {selected.status === "checked_in" && <>
              <p>Counter: {selected.counter ?? "Not recorded"} · {selected.checked_in_at
                ? formatDateTime(selected.checked_in_at) : "Historical check-in time not recorded"}</p>
              <button type="button" onClick={printSlip} className="rounded border px-3 py-2">Print reception slip</button>
              {selected.patient_id && selected.patient_name && selected.patient_uhid
                ? <StartVisit key={selected.id} patient={{
                  id: selected.patient_id, full_name: selected.patient_name,
                  uhid: selected.patient_uhid, thid: null,
                }} />
                : <p>Patient binding requires reconciliation before starting a visit. Do not register a duplicate record.</p>}
            </>}
          </> : <p>Select and confirm the patient before checking in.</p>}
        </section>
      </div>
    </Modal>
    {selected?.status === "checked_in" && typeof document !== "undefined" && createPortal(
      <div id="scan-share-slip-print-root" className="thermal-slip hidden">
        <h2>Reception ticket</h2>
        <p>{selected.patient_name ?? "Patient"} · {selected.patient_uhid ?? "UHID not recorded"}</p>
        <p>Token: {selected.token_number} · Counter: {selected.counter}</p>
        <p>{selected.checked_in_at ? formatDateTime(selected.checked_in_at) : "Check-in time not recorded"}</p>
        <QRCode value={selected.id} size={80} />
        <p>Reception check-in only. Visit allocation is separate.</p>
      </div>, document.body,
    )}
  </>;
}
