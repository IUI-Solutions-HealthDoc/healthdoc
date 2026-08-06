/**
 * Meridian design tokens — navy / light HMIS theme (single source of truth).
 */
export const meridian = {
  brandPrimary: "#001f54",
  brandDeep: "#001536",
  canvas: "#ffffff",
  surface: "#ffffff",
  muted: "#f4f6f9",
  textPrimary: "#001f54",
  textSecondary: "#4a6282",
  textMuted: "#4a6282",
  border: "#d6dee8",
  success: "#166534",
  warning: "#b45309",
  danger: "#b91c1c",
  info: "#001f54",
} as const;

export type MeridianColor = keyof typeof meridian;
