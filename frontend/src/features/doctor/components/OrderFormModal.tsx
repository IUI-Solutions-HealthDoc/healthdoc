"use client";

import * as React from "react";
import MenuItem from "@mui/material/MenuItem";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";

import { Button } from "@/components/ui/Button";
import { Modal } from "@/components/ui/Modal";
import { useLocale } from "@/lib/i18n";
import type { MessageKey } from "@/lib/i18n";
import {
  MODALITY_OPTIONS,
  ORDER_PRIORITY_OPTIONS,
  ORDER_TYPE_OPTIONS,
  PROCEDURE_SETTING_OPTIONS,
  SAMPLE_TYPE_OPTIONS,
} from "../constants";
import { doctorButtonSx } from "../panelSx";
import type {
  DraftOrder,
  Modality,
  OrderPriority,
  OrderType,
  ProcedureSetting,
  SampleType,
} from "../types";

const ORDER_TYPE_KEYS: Record<OrderType, MessageKey> = {
  lab: "doctor.orderType.lab",
  radiology: "doctor.orderType.radiology",
  procedure: "doctor.orderType.procedure",
  pharmacy: "doctor.orderType.pharmacy",
  blood: "doctor.orderType.blood",
};

const PRIORITY_KEYS: Record<OrderPriority, MessageKey> = {
  routine: "doctor.orderPriority.routine",
  urgent: "doctor.orderPriority.urgent",
  stat: "doctor.orderPriority.stat",
};

const SAMPLE_KEYS: Record<SampleType, MessageKey> = {
  blood: "doctor.sampleType.blood",
  serum: "doctor.sampleType.serum",
  plasma: "doctor.sampleType.plasma",
  urine: "doctor.sampleType.urine",
  stool: "doctor.sampleType.stool",
  swab: "doctor.sampleType.swab",
  tissue: "doctor.sampleType.tissue",
};

const MODALITY_KEYS: Record<Modality, MessageKey> = {
  xray: "doctor.modality.xray",
  ct: "doctor.modality.ct",
  mri: "doctor.modality.mri",
  usg: "doctor.modality.usg",
  mammo: "doctor.modality.mammo",
};

const PROCEDURE_SETTING_KEYS: Record<ProcedureSetting, MessageKey> = {
  opd_minor: "doctor.procedureSetting.opd_minor",
  bedside: "doctor.procedureSetting.bedside",
  emergency: "doctor.procedureSetting.emergency",
  ot: "doctor.procedureSetting.ot",
};

export interface OrderFormModalProps {
  open: boolean;
  busy: boolean;
  onClose: () => void;
  onAdd: (
    draft: Omit<DraftOrder, "tempId">,
    idempotencyKey: string,
  ) => Promise<boolean> | boolean;
}

export function OrderFormModal({ open, busy, onClose, onAdd }: OrderFormModalProps) {
  const { t } = useLocale();
  const [orderType, setOrderType] = React.useState<OrderType>("lab");
  const [item, setItem] = React.useState("");
  const [priority, setPriority] = React.useState<OrderPriority>("routine");
  const [sampleType, setSampleType] = React.useState<SampleType>("blood");
  const [modality, setModality] = React.useState<Modality>("xray");
  const [procedureSetting, setProcedureSetting] = React.useState<ProcedureSetting>("opd_minor");
  const [idempotencyKey, setIdempotencyKey] = React.useState(() => crypto.randomUUID());

  const reset = () => {
    setOrderType("lab");
    setItem("");
    setPriority("routine");
    setSampleType("blood");
    setModality("xray");
    setProcedureSetting("opd_minor");
    setIdempotencyKey(crypto.randomUUID());
  };

  const close = () => {
    reset();
    onClose();
  };

  const handleAdd = async () => {
    const label = item.trim();
    if (!label) return;
    const ok = await onAdd(
      {
        order_type: orderType,
        priority,
        ...(orderType === "lab"
          ? { test_name: label, sample_type: sampleType }
          : orderType === "radiology"
            ? { scan_type: label, modality }
            : { procedure_name: label, setting: procedureSetting }),
      },
      idempotencyKey,
    );
    if (ok) close();
  };

  const itemLabel =
    orderType === "lab"
      ? t("doctor.orderTestName")
      : orderType === "radiology"
        ? t("doctor.orderStudyName")
        : t("doctor.orderProcedureName");

  const secondaryLabel =
    orderType === "lab"
      ? t("doctor.orderSampleType")
      : orderType === "radiology"
        ? t("doctor.orderModality")
        : t("doctor.orderProcedureSetting");

  return (
    <Modal
      open={open}
      onClose={close}
      title={t("doctor.orderModalTitle")}
      loading={busy}
      actions={
        <>
          <Button sx={doctorButtonSx} onClick={close}>
            {t("common.cancel")}
          </Button>
          <Button
            variant="contained"
            sx={doctorButtonSx}
            onClick={handleAdd}
            disabled={!item.trim()}
          >
            {t("doctor.orderModalAdd")}
          </Button>
        </>
      }
    >
      <Stack spacing={2}>
        <TextField
          select
          label={t("doctor.orderTypeLabel")}
          value={orderType}
          onChange={(event) => {
            setOrderType(event.target.value as OrderType);
            setItem("");
          }}
          size="small"
        >
          {ORDER_TYPE_OPTIONS.map((option) => (
            <MenuItem key={option.value} value={option.value}>
              {t(ORDER_TYPE_KEYS[option.value])}
            </MenuItem>
          ))}
        </TextField>

        <TextField
          label={itemLabel}
          value={item}
          onChange={(event) => setItem(event.target.value)}
          helperText={t("doctor.orderClinicalTextHint")}
          size="small"
          autoFocus
        />

        <TextField
          select
          label={secondaryLabel}
          value={
            orderType === "lab"
              ? sampleType
              : orderType === "radiology"
                ? modality
                : procedureSetting
          }
          onChange={(event) => {
            if (orderType === "lab") setSampleType(event.target.value as SampleType);
            else if (orderType === "radiology") setModality(event.target.value as Modality);
            else setProcedureSetting(event.target.value as ProcedureSetting);
          }}
          size="small"
          helperText={t("doctor.orderRowRequiredHint")}
        >
          {(orderType === "lab"
            ? SAMPLE_TYPE_OPTIONS
            : orderType === "radiology"
              ? MODALITY_OPTIONS
              : PROCEDURE_SETTING_OPTIONS
          ).map((option) => {
            const labelKey =
              orderType === "lab"
                ? SAMPLE_KEYS[option.value as SampleType]
                : orderType === "radiology"
                  ? MODALITY_KEYS[option.value as Modality]
                  : PROCEDURE_SETTING_KEYS[option.value as ProcedureSetting];
            return (
              <MenuItem key={option.value} value={option.value}>
                {t(labelKey)}
              </MenuItem>
            );
          })}
        </TextField>

        <TextField
          select
          label={t("doctor.orderPriority")}
          value={priority}
          onChange={(event) => setPriority(event.target.value as OrderPriority)}
          size="small"
        >
          {ORDER_PRIORITY_OPTIONS.map((option) => (
            <MenuItem key={option.value} value={option.value}>
              {t(PRIORITY_KEYS[option.value])}
            </MenuItem>
          ))}
        </TextField>
      </Stack>
    </Modal>
  );
}
