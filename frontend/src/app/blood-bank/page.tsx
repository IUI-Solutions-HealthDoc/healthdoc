"use client";

import { ModuleCapabilityGate } from "@/components/common/ModuleCapabilityGate";
import { BloodBankPage } from "@/features/blood-bank/BloodBankPage";

export default function Page() {
  return (
    <ModuleCapabilityGate module="blood_bank">
      <div className="p-6">
        <BloodBankPage />
      </div>
    </ModuleCapabilityGate>
  );
}
