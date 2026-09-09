"use client";

import * as React from "react";
import Box from "@mui/material/Box";
import Divider from "@mui/material/Divider";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";
import Link from "next/link";

import { Button } from "@/components/ui/Button";
import { StatusChip } from "@/components/ui/StatusChip";
import { meridian } from "@/styles/theme";
import { getPatient, getPatientHistory, listAllergies } from "../api";
import { formatAgeSex } from "../lib/formatters";
import { doctorPanelSx } from "../panelSx";
import type { Allergy, Patient, PatientHistoryEntry, QueueToken, QueueTokenStatus } from "../types";

const CONSULTABLE: QueueTokenStatus[] = ["waiting", "called", "in_service", "recalled"];

const labelSx = {
  fontSize: "0.6875rem",
  fontWeight: 600,
  letterSpacing: "0.06em",
  textTransform: "uppercase",
  color: meridian.textSecondary,
} as const;

function Field({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <Box>
      <Typography sx={labelSx}>{label}</Typography>
      <Typography sx={{ fontSize: "0.875rem", fontWeight: 500, mt: 0.25 }}>{value}</Typography>
    </Box>
  );
}

/** Anaphylaxis reads differently from every other allergy, because it is. */
function AllergyRow({ allergy }: { allergy: Allergy }) {
  const absolute = allergy.severity === "anaphylaxis";
  return (
    <Box
      sx={{
        px: 1,
        py: 0.5,
        borderRadius: "8px",
        color: absolute ? meridian.danger : meridian.textPrimary,
        backgroundColor: absolute ? "#fee2e2" : meridian.muted,
        border: `1px solid ${absolute ? "rgb(185 28 28 / 0.22)" : meridian.border}`,
      }}
    >
      <Typography sx={{ fontSize: "0.8125rem", fontWeight: 600 }}>
        {allergy.substance_text}
      </Typography>
      <Typography
        sx={{
          fontSize: "0.6875rem",
          color: absolute ? meridian.danger : meridian.textSecondary,
        }}
      >
        {allergy.severity}
        {allergy.reaction ? ` · ${allergy.reaction}` : ""}
        {allergy.ingredient_code ? "" : " · not coded, cannot be auto-checked"}
      </Typography>
    </Box>
  );
}

export interface PatientSummarySidebarProps {
  token: QueueToken | null;
}

/**
 * The patient record behind a queue token. Patient, history and allergies are
 * three separate reads — a token carries token columns, not clinical facts.
 */
export function PatientSummarySidebar({ token }: PatientSummarySidebarProps) {
  if (!token) {
    return (
      <Box sx={doctorPanelSx}>
        <Typography
          sx={{ color: meridian.textSecondary, fontSize: "0.875rem", textAlign: "center", py: 2 }}
        >
          Select a patient from the queue to see their summary.
        </Typography>
      </Box>
    );
  }

  // Re-mount before rendering a different patient, not in a later effect that
  // can briefly paint the old patient's allergies beneath the new token.
  return <PatientSummary key={token.patient_id} token={token} />;
}

type ReadState<T> = { status: "loading" | "error" } | { status: "ready"; data: T };

