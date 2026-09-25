"use client";

import Box from "@mui/material/Box";

import { PageHeading } from "@/components/common/PageHeading";
import { OrdersWorkspace } from "@/features/doctor";
import { doctorPageSx } from "@/features/doctor/panelSx";
import { useEncounterContext } from "@/features/doctor/hooks/useEncounterContext";
import { useLocale } from "@/lib/i18n";

export default function Page() {
  const { t } = useLocale();
  const { context, loading } = useEncounterContext();

  // No fallback patient. mockEncounterContext used to supply the visit_id and
  // patient_id that orders and prescriptions are FILED AGAINST, not just the
  // name in the header — so a wrong one attaches clinical writes to the wrong
  // visit. If no token is in service there is no consultation to chart.
  if (loading) return null;
  if (!context) {
    return (
      <Box sx={doctorPageSx}>
        <p>{t("common.noPatientInService")}</p>
      </Box>
    );
  }

  return (
    <Box sx={doctorPageSx}>
      <PageHeading titleKey="doctor.ordersTitle" className="mb-4 space-y-1" />
      <OrdersWorkspace context={context} />
    </Box>
  );
}
