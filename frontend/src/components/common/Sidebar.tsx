"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  BarChart3,
  Bed,
  Building2,
  ChevronRight,
  ClipboardList,
  FileText,
  FlaskConical,
  LayoutDashboard,
  Package,
  Pill,
  Radio,
  Receipt,
  Search,
  Shield,
  Stethoscope,
  UserRound,
  Users,
  X,
  type LucideIcon,
} from "lucide-react";

import { REALM_ROLE_LABELS } from "@/features/admin/constants";
import { ROLES, type Role } from "@/config/roles";
import { canRoleAccessPath } from "@/lib/auth/routes";
import { useAuth } from "@/providers/auth-provider";

type NavItem = {
  href: string;
  label: string;
  icon: LucideIcon;
  area: "front_desk" | "clinical" | "diagnostics" | "finance" | "audit" | "admin" | "platform" | "patient";
  roles: readonly Role[];
};

const NAV_ITEMS: readonly NavItem[] = [
  { href: "/superadmin", label: "Facilities", icon: Building2, area: "platform", roles: [ROLES.SUPERADMIN] },
  // Head of department. Eight endpoints existed for this role with no route and
  // no nav entry, so an HOD logged in and had nowhere to go.
  { href: "/hod", label: "Department dashboard", icon: LayoutDashboard, area: "clinical", roles: [ROLES.HOD] },
  { href: "/receptionist/registration", label: "Registration", icon: UserRound, area: "front_desk", roles: [ROLES.RECEPTIONIST] },
  { href: "/receptionist/patient-search", label: "Patient search", icon: Search, area: "front_desk", roles: [ROLES.RECEPTIONIST] },
  { href: "/receptionist/queue", label: "Queue", icon: Users, area: "front_desk", roles: [ROLES.RECEPTIONIST] },
  { href: "/doctor/dashboard", label: "Doctor queue", icon: Stethoscope, area: "clinical", roles: [ROLES.DOCTOR] },
  { href: "/doctor/consultation", label: "Consultation", icon: ClipboardList, area: "clinical", roles: [ROLES.DOCTOR] },
  { href: "/doctor/orders", label: "Orders", icon: FlaskConical, area: "clinical", roles: [ROLES.DOCTOR] },
  { href: "/doctor/prescriptions", label: "Prescriptions", icon: Pill, area: "clinical", roles: [ROLES.DOCTOR] },
  { href: "/doctor/results", label: "Results", icon: FileText, area: "clinical", roles: [ROLES.DOCTOR] },
  { href: "/doctor/pharmacy-approvals", label: "Pharmacy approvals", icon: Pill, area: "clinical", roles: [ROLES.DOCTOR] },
  { href: "/nurse/ward-dashboard", label: "Ward dashboard", icon: Bed, area: "clinical", roles: [ROLES.NURSE] },
  { href: "/nurse/emar", label: "eMAR", icon: ClipboardList, area: "clinical", roles: [ROLES.NURSE] },
  { href: "/ipd", label: "IPD", icon: Building2, area: "clinical", roles: [ROLES.DOCTOR, ROLES.NURSE] },
  { href: "/emergency", label: "Emergency", icon: Stethoscope, area: "clinical", roles: [ROLES.EMERGENCY] },
  { href: "/supervisor/merges", label: "Identity merges", icon: Shield, area: "audit", roles: [ROLES.SUPERVISOR] },
  { href: "/consent", label: "Consent", icon: FileText, area: "clinical", roles: [ROLES.RECEPTIONIST, ROLES.DOCTOR, ROLES.NURSE] },
  { href: "/lab", label: "Laboratory", icon: FlaskConical, area: "diagnostics", roles: [ROLES.LAB_TECH, ROLES.DOCTOR] },
  { href: "/radiology", label: "Radiology", icon: Radio, area: "diagnostics", roles: [ROLES.RADIOLOGY_TECH, ROLES.DOCTOR] },
  { href: "/pharmacy/prescription-queue", label: "Pharmacy queue", icon: Pill, area: "clinical", roles: [ROLES.PHARMACIST] },
  { href: "/pharmacy/dispense", label: "Dispense", icon: Package, area: "clinical", roles: [ROLES.PHARMACIST] },
  { href: "/inventory", label: "Inventory", icon: Package, area: "clinical", roles: [ROLES.PHARMACIST, ROLES.HOD] },
  { href: "/billing", label: "Billing", icon: Receipt, area: "finance", roles: [ROLES.RECEPTIONIST, ROLES.ADMIN] },
  { href: "/reports", label: "Reports", icon: BarChart3, area: "finance", roles: [ROLES.SUPERVISOR, ROLES.ADMIN, ROLES.AUDITOR] },
  { href: "/audit-viewer", label: "Audit trail", icon: Shield, area: "audit", roles: [ROLES.ADMIN, ROLES.AUDITOR] },
  { href: "/patient-portal", label: "My health record", icon: UserRound, area: "patient", roles: [ROLES.PATIENT] },
  { href: "/admin", label: "Admin overview", icon: LayoutDashboard, area: "admin", roles: [ROLES.ADMIN] },
  { href: "/admin/users", label: "Users", icon: Users, area: "admin", roles: [ROLES.ADMIN] },
  { href: "/admin/account-requests", label: "Account requests", icon: UserRound, area: "admin", roles: [ROLES.ADMIN] },
  { href: "/admin/permissions", label: "Permissions", icon: Shield, area: "admin", roles: [ROLES.ADMIN] },
  { href: "/admin/departments", label: "Departments & rooms", icon: Building2, area: "admin", roles: [ROLES.ADMIN] },
  { href: "/admin/abdm-sync", label: "ABDM identity links", icon: Shield, area: "admin", roles: [ROLES.ADMIN] },
  // DPDP obligations: the named DPO, the grievance register, consent managers.
  // All three tables shipped in 0022a with nothing able to read or write them.
  { href: "/admin/data-protection", label: "Data protection", icon: Shield, area: "admin", roles: [ROLES.ADMIN, ROLES.AUDITOR] },
  { href: "/admin/maintenance", label: "Equipment maintenance", icon: Building2, area: "admin", roles: [ROLES.ADMIN, ROLES.LAB_TECH, ROLES.RADIOLOGY_TECH] },
];