function PatientSummary({ token }: { token: QueueToken }) {
  const [patientRead, setPatientRead] = React.useState<ReadState<Patient>>({ status: "loading" });
  const [historyRead, setHistoryRead] = React.useState<ReadState<PatientHistoryEntry[]>>({ status: "loading" });
  const [allergiesRead, setAllergiesRead] = React.useState<ReadState<Allergy[]>>({ status: "loading" });
  const [attempt, setAttempt] = React.useState(0);
  const patientId = token.patient_id;

  React.useEffect(() => {
    let alive = true;
    // Independent outcomes: an allergy failure must not hide successful
    // demographics, or turn unknown clinical history into an empty history.
    void getPatient(patientId).then(
      (data) => { if (alive) setPatientRead(data ? { status: "ready", data } : { status: "error" }); },
      () => { if (alive) setPatientRead({ status: "error" }); },
    );
    void getPatientHistory(patientId).then(
      (data) => { if (alive) setHistoryRead({ status: "ready", data }); },
      () => { if (alive) setHistoryRead({ status: "error" }); },
    );
    void listAllergies(patientId).then(
      (data) => { if (alive) setAllergiesRead({ status: "ready", data }); },
      () => { if (alive) setAllergiesRead({ status: "error" }); },
    );
    return () => { alive = false; };
  }, [patientId, attempt]);

  function retry() {
    setPatientRead({ status: "loading" });
    setHistoryRead({ status: "loading" });
    setAllergiesRead({ status: "loading" });
    setAttempt((previous) => previous + 1);
  }

  const patient = patientRead.status === "ready" ? patientRead.data : null;
  const history = historyRead.status === "ready" ? historyRead.data : [];
  const allergies = allergiesRead.status === "ready" ? allergiesRead.data : [];
  const failed = [patientRead, historyRead, allergiesRead].some((read) => read.status === "error");

  const canConsult = CONSULTABLE.includes(token.status);
  const lastVisit = history[0];

  return (
    <Box sx={{ ...doctorPanelSx, display: "flex", flexDirection: "column", gap: 2 }}>
      <Box>
        <Typography sx={{ fontSize: "1.0625rem", fontWeight: 700 }}>
          {patient?.full_name ?? token.full_name}
        </Typography>
        <Box sx={{ mt: 0.75 }}>
          <StatusChip status={token.status} />
        </Box>
      </Box>

      <Divider />

      <Stack spacing={1.5}>
        {patientRead.status !== "ready" ? (
          <Typography role={patientRead.status === "error" ? "alert" : "status"} sx={{ fontSize: "0.8125rem", color: meridian.textSecondary }}>
            {patientRead.status === "error" ? "Patient details unavailable. Showing queue details only." : "Loading patient details…"}
          </Typography>
        ) : null}
        <Field label="Token" value={token.token_display} />
        {/* A THID-only patient has no UHID yet — name the identifier being shown. */}
        <Field
          label={patient?.uhid ? "UHID" : "THID"}
          value={patient?.uhid ?? patient?.thid ?? token.uhid}
        />
        <Field
          label="Age / Sex"
          value={formatAgeSex(patient?.age_years ?? token.age_years, patient?.sex ?? token.sex)}
        />
        <Field label="Last Visit" value={historyRead.status === "loading" ? "Loading…" : historyRead.status === "error" ? "Unavailable" : lastVisit ? lastVisit.visit_date : "First visit"} />
      </Stack>

      <Divider />

      <Box>
        <Typography sx={{ ...labelSx, mb: 1 }}>Known Allergies</Typography>
        {allergiesRead.status !== "ready" ? (
          <Typography role={allergiesRead.status === "error" ? "alert" : "status"} sx={{ fontSize: "0.8125rem", color: meridian.textSecondary }}>
            {allergiesRead.status === "error" ? "Allergy status unavailable. Retry before relying on this summary." : "Loading allergies…"}
          </Typography>
        ) : allergies.length > 0 ? (
          <Stack spacing={0.75}>
            {allergies.map((a) => (
              <AllergyRow key={a.id} allergy={a} />
            ))}
          </Stack>
        ) : (
          <Typography sx={{ fontSize: "0.8125rem", color: meridian.textSecondary }}>
            None recorded.
          </Typography>
        )}
      </Box>

      <Box>
        <Typography sx={{ ...labelSx, mb: 1 }}>Previous Diagnoses</Typography>
        {historyRead.status !== "ready" ? (
          <Typography role={historyRead.status === "error" ? "alert" : "status"} sx={{ fontSize: "0.8125rem", color: meridian.textSecondary }}>
            {historyRead.status === "error" ? "Clinical history unavailable." : "Loading clinical history…"}
          </Typography>
        ) : history.some((visit) => visit.diagnoses.length > 0) ? (
          <Stack spacing={0.5}>
            {history.flatMap((v) =>
              v.diagnoses.map((d) => (
                <Typography key={`${v.visit_id}-${d}`} sx={{ fontSize: "0.8125rem" }}>
                  • {d}{" "}
                  <Box component="span" sx={{ color: meridian.textSecondary }}>
                    ({v.visit_date})
                  </Box>
                </Typography>
              )),
            )}
          </Stack>
        ) : (
          <Typography sx={{ fontSize: "0.8125rem", color: meridian.textSecondary }}>
            None recorded.
          </Typography>
        )}
      </Box>

      {failed ? (
        <Button onClick={retry} variant="outlined">Retry patient summary</Button>
      ) : null}

      {canConsult ? (
        <>
          <Divider />
          <Button
            component={Link}
            href={`/doctor/consultation?token=${encodeURIComponent(token.id)}`}
            variant="contained"
            fullWidth
            sx={{ textTransform: "none", fontWeight: 600, borderRadius: "10px", py: 1.1 }}
          >
            Start consultation
          </Button>
        </>
      ) : null}
    </Box>
  );
}
