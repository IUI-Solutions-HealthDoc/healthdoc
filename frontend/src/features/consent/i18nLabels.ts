import type { MessageKey } from "@/lib/i18n";

import type { AccessChannel, ConsentChannel, ConsentStatus } from "./types";

export const CONSENT_STATUSES: ConsentStatus[] = [
  "requested",
  "granted",
  "denied",
  "revoked",
  "expired",
];

export const CONSENT_CHANNELS: ConsentChannel[] = [
  "verbal",
  "written",
  "digital_otp",
  "abdm_consent_manager",
];

export const ACCESS_CHANNELS: AccessChannel[] = ["ui", "api", "abdm_hiu", "export"];

export type TranslateFn = (key: MessageKey, vars?: Record<string, string | number>) => string;

export function consentStatusLabel(t: TranslateFn, status: ConsentStatus): string {
  return t(`consent.status.${status}`);
}

export function consentChannelLabel(t: TranslateFn, channel: ConsentChannel | string): string {
  const key = `consent.channel.${channel}` as MessageKey;
  const translated = t(key);
  return translated === key ? String(channel) : translated;
}

/** Grant-form channel options (written / verbal use dedicated copy keys). */
export function consentChannelFormLabel(t: TranslateFn, channel: ConsentChannel): string {
  if (channel === "written") return t("consent.channel.writtenForm");
  if (channel === "verbal") return t("consent.channel.verbalConsent");
  return consentChannelLabel(t, channel);
}

export function consentPurposeLabel(
  t: TranslateFn,
  purposeCode: string | null | undefined,
  purposeLabel?: string | null,
): string {
  if (purposeCode) {
    const key = `consent.purpose.${purposeCode}` as MessageKey;
    const translated = t(key);
    if (translated !== key) return translated;
  }
  if (purposeLabel) return purposeLabel;
  if (!purposeCode) return t("consent.unknownUnavailable");
  return purposeCode.replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

export function accessChannelLabel(t: TranslateFn, channel: AccessChannel): string {
  return t(`consent.access.${channel}`);
}

export function accessChannelLabels(t: TranslateFn): Record<AccessChannel, string> {
  return Object.fromEntries(
    ACCESS_CHANNELS.map((channel) => [channel, accessChannelLabel(t, channel)]),
  ) as Record<AccessChannel, string>;
}
