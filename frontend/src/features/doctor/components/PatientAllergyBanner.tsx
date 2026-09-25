"use client";

import * as React from "react";
import Box from "@mui/material/Box";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";

import { useLocale } from "@/lib/i18n";
import { meridian } from "@/styles/theme";
import { listAllergies } from "../api";
import type { Allergy } from "../types";

/**
 * Standing allergy banner for the whole consultation.
 *
 * Loaded when the screen opens, not when prescribing starts: the doctor should
 * know about an anaphylaxis before choosing a drug, not after. This is
 * informational — the blocking check happens per item at prescribing time.
 *
 * An allergy with no ingredient_code is called out explicitly, because it
 * cannot be matched automatically and silence would read as "checked and clear".
 */
export function PatientAllergyBanner({ patientId }: { patientId: string }) {
  const { t } = useLocale();
  const [allergies, setAllergies] = React.useState<Allergy[]>([]);
  const [loaded, setLoaded] = React.useState(false);

  const [error, setError] = React.useState<string | null>(null);

  React.useEffect(() => {
    let alive = true;
    void listAllergies(patientId)
      .then((rows) => {
        if (!alive) return;
        setAllergies(rows);
        setLoaded(true);
      })
      .catch((e: unknown) => {
        if (!alive) return;
        // A failed allergy read must be loud. Showing nothing would let the
        // clinician assume the patient has no allergies.
        setError(e instanceof Error ? e.message : t("doctor.errLoadAllergies"));
        setLoaded(true);
      });
    return () => {
      alive = false;
    };
  }, [patientId]);

  // Never render nothing: a blank space where allergies belong reads as
  // "no allergies", which is exactly the failure this banner exists to prevent.
  if (!loaded) {
    return (
      <Box
        sx={{
          px: 2,
          py: 1.25,
          borderRadius: "16px",
          backgroundColor: meridian.muted,
          border: `1px solid ${meridian.border}`,
        }}
      >
        <Typography sx={{ fontSize: "0.8125rem", color: meridian.textSecondary }}>
          {t("doctor.loadingAllergies")}
        </Typography>
      </Box>
    );
  }

  if (error) {
    return (
      <Box
        sx={{
          px: 2,
          py: 1.25,
          borderRadius: "16px",
          backgroundColor: "#fee2e2",
          border: "1px solid rgb(185 28 28 / 0.22)",
        }}
      >
        <Typography sx={{ fontSize: "0.8125rem", color: meridian.textPrimary }}>
          <strong>{t("doctor.allergyLoadFailedBanner")}</strong> ({error})
        </Typography>
      </Box>
    );
  }

  const absolute = allergies.some((a) => a.severity === "anaphylaxis");
  const uncoded = allergies.filter((a) => !a.ingredient_code).length;

  if (allergies.length === 0) {
    return (
      <Box
        sx={{
          px: 2,
          py: 1.25,
          borderRadius: "16px",
          backgroundColor: meridian.muted,
          border: `1px solid ${meridian.border}`,
        }}
      >
        <Typography sx={{ fontSize: "0.8125rem", color: meridian.textSecondary }}>
          <strong>No allergies recorded</strong> for this patient. Confirm with the patient before
          prescribing — an empty record is not the same as no allergy.
        </Typography>
      </Box>
    );
  }

  return (
    <Box
      sx={{
        px: 2,
        py: 1.5,
        borderRadius: "16px",
        backgroundColor: absolute ? "#fee2e2" : "#fef3c7",
        border: `1px solid ${absolute ? "rgb(185 28 28 / 0.22)" : "rgb(180 83 9 / 0.22)"}`,
      }}
    >
      <Typography
        sx={{
          fontSize: "0.6875rem",
          fontWeight: 700,
          letterSpacing: "0.06em",
          textTransform: "uppercase",
          color: absolute ? meridian.danger : meridian.warning,
          mb: 0.75,
        }}
      >
        Allergies on record
      </Typography>

      <Stack direction="row" spacing={1} sx={{ flexWrap: "wrap", gap: 0.75 }}>
        {allergies.map((a) => {
          const hard = a.severity === "anaphylaxis";
          return (
            <Box
              key={a.id}
              sx={{
                px: 1,
                py: 0.4,
                borderRadius: "8px",
                backgroundColor: meridian.surface,
                border: `1px solid ${hard ? "rgb(185 28 28 / 0.3)" : meridian.border}`,
              }}
            >
              <Typography
                sx={{
                  fontSize: "0.8125rem",
                  fontWeight: 600,
                  color: hard ? meridian.danger : meridian.textPrimary,
                }}
              >
                {a.substance_text}
              </Typography>
              <Typography sx={{ fontSize: "0.6875rem", color: meridian.textSecondary }}>
                {a.severity}
                {a.reaction ? ` · ${a.reaction}` : ""}
              </Typography>
            </Box>
          );
        })}
      </Stack>

      {uncoded > 0 && (
        <Typography sx={{ fontSize: "0.75rem", color: meridian.textPrimary, mt: 1 }}>
          {uncoded} of these {uncoded === 1 ? "has" : "have"} no ingredient code —{" "}
          <strong>they cannot be checked automatically when you prescribe.</strong>
        </Typography>
      )}
    </Box>
  );
}
