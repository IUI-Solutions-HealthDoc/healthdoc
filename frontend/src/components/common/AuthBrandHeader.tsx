"use client";

import { HealthDocBrand } from "@/components/common/HealthDocBrand";
import { useLocale } from "@/lib/i18n";

type Props = {
  size?: number;
  preload?: boolean;
  nameClassName?: string;
  className?: string;
};

export function AuthBrandHeader({ size = 52, preload, nameClassName, className }: Props) {
  const { t } = useLocale();
  return (
    <HealthDocBrand
      size={size}
      preload={preload}
      subtitle={t("auth.brandSubtitle")}
      nameClassName={nameClassName}
      className={className}
    />
  );
}
