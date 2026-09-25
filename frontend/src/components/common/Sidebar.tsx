"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  BarChart3,
  Bed,
  Building2,
  Calendar,
  ChevronRight,
  ClipboardList,
  Droplets,
  FileText,
  FlaskConical,
  LayoutDashboard,
  Package,
  Pill,
  Radio,
  Receipt,
  RotateCcw,
  Search,
  Shield,
  Stethoscope,
  Syringe,
  UserRound,
  Users,
  X,
  type LucideIcon,
} from "lucide-react";

import { ROLES, type Role } from "@/config/roles";
import { canRoleAccessPath } from "@/lib/auth/routes";
import { useLocale, type MessageKey } from "@/lib/i18n";
import { useAuth } from "@/providers/auth-provider";
import { HealthDocBrand } from "./HealthDocBrand";

type NavArea = "front_desk" | "clinical" | "diagnostics" | "finance" | "audit" | "admin" | "platform" | "patient";

type NavItem = {
  href: string;
  labelKey: MessageKey;
  icon: LucideIcon;
  area: NavArea;
  roles: readonly Role[];
};

const AREA_KEYS: Record<NavArea, MessageKey> = {
  front_desk: "area.front_desk",
  clinical: "area.clinical",
  diagnostics: "area.diagnostics",
  finance: "area.finance",
  audit: "area.audit",
  admin: "area.admin",
  platform: "area.platform",
  patient: "area.patient",
};

const ROLE_KEYS: Partial<Record<Role, MessageKey>> = {
  [ROLES.RECEPTIONIST]: "role.receptionist",
  [ROLES.DOCTOR]: "role.doctor",
  [ROLES.NURSE]: "role.nurse",
  [ROLES.LAB_TECH]: "role.lab_tech",
  [ROLES.RADIOLOGY_TECH]: "role.radiology_tech",
  [ROLES.PHARMACIST]: "role.pharmacist",
  [ROLES.EMERGENCY]: "role.emergency",
  [ROLES.SUPERVISOR]: "role.supervisor",
  [ROLES.BILLING]: "role.billing",
  [ROLES.ADMIN]: "role.admin",
  [ROLES.HOD]: "role.hod",
  [ROLES.AUDITOR]: "role.auditor",
  [ROLES.PATIENT]: "role.patient",
  [ROLES.SUPERADMIN]: "role.superadmin",
};

