"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Alert, Box, Button, Checkbox, FormControlLabel, Stack, Table, TableBody, TableCell,
  TableContainer, TableHead, TablePagination, TableRow, TextField, Typography } from "@mui/material";
import { Modal } from "@/components/ui/Modal";
import { formatMoney, newIdempotencyKey } from "@/lib/api";
import { useLocale, type MessageKey } from "@/lib/i18n";
import { useAuth } from "@/providers/auth-provider";
import { meridian } from "@/styles/theme";
import { deactivateTariff, listChargeMaster } from "../api/chargeMaster";
import type { ChargeMaster } from "../types";
import { chargeCategoryLabel } from "../lib/labels";
import { TariffForm } from "./TariffForm";

const TABLE_COLUMN_KEYS: MessageKey[] = [
  "billing.tariff.colCodeDescription",
  "billing.tariff.colCategory",
  "billing.tariff.colUnitPrice",
  "billing.tariff.colScheme",
  "billing.tariff.colEffectiveFrom",
  "billing.tariff.colThrough",
  "billing.tariff.colState",
  "billing.tariff.colActions",
];

export function TariffWorkspace() {
  const { user } = useAuth();
  const { localizeField, t } = useLocale();
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
      if (request === generation.current) {
        setError(error instanceof Error ? error.message : t("billing.tariff.loadFailed"));
      }
    } finally { if (request === generation.current) setLoading(false); }
  }, [allowed, includeRetired, t]);

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
      setMessage(t("billing.tariff.retiredSuccess", {
        code: retire.row.charge_code,
        effectiveFrom: retire.row.effective_from,
      }));
      setRetire(null); await reload();
    } catch (error) {
      setRetireError(error instanceof Error ? error.message : t("billing.tariff.retireFailed"));
    }
    finally { saving.current = false; setBusy(false); }
  }

  if (!allowed) {
    return <Alert severity="error">{t("billing.tariff.accessDenied")}</Alert>;
  }

  return <Stack spacing={2.5} sx={{ color: meridian.textPrimary }}>
    <Typography component="h1" variant="h5" sx={{ fontWeight: 700 }}>{t("billing.tariffsTitle")}</Typography>
    <Typography>{t("billing.tariff.maintainIntro")}</Typography>
    {message && <Alert severity="success" onClose={() => setMessage(null)}>{message}</Alert>}
    <Stack direction="row" useFlexGap sx={{ flexWrap: "wrap", gap: 2, alignItems: "center" }}>
      <TextField label={t("billing.tariff.searchLabel")} value={query} onChange={(e) => { setQuery(e.target.value); setPage(0); }} sx={{ minWidth: 280 }} />
      <FormControlLabel label={t("billing.tariff.includeRetired")} control={<Checkbox checked={includeRetired} onChange={(e) => { setIncludeRetired(e.target.checked); setPage(0); }} />} />
      <Button onClick={() => void reload()} disabled={loading}>{t("billing.tariff.reloadCatalogue")}</Button>
      <Button variant="contained" onClick={() => { setMessage(null); setForm({ revision: null }); }}>{t("billing.tariff.newTariff")}</Button>
    </Stack>
    <Typography variant="body2">{t("billing.tariff.enabledHint")}</Typography>
    {error ? <Alert severity="error">{error} {t("billing.tariff.reloadRetry")}</Alert> : loading || snapshot?.history !== includeRetired ?
      <Typography role="status">{t("billing.tariff.loading")}</Typography> : <Box sx={{ border: `1px solid ${meridian.border}`, borderRadius: 3, overflow: "hidden", backgroundColor: meridian.surface }}>
        <TableContainer><Table size="small" aria-label="Tariff versions">
          <TableHead><TableRow>{TABLE_COLUMN_KEYS.map((key) => <TableCell key={key}>{t(key)}</TableCell>)}</TableRow></TableHead>
          <TableBody>{rows.slice(visiblePage * 15, visiblePage * 15 + 15).map((row) => <TableRow key={row.id}>
            <TableCell><Typography sx={{ fontWeight: 600 }}>{row.charge_code}</Typography>{localizeField(row.description, row.description_hi)}</TableCell>
            <TableCell>{chargeCategoryLabel(t, row.charge_category)}</TableCell>
            <TableCell sx={{ whiteSpace: "nowrap" }}>{formatMoney(row.unit_price)}</TableCell>
            <TableCell>{row.scheme_code ?? t("billing.tariff.schemeGeneral")}</TableCell>
            <TableCell sx={{ whiteSpace: "nowrap" }}>{row.effective_from}</TableCell>
            <TableCell sx={{ whiteSpace: "nowrap" }}>{row.effective_to ?? t("billing.tariff.openEnded")}</TableCell>
            <TableCell>{row.is_active ? t("billing.tariff.stateEnabled") : t("billing.tariff.stateRetired")}</TableCell>
            <TableCell><Stack direction="row">
              {row.is_active && !row.effective_to && <Button onClick={() => setForm({ revision: row })}>{t("billing.tariff.revise")}</Button>}
              {row.is_active && <Button color="error" onClick={() => { setRetireError(null); setRetire({ row, key: newIdempotencyKey() }); }}>{t("billing.tariff.retire")}</Button>}
            </Stack></TableCell>
          </TableRow>)}</TableBody>
        </Table></TableContainer>
        {rows.length === 0 && <Typography sx={{ p: 3 }}>{t("billing.tariff.noMatch")}</Typography>}
        <TablePagination component="div" count={rows.length} page={visiblePage} onPageChange={(_, next) => setPage(next)} rowsPerPage={15} rowsPerPageOptions={[15]} />
      </Box>}
    {form && <TariffForm revision={form.revision} onClose={() => { setForm(null); void reload(); }} onSaved={() => {
      setForm(null); setMessage(t("billing.tariff.savedSuccess")); void reload();
    }} />}
    <Modal open={!!retire} onClose={() => { if (!saving.current) { setRetire(null); void reload(); } }} title={t("billing.tariff.retireTitle")} loading={busy}
      actions={<><Button onClick={() => { setRetire(null); void reload(); }}>{retireError ? t("billing.tariff.closeCheckCatalogue") : t("billing.common.cancel")}</Button>
        {!retireError && <Button color="error" variant="contained" onClick={() => void confirmRetire()}>{t("billing.tariff.confirmRetirement")}</Button>}</>}>
      {retire && <Stack spacing={2}>
        {retireError && <Alert severity="error">{retireError} {t("billing.tariff.retireReloadHint")}</Alert>}
        <Typography>{t("billing.tariff.retireSummary", {
          code: retire.row.charge_code,
          scheme: retire.row.scheme_code ?? t("billing.tariff.schemeGeneral"),
          price: formatMoney(retire.row.unit_price),
          effectiveFrom: retire.row.effective_from,
        })}</Typography>
        <Alert severity="warning">{t("billing.tariff.retireWarning")}</Alert>
      </Stack>}
    </Modal>
  </Stack>;
}
