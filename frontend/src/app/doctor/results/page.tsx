"use client";

import Box from "@mui/material/Box";

import { PageHeading } from "@/components/common/PageHeading";
import { ResultsWorkspace } from "@/features/doctor";
import { doctorPageSx } from "@/features/doctor/panelSx";

export default function Page() {
  return (
    <Box sx={doctorPageSx}>
      <PageHeading titleKey="doctor.resultsTitle" className="mb-4 space-y-1" />
      <ResultsWorkspace />
    </Box>
  );
}
