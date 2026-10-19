"use client";

import { Badge } from "@/components/ui/Badge";
import { translate } from "@/lib/i18n";

/**
 * Critical-value marker. The severity always comes from the lab's own `flag` on
 * the analyte — reference ranges vary by test, method, age and sex, so the
 * browser must never decide what is critical.
 */
export function CriticalBadge({ label = translate("equipment.critical") }: { label?: string }) {
  return <Badge variant="destructive">{label}</Badge>;
}
