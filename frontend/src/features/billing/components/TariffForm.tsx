"use client";

import { useRef, useState } from "react";
import { Alert, Button, MenuItem, Stack, TextField, Typography } from "@mui/material";
import { Modal } from "@/components/ui/Modal";
import { formatMoney, newIdempotencyKey } from "@/lib/api";
import { createTariff } from "../api/chargeMaster";
import { CHARGE_CATEGORY_LABELS } from "../constants";
import { tariffFormSchema } from "../lib/tariff-form";
import type { ChargeMaster, TariffCreateInput } from "../types";

export function TariffForm({ revision, onClose, onSaved }: {
  revision: ChargeMaster | null; onClose: () => void; onSaved: () => void;
}) {
  const [values, setValues] = useState({ charge_code: revision?.charge_code ?? "",
    description: revision?.description ?? "", charge_category: revision?.charge_category ?? "",
    unit_price: "", effective_from: "", scheme_code: revision?.scheme_code ?? "" });
  const [errors, setErrors] = useState<Record<string, string[] | undefined>>({});
  const [review, setReview] = useState<TariffCreateInput | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const saving = useRef(false);
  const [actionKey] = useState(newIdempotencyKey);
  const close = () => { if (!saving.current) onClose(); };

  function validate() {
    const parsed = tariffFormSchema.safeParse(values);
    if (!parsed.success) { setErrors(parsed.error.flatten().fieldErrors); return; }
    if (revision && parsed.data.effective_from <= revision.effective_from) {
      setErrors({ effective_from: [`Choose a date after ${revision.effective_from}.`] }); return;
    }
    setErrors({}); setReview(parsed.data);
  }

  async function save() {
    if (!review || saving.current || error) return;
    saving.current = true; setBusy(true);
    try { await createTariff(review, actionKey); onSaved(); }
    catch (error) {
      setError(error instanceof Error ? error.message : "The tariff could not be saved.");
      // These existing routes do not implement replay. An ambiguous failure
      // requires reading the catalogue, not another speculative POST.
    } finally { saving.current = false; setBusy(false); }
  }

  return <Modal open onClose={close} title={review ? "Review tariff version" : revision ? "Revise tariff" : "New tariff"}
    loading={busy} actions={<>
      <Button onClick={close}>{error ? "Close and check catalogue" : "Cancel"}</Button>
      {!error && (review ? <>
        <Button onClick={() => setReview(null)}>Back to edit</Button>
        <Button variant="contained" onClick={() => void save()}>Save tariff version</Button>
      </> : <Button variant="contained" onClick={validate}>Review tariff</Button>)}
    </>}>
    <Stack spacing={2}>
      {error && <Alert severity="error">{error} Close this dialog and reload the catalogue before trying again; the request may have completed.</Alert>}
      {review ? <>
        <Typography>Code: {review.charge_code} · Scheme: {review.scheme_code ?? "General"}</Typography>
        <Typography>{review.description} · {CHARGE_CATEGORY_LABELS[review.charge_category]}</Typography>
        <Typography>Unit price: {formatMoney(review.unit_price)} · Effective from: {review.effective_from}</Typography>
        <Alert severity="warning">This creates a new version and closes any open version for this code and scheme on the preceding day. Existing posted invoice lines are not repriced. Confirm this is a finance-approved tariff.</Alert>
      </> : <>
        <Typography variant="body2">Use the service’s exact charge code. A blank scheme means the general rate. Pricing remains server-calculated for the service date.</Typography>
        {revision && <Alert severity="info">Current version starts {revision.effective_from} at {formatMoney(revision.unit_price)}. Enter the approved replacement price and date.</Alert>}
        <TextField label="Charge code" value={values.charge_code} disabled={!!revision}
          error={!!errors.charge_code} helperText={errors.charge_code?.[0]}
          onChange={(e) => setValues({ ...values, charge_code: e.target.value })} />
        <TextField label="Description" value={values.description} error={!!errors.description} helperText={errors.description?.[0]}
          onChange={(e) => setValues({ ...values, description: e.target.value })} />
        <TextField select label="Category" value={values.charge_category} disabled={!!revision}
          error={!!errors.charge_category} helperText={errors.charge_category ? "Select a category." : undefined}
          onChange={(e) => setValues({ ...values, charge_category: e.target.value })}>
          {Object.entries(CHARGE_CATEGORY_LABELS).map(([code, label]) => <MenuItem key={code} value={code}>{label}</MenuItem>)}
        </TextField>
        <TextField label="Unit price (₹)" value={values.unit_price} slotProps={{ htmlInput: { inputMode: "decimal" } }}
          error={!!errors.unit_price} helperText={errors.unit_price?.[0]}
          onChange={(e) => setValues({ ...values, unit_price: e.target.value })} />
        <TextField label="Effective from" type="date" value={values.effective_from} slotProps={{ inputLabel: { shrink: true } }}
          error={!!errors.effective_from} helperText={errors.effective_from?.[0]}
          onChange={(e) => setValues({ ...values, effective_from: e.target.value })} />
        <TextField label="Scheme code (optional)" value={values.scheme_code} disabled={!!revision}
          error={!!errors.scheme_code} helperText={errors.scheme_code?.[0] ?? "Blank = general rate; otherwise use the exact approved scheme code."}
          onChange={(e) => setValues({ ...values, scheme_code: e.target.value })} />
      </>}
    </Stack>
  </Modal>;
}
