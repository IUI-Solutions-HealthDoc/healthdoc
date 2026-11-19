import Image from "next/image";
import { useLocale } from "@/lib/i18n";

interface HealthDocBrandProps {
  className?: string;
  imageClassName?: string;
  nameClassName?: string;
  preload?: boolean;
  showName?: boolean;
  size?: number;
  subtitle?: string;
}

/** The single in-app rendering of the HealthDoc product mark. */
export function HealthDocBrand({
  className = "",
  imageClassName = "",
  nameClassName = "",
  preload = false,
  showName = true,
  size = 44,
  subtitle,
}: HealthDocBrandProps) {
  const { t } = useLocale();
  return (
    <span className={`inline-flex min-w-0 items-center gap-3 ${className}`}>
      <Image
        src="/healthdoc-logo.png"
        alt={showName ? "" : "HealthDoc"}
        aria-hidden={showName || undefined}
        width={size}
        height={size}
        preload={preload}
        className={`shrink-0 rounded-[22%] object-contain ${imageClassName}`}
      />
      {showName ? (
        <span className="min-w-0 leading-tight">
          <span className={`block font-semibold tracking-tight ${nameClassName}`}>{t("common.ui.healthdoc")}</span>
          {subtitle ? (
            <span className="block text-[0.65em] font-medium uppercase tracking-[0.18em] opacity-65">
              {subtitle}
            </span>
          ) : null}
        </span>
      ) : null}
    </span>
  );
}
