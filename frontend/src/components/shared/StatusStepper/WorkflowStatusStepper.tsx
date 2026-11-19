"use client";

import Button from "@mui/material/Button";
import Stack from "@mui/material/Stack";

import StatusChip from "./StatusChip";
import { workflowActionButtonSx } from "./StatusActionMenu";
import type { WorkflowStatusStepperProps } from "./types";
import { meridian } from "@/styles/theme";
import { translate } from "@/lib/i18n";

export default function WorkflowStatusStepper({
  currentStatus,
  workflow,
  onStatusChange,
  disabled = false,
  showButton = true,
  buttonText,
  actions,
}: WorkflowStatusStepperProps) {
  const currentStep = workflow.find((step) => step.value === currentStatus);

  const nextStep = currentStep?.next
    ? workflow.find((step) => step.value === currentStep.next)
    : undefined;

  const showNextButton =
    showButton && !disabled && !currentStep?.terminal && !!nextStep;

  return (
    <Stack
      spacing={1.25}
      sx={{
        alignItems: "center",
      }}
    >
      <StatusChip status={currentStatus} workflow={workflow} />

      {showNextButton && (
        <Button
          variant="outlined"
          size="small"
          color="primary"
          onClick={() =>
            onStatusChange({
              from: currentStatus,
              to: nextStep.value,
            })
          }
          sx={{
            ...workflowActionButtonSx,
            color: meridian.brandPrimary,
            "&:hover": {
              borderColor: meridian.brandPrimary,
              backgroundColor: meridian.muted,
              boxShadow: "0 4px 12px rgb(0 31 84 / 0.08)",
            },
          }}
        >
          {buttonText ?? translate("common.msg.markLabel", undefined, { label: nextStep.label })}
        </Button>
      )}

      {actions}
    </Stack>
  );
}
