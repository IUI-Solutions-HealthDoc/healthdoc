import type { MessageKey } from "@/lib/i18n";

export interface QuickAction {
  id: string;
  labelKey: MessageKey;
  icon: string;
  color: string;
}

export interface QuickActionsProps {
  onAction?: (actionId: string) => void;
}
