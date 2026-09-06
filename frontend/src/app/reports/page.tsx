"use client";

import Box from "@mui/material/Box";

import { BillingMisPanel, MisDashboard } from "@/features/reports";
import { ROLES } from "@/config/roles";
import { useAuth } from "@/providers/auth-provider";

/**
 * Two panels, two audiences, mounted separately.
 *
 * They used to be one component, which meant every visitor fetched both
 * /reports/kpis and /billing/mis/*. Splitting billing out of the front desk
 * left the billing role 403ing on the clinical KPIs and the supervisor 403ing
 * on the finance panel — the same screen broken from both directions.
 *
 * Gating the render alone is not enough: the KPI hook fetches on mount, so the
 * component must not be mounted at all for a role that cannot read it.
 */
const CLINICAL_KPI_ROLES: string[] = [ROLES.ADMIN, ROLES.AUDITOR, ROLES.SUPERVISOR];
const FINANCE_MIS_ROLES: string[] = [ROLES.ADMIN, ROLES.AUDITOR, ROLES.BILLING];

export default function Page() {
  const { user } = useAuth();
  const role = user?.role ?? "";

  return (
    <Box sx={{ mx: "auto", maxWidth: 1280, px: { xs: 2, md: 3 }, py: 3 }}>
      {CLINICAL_KPI_ROLES.includes(role) ? <MisDashboard /> : null}
      {FINANCE_MIS_ROLES.includes(role) ? <BillingMisPanel /> : null}
    </Box>
  );
}