const AREA_LABELS: Record<NavItem["area"], string> = {
  front_desk: "Front desk",
  clinical: "Clinical",
  diagnostics: "Diagnostics",
  finance: "Finance / MIS",
  audit: "Audit",
  admin: "Facility admin",
  platform: "Platform admin",
  patient: "Patient portal",
};

interface SidebarProps {
  open: boolean;
  setOpen: (value: boolean) => void;
}

export default function Sidebar({ open, setOpen }: SidebarProps) {
  const [query, setQuery] = useState("");
  const pathname = usePathname();
  const { user } = useAuth();
  const role = user?.role ?? null;
  const roleLabel = role
    ? (REALM_ROLE_LABELS[role] ?? role)
    : "Unassigned";

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [setOpen]);

  const closeOnMobile = () => {
    if (!window.matchMedia("(min-width: 768px)").matches) setOpen(false);
  };

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return NAV_ITEMS.filter(
      (item) =>
        Boolean(role && item.roles.includes(role)) &&
        canRoleAccessPath(role, item.href) &&
        item.label.toLowerCase().includes(q),
    );
  }, [query, role]);

  const groups = useMemo(() => {
    const map = new Map<string, typeof filtered>();
    for (const item of filtered) {
      const key = AREA_LABELS[item.area];
      const list = map.get(key) ?? [];
      list.push(item);
      map.set(key, list);
    }
    return [...map.entries()];
  }, [filtered]);

  return (
    <>
      {open && (
        <button
          type="button"
          aria-label="Close navigation menu"
          onClick={() => setOpen(false)}
          className="fixed inset-x-0 bottom-0 top-16 z-30 bg-black/40 md:hidden"
        />
      )}

      <aside
        id="workspace-sidebar"
        aria-label="Workspace navigation"
        aria-hidden={!open}
        inert={!open}
        className={`
    fixed
    top-16
    left-0
    z-40
    h-[calc(100vh-64px)]
    w-[260px]
    bg-white
    border-r
    border-border
    shadow-lg
    overflow-y-auto
    transition-transform
    duration-300
    ease-in-out
    p-4

    ${open ? "translate-x-0" : "-translate-x-full"}
  `}
      >
        <div className="flex items-center justify-between border-b border-gray-200 pb-4">
          <div>
            <h2 className="text-xl font-bold text-[#001F54] tracking-wide">
              HMIS
            </h2>
            <p className="text-xs text-gray-500 mt-1">
              Signed in as {roleLabel}
            </p>
          </div>

          <button
            onClick={() => setOpen(false)}
            className="flex h-9 w-9 items-center justify-center rounded-lg hover:bg-gray-100 transition"
            type="button"
            aria-label="Close sidebar"
          >
            <X size={20} />
          </button>
        </div>

        <div className="relative mt-5 mb-6">
          <Search
            size={18}
            className="absolute left-4 top-1/2 -translate-y-1/2 text-gray-400"
          />
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search menu..."
            className="w-full h-11 rounded-xl border border-gray-200 bg-gray-50 pl-11 pr-4 text-sm outline-none focus:border-[#001F54] focus:bg-white transition"
          />
        </div>

        <nav aria-label="HealthDoc modules" className="space-y-4">
          {groups.length === 0 ? (
            <p className="px-2 text-sm text-gray-500">No screens for this role.</p>
          ) : (
            groups.map(([group, items]) => (
              <div key={group}>
                <p className="mb-2 text-[11px] uppercase tracking-[2px] text-gray-400 font-semibold">
                  {group}
                </p>
                <div className="space-y-1">
                  {items.map((item) => {
                    const Icon = item.icon;
                    const active =
                      pathname === item.href ||
                      (item.href !== "/" && pathname.startsWith(`${item.href}/`));
                    return (
                      <Link
                        key={item.href}
                        href={item.href}
                        onClick={closeOnMobile}
                        aria-current={active ? "page" : undefined}
                        className={`group flex items-center justify-between rounded-xl px-4 py-3 transition ${
                          active ? "bg-[#EEF4FF]" : "hover:bg-[#EEF4FF]"
                        }`}
                      >
                        <div className="flex items-center gap-3">
                          <div className="w-6 flex justify-center">
                            <Icon
                              size={20}
                              className={
                                active
                                  ? "text-[#001F54]"
                                  : "text-gray-500 group-hover:text-[#001F54]"
                              }
                            />
                          </div>
                          <span
                            className={`font-medium ${
                              active
                                ? "text-[#001F54]"
                                : "text-gray-700 group-hover:text-[#001F54]"
                            }`}
                          >
                            {item.label}
                          </span>
                        </div>
                        <ChevronRight
                          size={16}
                          className="text-gray-300 group-hover:text-[#001F54]"
                        />
                      </Link>
                    );
                  })}
                </div>
              </div>
            ))
          )}
        </nav>
      </aside>
    </>
  );
}
