"use client";

import Box from "@mui/material/Box";
import Stack from "@mui/material/Stack";

import { PageHeading } from "@/components/common/PageHeading";
import { BillingMisPanel, EdCensusPanel, MisDashboard, ReceptionistTrackerPanel } from "@/features/reports";
import { ROLES } from "@/config/roles";
import { useAuth } from "@/providers/auth-provider";

/**
 * Reports and Executive Operational MIS:
 * - Receptionist live tracker & queue wait time
 * - Emergency Department live census & triage acuity
 * - Clinical & facility KPI snapshots
 * - Billing & collection MIS
 */
const CLINICAL_KPI_ROLES: string[] = [ROLES.ADMIN, ROLES.AUDITOR, ROLES.SUPERVISOR, ROLES.DOCTOR, ROLES.NURSE];
const FINANCE_MIS_ROLES: string[] = [ROLES.ADMIN, ROLES.AUDITOR, ROLES.BILLING];

export default function Page() {
  const { user } = useAuth();
  const role = user?.role ?? "";

  return (
    <Box sx={{ mx: "auto", maxWidth: 1280, px: { xs: 2, md: 3 }, py: 3 }}>
      <Stack spacing={3}>
        <PageHeading titleKey="reports.title" />
        <ReceptionistTrackerPanel />
        <EdCensusPanel />
        {CLINICAL_KPI_ROLES.includes(role) ? <MisDashboard /> : null}
        {FINANCE_MIS_ROLES.includes(role) ? <BillingMisPanel /> : null}
      </Stack>
    </Box>
  );
}
