"use client";

import { useLocale, type MessageKey } from "@/lib/i18n";

type Props = {
  titleKey: MessageKey;
  subtitleKey?: MessageKey;
  className?: string;
  titleClassName?: string;
};

/** Localized page title/subtitle for role dashboards. */
export function PageHeading({
  titleKey,
  subtitleKey,
  className = "space-y-1",
  titleClassName = "text-2xl font-semibold",
}: Props) {
  const { t } = useLocale();
  return (
    <div className={className}>
      <h1 className={titleClassName}>{t(titleKey)}</h1>
      {subtitleKey ? (
        <p className="text-sm text-muted-foreground">{t(subtitleKey)}</p>
      ) : null}
    </div>
  );
}
