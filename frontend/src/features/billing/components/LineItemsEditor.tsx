"use client";

import { useState } from "react";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import IconButton from "@mui/material/IconButton";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";
import DeleteOutlinedIcon from "@mui/icons-material/DeleteOutlined";

import { DataTable, type DataTableColumn } from "@/components/tables/DataTable";
import { useLocale } from "@/lib/i18n";
import { meridian } from "@/styles/theme";
import { formatINR } from "../lib/formatters";
import { chargeCategoryLabel } from "../lib/labels";
import { fromMoney } from "../lib/money";
import type { AddInvoiceItemInput, InvoiceItem } from "../types";
import { AddInvoiceItemModal } from "./AddInvoiceItemModal";

type Props = {
  items: InvoiceItem[];
  canEdit: boolean;
  busy?: boolean;
  scheme_code?: string | null;
  onAdd: (body: AddInvoiceItemInput) => Promise<void> | void;
  onPatch: (
    itemId: string,
    patch: Partial<{ quantity: number; unit_price: number; description: string }>,
  ) => Promise<void> | void;
  onRemove: (itemId: string) => Promise<void> | void;
};

export function LineItemsEditor({
  items,
  canEdit,
  busy,
  scheme_code,
  onAdd,
  onPatch,
  onRemove,
}: Props) {
  const { t } = useLocale();
  const [addOpen, setAddOpen] = useState(false);

  const columns: DataTableColumn<InvoiceItem>[] = [
    {
      key: "charge_category",
      label: t("billing.lineItems.col.category"),
      width: "14%",
      render: (row) => chargeCategoryLabel(t, row.charge_category),
    },
    {
      key: "description",
      label: t("billing.lineItems.col.description"),
      render: (row) =>
        canEdit ? (
          <TextField
            size="small"
            fullWidth
            defaultValue={row.description}
            onBlur={(e) => {
              if (e.target.value !== row.description) {
                void onPatch(row.id, { description: e.target.value });
              }
            }}
          />
        ) : (
          row.description
        ),
    },
    {
      key: "quantity",
      label: t("billing.lineItems.col.qty"),
      width: 100,
      align: "right",
      render: (row) =>
        canEdit ? (
          <TextField
            size="small"
            type="number"
            defaultValue={row.quantity}
            slotProps={{ htmlInput: { min: 0.01, step: 1 } }}
            onBlur={(e) => {
              const quantity = Number(e.target.value);
              if (quantity > 0 && quantity !== row.quantity) {
                void onPatch(row.id, { quantity });
              }
            }}
            sx={{ width: 88 }}
          />
        ) : (
          row.quantity
        ),
    },
    {
      key: "unit_price",
      label: t("billing.lineItems.col.unitPrice"),
      width: 120,
      align: "right",
      render: (row) =>
        canEdit ? (
          <TextField
            size="small"
            type="number"
            defaultValue={fromMoney(row.unit_price)}
            slotProps={{ htmlInput: { min: 0, step: 1 } }}
            onBlur={(e) => {
              const unit_price = Number(e.target.value);
              if (unit_price >= 0 && unit_price !== fromMoney(row.unit_price)) {
                void onPatch(row.id, { unit_price });
              }
            }}
            sx={{ width: 110 }}
          />
        ) : (
          formatINR(row.unit_price)
        ),
    },
    {
      key: "amount",
      label: t("billing.lineItems.col.amount"),
      width: 120,
      align: "right",
      render: (row) => (
        <Typography sx={{ fontWeight: 600, fontSize: "0.875rem" }}>
          {formatINR(row.amount)}
        </Typography>
      ),
    },
    {
      key: "actions",
      label: "",
      width: 56,
      align: "center",
      render: (row) =>
        canEdit ? (
          <IconButton
            size="small"
            aria-label={t("billing.lineItems.removeAria")}
            disabled={busy}
            onClick={() => void onRemove(row.id)}
            sx={{ color: meridian.danger }}
          >
            <DeleteOutlinedIcon fontSize="small" />
          </IconButton>
        ) : null,
    },
  ];

  return (
    <Box
      sx={{
        borderRadius: "16px",
        border: `1px solid ${meridian.border}`,
        background: `linear-gradient(180deg, ${meridian.surface} 0%, #fbfcfe 100%)`,
        boxShadow: "0 1px 2px rgb(0 31 84 / 0.04), 0 12px 32px rgb(0 31 84 / 0.06)",
        overflow: "hidden",
      }}
    >
      <Stack
        direction="row"
        sx={{
          px: 2.5,
          pt: 2.25,
          pb: 1.75,
          justifyContent: "space-between",
          alignItems: "center",
          gap: 2,
        }}
      >
        <Box>
          <Typography
            sx={{
              m: 0,
              fontSize: "1.0625rem",
              fontWeight: 700,
              color: meridian.textPrimary,
            }}
          >
            {t("billing.lineItems.title")}
          </Typography>
          <Typography sx={{ m: 0, mt: 0.4, fontSize: "0.8125rem", color: meridian.textSecondary }}>
            {t("billing.lineItems.hint")}
          </Typography>
        </Box>
        {canEdit ? (
          <Button
            variant="outlined"
            size="small"
            disabled={busy}
            onClick={() => setAddOpen(true)}
            sx={{ textTransform: "none", fontWeight: 600, borderRadius: "10px" }}
          >
            {t("billing.lineItems.addItem")}
          </Button>
        ) : null}
      </Stack>

      <DataTable
        columns={columns}
        rows={items}
        getRowId={(row) => row.id}
        emptyMessage={t("billing.noLineItems")}
      />

      <AddInvoiceItemModal
        open={addOpen}
        scheme_code={scheme_code}
        onClose={() => setAddOpen(false)}
        onSave={async (body) => {
          await onAdd(body);
          setAddOpen(false);
        }}
      />
    </Box>
  );
}
