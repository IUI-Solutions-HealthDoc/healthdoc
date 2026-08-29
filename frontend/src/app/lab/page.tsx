"use client";

import { useState } from "react";

import { ModuleCapabilityGate } from "@/components/common/ModuleCapabilityGate";
import { LabMisPanel } from "@/features/lab/components/LabMisPanel";
import { LabWorklistPanel } from "@/features/lab/components/LabWorklistPanel";

type LabTab = "worklist" | "mis";

function LabPageContent() {
  const [tab, setTab] = useState<LabTab>("worklist");

  return (
    <div className="space-y-6 p-6">
      <div>
        <h1 className="text-2xl font-semibold">Laboratory</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Sample collection, result entry, verification, amendments, and MIS.
        </p>
      </div>

      <div className="flex gap-1 border-b border-border">
        {(
          [
            { id: "worklist" as const, label: "Worklist" },
            { id: "mis" as const, label: "MIS summary" },
          ] as const
        ).map((entry) => (
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
            {entry.label}
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
