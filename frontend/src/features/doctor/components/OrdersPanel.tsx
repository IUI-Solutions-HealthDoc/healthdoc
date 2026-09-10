"use client";

import * as React from "react";
import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";

import { Button } from "@/components/ui/Button";
import { Badge, type BadgeVariant } from "@/components/ui/Badge";
import { meridian } from "@/styles/theme";
import { ORDER_TYPE_OPTIONS } from "../constants";
import { useOrders } from "../hooks/useOrders";
import { doctorPanelSx, doctorButtonSx } from "../panelSx";
import type { ActiveEncounter, OrderPriority, PlacedOrder } from "../types";
import { OrderFormModal } from "./OrderFormModal";
import { ExternalResultPanel } from "./ExternalResultPanel";

const PRIORITY_BADGE: Record<OrderPriority, BadgeVariant> = {
  routine: "secondary",
  urgent: "outline",
  stat: "destructive",
};

const typeLabel = (t: string) => ORDER_TYPE_OPTIONS.find((o) => o.value === t)?.label ?? t;

export interface OrdersPanelProps {
  encounter: ActiveEncounter;
  patientLabel?: string;
}

export function OrdersPanel(props: OrdersPanelProps) {
  return <EncounterOrders key={`${props.encounter.patient_id}:${props.encounter.id}`} {...props} />;
}

function EncounterOrders({ encounter, patientLabel }: OrdersPanelProps) {
  const { placed, loading, adding, error, refresh, addOrder } = useOrders(encounter);
  const [open, setOpen] = React.useState(false);
  const [referredOnly, setReferredOnly] = React.useState(false);
  const [selected, setSelected] = React.useState<PlacedOrder | null>(null);
  const visible = referredOnly ? placed.filter((order) => order.fulfilment_mode === "external_referral") : placed;

  return (
    <Box sx={{ ...doctorPanelSx, display: "flex", flexDirection: "column", gap: 2 }}>
      <Stack direction="row" spacing={2} sx={{ alignItems: "flex-start", justifyContent: "space-between" }}>
        <Box>
          <Typography sx={{ fontSize: "1.0625rem", fontWeight: 700 }}>Orders</Typography>
          <Typography sx={{ fontSize: "0.8125rem", color: meridian.textSecondary, mt: 0.25 }}>
            Lab, radiology and procedure orders for this encounter
          </Typography>
        </Box>
        <Button variant="outlined" size="small" sx={doctorButtonSx} disabled={loading || adding || !!error || !!encounter.ended_at} onClick={() => setOpen(true)}>
          + Add order
        </Button>
      </Stack>

      {patientLabel && <Typography>{patientLabel}</Typography>}
      {encounter.ended_at && <Alert severity="info">Consultation completed. New orders are locked; outside results for existing referrals can still be recorded.</Alert>}
      <Stack direction="row" spacing={1}>
        <Button aria-pressed={!referredOnly} onClick={() => setReferredOnly(false)}>All orders</Button>
        <Button aria-pressed={referredOnly} onClick={() => setReferredOnly(true)}>Referred externally</Button>
        <Button disabled={loading || adding} onClick={refresh}>Refresh orders</Button>
      </Stack>

      {loading ? (
        <Typography sx={{ fontSize: "0.8125rem", color: meridian.textSecondary }}>
          Loading orders…
        </Typography>
      ) : error ? <Alert severity="error">{error}</Alert> : visible.length === 0 ? (
        <Typography sx={{ fontSize: "0.8125rem", color: meridian.textSecondary }}>
          {referredOnly ? "No externally referred orders in this encounter." : "No orders added yet for this encounter."}
        </Typography>
      ) : (
        <Stack spacing={1}>
          {visible.map((order) => (
            <Box
              key={order.id}
              sx={{
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                p: 1.5,
                borderRadius: "12px",
                border: `1px solid ${meridian.border}`,
              }}
            >
              <Box>
                <Typography sx={{ fontSize: "0.875rem", fontWeight: 600 }}>
                  {order.item_label}
                </Typography>
                <Typography
                  sx={{
                    fontSize: "0.75rem",
                    color: order.detail_status === "failed" ? meridian.danger : meridian.textSecondary,
                  }}
                >
                  {order.detail_status === "failed"
                    ? `${order.order_number} · department item failed`
                    : order.accession_number
                      ? `${order.order_number} · ${order.accession_number}`
                      : order.order_number}
                </Typography>
              </Box>
              <Stack direction="row" spacing={1} sx={{ alignItems: "center" }}>
                <Badge variant="outline">{typeLabel(order.order_type)}</Badge>
                <Badge variant={PRIORITY_BADGE[order.priority]}>{order.priority}</Badge>
                <Badge variant="outline">{order.status}</Badge>
                {order.fulfilment_mode === "external_referral" ? <Button size="small" onClick={() => setSelected(order)}>Outside results</Button> : !order.fulfilment_mode ? <span>Fulfilment unknown — refresh orders</span> : null}
              </Stack>
            </Box>
          ))}
        </Stack>
      )}

      {selected && <ExternalResultPanel
        order={placed.find((order) => order.id === selected.id) ?? selected}
        patientId={encounter.patient_id} patientLabel={patientLabel} onSaved={refresh}
      />}

      <OrderFormModal open={open} busy={adding} onClose={() => setOpen(false)} onAdd={addOrder} />
    </Box>
  );
}
