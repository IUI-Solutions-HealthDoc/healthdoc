"use client";

import { useState } from "react";

import { ModuleCapabilityGate } from "@/components/common/ModuleCapabilityGate";
import { PageHeading } from "@/components/common/PageHeading";
import { LabMisPanel } from "@/features/lab/components/LabMisPanel";
import { LabWorklistPanel } from "@/features/lab/components/LabWorklistPanel";
import { useLocale, type MessageKey } from "@/lib/i18n";

type LabTab = "worklist" | "mis";

const LAB_TABS: { id: LabTab; labelKey: MessageKey }[] = [
  { id: "worklist", labelKey: "lab.tab.worklist" },
  { id: "mis", labelKey: "lab.tab.mis" },
];

function LabPageContent() {
  const { t } = useLocale();
  const [tab, setTab] = useState<LabTab>("worklist");

  return (
    <div className="space-y-6 p-6">
      <PageHeading titleKey="lab.title" subtitleKey="lab.subtitle" />

      <div className="flex gap-1 border-b border-border">
        {LAB_TABS.map((entry) => (
          <button
            key={entry.id}
            type="button"
            onClick={() => setTab(entry.id)}
            className={`px-4 py-2 text-sm ${
              tab === entry.id
                ? "border-b-2 border-primary font-medium text-primary"
                : "text-muted-foreground"
            }`}
          >
            {t(entry.labelKey)}
          </button>
        ))}
      </div>

      {tab === "worklist" ? <LabWorklistPanel /> : null}
      {tab === "mis" ? <LabMisPanel /> : null}
    </div>
  );
}

export default function LabPage() {
  return (
    <ModuleCapabilityGate module="lab">
      <LabPageContent />
    </ModuleCapabilityGate>
  );
}
