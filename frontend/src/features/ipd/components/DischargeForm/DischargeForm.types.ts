import type { DischargeOutcome } from "@/features/ipd/hooks/useAddDischarge";
import type { AddDischargeSchema } from "./validation";

export type NotificationStatus = "queued" | "sent" | "delivered" | "failed";

export type TargetModule =
  | "pharmacy"
  | "billing"
  | "nursing"
  | "lab"
  | "radiology"
  | "patient";

export interface DischargeNotificationPreview {
  target_module: TargetModule;
  status: NotificationStatus;
}

export interface DischargeFormProps {
  admissionId: string;
  notificationPreview: DischargeNotificationPreview[];

  isSubmitting?: boolean;

  onSubmit: (data: AddDischargeSchema) => Promise<DischargeOutcome>;
}