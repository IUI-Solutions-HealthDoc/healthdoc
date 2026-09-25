"use client";

import { PageHeading } from "@/components/common/PageHeading";
import { MaintenanceLogPanel } from "@/features/maintenance/MaintenanceLogPanel";

export default function Page() {
  return (
    <div className="space-y-6 p-6">
      <PageHeading titleKey="maintenance.title" titleClassName="text-3xl font-semibold" />
      <MaintenanceLogPanel />
    </div>
  );
}