const NAV_ITEMS: readonly NavItem[] = [
  { href: "/superadmin", labelKey: "sidebar.facilities", icon: Building2, area: "platform", roles: [ROLES.SUPERADMIN] },
  { href: "/hod", labelKey: "sidebar.hodDashboard", icon: LayoutDashboard, area: "clinical", roles: [ROLES.HOD] },
  { href: "/receptionist/registration", labelKey: "sidebar.registration", icon: UserRound, area: "front_desk", roles: [ROLES.RECEPTIONIST] },
  { href: "/receptionist/appointments", labelKey: "sidebar.appointments", icon: Calendar, area: "front_desk", roles: [ROLES.RECEPTIONIST] },
  { href: "/receptionist/patient-search", labelKey: "sidebar.patientSearch", icon: Search, area: "front_desk", roles: [ROLES.RECEPTIONIST] },
  { href: "/receptionist/queue", labelKey: "sidebar.queue", icon: Users, area: "front_desk", roles: [ROLES.RECEPTIONIST] },
  { href: "/doctor/dashboard", labelKey: "sidebar.doctorQueue", icon: Stethoscope, area: "clinical", roles: [ROLES.DOCTOR] },
  { href: "/doctor/consultation", labelKey: "sidebar.consultation", icon: ClipboardList, area: "clinical", roles: [ROLES.DOCTOR] },
  { href: "/doctor/orders", labelKey: "sidebar.orders", icon: FlaskConical, area: "clinical", roles: [ROLES.DOCTOR] },
  { href: "/doctor/prescriptions", labelKey: "sidebar.prescriptions", icon: Pill, area: "clinical", roles: [ROLES.DOCTOR] },
  { href: "/doctor/results", labelKey: "sidebar.results", icon: FileText, area: "clinical", roles: [ROLES.DOCTOR] },
  { href: "/doctor/abdm", labelKey: "sidebar.abdmRecords", icon: FileText, area: "clinical", roles: [ROLES.DOCTOR] },
  { href: "/doctor/pharmacy-approvals", labelKey: "sidebar.pharmacyApprovals", icon: Pill, area: "clinical", roles: [ROLES.DOCTOR] },
  { href: "/nurse/ward-dashboard", labelKey: "sidebar.wardDashboard", icon: Bed, area: "clinical", roles: [ROLES.NURSE] },
  { href: "/nurse/emar", labelKey: "sidebar.emar", icon: ClipboardList, area: "clinical", roles: [ROLES.NURSE] },
  { href: "/ipd", labelKey: "sidebar.ipd", icon: Building2, area: "clinical", roles: [ROLES.DOCTOR, ROLES.NURSE] },
  { href: "/emergency", labelKey: "sidebar.emergency", icon: Stethoscope, area: "clinical", roles: [ROLES.EMERGENCY] },
  { href: "/supervisor/merges", labelKey: "sidebar.identityMerges", icon: Shield, area: "audit", roles: [ROLES.SUPERVISOR] },
  { href: "/consent", labelKey: "sidebar.consent", icon: FileText, area: "clinical", roles: [ROLES.RECEPTIONIST, ROLES.DOCTOR, ROLES.NURSE] },
  { href: "/immunization", labelKey: "sidebar.immunization", icon: Syringe, area: "clinical", roles: [ROLES.DOCTOR, ROLES.NURSE, ROLES.ADMIN] },
  { href: "/forms", labelKey: "sidebar.clinicalForms", icon: FileText, area: "clinical", roles: [ROLES.DOCTOR, ROLES.NURSE, ROLES.ADMIN] },
  { href: "/lab", labelKey: "sidebar.laboratory", icon: FlaskConical, area: "diagnostics", roles: [ROLES.LAB_TECH, ROLES.DOCTOR] },
  { href: "/blood-bank", labelKey: "sidebar.bloodBank", icon: Droplets, area: "diagnostics", roles: [ROLES.LAB_TECH, ROLES.DOCTOR, ROLES.ADMIN] },
  { href: "/radiology", labelKey: "sidebar.radiology", icon: Radio, area: "diagnostics", roles: [ROLES.RADIOLOGY_TECH, ROLES.DOCTOR] },
  { href: "/pharmacy/prescription-queue", labelKey: "sidebar.pharmacyQueue", icon: Pill, area: "clinical", roles: [ROLES.PHARMACIST] },
  { href: "/pharmacy/dispense", labelKey: "sidebar.dispense", icon: Package, area: "clinical", roles: [ROLES.PHARMACIST] },
  { href: "/pharmacy/returns", labelKey: "sidebar.medicineReturns", icon: RotateCcw, area: "clinical", roles: [ROLES.PHARMACIST] },
  { href: "/inventory", labelKey: "sidebar.inventory", icon: Package, area: "clinical", roles: [ROLES.PHARMACIST, ROLES.HOD] },
  { href: "/billing", labelKey: "sidebar.billing", icon: Receipt, area: "finance", roles: [ROLES.BILLING, ROLES.ADMIN] },
  { href: "/billing/tariffs", labelKey: "sidebar.tariffCatalogue", icon: Receipt, area: "finance", roles: [ROLES.BILLING, ROLES.ADMIN] },
  { href: "/reports", labelKey: "sidebar.reports", icon: BarChart3, area: "finance", roles: [ROLES.SUPERVISOR, ROLES.BILLING, ROLES.ADMIN, ROLES.AUDITOR] },
  { href: "/audit-viewer", labelKey: "sidebar.auditTrail", icon: Shield, area: "audit", roles: [ROLES.ADMIN, ROLES.AUDITOR] },
  { href: "/patient-portal", labelKey: "sidebar.myHealthRecord", icon: UserRound, area: "patient", roles: [ROLES.PATIENT] },
  { href: "/admin", labelKey: "sidebar.adminOverview", icon: LayoutDashboard, area: "admin", roles: [ROLES.ADMIN] },
  { href: "/admin/users", labelKey: "sidebar.users", icon: Users, area: "admin", roles: [ROLES.ADMIN] },
  { href: "/admin/account-requests", labelKey: "sidebar.accountRequests", icon: UserRound, area: "admin", roles: [ROLES.ADMIN] },
  { href: "/admin/permissions", labelKey: "sidebar.permissions", icon: Shield, area: "admin", roles: [ROLES.ADMIN] },
  { href: "/admin/departments", labelKey: "sidebar.departmentsRooms", icon: Building2, area: "admin", roles: [ROLES.ADMIN] },
  { href: "/admin/abdm-sync", labelKey: "sidebar.abdmIdentityLinks", icon: Shield, area: "admin", roles: [ROLES.ADMIN] },
  { href: "/admin/data-protection", labelKey: "sidebar.dataProtection", icon: Shield, area: "admin", roles: [ROLES.ADMIN, ROLES.AUDITOR] },
  { href: "/admin/maintenance", labelKey: "sidebar.equipmentMaintenance", icon: Building2, area: "admin", roles: [ROLES.ADMIN, ROLES.LAB_TECH, ROLES.RADIOLOGY_TECH] },
  { href: "/admin/integration", labelKey: "sidebar.integrationDlq", icon: Radio, area: "admin", roles: [ROLES.ADMIN] },
];

interface SidebarProps {
  open: boolean;
  setOpen: (value: boolean) => void;
}

