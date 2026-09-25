"use client";

import { useRef, useState } from "react";
import { Alert, Button, MenuItem, Stack, TextField, Typography } from "@mui/material";
import { Modal } from "@/components/ui/Modal";
import { formatMoney, newIdempotencyKey } from "@/lib/api";
import { useLocale } from "@/lib/i18n";
import { createTariff } from "../api/chargeMaster";
import { CHARGE_CATEGORIES, chargeCategoryLabel } from "../lib/labels";
import { tariffFormSchema } from "../lib/tariff-form";
import type { ChargeMaster, TariffCreateInput } from "../types";

export function TariffForm({ revision, onClose, onSaved }: {
  revision: ChargeMaster | null; onClose: () => void; onSaved: () => void;
}) {
  const { t } = useLocale();
  const [values, setValues] = useState({ charge_code: revision?.charge_code ?? "",
    description: revision?.description ?? "", description_hi: revision?.description_hi ?? "",
    charge_category: revision?.charge_category ?? "",
    unit_price: "", effective_from: "", scheme_code: revision?.scheme_code ?? "" });
  const [errors, setErrors] = useState<Record<string, string[] | undefined>>({});
  const [review, setReview] = useState<TariffCreateInput | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const saving = useRef(false);
  const [actionKey] = useState(newIdempotencyKey);
  const close = () => { if (!saving.current) onClose(); };
  const schemeGeneral = t("billing.tariff.schemeGeneral");

  function validate() {
    const parsed = tariffFormSchema.safeParse(values);
    if (!parsed.success) { setErrors(parsed.error.flatten().fieldErrors); return; }
    if (revision && parsed.data.effective_from <= revision.effective_from) {
      setErrors({
        effective_from: [t("billing.tariff.form.effectiveAfterDate", { date: revision.effective_from })],
      });
      return;
    }
    setErrors({}); setReview(parsed.data);
  }

  async function save() {
    if (!review || saving.current || error) return;
    saving.current = true; setBusy(true);
    try { await createTariff(review, actionKey); onSaved(); }
    catch (error) {
      setError(error instanceof Error ? error.message : t("billing.tariff.form.saveFailed"));
    } finally { saving.current = false; setBusy(false); }
  }

  const modalTitle = review
    ? t("billing.tariff.form.reviewTitle")
    : revision
      ? t("billing.tariff.form.reviseTitle")
      : t("billing.tariff.form.newTitle");

  return <Modal open onClose={close} title={modalTitle}
    loading={busy} actions={<>
      <Button onClick={close}>{error ? t("billing.tariff.closeCheckCatalogue") : t("billing.common.cancel")}</Button>
      {!error && (review ? <>
        <Button onClick={() => setReview(null)}>{t("billing.tariff.form.backEdit")}</Button>
        <Button variant="contained" onClick={() => void save()}>{t("billing.tariff.form.saveVersion")}</Button>
      </> : <Button variant="contained" onClick={validate}>{t("billing.tariff.form.reviewButton")}</Button>)}
    </>}>
    <Stack spacing={2}>
      {error && <Alert severity="error">{error} {t("billing.tariff.form.saveErrorHint")}</Alert>}
      {review ? <>
        <Typography>{t("billing.tariff.form.reviewCodeScheme", {
          code: review.charge_code,
          scheme: review.scheme_code ?? schemeGeneral,
        })}</Typography>
        <Typography>{review.description} · {chargeCategoryLabel(t, review.charge_category)}</Typography>
        <Typography>{t("billing.tariff.form.reviewDetails", {
          price: formatMoney(review.unit_price),
          effectiveFrom: review.effective_from,
        })}</Typography>
        <Alert severity="warning">{t("billing.tariff.form.reviewWarning")}</Alert>
      </> : <>
        <Typography variant="body2">{t("billing.tariff.form.hint")}</Typography>
        {revision && <Alert severity="info">{t("billing.tariff.form.revisionInfo", {
          effectiveFrom: revision.effective_from,
          price: formatMoney(revision.unit_price),
        })}</Alert>}
        <TextField label={t("billing.tariff.form.chargeCode")} value={values.charge_code} disabled={!!revision}
          error={!!errors.charge_code} helperText={errors.charge_code?.[0]}
          onChange={(e) => setValues({ ...values, charge_code: e.target.value })} />
        <TextField label={t("billing.tariff.form.description")} value={values.description} error={!!errors.description} helperText={errors.description?.[0]}
          onChange={(e) => setValues({ ...values, description: e.target.value })} />
        <TextField label={t("billing.descriptionHi")} value={values.description_hi}
          error={!!errors.description_hi} helperText={errors.description_hi?.[0] ?? t("billing.tariff.form.descriptionHiHint")}
          onChange={(e) => setValues({ ...values, description_hi: e.target.value })} />
        <TextField select label={t("billing.tariff.form.category")} value={values.charge_category} disabled={!!revision}
          error={!!errors.charge_category} helperText={errors.charge_category ? t("billing.tariff.form.selectCategory") : undefined}
          onChange={(e) => setValues({ ...values, charge_category: e.target.value })}>
          {CHARGE_CATEGORIES.map((code) => (
            <MenuItem key={code} value={code}>{chargeCategoryLabel(t, code)}</MenuItem>
          ))}
        </TextField>
        <TextField label={t("billing.tariff.form.unitPrice")} value={values.unit_price} slotProps={{ htmlInput: { inputMode: "decimal" } }}
          error={!!errors.unit_price} helperText={errors.unit_price?.[0]}
          onChange={(e) => setValues({ ...values, unit_price: e.target.value })} />
        <TextField label={t("billing.tariff.form.effectiveFrom")} type="date" value={values.effective_from} slotProps={{ inputLabel: { shrink: true } }}
          error={!!errors.effective_from} helperText={errors.effective_from?.[0]}
          onChange={(e) => setValues({ ...values, effective_from: e.target.value })} />
        <TextField label={t("billing.tariff.form.schemeCode")} value={values.scheme_code} disabled={!!revision}
          error={!!errors.scheme_code} helperText={errors.scheme_code?.[0] ?? t("billing.tariff.form.schemeHint")}
          onChange={(e) => setValues({ ...values, scheme_code: e.target.value })} />
      </>}
    </Stack>
  </Modal>;
}
