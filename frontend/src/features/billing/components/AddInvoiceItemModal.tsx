"use client";

import { useEffect, useState } from "react";
import Button from "@mui/material/Button";
import MenuItem from "@mui/material/MenuItem";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";

import { Modal } from "@/components/ui/Modal";
import { listChargeMaster } from "../api/chargeMaster";
import { formatMoney } from "@/lib/api";
import type { AddInvoiceItemInput, ChargeMaster } from "../types";

type Props = {
  open: boolean;
  onClose: () => void;
  onSave: (body: AddInvoiceItemInput) => Promise<void> | void;
  /** Prefer scheme-specific tariffs when invoice has a scheme */
  scheme_code?: string | null;
};

export function AddInvoiceItemModal({ open, onClose, onSave, scheme_code }: Props) {
  const [tariffs, setTariffs] = useState<ChargeMaster[]>([]);
  const [chargeMasterId, setChargeMasterId] = useState("");
  const [quantity, setQuantity] = useState(1);
  const [saving, setSaving] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    void listChargeMaster({ active_only: true, scheme_code: "all" }).then((rows) => {
      if (cancelled) return;
      // Prefer general tariffs; include scheme match when invoice has scheme
      const general = rows.filter((r) => r.scheme_code === null);
      const schemeRows =
        scheme_code != null
          ? rows.filter((r) => r.scheme_code === scheme_code)
          : [];
      const byCode = new Map<string, ChargeMaster>();
      for (const r of general) byCode.set(r.charge_code, r);
      for (const r of schemeRows) byCode.set(r.charge_code, r);
      const list = [...byCode.values()].sort((a, b) =>
        a.charge_code.localeCompare(b.charge_code),
      );
      setTariffs(list);
      setChargeMasterId(list[0]?.id ?? "");
    }).catch((error: unknown) => {
      if (!cancelled) setError(error instanceof Error ? error.message : "Could not load tariffs.");
    }).finally(() => { if (!cancelled) setLoading(false); });
    return () => {
      cancelled = true;
    };
  }, [open, scheme_code]);

  const selected = tariffs.find((t) => t.id === chargeMasterId) ?? null;

  const reset = () => {
    setQuantity(1);
    setChargeMasterId(tariffs[0]?.id ?? "");
  };

  const handleClose = () => {
    if (saving) return;
    reset();
    onClose();
  };

  const handleSave = async () => {
    if (!selected || quantity <= 0) return;
    setSaving(true);
    try {
      await onSave({
        charge_category: selected.charge_category,
        description: selected.description,
        quantity,
        unit_price: { amount: selected.unit_price, currency: "INR" },
        charge_master_id: selected.id,
      });
      reset();
    } catch (error) {
      setError(error instanceof Error ? error.message : "Could not add the item.");
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal
      open={open}
      onClose={handleClose}
      title="Add from charge master"
      size="sm"
      loading={saving || loading}
      actions={
        <>
          <Button onClick={handleClose} sx={{ textTransform: "none" }}>
            Cancel
          </Button>
          <Button
            variant="contained"
            onClick={() => void handleSave()}
            disabled={!selected || quantity <= 0}
            sx={{ textTransform: "none", fontWeight: 600, borderRadius: "10px" }}
          >
            Add
          </Button>
        </>
      }
    >
      <Stack spacing={2} sx={{ pt: 1 }}>
        {error ? <Typography role="alert" color="error">{error}</Typography> : null}
        <Typography sx={{ fontSize: "0.8125rem", color: "text.secondary" }}>
          Prices come from charge_master (0033). Missing tariff → BE returns 409
          no_tariff on accrual.
        </Typography>
        <TextField
          select
          label="Tariff"
          value={chargeMasterId}
          onChange={(e) => setChargeMasterId(e.target.value)}
          fullWidth
          size="small"
          disabled={loading || tariffs.length === 0}
        >
          {tariffs.map((t) => (
            <MenuItem key={t.id} value={t.id}>
              {t.charge_code} — {t.description} ({formatMoney(t.unit_price)}
              {t.scheme_code ? ` · ${t.scheme_code}` : ""})
            </MenuItem>
          ))}
        </TextField>
        {selected ? (
          <Typography sx={{ fontSize: "0.8125rem" }}>
            Category: {selected.charge_category} · Unit: {formatMoney(selected.unit_price)}
          </Typography>
        ) : null}
        <TextField
          type="number"
          label="Quantity"
          value={quantity}
          onChange={(e) => setQuantity(Number(e.target.value) || 0)}
          slotProps={{ htmlInput: { min: 0.01, step: 1 } }}
          fullWidth
          size="small"
        />
      </Stack>
    </Modal>
  );
}
