import { useEffect, useState } from "react";
import { Menu, LogOut, User, Languages, AlertTriangle } from "lucide-react";
import { REALM_ROLE_LABELS } from "@/features/admin/constants";
import { useAuth } from "@/providers/auth-provider";
import { useLocale } from "@/lib/i18n";
import { useDeskCounter } from "@/features/receptionist/useDeskCounter";
import { HealthDocBrand } from "./HealthDocBrand";
import { listCriticalAlerts } from "@/features/lab/api";
import { CriticalAlertsModal } from "@/features/lab/components/CriticalAlertsModal";

interface NavbarProps {
  open: boolean;
  setOpen: React.Dispatch<React.SetStateAction<boolean>>;
}

export default function Navbar({ open, setOpen }: NavbarProps) {
  const { user, logout } = useAuth();
  const { locale, setLocale, t } = useLocale();
  const { counter, setDeskCounter, availableCounters } = useDeskCounter();
  const [unackAlertCount, setUnackAlertCount] = useState(0);
  const [alertModalOpen, setAlertModalOpen] = useState(false);

  const canSeeAlerts =
    user?.role === "doctor" ||
    user?.role === "nurse" ||
    user?.role === "lab_tech" ||
    user?.role === "admin";

  const refreshAlertCount = async () => {
    if (!canSeeAlerts) return;
    try {
      const res = await listCriticalAlerts("unacknowledged");
      setUnackAlertCount(res.total);
    } catch {
      // Non-intrusive
    }
  };

  useEffect(() => {
    if (canSeeAlerts) {
      void refreshAlertCount();
      const interval = setInterval(() => {
        void refreshAlertCount();
      }, 20000);
      return () => clearInterval(interval);
    }
  }, [canSeeAlerts]);

  const roleLabel = user?.role
    ? (REALM_ROLE_LABELS[user.role] ?? user.role)
    : "Unassigned";

  return (
    <header
      className="fixed top-0 left-0 right-0 z-50 flex h-16 items-center justify-between border-b border-border/80 bg-card/95 px-5 backdrop-blur-md transition-all sm:px-6"
      style={{
        boxShadow: "0 1px 3px rgba(0, 31, 84, 0.05), 0 1px 2px rgba(0, 0, 0, 0.03)",
      }}
    >
      <div className="flex items-center gap-3 sm:gap-4">
        <button
          type="button"
          onClick={() => setOpen((prev) => !prev)}
          className="rounded-lg p-2 text-foreground/80 transition-colors hover:bg-muted hover:text-foreground focus:outline-none focus:ring-2 focus:ring-primary/20"
          aria-label="Toggle menu"
          aria-controls="workspace-sidebar"
          aria-expanded={open}
        >
          <Menu size={20} />
        </button>

        <HealthDocBrand
          size={38}
          preload
          subtitle="HIMS"
          nameClassName="text-lg font-bold tracking-tight text-[#001F54] dark:text-blue-200"
          className="text-[#001F54]"
        />

        <div className="hidden items-center gap-2 border-l border-border/70 pl-4 md:flex">
          <div className="flex h-2 w-2 rounded-full bg-emerald-500 animate-pulse" />
          <span className="text-xs font-semibold text-foreground/75 uppercase tracking-wider">
            {t("common.online")}
          </span>
        </div>
      </div>

      <div className="flex items-center gap-3 sm:gap-4">
        {user?.role === "receptionist" && (
          <div className="hidden sm:flex items-center gap-2 rounded-full border border-border/80 bg-muted/40 px-3 py-1 text-xs">
            <span className="font-medium text-muted-foreground">{t("counter.label")}:</span>
            <select
              value={counter}
              onChange={(e) => setDeskCounter(e.target.value)}
              className="bg-transparent font-semibold text-foreground focus:outline-none cursor-pointer"
              aria-label="Select desk counter"
            >
              {availableCounters.map((c) => (
                <option key={c} value={c} className="bg-card text-foreground">
                  {c}
                </option>
              ))}
            </select>
          </div>
        )}

        <div className="flex items-center gap-1 rounded-full border border-border/80 bg-muted/40 p-1 text-xs">
          <Languages size={14} className="ml-1 text-muted-foreground hidden xs:block" />
          <button
            type="button"
            onClick={() => setLocale("en")}
            className={`rounded-full px-2 py-0.5 font-medium transition-colors ${
              locale === "en"
                ? "bg-primary text-white shadow-xs"
                : "text-muted-foreground hover:text-foreground"
            }`}
            aria-label="Switch language to English"
          >
            English
          </button>
          <button
            type="button"
            onClick={() => setLocale("hi")}
            className={`rounded-full px-2 py-0.5 font-medium transition-colors ${
              locale === "hi"
                ? "bg-primary text-white shadow-xs"
                : "text-muted-foreground hover:text-foreground"
            }`}
            aria-label="Switch language to Hindi"
          >
            हिंदी
          </button>
        </div>

        <div className="flex items-center gap-3 rounded-full border border-border/80 bg-muted/40 py-1 pl-1.5 pr-3 transition-colors hover:bg-muted/70">
          <div
            className="flex h-8 w-8 items-center justify-center rounded-full bg-[#001F54] text-white shadow-sm"
          >
            <User size={15} />
          </div>
          <div className="text-left">
            <p className="text-xs font-semibold leading-tight text-foreground">
              {user?.name || roleLabel}
            </p>
            <p className="text-[10px] font-medium leading-tight text-foreground/70">
              {roleLabel}
            </p>
          </div>
        </div>

        {canSeeAlerts && (
          <button
            type="button"
            onClick={() => setAlertModalOpen(true)}
            className={`flex items-center gap-1.5 rounded-full px-3 py-1 text-xs font-semibold transition-all ${
              unackAlertCount > 0
                ? "border border-red-300 bg-red-500/10 text-red-600 hover:bg-red-500/20 dark:border-red-800 dark:bg-red-950/40 dark:text-red-300 animate-pulse"
                : "border border-border/80 bg-muted/40 text-muted-foreground hover:text-foreground"
            }`}
            title="Critical Panic Lab Alerts"
            aria-label={`Critical alerts: ${unackAlertCount} pending`}
          >
            <AlertTriangle size={14} className={unackAlertCount > 0 ? "text-red-600 dark:text-red-400" : "text-muted-foreground"} />
            <span>
              {unackAlertCount > 0
                ? `${unackAlertCount} Panic Alert${unackAlertCount > 1 ? "s" : ""}`
                : "Lab Alerts"}
            </span>
          </button>
        )}

        <button
          type="button"
          onClick={() => void logout()}
          className="flex h-9 w-9 items-center justify-center rounded-full border border-border/80 text-muted-foreground transition-all hover:border-red-200 hover:bg-red-50 hover:text-red-600 focus:outline-none focus:ring-2 focus:ring-red-200 dark:hover:bg-red-950/30"
          aria-label="Sign out"
          title={t("nav.logout")}
        >
          <LogOut size={16} />
        </button>
      </div>

      <CriticalAlertsModal
        isOpen={alertModalOpen}
        onClose={() => setAlertModalOpen(false)}
        onAlertAcknowledged={() => void refreshAlertCount()}
      />
    </header>
  );
}
