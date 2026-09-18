/**
 * Shared UI primitives — import from `@/components/ui`.
 * Meridian-themed building blocks for every F* module.
 */

export { Button } from "./Button";
export type { ButtonProps } from "./Button";

export { Badge } from "./Badge";
export type { BadgeProps, BadgeVariant } from "./Badge";

export { MetricCard } from "./MetricCard";
export type {
  MetricCardProps,
  MetricCardSize,
  MetricDelta,
  MetricDeltaDirection,
} from "./MetricCard";

export { ChartWrapper } from "./ChartWrapper";
export type { ChartWrapperProps, ChartEmptyState } from "./ChartWrapper";

export { ExportButton } from "./ExportButton";
export type { ExportButtonProps, ExportFormat } from "./ExportButton";

export { Modal } from "./Modal";
export type { ModalProps } from "./Modal";

export { StatusChip } from "./StatusChip";
export type { StatusChipProps } from "./StatusChip";

export { SearchAutocomplete } from "./SearchAutocomplete";
export type { SearchAutocompleteProps } from "./SearchAutocomplete";

export { toast } from "./toast";
export { Toaster } from "./Toaster";
export { EmptyState, ErrorState, LoadingState } from "./AsyncState";

export { PatientAvatar } from "./PatientAvatar";
export type { PatientAvatarProps } from "./PatientAvatar";

/** Inventory chips (Vanshika) — FEFO / expiry / stock */
export { default as ExpiryChip } from "./ExpiryChip";
export type { ExpiryChipProps } from "./ExpiryChip";
export { default as FEFOIndicator } from "./FEFOindicator";
export type { FEFOIndicatorProps } from "./FEFOindicator";
export { default as StockLevelBadge } from "./StockLevelBadge";
export type { StockLevelBadgeProps } from "./StockLevelBadge";

