"use client";

import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import CircularProgress from "@mui/material/CircularProgress";

import { usePersistedEncounter } from "../hooks/usePersistedEncounter";
import type { EncounterContext } from "../types";
import { OrdersPanel } from "./OrdersPanel";

export interface OrdersWorkspaceProps {
  context: EncounterContext;
}

/** Standalone /doctor/orders view — the same Orders panel used in the consultation. */
export function OrdersWorkspace(props: OrdersWorkspaceProps) {
  return <EncounterWorkspace key={`${props.context.patient_id}:${props.context.visit_id}`} {...props} />;
}

function EncounterWorkspace({ context }: OrdersWorkspaceProps) {
  const { encounter, loading, error } = usePersistedEncounter(context);

  if (loading) return <CircularProgress size={28} />;
  if (error) return <Alert severity="error">{error}</Alert>;
  if (!encounter) {
    return (
      <Alert severity="info">
        Save this patient&apos;s consultation before placing an order.
      </Alert>
    );
  }

  return (
    <Box sx={{ display: "flex", flexDirection: "column", gap: 3 }}>
      <OrdersPanel encounter={encounter} patientLabel={`${context.patient_name} · ${context.uhid || context.patient_id}`} />
    </Box>
  );
}
