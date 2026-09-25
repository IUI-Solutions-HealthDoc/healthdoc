"use client";

import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import CircularProgress from "@mui/material/CircularProgress";

import { PageHeading } from "@/components/common/PageHeading";
import { PrescriptionWorkspace } from "@/features/doctor";
import { doctorPageSx } from "@/features/doctor/panelSx";
import { useEncounterContext } from "@/features/doctor/hooks/useEncounterContext";
import { usePersistedEncounter } from "@/features/doctor/hooks/usePersistedEncounter";
import type { EncounterContext } from "@/features/doctor/types";
import { useLocale } from "@/lib/i18n";

/**
 * Resolve the encounter from PostgreSQL. A prescription must never point at a
 * browser-generated UUID.
 */
function PrescribeFor({ context }: { context: EncounterContext }) {
  const { t } = useLocale();
  const { encounter, loading, error } = usePersistedEncounter(context);

  return (
    <Box sx={doctorPageSx}>
      <PageHeading titleKey="doctor.prescriptionsTitle" className="mb-4 space-y-1" />
      {loading ? (
        <CircularProgress size={28} />
      ) : error ? (
        <Alert severity="error">{error}</Alert>
      ) : encounter?.ended_at ? (
        <Alert severity="info">{t("doctor.prescriptionCompletedLocked")}</Alert>
      ) : encounter ? (
        <PrescriptionWorkspace context={context} encounter={encounter} />
      ) : (
        <Alert severity="info">{t("doctor.saveConsultationBeforePrescription")}</Alert>
      )}
    </Box>
  );
}

export default function Page() {
  const { t } = useLocale();
  const { context, loading } = useEncounterContext();

  // No fallback patient. mockEncounterContext supplied the visit_id and
  // patient_id a prescription is FILED AGAINST, not just the name in the
  // header — a wrong one attaches a drug order to the wrong visit. If no token
  // is in service there is no consultation to prescribe into.
  if (loading) return null;
  if (!context) {
    return (
      <Box sx={doctorPageSx}>
        <p>{t("common.noPatientInService")}</p>
      </Box>
    );
  }

  return <PrescribeFor context={context} />;
}
