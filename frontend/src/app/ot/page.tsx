"use client";

import { ModuleCapabilityGate } from "@/components/common/ModuleCapabilityGate";
import { OtDashboard } from "@/features/ot";

// OT is an optional module; a facility without it gets "not offered here",
// not a page whose every call answers 409 module_disabled.
export default function OtPage() {
  return (
    <ModuleCapabilityGate module="ot">
      <OtDashboard />
    </ModuleCapabilityGate>
  );
}
