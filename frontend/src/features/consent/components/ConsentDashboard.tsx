"use client";

import { useCallback, useState } from "react";
import Box from "@mui/material/Box";
import Typography from "@mui/material/Typography";

import { PatientSearch } from "@/features/receptionist/PatientSearch";
import { meridian } from "@/styles/theme";
import { useConsentDetail } from "../hooks/useConsentDetail";
import { useConsentRecords } from "../hooks/useConsentRecords";
import { useDataAccessLogs } from "../hooks/useDataAccessLogs";
import { ConsentListPanel } from "./ConsentListPanel";
import { ConsentRecordDetail } from "./ConsentRecordDetail";
import { ConsentGrantForm } from "./ConsentGrantForm";

export function ConsentDashboard() {
  /**
   * Consent is read per patient, not per facility.
   *
   * The fixture listed every consent in the facility. No endpoint does that —
   * consent_records has no facility_id and would need a deliberate join through
   * patients — and whether a DPO console should exist is a product decision
   * that was deferred. So the screen asks who first, reusing the receptionist's
   * PatientSearch rather than growing a second patient picker.
   */
  const [patient, setPatient] = useState<{ id: string; full_name: string } | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const list = useConsentRecords({ status: "all", patient_id: patient?.id });
  const detail = useConsentDetail(patient?.id ?? null, selectedId);
  const access = useDataAccessLogs(selectedId);

  const handleRecordUpdated = useCallback(() => {
    void list.refresh();
    if (selectedId) void detail.refresh?.();
  }, [list, detail, selectedId]);

  return (
    <Box sx={{ display: "flex", flexDirection: "column", gap: 2.5 }}>
      <Box>
        <Typography
          component="h1"
          sx={{
            m: 0,
            fontSize: "1.5rem",
            fontWeight: 700,
            letterSpacing: "-0.03em",
            color: meridian.textPrimary,
          }}
        >
          Consent records
        </Typography>
        <Typography sx={{ m: 0, mt: 0.5, fontSize: "0.875rem", color: meridian.textSecondary }}>
          Record consent decisions and review the patient&apos;s consent history.
        </Typography>
      </Box>

      <Box
        sx={{
          px: 2,
          py: 1.25,
          borderRadius: "12px",
          backgroundColor: "#e8eef5",
          color: meridian.brandPrimary,
          fontSize: "0.875rem",
          fontWeight: 600,
        }}
      >
        Consent decisions remain in the audit history. Revoked consent is recorded, not erased.
      </Box>

      {!patient ? (
        <Box sx={{ mt: 2 }}>
          <Typography sx={{ mb: 1.5, fontSize: "0.875rem", color: meridian.textSecondary }}>
            Find the patient whose consents you need. Records are read per
            patient — there is no facility-wide consent list.
          </Typography>
          <PatientSearch
            selectLabel="View consents"
            onSelect={(found) => {
              setPatient({ id: found.id, full_name: found.full_name });
              setSelectedId(null);
            }}
          />
        </Box>
      ) : (
        <>
          <Box sx={{ mt: 1, mb: 1 }}>
            <Typography sx={{ fontSize: "0.875rem" }}>
              {patient.full_name}
              {" · "}
              <button
                type="button"
                onClick={() => {
                  setPatient(null);
                  setSelectedId(null);
                }}
                style={{ textDecoration: "underline", background: "none", border: 0, cursor: "pointer" }}
              >
                change patient
              </button>
            </Typography>
          </Box>
          <ConsentGrantForm
            key={patient.id}
            patientId={patient.id}
            onCreated={(record) => {
              setSelectedId(record.id);
              void list.refresh();
            }}
          />
          {list.error ? (
            <Typography role="alert" sx={{ color: meridian.danger, fontSize: "0.875rem" }}>
              {list.error}
            </Typography>
          ) : null}
          {detail.error || access.error ? (
            <Typography role="alert" sx={{ color: meridian.danger, fontSize: "0.875rem" }}>
              {detail.error ?? access.error}
            </Typography>
          ) : null}
          <Box
            sx={{
              display: "grid",
              gridTemplateColumns: { xs: "1fr", lg: "320px 1fr" },
              gap: 2.5,
              alignItems: "start",
            }}
          >
            <ConsentListPanel
          rows={list.rows}
          loading={list.loading}
          query={list.filters.query ?? ""}
          status={list.filters.status ?? "all"}
          selectedId={selectedId}
          onQueryChange={list.setQuery}
          onStatusChange={list.setStatus}
          onSelect={setSelectedId}
        />
        <ConsentRecordDetail
          record={detail.record}
          loading={detail.loading}
          accessRows={access.rows}
          accessLoading={access.loading}
          onRecordUpdated={handleRecordUpdated}
            />
          </Box>
        </>
      )}
    </Box>
  );
}