export default function Sidebar({ open, setOpen }: SidebarProps) {
  const [query, setQuery] = useState("");
  const pathname = usePathname();
  const { user } = useAuth();
  const { t } = useLocale();
  const role = user?.role ?? null;
  const roleLabel = role && ROLE_KEYS[role] ? t(ROLE_KEYS[role]!) : t("common.unassigned");

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
    return NAV_ITEMS.filter((item) => {
      if (!(role && item.roles.includes(role) && canRoleAccessPath(role, item.href))) return false;
      if (!q) return true;
      return t(item.labelKey).toLowerCase().includes(q);
    });
  }, [query, role, t]);

  const groups = useMemo(() => {
    const map = new Map<string, typeof filtered>();
    for (const item of filtered) {
      const key = t(AREA_KEYS[item.area]);
      const list = map.get(key) ?? [];
      list.push(item);
      map.set(key, list);
    }
    return [...map.entries()];
  }, [filtered, t]);

  return (
    <>
      {open && (
        <button
          type="button"
          aria-label={t("sidebar.closeNav")}
          onClick={() => setOpen(false)}
          className="fixed inset-x-0 bottom-0 top-16 z-30 bg-black/40 md:hidden"
        />
      )}

      <aside
        id="workspace-sidebar"
        aria-label={t("sidebar.workspaceNav")}
        aria-hidden={!open}
        inert={!open}
        className={`fixed top-16 left-0 z-40 h-[calc(100vh-64px)] w-[260px] bg-card border-r border-border/80 shadow-md overflow-y-auto transition-transform duration-300 ease-in-out p-4 ${
          open ? "translate-x-0" : "-translate-x-full"
        }`}
      >
        <div className="flex items-center justify-between border-b border-border/70 pb-3.5">
          <div>
            <HealthDocBrand
              size={36}
              subtitle="HIMS"
              nameClassName="text-base font-bold text-foreground"
            />
            <p className="text-[11px] font-medium text-foreground/80 mt-0.5">
              {t("common.role")}: <span className="text-foreground font-semibold">{roleLabel}</span>
            </p>
          </div>

          <button
            onClick={() => setOpen(false)}
            className="flex h-8 w-8 items-center justify-center rounded-lg text-foreground/70 hover:bg-muted hover:text-foreground transition"
            type="button"
            aria-label={t("sidebar.closeSidebar")}
          >
            <X size={18} />
          </button>
        </div>

        <div className="relative mt-4 mb-5">
          <Search
            size={16}
            className="absolute left-3.5 top-1/2 -translate-y-1/2 text-foreground/60"
          />
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder={t("sidebar.searchModules")}
            className="w-full h-10 rounded-lg border border-border/80 bg-muted/40 pl-10 pr-3 text-xs font-medium outline-none focus:border-primary focus:bg-card focus:ring-2 focus:ring-primary/20 transition"
          />
        </div>

        <nav aria-label="HealthDoc modules" className="space-y-4">
          {groups.length === 0 ? (
            <p className="px-2 text-xs text-foreground/70">{t("sidebar.noScreens")}</p>
          ) : (
            groups.map(([group, items]) => (
              <div key={group} className="space-y-1">
                <p className="px-2.5 mb-1.5 text-[10px] uppercase tracking-[1.5px] text-foreground/75 font-bold">
                  {group}
                </p>
                <div className="space-y-0.5">
                  {items.map((item) => {
                    const Icon = item.icon;
                    const active =
                      pathname === item.href ||
                      (item.href !== "/" && pathname.startsWith(`${item.href}/`) &&
                        !filtered.some((other) => other.href !== item.href &&
                          other.href.startsWith(`${item.href}/`) &&
                          (pathname === other.href || pathname.startsWith(`${other.href}/`))));
                    return (
                      <Link
                        key={item.href}
                        href={item.href}
                        onClick={closeOnMobile}
                        aria-current={active ? "page" : undefined}
                        className={`group flex items-center justify-between rounded-lg px-3 py-2 text-xs font-semibold transition-all ${
                          active
                            ? "bg-primary/10 text-primary border-l-3 border-primary shadow-xs"
                            : "text-foreground/80 hover:bg-muted hover:text-foreground border-l-3 border-transparent"
                        }`}
                      >
                        <div className="flex items-center gap-2.5 min-w-0">
                          <Icon
                            size={17}
                            className={`shrink-0 transition-colors ${
                              active
                                ? "text-primary"
                                : "text-muted-foreground group-hover:text-primary"
                            }`}
                          />
                          <span className="truncate">{t(item.labelKey)}</span>
                        </div>
                        <ChevronRight
                          size={14}
                          className={`shrink-0 transition-transform ${
                            active
                              ? "text-primary translate-x-0.5"
                              : "text-muted-foreground/40 group-hover:text-muted-foreground group-hover:translate-x-0.5"
                          }`}
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
