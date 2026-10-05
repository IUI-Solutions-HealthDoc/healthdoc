"use client";

import { useState } from "react";

import { HfrFacilityRegistry } from "@/features/admin/HfrFacilityRegistry";
import { HfrRegistration } from "@/features/admin/HfrRegistration";
import { HpidCreation } from "@/features/admin/HpidCreation";
import { HprProfessionalRegistration } from "@/features/admin/HprProfessionalRegistration";
import { HprLoginPanel } from "@/features/admin/HprLoginPanel";
import { useLocale } from "@/lib/i18n";

export default function Page() {
  const { t } = useLocale();
  const [signedIn, setSignedIn] = useState(false);
  // A new HPID signs its professional in; the login panel reloads to show it.
  const [hprReload, setHprReload] = useState(0);
  return (
    <div className="space-y-6 p-6">
      <h1 className="text-3xl font-semibold">{t("admin.hfr.title")}</h1>
      <HfrFacilityRegistry />
      <HprLoginPanel reloadKey={hprReload} onChange={(session) => setSignedIn(session.logged_in)} />
      <HpidCreation onSignedIn={() => setHprReload((n) => n + 1)} />
      <HprProfessionalRegistration signedIn={signedIn} />
      <HfrRegistration signedIn={signedIn} />
    </div>
  );
}
