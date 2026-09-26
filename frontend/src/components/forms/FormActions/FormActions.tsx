"use client";

import { useLocale } from "@/lib/i18n";
import { FormActionsProps } from "./FormActions.types";

export default function FormActions({
  isSubmitting = false,
  submitLabel,
  resetLabel,
  onReset,
}: FormActionsProps) {
  const { t } = useLocale();
  const submit = submitLabel ?? t("common.save");
  const reset = resetLabel ?? t("common.reset");

  return (
    <div className="flex justify-end gap-3">
      <button
        type="button"
        onClick={onReset}
        disabled={isSubmitting}
        className="btn btn-outline"
      >
        {reset}
      </button>

      <button
        type="submit"
        disabled={isSubmitting}
        aria-busy={isSubmitting}
        className="btn btn-primary"
      >
        {isSubmitting ? t("forms.saving") : submit}
      </button>
    </div>
  );
}
