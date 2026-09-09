"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Alert, Box, Button, Checkbox, FormControlLabel, Stack, Table, TableBody, TableCell,
  TableContainer, TableHead, TablePagination, TableRow, TextField, Typography } from "@mui/material";
import { Modal } from "@/components/ui/Modal";
import { formatMoney, newIdempotencyKey } from "@/lib/api";
import { useAuth } from "@/providers/auth-provider";
import { meridian } from "@/styles/theme";
import { deactivateTariff, listChargeMaster } from "../api/chargeMaster";
import { CHARGE_CATEGORY_LABELS } from "../constants";
import type { ChargeMaster } from "../types";
import { TariffForm } from "./TariffForm";

export function TariffWorkspace() {
  const { user } = useAuth();
  const allowed = user?.role === "billing" || user?.role === "admin";
  const [includeRetired, setIncludeRetired] = useState(false);
  const [query, setQuery] = useState("");
  const [page, setPage] = useState(0);
  const [snapshot, setSnapshot] = useState<{ history: boolean; rows: ChargeMaster[] } | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [form, setForm] = useState<{ revision: ChargeMaster | null } | null>(null);
  const [retire, setRetire] = useState<{ row: ChargeMaster; key: string } | null>(null);
  const [retireError, setRetireError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const saving = useRef(false);
  const generation = useRef(0);

  const reload = useCallback(async () => {
    if (!allowed) return;
    const request = ++generation.current;
    setLoading(true); setError(null); setSnapshot(null);
    try {
      const rows = await listChargeMaster({ active_only: !includeRetired });
      if (request === generation.current) setSnapshot({ history: includeRetired, rows });
    } catch (error) {
      if (request === generation.current) setError(error instanceof Error ? error.message : "Could not load the tariff catalogue.");
    } finally { if (request === generation.current) setLoading(false); }
  }, [allowed, includeRetired]);

  useEffect(() => {
    const requests = generation;
    void reload();
    return () => { requests.current++; };
  }, [reload]);
  const rows = useMemo(() => {
    if (snapshot?.history !== includeRetired) return [];
    const term = query.trim().toLowerCase();
    return snapshot.rows.filter((row) => [row.charge_code, row.description, row.scheme_code ?? "General", row.charge_category]
      .some((value) => value.toLowerCase().includes(term)));
  }, [snapshot, includeRetired, query]);
  const visiblePage = Math.min(page, Math.max(0, Math.ceil(rows.length / 15) - 1));

  async function confirmRetire() {
    if (!retire || saving.current || retireError) return;
    saving.current = true; setBusy(true);
    try {
      await deactivateTariff(retire.row.id, retire.key);
      setMessage(`Retired ${retire.row.charge_code} (${retire.row.effective_from}). History is retained.`);
      setRetire(null); await reload();
    } catch (error) { setRetireError(error instanceof Error ? error.message : "Could not retire the tariff."); }
    finally { saving.current = false; setBusy(false); }
  }

  if (!allowed) return <Alert severity="error">Tariff maintenance is available to billing and facility administrators.</Alert>;

  return <Stack spacing={2.5} sx={{ color: meridian.textPrimary }}>
    <Typography component="h1" variant="h5" sx={{ fontWeight: 700 }}>Tariff catalogue</Typography>
    <Typography>Maintain your facility’s approved effective-dated prices. Each revision creates a new version; existing posted invoice lines keep their recorded amounts.</Typography>
    {message && <Alert severity="success" onClose={() => setMessage(null)}>{message}</Alert>}
    <Stack direction="row" useFlexGap sx={{ flexWrap: "wrap", gap: 2, alignItems: "center" }}>
      <TextField label="Search code, description or scheme" value={query} onChange={(e) => { setQuery(e.target.value); setPage(0); }} sx={{ minWidth: 280 }} />
      <FormControlLabel label="Include retired tariffs" control={<Checkbox checked={includeRetired} onChange={(e) => { setIncludeRetired(e.target.checked); setPage(0); }} />} />
      <Button onClick={() => void reload()} disabled={loading}>Reload catalogue</Button>
      <Button variant="contained" onClick={() => { setMessage(null); setForm({ revision: null }); }}>New tariff</Button>
    </Stack>
    <Typography variant="body2">Enabled means available for its effective-date range, not necessarily today. End dates are inclusive. Retiring a version removes it from future tariff lookups, including unbuilt historical charges.</Typography>
    {error ? <Alert severity="error">{error} Use Reload catalogue to retry.</Alert> : loading || snapshot?.history !== includeRetired ?
      <Typography role="status">Loading tariff catalogue…</Typography> : <Box sx={{ border: `1px solid ${meridian.border}`, borderRadius: 3, overflow: "hidden", backgroundColor: meridian.surface }}>
        <TableContainer><Table size="small" aria-label="Tariff versions">
          <TableHead><TableRow>{["Code / description", "Category", "Unit price", "Scheme", "Effective from", "Through (inclusive)", "State", "Actions"].map((label) => <TableCell key={label}>{label}</TableCell>)}</TableRow></TableHead>
          <TableBody>{rows.slice(visiblePage * 15, visiblePage * 15 + 15).map((row) => <TableRow key={row.id}>
            <TableCell><Typography sx={{ fontWeight: 600 }}>{row.charge_code}</Typography>{row.description}</TableCell>
            <TableCell>{CHARGE_CATEGORY_LABELS[row.charge_category]}</TableCell>
            <TableCell sx={{ whiteSpace: "nowrap" }}>{formatMoney(row.unit_price)}</TableCell>
            <TableCell>{row.scheme_code ?? "General"}</TableCell>
            <TableCell sx={{ whiteSpace: "nowrap" }}>{row.effective_from}</TableCell>
            <TableCell sx={{ whiteSpace: "nowrap" }}>{row.effective_to ?? "Open-ended"}</TableCell>
            <TableCell>{row.is_active ? "Enabled" : "Retired"}</TableCell>
            <TableCell><Stack direction="row">
              {row.is_active && !row.effective_to && <Button onClick={() => setForm({ revision: row })}>Revise</Button>}
              {row.is_active && <Button color="error" onClick={() => { setRetireError(null); setRetire({ row, key: newIdempotencyKey() }); }}>Retire</Button>}
            </Stack></TableCell>
          </TableRow>)}</TableBody>
        </Table></TableContainer>
        {rows.length === 0 && <Typography sx={{ p: 3 }}>No tariffs match these filters.</Typography>}
        <TablePagination component="div" count={rows.length} page={visiblePage} onPageChange={(_, next) => setPage(next)} rowsPerPage={15} rowsPerPageOptions={[15]} />
      </Box>}
    {form && <TariffForm revision={form.revision} onClose={() => { setForm(null); void reload(); }} onSaved={() => {
      setForm(null); setMessage("Tariff version saved. The catalogue below is read back from the server."); void reload();
    }} />}
    <Modal open={!!retire} onClose={() => { if (!saving.current) { setRetire(null); void reload(); } }} title="Retire tariff" loading={busy}
      actions={<><Button onClick={() => { setRetire(null); void reload(); }}>{retireError ? "Close and check catalogue" : "Cancel"}</Button>
        {!retireError && <Button color="error" variant="contained" onClick={() => void confirmRetire()}>Confirm retirement</Button>}</>}>
      {retire && <Stack spacing={2}>
        {retireError && <Alert severity="error">{retireError} Reload the catalogue before retrying; the request may have completed.</Alert>}
        <Typography>{retire.row.charge_code} · {retire.row.scheme_code ?? "General"} · {formatMoney(retire.row.unit_price)} · From {retire.row.effective_from}</Typography>
        <Alert severity="warning">This version will no longer be used for new charges, including unbuilt historical charges. Missing replacement tariffs can prevent registration or leave services unpriced. Existing posted lines and tariff history are retained. There is no reactivation action.</Alert>
      </Stack>}
    </Modal>
  </Stack>;
}
